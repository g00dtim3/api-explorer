"""
bulk_export/engine.py
──────────────────────────────────────────────────────────────
Moteur d'export : lit l'API page par page et enregistre chaque page avec son point de reprise.

Pour chaque page : lire → trier (dedup) → enregistrer « mentions + point de reprise » en UNE
transaction (state_store.commit_page) → passer au curseur suivant.

- seule la page courante est en mémoire (aucun DataFrame) ;
- fin de pagination → INCOMPLETE (la validation du sprint 6 décidera de COMPLETED) ;
- erreur API persistante ou fin anormale → FAILED, reprenable : les pages déjà enregistrées restent ;
- coupure de la base pendant l'enregistrement → reconnexion, puis on regarde ce que la base contient
  vraiment : page absente → on la réenregistre ; page présente → on passe à la suivante.

Ne dépend pas de Streamlit : utilisable par l'application (sprint 4/5) et en ligne de commande.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

import psycopg

from bulk_export import dedup, state_store as ss
from bulk_export.api_adapter import PaginationAdapter, PaginationError
from bulk_export.api_http import ApiError
from bulk_export.logging_utils import get_logger, mask
from bulk_export.models import ExportConfig, ExportStatus as S

logger = get_logger(__name__)

# Statuts depuis lesquels le moteur peut (re)démarrer la collecte.
_STARTABLE = {S.PENDING.value, S.PAUSED.value, S.FAILED.value, S.INCOMPLETE.value, S.RUNNING.value}


@dataclass(frozen=True)
class EngineResult:
    export_id: str
    outcome: str            # FINISHED, PAUSED, FAILED, LEASE_LOST, NOTHING_TO_DO, REFUSED
    status: str | None      # statut en base à la sortie
    pages_this_run: int
    message: str = ""


class ExportEngine:
    def __init__(self, connect: Callable[[], psycopg.Connection],
                 adapter_factory: Callable[[ExportConfig], PaginationAdapter], *,
                 owner: str, lease_ttl_s: int = 300, commit_attempts: int = 3,
                 reconnect_wait_s: float = 2.0, sleep: Callable[[float], None] = time.sleep):
        self._connect = connect
        self._adapter_factory = adapter_factory
        self.owner = owner
        self.lease_ttl_s = lease_ttl_s
        self.commit_attempts = commit_attempts
        self.reconnect_wait_s = reconnect_wait_s
        self._sleep = sleep
        self._conn: psycopg.Connection | None = None

    # ─── Boucle principale ───────────────────────────────────────────────────

    def run(self, export_id: str, should_stop: Callable[[], bool] = lambda: False) -> EngineResult:
        self._conn = self._connect()
        pages_done = 0
        lease_taken = False
        try:
            row = ss.get_export(self._conn, export_id)
            if row["status"] not in _STARTABLE:
                return self._result(export_id, "REFUSED", 0, f"Statut {row['status']} : rien à collecter.")
            if not ss.acquire_lease(self._conn, export_id, self.owner, self.lease_ttl_s):
                return self._result(export_id, "REFUSED", 0, "Export déjà tenu par un autre exécutant, "
                                                              "ou un autre export est en cours.")
            lease_taken = True
            if row["pagination_finished"]:
                if row["status"] != S.INCOMPLETE.value:
                    self._set_status(export_id, row["status"], S.INCOMPLETE)
                return self._result(export_id, "NOTHING_TO_DO", 0, "Pagination déjà terminée.")

            config = ss.get_config(self._conn, export_id)
            if row["status"] != S.RUNNING.value:
                ss.set_status(self._conn, export_id, S.RUNNING)
            adapter = self._adapter_factory(config)

            expected = row["expected_count"]
            if expected is None:
                expected = adapter.expected_count()
                ss.set_expected_count(self._conn, export_id, expected)
                ss.add_event(self._conn, export_id, "INFO", f"Volume annoncé par /metrics : {expected} mentions.")
            limit = adapter.max_pages(expected)

            page_no = row["pages_count"] + 1
            cursor = row["last_committed_cursor"] or adapter.initial_cursor()
            ss.add_event(self._conn, export_id, "INFO",
                         "Démarrage de la collecte." if page_no == 1 else f"Reprise à la page {page_no}.")
            first_page_of_run = True

            while True:
                if page_no > limit:
                    raise PaginationError(f"Plafond de {limit} pages dépassé (volume annoncé : {expected}). "
                                          "Arrêt par sécurité : la pagination ne semble pas se terminer.")
                result = adapter.fetch_page(cursor)
                prepared = dedup.prepare(result.records, config.fingerprint)
                hashes = [p.fp.raw_hash for p in prepared if p.fp]
                keys = [p.fp.content_key for p in prepared if p.fp]
                classified = dedup.classify(
                    prepared,
                    known_raw=ss.find_known_mentions(self._conn, export_id, hashes),
                    known_content=ss.find_by_content_keys(self._conn, export_id, keys),
                )
                commit = ss.PageCommit(
                    page_no=page_no, cursor_sent=result.cursor_sent, cursor_received=result.next_cursor,
                    records_count=len(result.records), new_mentions=classified.new_mentions,
                    conflicts=classified.conflicts, rejected=classified.rejected,
                    pagination_finished=result.is_last,
                )
                self._commit_with_recovery(export_id, commit)
                pages_done += 1
                self._log_page(export_id, commit, result.raw_meta, result.records, classified,
                               result.warnings, first_page_of_run)
                first_page_of_run = False

                if result.is_last:
                    self._set_status(export_id, S.RUNNING.value, S.INCOMPLETE)
                    ss.add_event(self._conn, export_id, "INFO",
                                 "Fin de pagination. Statut INCOMPLETE en attendant la validation.")
                    return self._result(export_id, "FINISHED", pages_done)

                cursor = result.next_cursor
                page_no += 1
                if not ss.renew_lease(self._conn, export_id, self.owner, self.lease_ttl_s):
                    return self._result(export_id, "LEASE_LOST", pages_done,
                                        "Bail perdu : arrêt sans rien écrire de plus.")
                if ss.get_export(self._conn, export_id)["stop_requested"] or should_stop():
                    ss.set_status(self._conn, export_id, S.STOPPING)
                    ss.set_status(self._conn, export_id, S.PAUSED)
                    ss.add_event(self._conn, export_id, "INFO",
                                 f"Arrêt propre après la page {page_no - 1}. Reprenable.")
                    return self._result(export_id, "PAUSED", pages_done)

        except ss.LeaseLostError as exc:
            return self._result(export_id, "LEASE_LOST", pages_done, str(exc))
        except (ApiError, PaginationError, ss.StateError, psycopg.Error, ValueError) as exc:
            return self._fail(export_id, exc, pages_done)
        except Exception as exc:  # erreur imprévue : jamais d'arrêt silencieux
            logger.exception("Erreur inattendue pendant l'export %s", export_id)
            return self._fail(export_id, exc, pages_done)
        finally:
            if lease_taken:
                self._release_and_close(export_id)
            else:
                self._close()

    # ─── Enregistrement avec reprise après coupure de la base ────────────────

    def _commit_with_recovery(self, export_id: str, commit: ss.PageCommit) -> None:
        for attempt in range(1, self.commit_attempts + 1):
            try:
                ss.commit_page(self._conn, export_id, self.owner, commit)
                return
            except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
                logger.warning("Coupure base pendant l'enregistrement de la page %d (essai %d/%d) : %s",
                               commit.page_no, attempt, self.commit_attempts, mask(exc))
                if attempt == self.commit_attempts:
                    raise
                self._close()
                self._sleep(self.reconnect_wait_s * attempt)
                self._conn = self._connect()
                row = ss.get_export(self._conn, export_id)
                # La coupure a pu survenir APRÈS l'enregistrement : la base fait foi.
                if row["pages_count"] >= commit.page_no and row["last_cursor_sent"] == commit.cursor_sent:
                    ss.add_event(self._conn, export_id, "WARNING",
                                 f"Coupure base : la page {commit.page_no} était déjà enregistrée.")
                    return
                ss.add_event(self._conn, export_id, "WARNING",
                             f"Coupure base : nouvel enregistrement de la page {commit.page_no}.")

    # ─── Journal ─────────────────────────────────────────────────────────────

    def _log_page(self, export_id: str, commit: ss.PageCommit, meta: dict[str, Any], records: list,
                  classified: dedup.ClassifiedPage, warnings: tuple[str, ...], first_of_run: bool) -> None:
        n = commit.counts()
        ss.add_event(self._conn, export_id, "INFO",
                     f"Page {commit.page_no} : {commit.records_count} reçues, {n['new']} nouvelles, "
                     f"{n['duplicate']} doublons, {n['collision']} jumelles, {n['error']} rejetées "
                     f"({meta.get('elapsed_ms')} ms, {meta.get('size_bytes')} octets).")
        if first_of_run and records:
            # Noms des champs uniquement, jamais les valeurs : tranche la question du champ verbatim.
            fields = sorted({str(k) for r in records for k in r})
            ss.add_event(self._conn, export_id, "INFO", "Champs reçus : " + ", ".join(fields))
        if classified.repeated_api_ids:
            ss.add_event(self._conn, export_id, "WARNING",
                         f"Page {commit.page_no} : {classified.repeated_api_ids} `id` API portés par des "
                         "mentions différentes (l'`id` n'est pas utilisé comme clé).")
        if n["error"]:
            ss.add_event(self._conn, export_id, "WARNING",
                         f"Page {commit.page_no} : {n['error']} mention(s) rejetée(s), gardées à part.")
        for w in warnings:
            ss.add_event(self._conn, export_id, "WARNING", f"Page {commit.page_no} : {w}")

    # ─── Utilitaires ─────────────────────────────────────────────────────────

    def _set_status(self, export_id: str, current: str, new: S) -> None:
        if current != new.value:
            ss.set_status(self._conn, export_id, new)

    def _fail(self, export_id: str, exc: Exception, pages_done: int) -> EngineResult:
        message = mask(f"{type(exc).__name__} : {exc}")
        try:
            if self._conn is None or self._conn.closed:
                self._conn = self._connect()
            row = ss.get_export(self._conn, export_id)
            if row["status"] in (S.RUNNING.value, S.STOPPING.value, S.PENDING.value):
                ss.set_status(self._conn, export_id, S.FAILED,
                              error_details={"type": type(exc).__name__, "message": message,
                                             "page": row["pages_count"] + 1})
            ss.add_event(self._conn, export_id, "ERROR", f"Échec : {message}")
        except Exception as inner:  # la base elle-même est indisponible
            logger.error("Impossible d'enregistrer l'échec de %s : %s", export_id, mask(inner))
        return self._result(export_id, "FAILED", pages_done, message)

    def _result(self, export_id: str, outcome: str, pages: int, message: str = "") -> EngineResult:
        status = None
        try:
            if self._conn is not None and not self._conn.closed:
                status = ss.get_export(self._conn, export_id)["status"]
        except Exception:
            pass
        return EngineResult(export_id, outcome, status, pages, mask(message))

    def _close(self) -> None:
        """Ferme la connexion (sans toucher au bail)."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _release_and_close(self, export_id: str) -> None:
        """Fin de run : libère le bail (s'il est encore à nous), puis ferme la connexion."""
        try:
            if self._conn is None or self._conn.closed:
                self._conn = self._connect()
            ss.release_lease(self._conn, export_id, self.owner)
        except Exception as exc:
            # Pas grave : le bail expirera tout seul.
            logger.warning("Bail de %s non libéré (il expirera) : %s", export_id, mask(exc))
        self._close()
