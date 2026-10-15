"""Moteur d'export sur la base de test, avec un faux serveur API paginé.

Nécessite BULK_EXPORT_TEST_DATABASE_URL (sinon sauté). Données synthétiques fake_*.
"""

import json
import os

import psycopg
import pytest

from bulk_export import db, state_store as ss
from bulk_export.api_adapter import RatingsReviewsAdapter
from bulk_export.api_http import RatingsReviewsHttpClient
from bulk_export.engine import ExportEngine
from bulk_export.models import ExportConfig, ExportStatus as S
from bulk_export.retry import RetryPolicy
from bulk_export.settings import load_settings
from tests.fake_api import FAKE_TOKEN, FakePagedServer, FakeResponse, conn_error

pytestmark = pytest.mark.db
TEST_SCHEMA = "bulk_export_test"
fake_config = ExportConfig(name="fake moteur", filters={"brand": "FAKE_BRAND"}, rows=3)


def fake_doc(n, **extra):
    return {"id": str(n), "brand": "FAKE_BRAND", "date": f"2024-11-{(n % 28) + 1:02d}T10:00:00Z",
            "product": "fake product", "country": "France", "source": "Fake", "rating": (n % 5) + 1,
            "verbatim content": f"fake verbatim {n}", **extra}


def fake_pages(total=8, size=3):
    docs = [fake_doc(n) for n in range(1, total + 1)]
    return [docs[i:i + size] for i in range(0, total, size)]


@pytest.fixture
def connect(pg_conn):
    settings = load_settings({"database_url": os.environ["BULK_EXPORT_TEST_DATABASE_URL"],
                              "db_schema": TEST_SCHEMA})
    return lambda: db.connect(settings, attempts=1)


def make_engine(connect, server, owner="fake-owner", **kw):
    def factory(config):
        http = RatingsReviewsHttpClient(FAKE_TOKEN, session=server)
        return RatingsReviewsAdapter(http, config.filters, rows=config.rows, pagination=config.pagination,
                                     retry_policy=RetryPolicy(max_attempts=2), sleep=lambda s: None)
    return ExportEngine(connect, factory, owner=owner, sleep=lambda s: None, **kw)


def stored(conn, export_id):
    """(seq, mention_id, raw_json) dans l'ordre d'arrivée."""
    return conn.execute("SELECT seq, mention_id, raw_json FROM raw_mentions WHERE export_id = %s ORDER BY seq",
                        (export_id,)).fetchall()


def events(conn, export_id):
    return [e["message"] for e in reversed(ss.list_events(conn, export_id, limit=500))]


# ─── Parcours complet ─────────────────────────────────────────────────────────

def test_export_complet_jusqu_a_incomplete(pg_conn, connect):
    server = FakePagedServer(fake_pages())
    export_id = ss.create_export(pg_conn, fake_config)
    result = make_engine(connect, server).run(export_id)
    assert result.outcome == "FINISHED" and result.status == "INCOMPLETE"  # jamais COMPLETED ici
    row = ss.get_export(pg_conn, export_id)
    assert (row["expected_count"], row["unique_count"], row["retrieved_count"]) == (8, 8, 8)
    assert row["pagination_finished"] and row["lease_owner"] is None
    assert [s for s, *_ in stored(pg_conn, export_id)] == list(range(1, 9))
    assert [json.loads(r)["id"] for *_, r in stored(pg_conn, export_id)] == [str(n) for n in range(1, 9)]
    # 3 pages de données + la page vide de fin
    assert row["pages_count"] == 4


def test_champs_au_journal_sans_valeurs(pg_conn, connect):
    server = FakePagedServer(fake_pages())
    export_id = ss.create_export(pg_conn, fake_config)
    make_engine(connect, server).run(export_id)
    log = events(pg_conn, export_id)
    assert any(m.startswith("Champs reçus : brand, country, date, id, product, rating, source, verbatim content")
               for m in log)
    assert not any("fake verbatim" in m for m in log)


def test_doublons_et_jumelles_entre_pages(pg_conn, connect):
    p1 = [fake_doc(1), fake_doc(2)]
    p2 = [{**fake_doc(1), "id": "77"}, fake_doc(3), {**fake_doc(2), "opinion": "negative"}]
    server = FakePagedServer([p1, p2])
    export_id = ss.create_export(pg_conn, fake_config)
    make_engine(connect, server).run(export_id)
    row = ss.get_export(pg_conn, export_id)
    assert (row["retrieved_count"], row["unique_count"], row["duplicate_count"], row["collision_count"]) == \
           (5, 4, 1, 1)
    kinds = pg_conn.execute("SELECT kind, api_id FROM conflicts ORDER BY conflict_no").fetchall()
    assert kinds == [("duplicate", "77"), ("collision", None)]


