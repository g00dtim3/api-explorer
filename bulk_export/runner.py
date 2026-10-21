"""
bulk_export/runner.py
──────────────────────────────────────────────────────────────
Gestionnaire d'exécution : lance le moteur dans une tâche de fond (thread) et garde le bail en vie.

- un seul gestionnaire par processus (côté Streamlit : créé une fois via ``st.cache_resource``) ;
- un seul export à la fois ; le verrou en base (bail) fait foi, même entre plusieurs processus ;
- « battement de cœur » : une petite tâche prolonge le bail toutes les ``heartbeat_s`` secondes tant que
  l'export tourne, même pendant une longue attente de l'API. Si l'application meurt, le battement s'arrête
  et le bail expire : l'export devient un « orphelin », repassé en PAUSED et reprenable ;
- ``request_stop`` écrit le drapeau EN BASE : l'arrêt survit à un rechargement de page ;
- la tâche de fond ne touche jamais à Streamlit (ni ``st.session_state``, ni widgets).
"""

from __future__ import annotations

import os
import secrets
import socket
import threading
from dataclasses import dataclass
from typing import Any, Callable

import psycopg

from bulk_export import state_store as ss
from bulk_export.api_adapter import PaginationAdapter, RatingsReviewsAdapter
from bulk_export.api_http import RatingsReviewsHttpClient
from bulk_export.engine import EngineResult, ExportEngine
from bulk_export.logging_utils import get_logger, mask
from bulk_export.models import ExportConfig, ExportStatus as S

logger = get_logger(__name__)

DEFAULT_LEASE_TTL_S = 120
DEFAULT_HEARTBEAT_S = 30
# Statuts reprenables (INCOMPLETE seulement si la pagination n'est pas terminée : contrôlé au démarrage).
RESUMABLE = {S.PENDING.value, S.PAUSED.value, S.FAILED.value, S.INCOMPLETE.value, S.RUNNING.value}


def new_owner_id() -> str:
    """Identifiant de l'exécutant (machine:processus:aléa) — sert uniquement au bail."""
    return f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(4)}"


@dataclass(frozen=True)
class StartResult:
    ok: bool
    message: str


