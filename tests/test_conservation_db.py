"""Lot 1A — conservation du brut : purge optionnelle, rétention « jamais », index Compass, taille de la base,
réhydratation depuis les lots. Faux exports (fake_*) sur la base de test et un stockage local."""

import gzip

import pytest

from bulk_export import finalize, rehydrate, state_store as ss
from bulk_export.runner import ExportRunner
from bulk_export.storage import LocalStorage
from tests.fake_api import FakePagedServer
from tests.test_engine_db import fake_doc, fake_pages
from tests.test_validation_db import TEST_SCHEMA, adapter_for, collect, connect, fake_config, run_finalize  # noqa: F401

pytestmark = pytest.mark.db

SNAPSHOT_SQL = """SELECT seq, mention_id, raw_json, content_key, compass_id, api_id FROM raw_mentions
                  WHERE export_id = %s ORDER BY seq"""


def raw_count(conn, export_id):
    return conn.execute("SELECT count(*) FROM raw_mentions WHERE export_id = %s", (export_id,)).fetchone()[0]


def events(conn, export_id):
    return [e["message"] for e in ss.list_events(conn, export_id, limit=50)]


def completed_export(pg_conn, connect, tmp_path, pages=None, purge_raw=False):
    pages = pages or fake_pages(total=8)
    export_id = collect(pg_conn, connect, pages)
    store = LocalStorage(tmp_path / "store")
    assert run_finalize(pg_conn, export_id, store, FakePagedServer(pages), purge_raw=purge_raw).passed
    return export_id, store


# ─── 1. Purge optionnelle ─────────────────────────────────────────────────────

def test_purge_desactivee_par_defaut_brut_conserve(pg_conn, connect, tmp_path):
    export_id, _ = completed_export(pg_conn, connect, tmp_path)
    row = ss.get_export(pg_conn, export_id)
    assert row["status"] == "COMPLETED" and row["raw_purged_at"] is None
    assert raw_count(pg_conn, export_id) == row["unique_count"] == 8
    assert "Mentions conservées en base (purge désactivée)." in events(pg_conn, export_id)


def _run(connect, tmp_path, **kw):
    pages = fake_pages(total=5)
    store = LocalStorage(tmp_path / "s")
    runner = ExportRunner(connect, lambda config: adapter_for(FakePagedServer(pages), config), lease_ttl_s=5,
                          heartbeat_s=1, storage_factory=lambda: store, **kw)
    return runner


@pytest.mark.parametrize("purge", [False, True])
def test_runner_transmet_le_reglage_de_purge(pg_conn, connect, tmp_path, purge):
    runner = _run(connect, tmp_path, purge_raw_after_validation=purge)
    export_id = ss.create_export(pg_conn, fake_config)
    assert runner.start(export_id).ok and runner.wait(30)
    row = ss.get_export(pg_conn, export_id)
    assert row["status"] == "COMPLETED"
    assert raw_count(pg_conn, export_id) == (0 if purge else 5)
    assert (row["raw_purged_at"] is not None) is purge


# ─── 2. Rétention « jamais » ──────────────────────────────────────────────────

def test_retention_zero_ne_supprime_jamais(pg_conn, connect, tmp_path):
    export_id, store = completed_export(pg_conn, connect, tmp_path)
    pg_conn.execute("UPDATE exports SET finished_at = now() - interval '3650 days'")
    assert ss.exports_with_expired_files(pg_conn, 0) == []
    assert finalize.apply_retention(pg_conn, store, retention_days=0) == []
    assert list((store.root / export_id).rglob("*.gz"))
    assert ss.get_export(pg_conn, export_id)["files_expired_at"] is None
    # Rappel : avec 30 jours, le même export expire (comportement inchangé).
    assert finalize.apply_retention(pg_conn, store, retention_days=30) == [export_id]


# ─── 3. Index et 4. taille de la base ─────────────────────────────────────────

def test_index_compass_id(pg_conn):
    found = pg_conn.execute("SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND indexname = %s",
                            (TEST_SCHEMA, "raw_mentions_compass_id_idx")).fetchone()
    assert found and "(compass_id)" in found[0]


def test_taille_de_la_base(pg_conn, connect, tmp_path):
    completed_export(pg_conn, connect, tmp_path)
    sizes = ss.database_sizes(pg_conn)
    assert sizes["database"] > sizes["raw_mentions"] > 0


# ─── 5. Réhydratation ─────────────────────────────────────────────────────────

def purged_export(pg_conn, connect, tmp_path):
    """Export COMPLETED avec un doublon tracé, brut photographié puis effacé."""
    p1 = [fake_doc(1), fake_doc(2), fake_doc(3)]
    p2 = [{**fake_doc(1), "id": "999"}, fake_doc(4), fake_doc(5, **{"content origin": "fake texte d'origine"})]
    export_id, store = completed_export(pg_conn, connect, tmp_path, pages=[p1, p2])
    before = pg_conn.execute(SNAPSHOT_SQL, (export_id,)).fetchall()
    duplicates = ss.list_duplicates(pg_conn, export_id)
    assert ss.purge_raw_mentions(pg_conn, export_id) == 5
    return export_id, store, before, duplicates


