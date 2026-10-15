"""
bulk_export/state_store.py
──────────────────────────────────────────────────────────────
Lecture et écriture de l'état des exports dans Postgres (schéma bulk_export).

Principes :
- l'état vit en base, jamais seulement dans ``st.session_state`` ;
- ``commit_page`` enregistre « mentions + doublons/collisions + ligne de page + compteurs +
  point de reprise » dans UNE transaction : soit tout est écrit, soit rien (règle n°4) ;
- un « bail » (lease) en base garantit un seul exécutant par export et un seul export actif à la fois ;
- les heures viennent de la base (``now()``), pas de l'horloge de la machine.

Toutes les fonctions reçoivent une connexion ouverte par ``db.connect`` (mode autocommit).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from bulk_export.logging_utils import mask
from bulk_export.models import ExportConfig, ExportStatus, check_transition, new_export_id, validate_export_id

# Verrou global (advisory lock Postgres) qui sérialise les prises de bail.
_LEASE_LOCK_KEY = 0x42554C4B  # "BULK"
MAX_EVENT_LENGTH = 2_000


class StateError(RuntimeError):
    """Opération refusée sur l'état d'un export."""


class ExportNotFound(StateError):
    pass


class LeaseLostError(StateError):
    """L'exécutant ne tient plus le bail : il doit s'arrêter sans rien écrire."""


# ─── Données d'une page à enregistrer ─────────────────────────────────────────

@dataclass(frozen=True)
class MentionRow:
    mention_id: str            # raw_hash
    raw_json: str              # texte JSON reçu, non modifié
    content_key: str
    compass_id: str | None
    api_id: str | None


@dataclass(frozen=True)
class ConflictRow:
    kind: str                  # 'duplicate' ou 'collision'
    mention_id: str
    other_mention_id: str | None = None
    api_id: str | None = None
    content_key: str | None = None


@dataclass(frozen=True)
class RejectedRow:
    reason: str                # ex. « Mention sans date. »
    raw_json: str              # texte JSON reçu, non modifié
    api_id: str | None


@dataclass(frozen=True)
class PageCommit:
    page_no: int
    cursor_sent: str
    cursor_received: str | None
    records_count: int                         # mentions présentes dans la réponse API
    new_mentions: Sequence[MentionRow] = ()
    conflicts: Sequence[ConflictRow] = ()
    rejected: Sequence[RejectedRow] = ()
    pagination_finished: bool = False

    def counts(self) -> dict[str, int]:
        dup = sum(1 for c in self.conflicts if c.kind == "duplicate")
        col = sum(1 for c in self.conflicts if c.kind == "collision")
        return {"new": len(self.new_mentions), "duplicate": dup, "collision": col, "error": len(self.rejected)}


# ─── Exports ──────────────────────────────────────────────────────────────────

def create_export(conn: psycopg.Connection, config: ExportConfig, *,
                  expected_count: int | None = None, export_id: str | None = None) -> str:
    """Crée un export au statut PENDING et renvoie son identifiant."""
    export_id = validate_export_id(export_id or new_export_id())
    with conn.transaction():
        conn.execute(
            """INSERT INTO exports (export_id, name, config_json, config_hash, status, expected_count)
               VALUES (%s, %s, %s, %s, 'PENDING', %s)""",
            (export_id, config.name, Jsonb(config.to_dict()), config.config_hash, expected_count),
        )
        add_event(conn, export_id, "INFO", f"Export créé : « {config.name} ».")
    return export_id


def get_export(conn: psycopg.Connection, export_id: str) -> dict[str, Any]:
    validate_export_id(export_id)
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute("SELECT * FROM exports WHERE export_id = %s", (export_id,)).fetchone()
    if row is None:
        raise ExportNotFound(f"Export introuvable : {export_id}")
    return row


def get_config(conn: psycopg.Connection, export_id: str) -> ExportConfig:
    """Recharge la configuration figée et vérifie qu'elle n'a pas été altérée."""
    row = get_export(conn, export_id)
    config = ExportConfig.from_dict(row["config_json"])
    if config.config_hash != row["config_hash"]:
        raise StateError("La configuration enregistrée ne correspond plus à son empreinte.")
    return config


def list_exports(conn: psycopg.Connection, limit: int = 100) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """SELECT export_id, name, status, expected_count, unique_count, duplicate_count,
                      collision_count, error_count, pages_count, created_at, last_updated_at, finished_at,
                      pagination_finished, raw_purged_at, files_expired_at, config_json
               FROM exports ORDER BY created_at DESC LIMIT %s""",
            (int(limit),),
        ).fetchall()


def set_status(conn: psycopg.Connection, export_id: str, new_status: ExportStatus | str, *,
               error_details: dict[str, Any] | None = None) -> None:
    """Change le statut en respectant les transitions autorisées (models.ALLOWED_TRANSITIONS).

    Contrôles supplémentaires, qui demandent de connaître l'état en base :
    - INCOMPLETE → RUNNING seulement si la pagination n'est pas terminée ;
    - COMPLETED seulement si la validation enregistrée est réussie (règle n°5).
    """
    new_status = ExportStatus(new_status)
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(
                "SELECT status, pagination_finished, validation_json FROM exports "
                "WHERE export_id = %s FOR UPDATE",
                (validate_export_id(export_id),),
            ).fetchone()
            if row is None:
                raise ExportNotFound(f"Export introuvable : {export_id}")
            current = ExportStatus(row["status"])
            check_transition(current, new_status)

            if current is ExportStatus.INCOMPLETE and new_status is ExportStatus.RUNNING \
                    and row["pagination_finished"]:
                raise StateError("Pagination déjà terminée : l'export ne peut pas repartir en collecte.")
            if new_status is ExportStatus.VALIDATING and not row["pagination_finished"]:
                raise StateError("Validation impossible : la collecte n'est pas terminée.")
            if new_status is ExportStatus.COMPLETED and (row["validation_json"] or {}).get("passed") is not True:
                raise StateError("COMPLETED refusé : aucune validation réussie n'est enregistrée.")

            details = Jsonb(_mask_json(error_details)) if error_details is not None else None
            cur.execute(
                """UPDATE exports SET status = %s,
                          error_details = COALESCE(%s, error_details),
                          stop_requested = CASE WHEN %s IN ('PAUSED','RUNNING') THEN FALSE ELSE stop_requested END,
                          finished_at = CASE WHEN %s = 'COMPLETED' THEN now() ELSE finished_at END,
                          last_updated_at = now()
                   WHERE export_id = %s""",
                (new_status.value, details, new_status.value, new_status.value, export_id),
            )
            _insert_event(cur, export_id, "INFO" if new_status is not ExportStatus.FAILED else "ERROR",
                          f"Statut : {current.value} → {new_status.value}")


def set_validation(conn: psycopg.Connection, export_id: str, validation: dict[str, Any]) -> None:
    """Enregistre le résultat des contrôles qualité (sprint 6). ``passed`` doit être un booléen."""
    if not isinstance(validation.get("passed"), bool):
        raise StateError("Le résultat de validation doit contenir « passed » (vrai/faux).")
    conn.execute(
        "UPDATE exports SET validation_json = %s, last_updated_at = now() WHERE export_id = %s",
        (Jsonb(_mask_json(validation)), validate_export_id(export_id)),
    )


def set_expected_count(conn: psycopg.Connection, export_id: str, expected_count: int) -> None:
    """Enregistre le volume annoncé par /metrics, une seule fois (il reste ensuite figé)."""
    conn.execute(
        """UPDATE exports SET expected_count = %s, last_updated_at = now()
           WHERE export_id = %s AND expected_count IS NULL""",
        (int(expected_count), validate_export_id(export_id)),
    )


def request_stop(conn: psycopg.Connection, export_id: str) -> None:
    """« Arrêter après la page en cours » : l'exécutant lit ce drapeau après chaque page."""
    conn.execute(
        "UPDATE exports SET stop_requested = TRUE, last_updated_at = now() WHERE export_id = %s",
        (validate_export_id(export_id),),
    )
    add_event(conn, export_id, "INFO", "Arrêt demandé (après la page en cours).")