class ExportRunner:
    def __init__(self, connect: Callable[[], psycopg.Connection],
                 adapter_factory: Callable[[ExportConfig], PaginationAdapter], *,
                 owner: str | None = None, lease_ttl_s: int = DEFAULT_LEASE_TTL_S,
                 heartbeat_s: float = DEFAULT_HEARTBEAT_S, engine_kwargs: dict[str, Any] | None = None,
                 storage_factory: Callable[[], Any] | None = None, purge_raw_after_validation: bool = False):
        if heartbeat_s >= lease_ttl_s:
            raise ValueError("Le battement de cœur doit être plus fréquent que la durée du bail.")
        self._connect = connect
        self._adapter_factory = adapter_factory
        self.owner = owner or new_owner_id()
        self.lease_ttl_s = lease_ttl_s
        self.heartbeat_s = heartbeat_s
        self._engine_kwargs = engine_kwargs or {}
        # Stockage des fichiers finaux (Supabase Storage). Sans lui, la validation ne peut pas se faire.
        self._storage_factory = storage_factory
        # Effacer le brut de la base après COMPLETED (faux par défaut : brut conservé, lot 1A).
        self._purge_raw = purge_raw_after_validation
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._export_id: str | None = None
        self.last_result: EngineResult | None = None

    # ─── État ────────────────────────────────────────────────────────────────

    def is_busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def current_export_id(self) -> str | None:
        return self._export_id if self.is_busy() else None

    def wait(self, timeout: float | None = None) -> bool:
        """Attend la fin de l'export en cours (tests, ligne de commande). True si terminé."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    # ─── Ordres ──────────────────────────────────────────────────────────────

    def start(self, export_id: str) -> StartResult:
        """Démarre ou reprend un export. Réponse immédiate : refusé, ou lancé en tâche de fond.
        Quand la collecte se termine, la validation s'enchaîne automatiquement."""
        return self._launch(export_id, validate_only=False)

    def validate(self, export_id: str) -> StartResult:
        """(Re)lance la validation d'un export dont la collecte est terminée."""
        return self._launch(export_id, validate_only=True)

    def _launch(self, export_id: str, *, validate_only: bool) -> StartResult:
        with self._lock:
            if self.is_busy():
                return StartResult(False, f"Un export tourne déjà dans cette application ({self._export_id}).")
            conn = self._connect()
            try:
                row = ss.get_export(conn, export_id)
                if validate_only:
                    if not (row["pagination_finished"] and row["status"] in (S.INCOMPLETE.value, S.FAILED.value)):
                        return StartResult(False, f"Statut {row['status']} : rien à valider.")
                    if self._storage_factory is None:
                        return StartResult(False, "Stockage non configuré (supabase_url, supabase_service_key).")
                elif row["status"] not in RESUMABLE:
                    return StartResult(False, f"Statut {row['status']} : cet export ne peut pas être (re)lancé.")
                elif row["status"] in (S.INCOMPLETE.value, S.FAILED.value) and row["pagination_finished"]:
                    return StartResult(False, "Collecte déjà terminée : utilisez « Valider ».")
                ss.get_config(conn, export_id)  # refuse une configuration altérée (empreinte)
                if not ss.acquire_lease(conn, export_id, self.owner, self.lease_ttl_s):
                    return StartResult(False, "Un autre export est en cours, ou celui-ci est tenu ailleurs.")
            except (ss.StateError, ValueError, psycopg.Error) as exc:
                return StartResult(False, mask(f"Démarrage refusé : {exc}"))
            finally:
                conn.close()

            self._stop_event = threading.Event()
            self._export_id = export_id
            self.last_result = None
            self._thread = threading.Thread(target=self._run, args=(export_id, self._stop_event, validate_only),
                                            name=f"bulk-export-{export_id}", daemon=True)
            self._thread.start()
            return StartResult(True, "Validation lancée en arrière-plan." if validate_only
                               else "Export lancé en arrière-plan.")

    def request_stop(self, export_id: str) -> None:
        """« Arrêter après la page en cours » : drapeau en base (et signal local si c'est notre export)."""
        conn = self._connect()
        try:
            ss.request_stop(conn, export_id)
        finally:
            conn.close()
        if self._export_id == export_id:
            self._stop_event.set()

    def recover(self, auto_resume: bool = False) -> list[str]:
        """À appeler au chargement de la page : orphelins → PAUSED ; option : relance du plus récent."""
        conn = self._connect()
        try:
            orphans = ss.recover_orphans(conn)
        finally:
            conn.close()
        if orphans:
            logger.warning("Exports orphelins repassés en PAUSED : %s", ", ".join(orphans))
        if auto_resume and orphans and not self.is_busy():
            result = self.start(orphans[0])
            logger.info("Reprise automatique de %s : %s", orphans[0], result.message)
        return orphans

    # ─── Tâche de fond ───────────────────────────────────────────────────────

    def _run(self, export_id: str, stop_event: threading.Event, validate_only: bool = False) -> None:
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat, args=(export_id, heartbeat_stop),
                                     name=f"bulk-heartbeat-{export_id}", daemon=True)
        heartbeat.start()
        try:
            if not validate_only:
                engine = ExportEngine(self._connect, self._adapter_factory, owner=self.owner,
                                      lease_ttl_s=self.lease_ttl_s, **self._engine_kwargs)
                self.last_result = engine.run(export_id, should_stop=stop_event.is_set)
                logger.info("Export %s : %s (%s)", export_id, self.last_result.outcome, self.last_result.message)
            if validate_only or self.last_result.outcome in ("FINISHED", "NOTHING_TO_DO"):
                self._finalize(export_id)
        except Exception as exc:  # ex. base injoignable au démarrage : jamais de tâche morte en silence
            logger.exception("Tâche d'export %s arrêtée par une erreur imprévue", export_id)
            self._mark_failed(export_id, exc)
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=5)

    def _finalize(self, export_id: str) -> None:
        """Validation dans la même tâche de fond, sous bail (collecte → validation sans interruption)."""
        from bulk_export.finalize import finalize

        conn = self._connect()
        try:
            if self._storage_factory is None:
                ss.add_event(conn, export_id, "WARNING", "Stockage non configuré : validation impossible "
                             "(renseignez supabase_url et supabase_service_key).")
                return
            if not ss.acquire_lease(conn, export_id, self.owner, self.lease_ttl_s):
                ss.add_event(conn, export_id, "WARNING", "Validation non lancée : un autre export est en cours.")
                return
            try:
                config = ss.get_config(conn, export_id)
                result = finalize(conn, export_id, self._storage_factory(), self._adapter_factory(config),
                                  check_lease=lambda: ss.renew_lease(conn, export_id, self.owner, self.lease_ttl_s),
                                  purge_raw=self._purge_raw)
                logger.info("Validation de %s : %s %s", export_id, result.status, result.message)
            finally:
                ss.release_lease(conn, export_id, self.owner)
        finally:
            conn.close()

    def _heartbeat(self, export_id: str, stop: threading.Event) -> None:
        conn: psycopg.Connection | None = None
        while not stop.wait(self.heartbeat_s):
            try:
                if conn is None or conn.closed:
                    conn = self._connect()
                # Un refus (bail rendu entre la collecte et la validation) n'arrête pas le battement :
                # il reprend dès que la validation a repris le bail.
                ss.renew_lease(conn, export_id, self.owner, self.lease_ttl_s)
            except Exception as exc:
                logger.warning("Battement de cœur de %s manqué : %s", export_id, mask(exc))
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = None
        if conn is not None:
            conn.close()

    def _mark_failed(self, export_id: str, exc: Exception) -> None:
        message = mask(f"{type(exc).__name__} : {exc}")
        try:
            conn = self._connect()
            try:
                row = ss.get_export(conn, export_id)
                if row["status"] in (S.RUNNING.value, S.STOPPING.value, S.PENDING.value, S.PAUSED.value):
                    ss.set_status(conn, export_id, S.FAILED, error_details={"type": type(exc).__name__,
                                                                            "message": message})
                ss.add_event(conn, export_id, "ERROR", f"Erreur imprévue de la tâche d'export : {message}")
                ss.release_lease(conn, export_id, self.owner)
            finally:
                conn.close()
        except Exception as inner:
            logger.error("Impossible d'enregistrer l'échec de %s : %s", export_id, mask(inner))
        self.last_result = EngineResult(export_id, "FAILED", None, 0, message)


# ─── Construction avec les vrais paramètres ───────────────────────────────────

def build_runner(settings, credentials, **kwargs: Any) -> ExportRunner:
    """Gestionnaire branché sur la vraie base et la vraie API (paramètres de settings.py)."""
    from bulk_export import db

    def connect() -> psycopg.Connection:
        return db.connect(settings)

    def adapter_factory(config: ExportConfig) -> PaginationAdapter:
        http = RatingsReviewsHttpClient(credentials.token, base_url=credentials.base_url)
        return RatingsReviewsAdapter(http, config.filters, rows=config.rows, pagination=config.pagination)

    storage_factory = None
    if settings.supabase_url and settings.supabase_service_key:
        from bulk_export.storage import build_storage

        def storage_factory():
            return build_storage(settings)

    kwargs.setdefault("storage_factory", storage_factory)
    kwargs.setdefault("purge_raw_after_validation", settings.purge_raw_after_validation)
    return ExportRunner(connect, adapter_factory, **kwargs)