def test_rehydratation_redonne_les_memes_empreintes(pg_conn, connect, tmp_path):
    export_id, store, before, duplicates = purged_export(pg_conn, connect, tmp_path)
    assert [r["export_id"] for r in rehydrate.rehydratable_exports(pg_conn)] == [export_id]
    assert rehydrate.rehydrate(pg_conn, export_id, store) == 5
    assert pg_conn.execute(SNAPSHOT_SQL, (export_id,)).fetchall() == before
    assert {r[0] for r in pg_conn.execute("SELECT page_no FROM raw_mentions WHERE export_id = %s",
                                          (export_id,)).fetchall()} == {rehydrate.REHYDRATED_PAGE_NO}
    assert ss.list_duplicates(pg_conn, export_id) == duplicates  # kept_api_id retrouvé
    row = ss.get_export(pg_conn, export_id)
    assert row["raw_purged_at"] is None
    assert "Brut réhydraté depuis les lots (5 mentions)." in events(pg_conn, export_id)
    assert rehydrate.rehydratable_exports(pg_conn) == []
    # Une deuxième fois : refusé, le brut est déjà en base.
    with pytest.raises(rehydrate.RehydrateError, match="déjà en base"):
        rehydrate.rehydrate(pg_conn, export_id, store)


def assert_nothing_written(pg_conn, export_id):
    assert raw_count(pg_conn, export_id) == 0
    assert ss.get_export(pg_conn, export_id)["raw_purged_at"] is not None
    assert not [m for m in events(pg_conn, export_id) if m.startswith("Brut réhydraté")]


def test_lot_altere_d_un_octet_refuse(pg_conn, connect, tmp_path):
    export_id, store, _, _ = purged_export(pg_conn, connect, tmp_path)
    batch = store.root / f"{export_id}/batches/batch_0001.jsonl.gz"
    data = bytearray(batch.read_bytes())
    data[len(data) // 2] ^= 0x01
    batch.write_bytes(bytes(data))
    with pytest.raises(rehydrate.RehydrateError, match="empreinte du fichier"):
        rehydrate.rehydrate(pg_conn, export_id, store)
    assert_nothing_written(pg_conn, export_id)


def test_contenu_altere_refuse_meme_si_le_fichier_est_reenregistre(pg_conn, connect, tmp_path):
    """Lot recompressé avec un verbatim modifié ET empreinte du fichier mise à jour : le contrôle du contenu
    décompressé (content_sha256) refuse quand même, et rien n'est enregistré."""
    export_id, store, _, _ = purged_export(pg_conn, connect, tmp_path)
    batch = store.root / f"{export_id}/batches/batch_0001.jsonl.gz"
    text = gzip.decompress(batch.read_bytes()).replace(b"fake verbatim 4", b"fake verbatim X")
    batch.write_bytes(gzip.compress(text))
    from bulk_export.downloads import sha256_file
    pg_conn.execute("UPDATE files SET sha256 = %s, size_bytes = %s WHERE export_id = %s AND kind = 'batch_jsonl'",
                    (sha256_file(batch), batch.stat().st_size, export_id))
    with pytest.raises(rehydrate.RehydrateError, match="empreinte du contenu"):
        rehydrate.rehydrate(pg_conn, export_id, store)
    assert_nothing_written(pg_conn, export_id)


def test_nombre_de_mentions_different_refuse(pg_conn, connect, tmp_path):
    export_id, store, _, _ = purged_export(pg_conn, connect, tmp_path)
    pg_conn.execute("UPDATE exports SET unique_count = 6 WHERE export_id = %s", (export_id,))
    with pytest.raises(rehydrate.RehydrateError, match="5 mentions dans les lots, 6 attendues"):
        rehydrate.rehydrate(pg_conn, export_id, store)
    assert_nothing_written(pg_conn, export_id)


def test_refus_si_non_purge_non_completed_ou_fichiers_expires(pg_conn, connect, tmp_path):
    export_id, store = completed_export(pg_conn, connect, tmp_path)
    with pytest.raises(rehydrate.RehydrateError, match="déjà en base"):
        rehydrate.rehydrate(pg_conn, export_id, store)
    ss.purge_raw_mentions(pg_conn, export_id)
    pg_conn.execute("UPDATE exports SET finished_at = now() - interval '31 days'")
    finalize.apply_retention(pg_conn, store, retention_days=30)
    with pytest.raises(rehydrate.RehydrateError, match="expiré"):
        rehydrate.rehydrate(pg_conn, export_id, store)
    other = ss.create_export(pg_conn, fake_config)
    with pytest.raises(rehydrate.RehydrateError, match="PENDING"):
        rehydrate.rehydrate(pg_conn, other, store)


def test_ligne_de_commande_liste(pg_conn, connect, tmp_path, monkeypatch, capsys):
    import os
    export_id, _, _, _ = purged_export(pg_conn, connect, tmp_path)
    monkeypatch.setenv("BULK_EXPORT_DATABASE_URL", os.environ["BULK_EXPORT_TEST_DATABASE_URL"])
    monkeypatch.setenv("BULK_EXPORT_DB_SCHEMA", TEST_SCHEMA)
    assert rehydrate.main(["--list"]) == rehydrate.EXIT_OK
    out = capsys.readouterr().out
    assert export_id in out and "1 export(s) réhydratable(s)." in out
    # Sans stockage configuré : paramètres invalides, rien n'est tenté.
    assert rehydrate.main([export_id]) == rehydrate.EXIT_USAGE