# ─── Enregistrement d'une page (transaction unique) ───────────────────────────

def commit_page(conn: psycopg.Connection, export_id: str, owner: str, page: PageCommit) -> None:
    """Enregistre une page et son point de reprise d'un seul coup.

    Refuse (et n'écrit rien) si : l'exécutant ne tient plus le bail, l'export n'est pas en
    collecte, la page n'est pas la suivante attendue, ou le curseur envoyé n'est pas le
    dernier point de reprise. Une mention déjà enregistrée fait échouer toute la page
    (clé primaire) : impossible d'enregistrer un doublon.
    """
    validate_export_id(export_id)
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            state = cur.execute(
                """SELECT status, pages_count, unique_count, last_committed_cursor, lease_owner,
                          (lease_expires_at > now()) AS lease_valid
                   FROM exports WHERE export_id = %s FOR UPDATE""",
                (export_id,),
            ).fetchone()
            if state is None:
                raise ExportNotFound(f"Export introuvable : {export_id}")
            if state["lease_owner"] != owner or not state["lease_valid"]:
                raise LeaseLostError("Bail perdu : la page n'est pas enregistrée.")
            if state["status"] not in (ExportStatus.RUNNING.value, ExportStatus.STOPPING.value):
                raise StateError(f"Enregistrement refusé : statut {state['status']}.")
            if page.page_no != state["pages_count"] + 1:
                raise StateError(f"Page {page.page_no} reçue, page {state['pages_count'] + 1} attendue.")
            if state["pages_count"] > 0 and page.cursor_sent != state["last_committed_cursor"]:
                raise StateError("Le curseur envoyé ne correspond pas au dernier point de reprise.")

            _insert_mentions(cur, export_id, page, first_seq=state["unique_count"] + 1)
            _insert_conflicts(cur, export_id, page)
            _insert_rejected(cur, export_id, page)
            _insert_page_row(cur, export_id, page)

            n = page.counts()
            cur.execute(
                """UPDATE exports SET
                       retrieved_count = retrieved_count + %s,
                       unique_count = unique_count + %s,
                       duplicate_count = duplicate_count + %s,
                       collision_count = collision_count + %s,
                       error_count = error_count + %s,
                       pages_count = pages_count + 1,
                       last_cursor_sent = %s,
                       last_committed_cursor = %s,
                       pagination_finished = %s,
                       last_updated_at = now()
                   WHERE export_id = %s""",
                (page.records_count, n["new"], n["duplicate"], n["collision"], n["error"],
                 page.cursor_sent, page.cursor_received, page.pagination_finished, export_id),
            )


