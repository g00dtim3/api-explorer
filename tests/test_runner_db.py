"""Gestionnaire d'exécution (tâche de fond, bail, orphelins). Base de test + faux serveur API."""

import os
import time

import pytest

from bulk_export import db, state_store as ss
from bulk_export.api_adapter import RatingsReviewsAdapter
from bulk_export.api_http import RatingsReviewsHttpClient
from bulk_export.models import ExportConfig
from bulk_export.retry import RetryPolicy
from bulk_export.runner import ExportRunner
from bulk_export.settings import load_settings
from tests.fake_api import FAKE_TOKEN, FakePagedServer, SlowServer
from tests.test_engine_db import fake_pages

pytestmark = pytest.mark.db
TEST_SCHEMA = "bulk_export_test"
fake_config = ExportConfig(name="fake runner", filters={"brand": "FAKE_BRAND"}, rows=3)


@pytest.fixture
def connect(pg_conn):
    settings = load_settings({"database_url": os.environ["BULK_EXPORT_TEST_DATABASE_URL"],
                              "db_schema": TEST_SCHEMA})
    return lambda: db.connect(settings, attempts=1)


def make_runner(connect, server, **kw):
    def factory(config):
        http = RatingsReviewsHttpClient(FAKE_TOKEN, session=server)
        return RatingsReviewsAdapter(http, config.filters, rows=config.rows,
                                     retry_policy=RetryPolicy(max_attempts=2), sleep=lambda s: None)
    kw.setdefault("lease_ttl_s", 5)
    kw.setdefault("heartbeat_s", 1)
    return ExportRunner(connect, factory, **kw)