def test_mention_sans_date_rejetee_et_gardee(pg_conn, connect):
    sans_date = fake_doc(2, date="")
    server = FakePagedServer([[fake_doc(1), sans_date]])
    export_id = ss.create_export(pg_conn, fake_config)
    make_engine(connect, server).run(export_id)
    row = ss.get_export(pg_conn, export_id)
    assert (row["unique_count"], row["error_count"]) == (1, 1)
    raw = pg_conn.execute("SELECT raw_json FROM rejected_mentions WHERE export_id = %s", (export_id,)).fetchone()[0]
    assert json.loads(raw) == sans_date


def test_verbatims_speciaux_relus_identiques(pg_conn, connect):
    docs = [fake_doc(1, **{"verbatim content": "Accents é è à ç, emoji 🙂👍, \"guillemets\", ; \n\r\t retour  "}),
            fake_doc(2, **{"verbatim content": "é échappé \\ antislash", "attributes": ["Texture", None]})]
    server = FakePagedServer([docs])
    export_id = ss.create_export(pg_conn, fake_config)
    make_engine(connect, server).run(export_id)
    assert [json.loads(r) for *_, r in stored(pg_conn, export_id)] == docs


# ─── Arrêt et reprise ─────────────────────────────────────────────────────────

def reference_run(pg_conn, connect):
    export_id = ss.create_export(pg_conn, fake_config)
    make_engine(connect, FakePagedServer(fake_pages())).run(export_id)
    return [(s, m) for s, m, _ in stored(pg_conn, export_id)]


def test_arret_puis_reprise_identique_a_une_traite(pg_conn, connect):
    reference = reference_run(pg_conn, connect)
    export_id = ss.create_export(pg_conn, fake_config)
    calls = {"n": 0}

    def stop_after_first_page():
        calls["n"] += 1
        return calls["n"] >= 1

    first = make_engine(connect, FakePagedServer(fake_pages())).run(export_id, should_stop=stop_after_first_page)
    assert first.outcome == "PAUSED" and first.status == "PAUSED" and first.pages_this_run == 1
    assert ss.get_export(pg_conn, export_id)["unique_count"] == 3
    second = make_engine(connect, FakePagedServer(fake_pages())).run(export_id)
    assert second.outcome == "FINISHED"
    assert [(s, m) for s, m, _ in stored(pg_conn, export_id)] == reference


def test_arret_demande_en_base(pg_conn, connect):
    export_id = ss.create_export(pg_conn, fake_config)
    server = FakePagedServer(fake_pages())
    engine = make_engine(connect, server)
    original = ss.renew_lease

    def renew_then_request_stop(conn, *a, **k):
        ss.request_stop(conn, export_id)
        return original(conn, *a, **k)

    ss.renew_lease = renew_then_request_stop
    try:
        result = engine.run(export_id)
    finally:
        ss.renew_lease = original
    assert result.outcome == "PAUSED" and result.pages_this_run == 1


def test_panne_pendant_l_enregistrement_puis_reprise(pg_conn, connect, monkeypatch):
    reference = reference_run(pg_conn, connect)
    export_id = ss.create_export(pg_conn, fake_config)
    real = ss._insert_page_row
    state = {"n": 0}

    def crash_on_page_2(cur, eid, page):
        state["n"] += 1
        if page.page_no == 2:
            raise RuntimeError("panne simulée au milieu de l'enregistrement de la page 2")
        return real(cur, eid, page)

    monkeypatch.setattr(ss, "_insert_page_row", crash_on_page_2)
    first = make_engine(connect, FakePagedServer(fake_pages())).run(export_id)
    assert first.outcome == "FAILED" and first.status == "FAILED"
    row = ss.get_export(pg_conn, export_id)
    assert (row["pages_count"], row["unique_count"], row["last_committed_cursor"]) == (1, 3, "C1")
    assert row["error_details"]["page"] == 2

    monkeypatch.setattr(ss, "_insert_page_row", real)
    second = make_engine(connect, FakePagedServer(fake_pages())).run(export_id)
    assert second.outcome == "FINISHED"
    assert [(s, m) for s, m, _ in stored(pg_conn, export_id)] == reference


def test_coupure_base_juste_apres_l_enregistrement(pg_conn, connect, monkeypatch):
    reference = reference_run(pg_conn, connect)
    export_id = ss.create_export(pg_conn, fake_config)
    real = ss.commit_page
    state = {"done": False}

    def commit_then_lose_connection(conn, eid, owner, page):
        real(conn, eid, owner, page)
        if page.page_no == 2 and not state["done"]:
            state["done"] = True
            raise psycopg.OperationalError("connexion perdue (simulée) après le COMMIT")

    monkeypatch.setattr(ss, "commit_page", commit_then_lose_connection)
    result = make_engine(connect, FakePagedServer(fake_pages())).run(export_id)
    assert result.outcome == "FINISHED"
    assert [(s, m) for s, m, _ in stored(pg_conn, export_id)] == reference
    assert any("déjà enregistrée" in m for m in events(pg_conn, export_id))