def _insert_mentions(cur: psycopg.Cursor, export_id: str, page: PageCommit, first_seq: int) -> None:
    if not page.new_mentions:
        return
    cur.executemany(
        """INSERT INTO raw_mentions (export_id, mention_id, seq, page_no, raw_json, content_key, compass_id, api_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        [(export_id, m.mention_id, first_seq + i, page.page_no, m.raw_json, m.content_key, m.compass_id, m.api_id)
         for i, m in enumerate(page.new_mentions)],
    )


def _insert_conflicts(cur: psycopg.Cursor, export_id: str, page: PageCommit) -> None:
    if not page.conflicts:
        return
    cur.executemany(
        """INSERT INTO conflicts (export_id, kind, mention_id, other_mention_id, api_id, content_key, page_no)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        [(export_id, c.kind, c.mention_id, c.other_mention_id, c.api_id, c.content_key, page.page_no)
         for c in page.conflicts],
    )


def _insert_rejected(cur: psycopg.Cursor, export_id: str, page: PageCommit) -> None:
    if not page.rejected:
        return
    cur.executemany(
        """INSERT INTO rejected_mentions (export_id, page_no, reason, raw_json, api_id)
           VALUES (%s, %s, %s, %s, %s)""",
        [(export_id, page.page_no, mask(r.reason), r.raw_json, r.api_id) for r in page.rejected],
    )


