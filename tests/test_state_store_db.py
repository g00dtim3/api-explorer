"""État des exports dans Postgres (schéma bulk_export_test).

Nécessite BULK_EXPORT_TEST_DATABASE_URL ; sinon ces tests sont sautés.
Les mentions sont de FAUSSES données (fake_*).
"""

import json

import psycopg
import pytest

from bulk_export import db, state_store as ss
from bulk_export.fingerprints import compute
from bulk_export.models import ExportConfig, ExportStatus as S, InvalidTransitionError

pytestmark = pytest.mark.db

TEST_SCHEMA = "bulk_export_test"
fake_config = ExportConfig(name="fake export", filters={"brand": "FAKE_BRAND"})


def fake_mention(n: int) -> dict:
    return {"id": str(n), "brand": "FAKE_BRAND", "date": "2024-11-28T15:45:28Z", "product": "fake product",
            "country": "France", "source": "Fake Source", "rating": 5, "verbatim content": f"fake verbatim {n}"}


def mention_row(record: dict) -> ss.MentionRow:
    fp = compute(record)
    return ss.MentionRow(mention_id=fp.raw_hash, raw_json=json.dumps(record, ensure_ascii=False),
                         content_key=fp.content_key, compass_id=fp.compass_id, api_id=record.get("id"))


def page(no: int, sent: str, received: str | None, records: list[dict], **kw) -> ss.PageCommit:
    return ss.PageCommit(page_no=no, cursor_sent=sent, cursor_received=received,
                         records_count=len(records), new_mentions=[mention_row(r) for r in records], **kw)


def running_export(conn, owner="fake-owner") -> str:
    export_id = ss.create_export(conn, fake_config, expected_count=4)
    assert ss.acquire_lease(conn, export_id, owner, ttl_seconds=60)
    ss.set_status(conn, export_id, S.RUNNING)
    return export_id


# ─── Migration ────────────────────────────────────────────────────────────────

