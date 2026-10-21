"""Test de résistance sur de vrais processus : `python -m bulk_export.run` tué brutalement (kill -9).

Faux serveur API local en HTTP (127.0.0.1) ; base de test. Le résultat après reprise doit être
identique à un export sans interruption : mêmes mentions, même ordre, aucun doublon.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bulk_export import state_store as ss
from tests.fake_api import FAKE_TOKEN, FakePagedServer, SlowServer, serve_http
from tests.test_engine_db import fake_pages

pytestmark = pytest.mark.db
REPO = Path(__file__).resolve().parents[1]
TEST_SCHEMA = "bulk_export_test"


def cli_env(base_url):
    return {**os.environ, "PYTHONPATH": str(REPO), "BULK_EXPORT_API_TOKEN": FAKE_TOKEN,
            "BULK_EXPORT_API_BASE_URL": base_url, "BULK_EXPORT_DB_SCHEMA": TEST_SCHEMA,
            "BULK_EXPORT_DATABASE_URL": os.environ["BULK_EXPORT_TEST_DATABASE_URL"]}


def run_cli(args, env, **kw):
    return subprocess.Popen([sys.executable, "-m", "bulk_export.run", *args], cwd=REPO, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kw)


def mentions(conn, export_id):
    return conn.execute("SELECT seq, mention_id FROM raw_mentions WHERE export_id = %s ORDER BY seq",
                        (export_id,)).fetchall()


def test_kill_9_puis_reprise_sans_perte_ni_doublon(pg_conn, tmp_path):
    pages = fake_pages(total=60, size=3)  # 20 pages
    httpd, base_url = serve_http(SlowServer(FakePagedServer(pages), delay=0.15))
    env = cli_env(base_url)
    config = tmp_path / "fake_config.json"
    config.write_text(json.dumps({"name": "fake kill", "filters": {"brand": "FAKE_BRAND"}, "rows": 3}))
    try:
        # 1) Export de référence, sans interruption.
        ref = run_cli(["--create", str(config)], env)
        out, _ = ref.communicate(timeout=60)
        assert ref.returncode == 0, out
        ref_id = out.split("Export créé : ")[1].split()[0]
        reference = mentions(pg_conn, ref_id)
        assert len(reference) == 60

        # 2) Même export, tué brutalement au milieu (bail court : 2 s).
        proc = run_cli(["--create", str(config), "--lease-ttl", "2", "--heartbeat", "0.5"], env)
        deadline = time.monotonic() + 30
        export_id = None
        while time.monotonic() < deadline:
            rows = pg_conn.execute("SELECT export_id, pages_count FROM exports WHERE export_id <> %s",
                                   (ref_id,)).fetchall()
            if rows and rows[0][1] >= 4:
                export_id = rows[0][0]
                break
            time.sleep(0.05)
        assert export_id, "l'export n'a pas avancé"
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)
        killed_at = ss.get_export(pg_conn, export_id)
        assert killed_at["status"] == "RUNNING" and killed_at["pages_count"] < 21

        # 3) Tant que le bail court, rien n'est touché ; ensuite, orphelin → PAUSED.
        assert ss.recover_orphans(pg_conn) == [] or killed_at["lease_expires_at"] is None
        time.sleep(2.5)
        assert ss.recover_orphans(pg_conn) == [export_id]
        assert ss.get_export(pg_conn, export_id)["status"] == "PAUSED"

        # 4) Reprise en ligne de commande.
        resume = run_cli(["--export-id", export_id], env)
        out, _ = resume.communicate(timeout=60)
        assert resume.returncode == 0, out
        assert FAKE_TOKEN not in out

        # 5) Identique à la référence : mêmes mentions, même ordre, aucun doublon.
        final = ss.get_export(pg_conn, export_id)
        assert final["status"] == "INCOMPLETE" and final["duplicate_count"] == 0
        assert mentions(pg_conn, export_id) == reference
    finally:
        httpd.shutdown()


def test_cli_ctrl_c_arret_propre(pg_conn, tmp_path):
    httpd, base_url = serve_http(SlowServer(FakePagedServer(fake_pages(total=60)), delay=0.15))
    config = tmp_path / "fake_config.json"
    config.write_text(json.dumps({"name": "fake ctrl-c", "filters": {"brand": "FAKE_BRAND"}, "rows": 3}))
    try:
        proc = run_cli(["--create", str(config)], cli_env(base_url))
        assert pg_wait_pages(pg_conn, 2)
        proc.send_signal(signal.SIGINT)
        out, _ = proc.communicate(timeout=30)
        assert proc.returncode == 0, out
        (export_id,) = [r[0] for r in pg_conn.execute("SELECT export_id FROM exports").fetchall()]
        row = ss.get_export(pg_conn, export_id)
        assert row["status"] == "PAUSED" and row["lease_owner"] is None and "PAUSED" in out
    finally:
        httpd.shutdown()


def pg_wait_pages(conn, n, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        row = conn.execute("SELECT max(pages_count) FROM exports").fetchone()
        if row and row[0] and row[0] >= n:
            return True
        time.sleep(0.05)
    return False


def test_cli_parametres_manquants():
    env = {k: v for k, v in os.environ.items() if not k.startswith("BULK_EXPORT_")}
    env["PYTHONPATH"] = str(REPO)
    proc = subprocess.run([sys.executable, "-m", "bulk_export.run", "--export-id", "x"], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 3 and "database_url" in proc.stdout