def _insert_page_row(cur: psycopg.Cursor, export_id: str, page: PageCommit) -> None:
    n = page.counts()
    cur.execute(
        """INSERT INTO pages (export_id, page_no, cursor_sent, cursor_received, records_count,
                              new_count, duplicate_count, collision_count, error_count)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (export_id, page.page_no, page.cursor_sent, page.cursor_received, page.records_count,
         n["new"], n["duplicate"], n["collision"], n["error"]),
    )


def find_known_mentions(conn: psycopg.Connection, export_id: str, mention_ids: Sequence[str]) -> set[str]:
    """Parmi ces raw_hash, lesquels sont déjà enregistrés ? (une requête par page)"""
    if not mention_ids:
        return set()
    rows = conn.execute(
        "SELECT mention_id FROM raw_mentions WHERE export_id = %s AND mention_id = ANY(%s)",
        (validate_export_id(export_id), list(mention_ids)),
    ).fetchall()
    return {r[0] for r in rows}


def find_by_content_keys(conn: psycopg.Connection, export_id: str,
                         content_keys: Sequence[str]) -> dict[str, str]:
    """content_key → raw_hash d'une mention déjà enregistrée (pour détecter les collisions)."""
    if not content_keys:
        return {}
    rows = conn.execute(
        """SELECT DISTINCT ON (content_key) content_key, mention_id FROM raw_mentions
           WHERE export_id = %s AND content_key = ANY(%s) ORDER BY content_key, seq""",
        (validate_export_id(export_id), list(content_keys)),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


# ─── Bail : un seul exécutant par export, un seul export actif ────────────────

def acquire_lease(conn: psycopg.Connection, export_id: str, owner: str, ttl_seconds: int) -> bool:
    """Prend le bail si l'export est libre (ou bail expiré, ou déjà à soi) ET si aucun
    autre export n'a de bail valide. Renvoie True si le bail est obtenu."""
    validate_export_id(export_id)
    with conn.transaction():
        # Sérialise les prises de bail : deux exécutants ne peuvent pas passer en même temps.
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LEASE_LOCK_KEY,))
        other_active = conn.execute(
            """SELECT 1 FROM exports WHERE export_id <> %s AND lease_owner IS NOT NULL
               AND lease_expires_at > now() LIMIT 1""",
            (export_id,),
        ).fetchone()
        if other_active:
            return False
        updated = conn.execute(
            """UPDATE exports SET lease_owner = %s,
                      lease_expires_at = now() + make_interval(secs => %s),
                      last_updated_at = now()
               WHERE export_id = %s
                 AND (lease_owner IS NULL OR lease_owner = %s OR lease_expires_at <= now())""",
            (owner, int(ttl_seconds), export_id, owner),
        ).rowcount
    return updated == 1


def renew_lease(conn: psycopg.Connection, export_id: str, owner: str, ttl_seconds: int) -> bool:
    """Prolonge le bail. False = bail perdu : l'exécutant doit s'arrêter."""
    updated = conn.execute(
        """UPDATE exports SET lease_expires_at = now() + make_interval(secs => %s)
           WHERE export_id = %s AND lease_owner = %s AND lease_expires_at > now()""",
        (int(ttl_seconds), validate_export_id(export_id), owner),
    ).rowcount
    return updated == 1


def release_lease(conn: psycopg.Connection, export_id: str, owner: str) -> None:
    conn.execute(
        """UPDATE exports SET lease_owner = NULL, lease_expires_at = NULL
           WHERE export_id = %s AND lease_owner = %s""",
        (validate_export_id(export_id), owner),
    )


# ─── Exports orphelins (application redémarrée) ───────────────────────────────

ORPHAN_MESSAGE = "Interrompu par un redémarrage de l'application — reprenable."


def recover_orphans(conn: psycopg.Connection) -> list[str]:
    """Exports en RUNNING / STOPPING dont plus personne ne tient le bail (expiré ou absent)
    → PAUSED ; en VALIDATING → INCOMPLETE (la validation se relance). Avec un événement.
    Renvoie leurs identifiants. Un export dont le bail est valide n'est jamais touché."""
    recovered: list[str] = []
    with conn.transaction():
        with conn.cursor() as cur:
            rows = cur.execute(
                """SELECT export_id, status FROM exports
                   WHERE status IN ('RUNNING', 'STOPPING', 'VALIDATING')
                     AND (lease_expires_at IS NULL OR lease_expires_at <= now())
                   ORDER BY last_updated_at DESC
                   FOR UPDATE SKIP LOCKED"""
            ).fetchall()
            for export_id, status in rows:
                target = ExportStatus.INCOMPLETE if status == "VALIDATING" else ExportStatus.PAUSED
                check_transition(status, target)
                cur.execute(
                    """UPDATE exports SET status = %s, stop_requested = FALSE, lease_owner = NULL,
                              lease_expires_at = NULL, last_updated_at = now()
                       WHERE export_id = %s""",
                    (target.value, export_id),
                )
                _insert_event(cur, export_id, "WARNING", f"{ORPHAN_MESSAGE} (statut {status} → {target.value})")
                recovered.append(export_id)
    return recovered


