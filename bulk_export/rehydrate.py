"""
bulk_export/rehydrate.py
──────────────────────────────────────────────────────────────
Réhydratation (lot 1A) : un export COMPLETED dont le brut a été effacé de la base retrouve ses mentions
à partir de ses lots ``batch_*.jsonl.gz``, encore présents dans Storage.

    python -m bulk_export.rehydrate exp_…     # réhydrate un export
    python -m bulk_export.rehydrate --list    # exports purgés encore réhydratables

Règles :
- refus si l'export n'est pas COMPLETED, si son brut n'a pas été effacé (``raw_purged_at`` vide)
  ou si ses fichiers ont expiré ;
- chaque lot est relu en flux et ses deux empreintes sont vérifiées (fichier .gz envoyé et contenu
  décompressé, colonnes ``sha256`` et ``content_sha256`` de ``files``) ;
- les empreintes (``mention_id`` = raw_hash, ``content_key``, ``compass_id``) sont recalculées avec
  ``fingerprints.compute()`` et les MÊMES réglages que l'export (``config_json``) ; ``raw_json`` est
  réinséré tel quel (la ligne du lot, sans le saut de ligne) ;
- ``seq`` = ordre de lecture (1, 2, 3…), identique à l'ordre d'origine puisque les lots suivent ``seq`` ;
- ``page_no`` n'est pas dans les lots : il vaut 0, qui veut dire « réhydraté » (une vraie page commence à 1) ;
- tout se fait dans UNE transaction : nombre de lignes égal à ``unique_count`` et ``mention_id`` uniques,
  sinon rien n'est enregistré.

Paramètres lus dans les variables d'environnement (comme ``bulk_export.run``) : BULK_EXPORT_DATABASE_URL,
BULK_EXPORT_SUPABASE_URL, BULK_EXPORT_SUPABASE_SERVICE_KEY, et en option BULK_EXPORT_DB_SCHEMA,
BULK_EXPORT_STORAGE_BUCKET.

Codes de sortie : 0 réhydraté / liste affichée · 1 échec · 2 refusé · 3 paramètres invalides.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Iterator

import psycopg

from bulk_export import fingerprints, state_store as ss
from bulk_export.logging_utils import mask
from bulk_export.models import ExportStatus, validate_export_id
from bulk_export.storage import Storage, StorageError

REHYDRATED_PAGE_NO = 0     # les lots ne gardent pas le numéro de page
INSERT_CHUNK = 1000
EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2, 3


class RehydrateError(RuntimeError):
    """Réhydratation refusée ou interrompue : rien n'a été enregistré."""


def rehydratable_exports(conn: psycopg.Connection) -> list[dict]:
    """Exports COMPLETED dont le brut a été effacé mais dont les fichiers sont encore dans Storage."""
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """SELECT export_id, name, unique_count, finished_at, raw_purged_at FROM exports
               WHERE status = 'COMPLETED' AND raw_purged_at IS NOT NULL AND files_expired_at IS NULL
               ORDER BY finished_at"""
        ).fetchall()


def check_rehydratable(row: dict) -> None:
    """Lève RehydrateError (message clair) si l'export ne peut pas être réhydraté."""
    if row["status"] != ExportStatus.COMPLETED.value:
        raise RehydrateError(f"Réhydratation refusée : l'export est {row['status']} (COMPLETED attendu).")
    if row["raw_purged_at"] is None:
        raise RehydrateError("Réhydratation refusée : le brut de cet export est déjà en base.")
    if row["files_expired_at"] is not None:
        raise RehydrateError("Réhydratation refusée : les fichiers de cet export ont expiré (supprimés de Storage).")


def _download(storage: Storage, f: dict, dest: Path) -> None:
    """Copie locale du lot .gz, empreinte et taille du fichier vérifiées."""
    digest, size = hashlib.sha256(), 0
    with open(dest, "wb") as fh:
        for block in storage.iter_bytes(f["path"]):
            digest.update(block)
            size += len(block)
            fh.write(block)
    if digest.hexdigest() != f["sha256"] or size != f["size_bytes"]:
        raise RehydrateError(f"{f['path']} : empreinte du fichier différente de celle enregistrée.")


def _lines(path: Path, f: dict) -> Iterator[str]:
    """Lignes du lot décompressé, en flux. L'empreinte du contenu est vérifiée à la fin."""
    digest, size = hashlib.sha256(), 0
    with gzip.open(path, "rb") as fh:
        for line in fh:
            digest.update(line)
            size += len(line)
            if not line.endswith(b"\n"):
                raise RehydrateError(f"{f['path']} : dernière ligne incomplète.")
            yield line[:-1].decode("utf-8")
    if f["content_sha256"] is None or digest.hexdigest() != f["content_sha256"] \
            or (f["content_bytes"] is not None and size != f["content_bytes"]):
        raise RehydrateError(f"{f['path']} : empreinte du contenu différente de celle enregistrée.")


def _row(export_id: str, seq: int, raw_json: str, settings) -> tuple:
    record = json.loads(raw_json)
    fp = fingerprints.compute(record, settings)
    api_id = record.get("id")
    return (export_id, fp.raw_hash, seq, REHYDRATED_PAGE_NO, raw_json, fp.content_key, fp.compass_id,
            None if api_id is None else str(api_id))