def test_coupure_base_avant_l_enregistrement(pg_conn, connect, monkeypatch):
    reference = reference_run(pg_conn, connect)
    export_id = ss.create_export(pg_conn, fake_config)
    real = ss.commit_page
    state = {"done": False}

    def lose_connection_first(conn, eid, owner, page):
        if page.page_no == 2 and not state["done"]:
            state["done"] = True
            raise psycopg.OperationalError("connexion perdue (simulée) avant le COMMIT")
        return real(conn, eid, owner, page)

    monkeypatch.setattr(ss, "commit_page", lose_connection_first)
    result = make_engine(connect, FakePagedServer(fake_pages())).run(export_id)
    assert result.outcome == "FINISHED"
    assert [(s, m) for s, m, _ in stored(pg_conn, export_id)] == reference


# ─── Erreurs ──────────────────────────────────────────────────────────────────

def test_erreur_api_persistante_failed_puis_reprise(pg_conn, connect):
    reference = reference_run(pg_conn, connect)
    export_id = ss.create_export(pg_conn, fake_config)
    broken = FakePagedServer(fake_pages(), failures={("/reviews", "C2"): [conn_error(), conn_error()]})
    first = make_engine(connect, broken).run(export_id)
    assert first.outcome == "FAILED" and ss.get_export(pg_conn, export_id)["pages_count"] == 2
    assert FAKE_TOKEN not in json.dumps(ss.get_export(pg_conn, export_id)["error_details"])
    assert not any(FAKE_TOKEN in m for m in events(pg_conn, export_id))
    second = make_engine(connect, FakePagedServer(fake_pages())).run(export_id)
    assert second.outcome == "FINISHED"
    assert [(s, m) for s, m, _ in stored(pg_conn, export_id)] == reference


def test_token_refuse_failed_immediat(pg_conn, connect):
    server = FakePagedServer(fake_pages(), failures={("/metrics", None): [FakeResponse(401, body=b"no")]})
    export_id = ss.create_export(pg_conn, fake_config)
    result = make_engine(connect, server).run(export_id)
    assert result.outcome == "FAILED" and "ApiAuthError" in result.message
    assert len([c for c in server.calls if c[0] == "/metrics"]) == 1


def test_plafond_de_pages_depasse(pg_conn, connect):
    # /metrics annonce 3 mentions mais l'API continue à renvoyer des pages : boucle infinie évitée.
    endless = FakePagedServer([[fake_doc(n)] for n in range(1, 40)], nb_docs=3)
    config = ExportConfig(name="fake plafond", filters={"brand": "FAKE"}, rows=3,
                          pagination={"page_margin_factor": 1, "page_margin_extra": 2})
    export_id = ss.create_export(pg_conn, config)
    result = make_engine(connect, endless).run(export_id)
    assert result.outcome == "FAILED" and "Plafond de 3 pages" in result.message
    assert ss.get_export(pg_conn, export_id)["pages_count"] == 3


def test_mentions_sans_curseur_failed(pg_conn, connect):
    server = FakePagedServer(fake_pages(), failures={("/reviews", "C1"): [
        FakeResponse(200, {"status": "success", "result": {"nbDocs": 8, "docs": [fake_doc(9)]}})]})
    export_id = ss.create_export(pg_conn, fake_config)
    result = make_engine(connect, server).run(export_id)
    assert result.outcome == "FAILED" and "sans curseur" in result.message
    assert ss.get_export(pg_conn, export_id)["unique_count"] == 3


def test_deux_executants_le_second_refuse(pg_conn, connect):
    export_id = ss.create_export(pg_conn, fake_config)
    assert ss.acquire_lease(pg_conn, export_id, "autre-executant", 60)
    result = make_engine(connect, FakePagedServer(fake_pages())).run(export_id)
    assert result.outcome == "REFUSED" and ss.get_export(pg_conn, export_id)["pages_count"] == 0


def test_export_termine_ou_valide_non_relance(pg_conn, connect):
    export_id = ss.create_export(pg_conn, fake_config)
    make_engine(connect, FakePagedServer(fake_pages())).run(export_id)
    again = make_engine(connect, FakePagedServer(fake_pages())).run(export_id)
    assert again.outcome == "NOTHING_TO_DO" and again.status == "INCOMPLETE"
    ss.set_status(pg_conn, export_id, S.VALIDATING)
    assert make_engine(connect, FakePagedServer(fake_pages())).run(export_id).outcome == "REFUSED"