def active_export_id(conn: psycopg.Connection) -> str | None:
    """L'export dont le bail est valide en ce moment (au plus un), sinon None."""
    row = conn.execute(
        """SELECT export_id FROM exports WHERE lease_owner IS NOT NULL AND lease_expires_at > now()
           ORDER BY lease_expires_at DESC LIMIT 1"""
    ).fetchone()
    return row[0] if row else None


# ─── Journal d'événements ─────────────────────────────────────────────────────

def add_event(conn: psycopg.Connection, export_id: str | None, level: str, message: str) -> None:
    with conn.cursor() as cur:
        _insert_event(cur, export_id, level, message)


def list_events(conn: psycopg.Connection, export_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """SELECT event_no, level, message, created_at FROM events
               WHERE export_id = %s ORDER BY event_no DESC LIMIT %s""",
            (validate_export_id(export_id), int(limit)),
        ).fetchall()


def _insert_event(cur: psycopg.Cursor, export_id: str | None, level: str, message: str) -> None:
    if export_id is not None:
        validate_export_id(export_id)
    text = mask(message)
    if len(text) > MAX_EVENT_LENGTH:
        text = text[:MAX_EVENT_LENGTH] + " […]"
    cur.execute("INSERT INTO events (export_id, level, message) VALUES (%s, %s, %s)",
                (export_id, level.upper(), text))


def _mask_json(value: Any) -> Any:
    """Masque les secrets dans toutes les chaînes d'un objet JSON."""
    if isinstance(value, dict):
        return {str(k): _mask_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask_json(v) for v in value]
    if isinstance(value, str):
        return mask(value)
    return value


# ─── Fichiers finaux, lecture en flux, rétention (sprint 6) ───────────────────

@dataclass(frozen=True)
class FileRecord:
    path: str                       # chemin dans le bucket
    kind: str                       # batch_jsonl, csv_complete, zip, manifest, csv_partial
    rows_count: int | None
    sha256: str                     # empreinte du fichier envoyé
    size_bytes: int
    content_sha256: str | None = None  # empreinte du contenu non compressé (lots .gz)
    content_bytes: int | None = None


def iter_mentions(conn: psycopg.Connection, export_id: str, chunk: int = 5000):
    """(seq, mention_id, raw_json) dans l'ordre d'arrivée, par paquets : jamais tout en mémoire."""
    validate_export_id(export_id)
    last = 0
    while True:
        rows = conn.execute(
            """SELECT seq, mention_id, raw_json FROM raw_mentions
               WHERE export_id = %s AND seq > %s ORDER BY seq LIMIT %s""",
            (export_id, last, int(chunk)),
        ).fetchall()
        if not rows:
            return
        yield from rows
        last = rows[-1][0]