def rehydrate(conn: psycopg.Connection, export_id: str, storage: Storage, *, workdir_root: str | None = None) -> int:
    """Réinsère le brut d'un export purgé à partir de ses lots. Renvoie le nombre de mentions."""
    validate_export_id(export_id)
    check_rehydratable(ss.get_export(conn, export_id))
    config = ss.get_config(conn, export_id)  # vérifie aussi que la configuration n'a pas été altérée
    batches = sorted((f for f in ss.list_files(conn, export_id) if f["kind"] == "batch_jsonl"),
                     key=lambda f: f["path"])
    if not batches:
        raise RehydrateError("Réhydratation refusée : aucun lot JSONL enregistré pour cet export.")

    seq = 0
    try:
        with tempfile.TemporaryDirectory(prefix="bulk_rehydrate_", dir=workdir_root) as tmp, conn.transaction():
            # Verrou sur la fiche : personne ne purge, ne supprime ni ne réhydrate en même temps.
            row = conn.execute("SELECT status, raw_purged_at, files_expired_at, unique_count FROM exports "
                               "WHERE export_id = %s FOR UPDATE", (export_id,)).fetchone()
            check_rehydratable(dict(zip(("status", "raw_purged_at", "files_expired_at"), row[:3])))
            unique_count = row[3]
            if conn.execute("SELECT count(*) FROM raw_mentions WHERE export_id = %s", (export_id,)).fetchone()[0]:
                raise RehydrateError("Réhydratation refusée : des mentions de cet export sont déjà en base.")
            for f in batches:
                local = Path(tmp) / "lot.jsonl.gz"
                _download(storage, f, local)
                rows, before = [], seq
                for raw_json in _lines(local, f):
                    seq += 1
                    rows.append(_row(export_id, seq, raw_json, config.fingerprint))
                    if len(rows) >= INSERT_CHUNK:
                        _insert(conn, rows)
                        rows = []
                _insert(conn, rows)
                if f["rows_count"] is not None and seq - before != f["rows_count"]:
                    raise RehydrateError(f"{f['path']} : {seq - before} lignes lues, {f['rows_count']} attendues.")
                local.unlink()
            if seq != unique_count:
                raise RehydrateError(f"Réhydratation refusée : {seq} mentions dans les lots, "
                                     f"{unique_count} attendues (unique_count).")
            conn.execute("UPDATE exports SET raw_purged_at = NULL, last_updated_at = now() WHERE export_id = %s",
                         (export_id,))
            ss.add_event(conn, export_id, "INFO", f"Brut réhydraté depuis les lots ({seq} mentions).")
    except psycopg.errors.UniqueViolation:
        raise RehydrateError("Réhydratation refusée : deux lignes des lots ont la même empreinte (mention_id).") from None
    except fingerprints.MissingDateError as exc:
        raise RehydrateError(f"Réhydratation refusée : mention sans date dans les lots ({exc}).") from None
    except (StorageError, ValueError) as exc:  # ValueError : JSON illisible, UTF-8 invalide
        raise RehydrateError(mask(f"Réhydratation interrompue : {type(exc).__name__} : {exc}")) from None
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise RehydrateError(mask(f"Réhydratation interrompue : lot illisible ({type(exc).__name__}).")) from None
    return seq


def _insert(conn: psycopg.Connection, rows: list[tuple]) -> None:
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO raw_mentions (export_id, mention_id, seq, page_no, raw_json, content_key, compass_id, api_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", rows)


# ─── Ligne de commande ────────────────────────────────────────────────────────

def _print(message: str) -> None:
    print(mask(message), flush=True)


def main(argv: list[str] | None = None) -> int:
    from bulk_export import db
    from bulk_export.settings import SettingsError, load_settings
    from bulk_export.storage import build_storage

    parser = argparse.ArgumentParser(prog="python -m bulk_export.rehydrate",
                                     description="Réhydrate le brut d'un export purgé à partir de ses lots.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("export_id", nargs="?", help="export à réhydrater")
    group.add_argument("--list", action="store_true", help="liste les exports purgés encore réhydratables")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(use_streamlit=False)
        conn = db.connect(settings)
    except (SettingsError, db.DatabaseError) as exc:
        _print(f"Paramètres invalides : {exc}")
        return EXIT_USAGE
    try:
        if args.list:
            rows = rehydratable_exports(conn)
            for r in rows:
                _print(f"{r['export_id']}  {r['unique_count']} mentions  purgé le {r['raw_purged_at']:%Y-%m-%d}"
                       f"  « {r['name']} »")
            _print(f"{len(rows)} export(s) réhydratable(s).")
            return EXIT_OK
        try:
            storage = build_storage(settings)
        except StorageError as exc:
            _print(f"Paramètres invalides : {exc}")
            return EXIT_USAGE
        try:
            count = rehydrate(conn, args.export_id, storage)
        except (RehydrateError, ss.StateError) as exc:
            _print(str(exc))
            return EXIT_REFUSED
        _print(f"{args.export_id} : brut réhydraté ({count} mentions).")
        return EXIT_OK
    except Exception as exc:
        _print(f"Échec : {type(exc).__name__} : {exc}")
        return EXIT_FAILED
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