def wait_until(predicate, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_demarrage_jusqu_a_incomplete(pg_conn, connect):
    export_id = ss.create_export(pg_conn, fake_config)
    runner = make_runner(connect, FakePagedServer(fake_pages()))
    assert runner.start(export_id).ok
    assert runner.wait(10)
    assert runner.last_result.outcome == "FINISHED"
    row = ss.get_export(pg_conn, export_id)
    assert row["status"] == "INCOMPLETE" and row["unique_count"] == 8 and row["lease_owner"] is None


def test_deux_demarrages_le_second_refuse(pg_conn, connect):
    first = ss.create_export(pg_conn, fake_config)
    second = ss.create_export(pg_conn, fake_config)
    slow = SlowServer(FakePagedServer(fake_pages()), delay=0.3)
    runner_a = make_runner(connect, slow)
    runner_b = make_runner(connect, slow)  # autre « application » (autre processus)
    assert runner_a.start(first).ok
    refused_same = runner_a.start(second)
    refused_other = runner_b.start(second)
    refused_same_export = runner_b.start(first)
    assert not refused_same.ok and "déjà" in refused_same.message
    assert not refused_other.ok and not refused_same_export.ok
    assert runner_a.wait(15)


def test_arret_demande_pause_apres_la_page_en_cours(pg_conn, connect):
    export_id = ss.create_export(pg_conn, fake_config)
    runner = make_runner(connect, SlowServer(FakePagedServer(fake_pages()), delay=0.3))
    assert runner.start(export_id).ok
    assert wait_until(lambda: ss.get_export(pg_conn, export_id)["pages_count"] >= 1)
    runner.request_stop(export_id)
    assert runner.wait(10)
    row = ss.get_export(pg_conn, export_id)
    assert row["status"] == "PAUSED" and 1 <= row["pages_count"] < 4 and not row["stop_requested"]
    # Reprise : va au bout
    assert runner.start(export_id).ok and runner.wait(10)
    assert ss.get_export(pg_conn, export_id)["unique_count"] == 8


def test_erreur_imprevue_dans_la_tache_failed(pg_conn, connect):
    export_id = ss.create_export(pg_conn, fake_config)
    calls = {"n": 0}

    def flaky_connect():
        calls["n"] += 1
        if calls["n"] == 2:  # 1 = start() ; 2 = connexion du moteur dans la tâche de fond
            raise RuntimeError("base injoignable (simulée)")
        return connect()

    runner = make_runner(flaky_connect, FakePagedServer(fake_pages()))
    assert runner.start(export_id).ok
    assert runner.wait(10)
    row = ss.get_export(pg_conn, export_id)
    assert runner.last_result.outcome == "FAILED" and row["status"] == "FAILED" and row["lease_owner"] is None
    assert any("imprévue" in e["message"] for e in ss.list_events(pg_conn, export_id))


def test_battement_de_coeur_garde_le_bail_pendant_une_longue_page(pg_conn, connect):
    export_id = ss.create_export(pg_conn, fake_config)
    # Une page met 3 s, le bail ne dure que 2 s : sans battement de cœur, il expirerait.
    runner = make_runner(connect, SlowServer(FakePagedServer(fake_pages(total=3)), delay=3.0),
                         lease_ttl_s=2, heartbeat_s=0.3)
    assert runner.start(export_id).ok
    time.sleep(2.5)
    assert ss.active_export_id(pg_conn) == export_id
    assert ss.recover_orphans(pg_conn) == []           # pas pris pour un orphelin
    assert runner.wait(15) and runner.last_result.outcome == "FINISHED"
    assert ss.active_export_id(pg_conn) is None         # bail rendu, battement arrêté


def test_orphelin_detecte_et_repasse_en_pause(pg_conn, connect):
    orphan = ss.create_export(pg_conn, fake_config)
    alive = ss.create_export(pg_conn, fake_config)
    ss.acquire_lease(pg_conn, orphan, "app-morte", 60)
    ss.set_status(pg_conn, orphan, "RUNNING")
    pg_conn.execute("UPDATE exports SET lease_expires_at = now() - interval '1 second' WHERE export_id = %s",
                    (orphan,))
    pg_conn.execute("UPDATE exports SET status = 'RUNNING' WHERE export_id = %s", (alive,))
    pg_conn.execute("UPDATE exports SET lease_owner = 'app-vivante', lease_expires_at = now() + interval '1 minute' "
                    "WHERE export_id = %s", (alive,))
    runner = make_runner(connect, FakePagedServer(fake_pages()))
    assert runner.recover() == [orphan]
    assert ss.get_export(pg_conn, orphan)["status"] == "PAUSED"
    assert ss.get_export(pg_conn, alive)["status"] == "RUNNING"
    assert any("redémarrage" in e["message"] for e in ss.list_events(pg_conn, orphan))
    assert not runner.is_busy()  # pas de reprise automatique par défaut


def test_reprise_automatique_si_activee(pg_conn, connect):
    orphan = ss.create_export(pg_conn, fake_config)
    ss.acquire_lease(pg_conn, orphan, "app-morte", 60)
    ss.set_status(pg_conn, orphan, "RUNNING")
    pg_conn.execute("UPDATE exports SET lease_expires_at = now() - interval '1 second'")
    runner = make_runner(connect, FakePagedServer(fake_pages()))
    assert runner.recover(auto_resume=True) == [orphan]
    assert runner.wait(10) and ss.get_export(pg_conn, orphan)["status"] == "INCOMPLETE"


def test_statut_non_reprenable_refuse(pg_conn, connect):
    export_id = ss.create_export(pg_conn, fake_config)
    runner = make_runner(connect, FakePagedServer(fake_pages()))
    assert runner.start(export_id).ok and runner.wait(10)
    again = runner.start(export_id)
    assert not again.ok and "Valider" in again.message


def test_configuration_alteree_refusee(pg_conn, connect):
    export_id = ss.create_export(pg_conn, fake_config)
    pg_conn.execute("""UPDATE exports SET config_json = jsonb_set(config_json, '{filters,brand}', '"AUTRE"')""")
    result = make_runner(connect, FakePagedServer(fake_pages())).start(export_id)
    assert not result.ok and "empreinte" in result.message