def list_duplicates(conn: psycopg.Connection, export_id: str) -> list[dict[str, Any]]:
    """Doublons tracés, avec l'`id` API de la copie gardée et de la copie écartée (manifeste, règle A)."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """SELECT c.page_no, c.mention_id, m.api_id AS kept_api_id, c.api_id AS dropped_api_id
               FROM conflicts c LEFT JOIN raw_mentions m USING (export_id, mention_id)
               WHERE c.export_id = %s AND c.kind = 'duplicate' ORDER BY c.conflict_no""",
            (validate_export_id(export_id),),
        ).fetchall()


def count_conflicts(conn: psycopg.Connection, export_id: str, kind: str) -> int:
    return conn.execute("SELECT count(*) FROM conflicts WHERE export_id = %s AND kind = %s",
                        (validate_export_id(export_id), kind)).fetchone()[0]


def replace_files(conn: psycopg.Connection, export_id: str, records: Sequence[FileRecord],
                  kinds: Sequence[str] | None = None) -> None:
    """Remplace la liste des fichiers d'un export (tous, ou seulement certains types)."""
    validate_export_id(export_id)
    with conn.transaction():
        if kinds is None:
            conn.execute("DELETE FROM files WHERE export_id = %s", (export_id,))
        else:
            conn.execute("DELETE FROM files WHERE export_id = %s AND kind = ANY(%s)", (export_id, list(kinds)))
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO files (export_id, path, kind, rows_count, sha256, size_bytes, content_sha256, content_bytes)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (export_id, path) DO UPDATE SET kind = EXCLUDED.kind, rows_count = EXCLUDED.rows_count,
                       sha256 = EXCLUDED.sha256, size_bytes = EXCLUDED.size_bytes,
                       content_sha256 = EXCLUDED.content_sha256, content_bytes = EXCLUDED.content_bytes,
                       created_at = now()""",
                [(export_id, f.path, f.kind, f.rows_count, f.sha256, f.size_bytes, f.content_sha256, f.content_bytes)
                 for f in records],
            )


def list_files(conn: psycopg.Connection, export_id: str) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute("SELECT * FROM files WHERE export_id = %s ORDER BY kind, path",
                           (validate_export_id(export_id),)).fetchall()


def purge_raw_mentions(conn: psycopg.Connection, export_id: str) -> int:
    """Après COMPLETED seulement : les fichiers validés dans Storage font référence."""
    validate_export_id(export_id)
    with conn.transaction():
        status = conn.execute("SELECT status FROM exports WHERE export_id = %s FOR UPDATE",
                              (export_id,)).fetchone()
        if status is None or status[0] != ExportStatus.COMPLETED.value:
            raise StateError("Les mentions ne sont effacées qu'après COMPLETED.")
        deleted = conn.execute("DELETE FROM raw_mentions WHERE export_id = %s", (export_id,)).rowcount
        conn.execute("UPDATE exports SET raw_purged_at = now(), last_updated_at = now() WHERE export_id = %s",
                     (export_id,))
        add_event(conn, export_id, "INFO", f"{deleted} mentions effacées de la base (les fichiers validés font référence).")
    return deleted


def exports_with_expired_files(conn: psycopg.Connection, retention_days: int) -> list[str]:
    rows = conn.execute(
        """SELECT export_id FROM exports
           WHERE status = 'COMPLETED' AND files_expired_at IS NULL
             AND finished_at < now() - make_interval(days => %s)""",
        (int(retention_days),),
    ).fetchall()
    return [r[0] for r in rows]


def mark_files_expired(conn: psycopg.Connection, export_id: str) -> None:
    with conn.transaction():
        conn.execute("DELETE FROM files WHERE export_id = %s", (validate_export_id(export_id),))
        conn.execute("UPDATE exports SET files_expired_at = now(), last_updated_at = now() WHERE export_id = %s",
                     (export_id,))
        add_event(conn, export_id, "INFO", "Fichiers supprimés de Storage (durée de conservation dépassée).")


def delete_export(conn: psycopg.Connection, export_id: str, *, confirm_resumable: bool = False) -> None:
    """Supprime un export et tout ce qui en dépend en base. Les fichiers Storage sont supprimés
    par l'appelant AVANT (il connaît le stockage). Refusé si l'export tourne ; un export encore
    reprenable demande une confirmation explicite."""
    row = get_export(conn, export_id)
    lease_valid = conn.execute("SELECT lease_expires_at > now() FROM exports WHERE export_id = %s",
                               (export_id,)).fetchone()[0]
    if row["lease_owner"] and lease_valid:
        raise StateError("Export en cours : arrêtez-le avant de le supprimer.")
    resumable = row["status"] in ("PENDING", "PAUSED", "FAILED") or (
        row["status"] == "INCOMPLETE")
    if resumable and not confirm_resumable:
        raise StateError("Cet export est encore reprenable ou validable : confirmation explicite nécessaire.")
    conn.execute("DELETE FROM exports WHERE export_id = %s", (export_id,))