def test_migration_rejouable(pg_conn):
    db.apply_all_migrations(pg_conn, schema=TEST_SCHEMA)
    db.apply_all_migrations(pg_conn, schema=TEST_SCHEMA)
    tables = {r[0] for r in pg_conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = %s", (TEST_SCHEMA,)).fetchall()}
    assert tables == {"exports", "pages", "raw_mentions", "conflicts", "events", "files", "rejected_mentions"}


def test_rls_active_sur_toutes_les_tables(pg_conn):
    rows = pg_conn.execute(
        """SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = %s AND c.relkind = 'r'""", (TEST_SCHEMA,)).fetchall()
    assert rows and all(rls for _, rls in rows)
    assert pg_conn.execute("SELECT count(*) FROM pg_policies WHERE schemaname = %s",
                           (TEST_SCHEMA,)).fetchone()[0] == 0


@pytest.mark.parametrize("name", db.migration_names())
def test_migration_ne_touche_que_son_schema(name):
    sql = db.migration_sql(name, schema=TEST_SCHEMA)
    assert "bulk_export." not in sql.replace(f"{TEST_SCHEMA}.", "")


# ─── Création, lecture, statuts ───────────────────────────────────────────────

def test_creation_et_relecture(pg_conn):
    export_id = ss.create_export(pg_conn, fake_config, expected_count=1234)
    row = ss.get_export(pg_conn, export_id)
    assert row["status"] == "PENDING" and row["expected_count"] == 1234
    assert ss.get_config(pg_conn, export_id) == fake_config
    assert [e["export_id"] for e in ss.list_exports(pg_conn)] == [export_id]
    assert ss.list_events(pg_conn, export_id)


def test_config_alteree_detectee(pg_conn):
    export_id = ss.create_export(pg_conn, fake_config)
    pg_conn.execute("""UPDATE exports SET config_json = jsonb_set(config_json, '{filters,brand}', '"AUTRE"')
                       WHERE export_id = %s""", (export_id,))
    with pytest.raises(ss.StateError, match="empreinte"):
        ss.get_config(pg_conn, export_id)


def test_transition_interdite_refusee_en_base(pg_conn):
    export_id = ss.create_export(pg_conn, fake_config)
    with pytest.raises(InvalidTransitionError):
        ss.set_status(pg_conn, export_id, S.COMPLETED)
    assert ss.get_export(pg_conn, export_id)["status"] == "PENDING"


def test_completed_exige_une_validation_reussie(pg_conn):
    export_id = running_export(pg_conn)
    ss.set_status(pg_conn, export_id, S.INCOMPLETE)
    ss.set_status(pg_conn, export_id, S.VALIDATING)
    with pytest.raises(ss.StateError, match="validation"):
        ss.set_status(pg_conn, export_id, S.COMPLETED)
    ss.set_validation(pg_conn, export_id, {"passed": False, "reason": "fake"})
    with pytest.raises(ss.StateError):
        ss.set_status(pg_conn, export_id, S.COMPLETED)
    ss.set_validation(pg_conn, export_id, {"passed": True})
    ss.set_status(pg_conn, export_id, S.COMPLETED)
    row = ss.get_export(pg_conn, export_id)
    assert row["status"] == "COMPLETED" and row["finished_at"] is not None


def test_incomplete_ne_repart_pas_si_pagination_terminee(pg_conn):
    export_id = running_export(pg_conn)
    ss.commit_page(pg_conn, export_id, "fake-owner",
                   page(1, "*", "C1", [fake_mention(1)], pagination_finished=True))
    ss.set_status(pg_conn, export_id, S.INCOMPLETE)
    with pytest.raises(ss.StateError, match="Pagination déjà terminée"):
        ss.set_status(pg_conn, export_id, S.RUNNING)


def test_erreur_masquee_dans_error_details(pg_conn):
    export_id = running_export(pg_conn)
    ss.set_status(pg_conn, export_id, S.FAILED,
                  error_details={"message": "Erreur 500 sur /reviews?token=FAKE_tok_123456&rows=1000"})
    stored = json.dumps(ss.get_export(pg_conn, export_id)["error_details"])
    assert "FAKE_tok_123456" not in stored


def test_evenement_masque(pg_conn):
    export_id = ss.create_export(pg_conn, fake_config)
    ss.add_event(pg_conn, export_id, "error", "échec : postgresql://u:FAKE_pw_99999@h:5432/db")
    assert "FAKE_pw_99999" not in json.dumps([e["message"] for e in ss.list_events(pg_conn, export_id)])


# ─── commit_page ──────────────────────────────────────────────────────────────

def test_commit_page_enregistre_tout(pg_conn):
    export_id = running_export(pg_conn)
    m1, m2, m3 = fake_mention(1), fake_mention(2), fake_mention(3)
    ss.commit_page(pg_conn, export_id, "fake-owner", page(1, "*", "C1", [m1, m2]))
    dup = ss.ConflictRow(kind="duplicate", mention_id=mention_row(m1).mention_id, api_id="77")
    ss.commit_page(pg_conn, export_id, "fake-owner",
                   ss.PageCommit(page_no=2, cursor_sent="C1", cursor_received="C2", records_count=2,
                                 new_mentions=[mention_row(m3)], conflicts=[dup]))
    row = ss.get_export(pg_conn, export_id)
    assert (row["pages_count"], row["retrieved_count"], row["unique_count"], row["duplicate_count"]) == (2, 4, 3, 1)
    assert (row["last_cursor_sent"], row["last_committed_cursor"]) == ("C1", "C2")
    seqs = pg_conn.execute("SELECT seq FROM raw_mentions WHERE export_id = %s ORDER BY seq", (export_id,)).fetchall()
    assert [s[0] for s in seqs] == [1, 2, 3]
    assert ss.find_known_mentions(pg_conn, export_id, [mention_row(m1).mention_id, "0" * 64]) \
        == {mention_row(m1).mention_id}


def test_raw_json_conserve_a_l_identique(pg_conn):
    export_id = running_export(pg_conn)
    record = {**fake_mention(1), "verbatim content": "  Accents é è, emoji 🙂, guillemets \" et ; \n retour  "}
    row = mention_row(record)
    ss.commit_page(pg_conn, export_id, "fake-owner",
                   ss.PageCommit(page_no=1, cursor_sent="*", cursor_received="C1", records_count=1, new_mentions=[row]))
    stored = pg_conn.execute("SELECT raw_json FROM raw_mentions WHERE export_id = %s", (export_id,)).fetchone()[0]
    assert stored == row.raw_json
    assert json.loads(stored) == record


def test_commit_page_atomique_si_erreur_au_milieu(pg_conn, monkeypatch):
    export_id = running_export(pg_conn)

    def boom(*args, **kwargs):
        raise RuntimeError("panne simulée après l'insertion des mentions")

    monkeypatch.setattr(ss, "_insert_page_row", boom)
    with pytest.raises(RuntimeError):
        ss.commit_page(pg_conn, export_id, "fake-owner", page(1, "*", "C1", [fake_mention(1), fake_mention(2)]))
    row = ss.get_export(pg_conn, export_id)
    assert (row["pages_count"], row["unique_count"], row["last_committed_cursor"]) == (0, 0, None)
    assert pg_conn.execute("SELECT count(*) FROM raw_mentions").fetchone()[0] == 0
    assert pg_conn.execute("SELECT count(*) FROM pages").fetchone()[0] == 0


def test_meme_mention_impossible_deux_fois(pg_conn):
    export_id = running_export(pg_conn)
    ss.commit_page(pg_conn, export_id, "fake-owner", page(1, "*", "C1", [fake_mention(1)]))
    # Même contenu, autre `id` API : même raw_hash → refusé, et rien de la page 2 n'est écrit.
    with pytest.raises(psycopg.errors.UniqueViolation):
        ss.commit_page(pg_conn, export_id, "fake-owner",
                       page(2, "C1", "C2", [fake_mention(2), {**fake_mention(1), "id": "999"}]))
    row = ss.get_export(pg_conn, export_id)
    assert (row["pages_count"], row["unique_count"], row["last_committed_cursor"]) == (1, 1, "C1")


def test_page_hors_sequence_refusee(pg_conn):
    export_id = running_export(pg_conn)
    with pytest.raises(ss.StateError, match="page 1 attendue"):
        ss.commit_page(pg_conn, export_id, "fake-owner", page(2, "*", "C1", [fake_mention(1)]))
    ss.commit_page(pg_conn, export_id, "fake-owner", page(1, "*", "C1", [fake_mention(1)]))
    with pytest.raises(ss.StateError, match="point de reprise"):
        ss.commit_page(pg_conn, export_id, "fake-owner", page(2, "MAUVAIS", "C2", [fake_mention(2)]))


def test_commit_refuse_sans_bail_ou_hors_collecte(pg_conn):
    export_id = running_export(pg_conn)
    with pytest.raises(ss.LeaseLostError):
        ss.commit_page(pg_conn, export_id, "autre-owner", page(1, "*", "C1", [fake_mention(1)]))
    ss.set_status(pg_conn, export_id, S.PAUSED)
    with pytest.raises(ss.StateError, match="statut PAUSED"):
        ss.commit_page(pg_conn, export_id, "fake-owner", page(1, "*", "C1", [fake_mention(1)]))


def test_collision_les_deux_mentions_gardees(pg_conn):
    export_id = running_export(pg_conn)
    a = fake_mention(1)
    jumeau = {**a, "id": "2", "opinion": "negative"}  # même content_key, contenu différent
    ra, rj = mention_row(a), mention_row(jumeau)
    assert ra.content_key == rj.content_key and ra.mention_id != rj.mention_id
    ss.commit_page(pg_conn, export_id, "fake-owner", page(1, "*", "C1", [a]))
    known = ss.find_by_content_keys(pg_conn, export_id, [rj.content_key])
    collision = ss.ConflictRow(kind="collision", mention_id=rj.mention_id,
                               other_mention_id=known[rj.content_key], content_key=rj.content_key)
    ss.commit_page(pg_conn, export_id, "fake-owner",
                   ss.PageCommit(page_no=2, cursor_sent="C1", cursor_received="C2", records_count=1,
                                 new_mentions=[rj], conflicts=[collision]))
    row = ss.get_export(pg_conn, export_id)
    assert (row["unique_count"], row["collision_count"]) == (2, 1)
    assert pg_conn.execute("SELECT kind, other_mention_id FROM conflicts").fetchall() == [("collision", ra.mention_id)]


# ─── Bail ─────────────────────────────────────────────────────────────────────

def test_bail_un_seul_executant(pg_conn, pg_conn_factory):
    other = pg_conn_factory()
    export_id = ss.create_export(pg_conn, fake_config)
    assert ss.acquire_lease(pg_conn, export_id, "owner-A", ttl_seconds=60)
    assert not ss.acquire_lease(other, export_id, "owner-B", ttl_seconds=60)
    assert ss.acquire_lease(pg_conn, export_id, "owner-A", ttl_seconds=60)  # le sien : renouvelable
    assert not ss.renew_lease(other, export_id, "owner-B", ttl_seconds=60)
    assert ss.renew_lease(pg_conn, export_id, "owner-A", ttl_seconds=60)


def test_bail_repris_apres_expiration(pg_conn, pg_conn_factory):
    other = pg_conn_factory()
    export_id = ss.create_export(pg_conn, fake_config)
    assert ss.acquire_lease(pg_conn, export_id, "owner-A", ttl_seconds=60)
    pg_conn.execute("UPDATE exports SET lease_expires_at = now() - interval '1 second'")
    assert ss.acquire_lease(other, export_id, "owner-B", ttl_seconds=60)
    assert not ss.renew_lease(pg_conn, export_id, "owner-A", ttl_seconds=60)


def test_un_seul_export_actif_a_la_fois(pg_conn, pg_conn_factory):
    other = pg_conn_factory()
    first = ss.create_export(pg_conn, fake_config)
    second = ss.create_export(pg_conn, fake_config)
    assert ss.acquire_lease(pg_conn, first, "owner-A", ttl_seconds=60)
    assert not ss.acquire_lease(other, second, "owner-B", ttl_seconds=60)
    ss.release_lease(pg_conn, first, "owner-A")
    assert ss.acquire_lease(other, second, "owner-B", ttl_seconds=60)


def test_arret_demande_puis_efface_a_la_reprise(pg_conn):
    export_id = running_export(pg_conn)
    ss.request_stop(pg_conn, export_id)
    assert ss.get_export(pg_conn, export_id)["stop_requested"] is True
    ss.set_status(pg_conn, export_id, S.STOPPING)
    ss.set_status(pg_conn, export_id, S.PAUSED)
    assert ss.get_export(pg_conn, export_id)["stop_requested"] is False
