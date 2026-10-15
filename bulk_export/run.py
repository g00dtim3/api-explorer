"""
bulk_export/run.py
──────────────────────────────────────────────────────────────
Lancement d'un export en ligne de commande (même moteur, mêmes règles de bail que l'application).

    python -m bulk_export.run --create ma_config.json   # crée un export et le lance
    python -m bulk_export.run --export-id exp_…          # reprend un export
    python -m bulk_export.run --status exp_…             # affiche l'état d'un export
    python -m bulk_export.run --recover                  # orphelins → PAUSED

Paramètres lus dans les variables d'environnement (jamais en argument, pour ne pas laisser de secret
dans l'historique du terminal) : BULK_EXPORT_API_TOKEN, BULK_EXPORT_DATABASE_URL, et en option
BULK_EXPORT_DB_SCHEMA, BULK_EXPORT_API_BASE_URL.

Ctrl+C (ou SIGTERM) : arrêt propre après la page en cours → PAUSED, reprenable.

Codes de sortie : 0 terminé / en pause / rien à faire · 1 échec · 2 refusé · 3 paramètres invalides.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from bulk_export import db, state_store as ss
from bulk_export.logging_utils import mask
from bulk_export.models import ConfigError, ExportConfig
from bulk_export.runner import DEFAULT_HEARTBEAT_S, DEFAULT_LEASE_TTL_S, build_runner
from bulk_export.settings import SettingsError, load_api_credentials, load_settings

EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2, 3


def _print(message: str) -> None:
    print(mask(message), flush=True)


def _status(conn, export_id: str) -> None:
    row = ss.get_export(conn, export_id)
    keys = ("export_id", "name", "status", "expected_count", "retrieved_count", "unique_count",
            "duplicate_count", "collision_count", "error_count", "pages_count", "pagination_finished",
            "created_at", "last_updated_at")
    _print(json.dumps({k: row[k] for k in keys}, default=str, ensure_ascii=False, indent=2))
    for event in reversed(ss.list_events(conn, export_id, limit=10)):
        _print(f"  [{event['level']}] {event['message']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bulk_export.run", description="Bulk Export V2")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--create", metavar="CONFIG.json", help="crée un export à partir d'une configuration et le lance")
    group.add_argument("--export-id", help="reprend un export existant")
    group.add_argument("--status", metavar="EXPORT_ID", help="affiche l'état d'un export")
    group.add_argument("--recover", action="store_true", help="repasse les exports orphelins en PAUSED")
    parser.add_argument("--lease-ttl", type=int, default=DEFAULT_LEASE_TTL_S, help=argparse.SUPPRESS)
    parser.add_argument("--heartbeat", type=float, default=DEFAULT_HEARTBEAT_S, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        settings = load_settings(use_streamlit=False)
        if args.status or args.recover:
            conn = db.connect(settings)
            try:
                if args.status:
                    _status(conn, args.status)
                else:
                    _print(f"Orphelins repassés en PAUSED : {ss.recover_orphans(conn) or 'aucun'}")
            finally:
                conn.close()
            return EXIT_OK
        credentials = load_api_credentials(use_streamlit=False)
    except (SettingsError, ss.StateError, ValueError) as exc:
        _print(f"Paramètres invalides : {exc}")
        return EXIT_USAGE

    runner = build_runner(settings, credentials, lease_ttl_s=args.lease_ttl, heartbeat_s=args.heartbeat)

    export_id = args.export_id
    if args.create:
        try:
            config = ExportConfig.from_json(Path(args.create).read_text(encoding="utf-8"))
        except (OSError, ConfigError) as exc:
            _print(f"Configuration refusée : {exc}")
            return EXIT_USAGE
        conn = db.connect(settings)
        try:
            export_id = ss.create_export(conn, config)
        finally:
            conn.close()
        _print(f"Export créé : {export_id}")

    def stop(signum, frame):  # Ctrl+C / SIGTERM : arrêt propre après la page en cours
        _print("Arrêt demandé : fin de la page en cours, puis pause…")
        runner.request_stop(export_id)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    started = runner.start(export_id)
    _print(f"{export_id} : {started.message}")
    if not started.ok:
        return EXIT_REFUSED
    while not runner.wait(timeout=1.0):
        pass
    result = runner.last_result
    _print(f"{export_id} : {result.outcome} (statut {result.status}). {result.message}".strip())
    if result.outcome == "FAILED":
        return EXIT_FAILED
    if result.outcome in ("REFUSED", "LEASE_LOST"):
        return EXIT_REFUSED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
