"""
bulk_export/finalize.py
──────────────────────────────────────────────────────────────
Après la collecte : VALIDATING → fichiers fabriqués et envoyés → contrôles → COMPLETED / INCOMPLETE / FAILED.
Puis rétention : mentions effacées de la base après COMPLETED ; fichiers expirés supprimés de Storage.

La validation est reprenable : si l'application redémarre pendant VALIDATING, l'export revient à INCOMPLETE
(détection des orphelins) et la validation se relance ; les fichiers sont simplement refabriqués.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bulk_export import downloads, state_store as ss, validation
from bulk_export.api_adapter import PaginationAdapter
from bulk_export.api_http import ApiError
from bulk_export.logging_utils import get_logger, mask
from bulk_export.models import ExportStatus as S
from bulk_export.storage import Storage, StorageError

logger = get_logger(__name__)
FINAL_KINDS = ("batch_jsonl", "csv_complete", "xlsx", "csv_plat", "manifest", "zip")


@dataclass(frozen=True)
class FinalizeResult:
    export_id: str
    status: str | None
    passed: bool
    message: str = ""


def finalize(conn, export_id: str, storage: Storage, adapter: PaginationAdapter, *,
             workdir_root: str | None = None, check_lease=None) -> FinalizeResult:
    """Valide un export dont la collecte est terminée. ``check_lease()`` → False si le bail est perdu."""
    row = ss.get_export(conn, export_id)
    if not row["pagination_finished"] or row["status"] not in (S.INCOMPLETE.value, S.FAILED.value):
        return FinalizeResult(export_id, row["status"], False, "Rien à valider (collecte non terminée ou déjà validé).")
    config = ss.get_config(conn, export_id)
    ss.set_status(conn, export_id, S.VALIDATING)
    ss.add_event(conn, export_id, "INFO", "Validation : fabrication des fichiers et contrôles…")
    workdir = Path(tempfile.mkdtemp(prefix="bulk_export_", dir=workdir_root))
    try:
        # Fichiers d'une validation précédente : remplacés (chemins identiques, envoi en écrasement).
        built = downloads.build_and_upload_data_files(conn, export_id, config, storage, workdir)
        ss.replace_files(conn, export_id, built.files, kinds=FINAL_KINDS)
        ss.add_event(conn, export_id, "INFO", f"{len(built.files)} fichier(s) envoyé(s) dans Storage. Relecture…")

        try:
            expected_now, metrics_error = adapter.expected_count(), None
        except ApiError as exc:
            expected_now, metrics_error = None, str(exc)
        row = ss.get_export(conn, export_id)
        checks, final = validation.run_checks(conn, row, config, storage, built.files, expected_now=expected_now,
                                              metrics_error=metrics_error, local_csv=built.csv_file)
        content_bytes = sum(f.content_bytes or 0 for f in built.files if f.kind == "batch_jsonl")
        result = {
            "passed": final == S.COMPLETED.value, "final_status": final, "rule": "A",
            "validated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "expected_at_end": expected_now, "checks": validation.checks_to_json(checks),
            "stats": {"mentions": row["unique_count"], "content_bytes": content_bytes},
            "derived_formats": built.derived,
        }
        manifest = downloads.build_manifest(row, config, built.files, ss.list_duplicates(conn, export_id),
                                            ss.count_conflicts(conn, export_id, "collision"), result, final)
        extra = downloads.upload_manifest_and_zip(export_id, config, storage, workdir, manifest, built)
        _verify_uploaded(storage, extra)
        ss.replace_files(conn, export_id, built.files + extra, kinds=FINAL_KINDS)
        ss.set_validation(conn, export_id, result)

        if check_lease is not None and not check_lease():
            raise ss.LeaseLostError("Bail perdu pendant la validation.")
        ss.set_status(conn, export_id, final)
        failed = [c.name for c in checks if c.ok is False]
        if final == S.COMPLETED.value:
            ss.add_event(conn, export_id, "INFO", "Validation réussie : export COMPLETED.")
            ss.purge_raw_mentions(conn, export_id)
        else:
            ss.add_event(conn, export_id, "ERROR" if final == "FAILED" else "WARNING",
                         f"Validation : {final}. Contrôles en échec : {', '.join(failed)}.")
        return FinalizeResult(export_id, final, final == S.COMPLETED.value, ", ".join(failed))
    except Exception as exc:
        message = mask(f"{type(exc).__name__} : {exc}")
        logger.exception("Validation de %s interrompue", export_id)
        try:
            if ss.get_export(conn, export_id)["status"] == S.VALIDATING.value:
                ss.set_status(conn, export_id, S.FAILED, error_details={"type": type(exc).__name__,
                                                                        "message": message, "step": "validation"})
            ss.add_event(conn, export_id, "ERROR", f"Validation interrompue : {message}")
        except Exception as inner:
            logger.error("Impossible d'enregistrer l'échec de validation de %s : %s", export_id, mask(inner))
        return FinalizeResult(export_id, S.FAILED.value, False, message)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _verify_uploaded(storage: Storage, records: list[ss.FileRecord]) -> None:
    """Relit le manifeste et le ZIP envoyés : empreinte identique, sinon erreur."""
    import hashlib
    for f in records:
        digest = hashlib.sha256()
        for block in storage.iter_bytes(f.path):
            digest.update(block)
        if digest.hexdigest() != f.sha256:
            raise StorageError(f"{f.path} : empreinte relue différente après envoi.")


# ─── Rétention et suppression ─────────────────────────────────────────────────

def apply_retention(conn, storage: Storage, retention_days: int) -> list[str]:
    """Exports COMPLETED dont les fichiers ont dépassé la durée de conservation : fichiers supprimés de
    Storage, fiche gardée dans l'historique (« fichiers expirés »)."""
    expired = []
    for export_id in ss.exports_with_expired_files(conn, retention_days):
        paths = [f["path"] for f in ss.list_files(conn, export_id)]
        try:
            if paths:
                storage.delete(paths)
        except StorageError as exc:
            logger.warning("Rétention de %s : suppression impossible (%s)", export_id, mask(exc))
            continue
        ss.mark_files_expired(conn, export_id)
        expired.append(export_id)
    return expired


def delete_everywhere(conn, storage: Storage | None, export_id: str, *, confirm_resumable: bool = False) -> None:
    """Supprime un export : fichiers dans Storage, puis tout en base. Mêmes garde-fous que ss.delete_export."""
    row = ss.get_export(conn, export_id)
    # Garde-fous AVANT de toucher aux fichiers (on ne supprime rien si la suppression serait refusée).
    if row["lease_owner"] and conn.execute("SELECT lease_expires_at > now() FROM exports WHERE export_id = %s",
                                           (export_id,)).fetchone()[0]:
        raise ss.StateError("Export en cours : arrêtez-le avant de le supprimer.")
    if row["status"] in ("PENDING", "PAUSED", "FAILED", "INCOMPLETE") and not confirm_resumable:
        raise ss.StateError("Cet export est encore reprenable ou validable : confirmation explicite nécessaire.")
    paths = [f["path"] for f in ss.list_files(conn, export_id)]
    if paths:
        if storage is None:
            raise ss.StateError("Stockage non configuré : impossible de supprimer les fichiers de cet export.")
        storage.delete(paths)
    ss.delete_export(conn, export_id, confirm_resumable=confirm_resumable)
