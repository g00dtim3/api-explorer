"""
Fixtures communes.

Les tests marqués ``db`` ont besoin d'une base Postgres : définir
BULK_EXPORT_TEST_DATABASE_URL (ex. postgresql://postgres@127.0.0.1:54329/postgres).
Ils travaillent dans le schéma ``bulk_export_test``, supprimé et recréé à chaque test.
Sans cette variable, ils sont sautés.
"""

import os

import pytest

TEST_SCHEMA = "bulk_export_test"


@pytest.fixture
def pg_conn():
    url = os.environ.get("BULK_EXPORT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("BULK_EXPORT_TEST_DATABASE_URL non défini : tests base de données sautés.")
    from bulk_export import db
    from bulk_export.settings import load_settings

    settings = load_settings({"database_url": url, "db_schema": TEST_SCHEMA})
    conn = db.connect(settings, attempts=1)
    conn.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
    db.apply_all_migrations(conn, schema=TEST_SCHEMA)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def pg_conn_factory(pg_conn):
    """Ouvre des connexions supplémentaires sur le même schéma (simule un 2e exécutant)."""
    from bulk_export import db
    from bulk_export.settings import load_settings

    settings = load_settings({"database_url": os.environ["BULK_EXPORT_TEST_DATABASE_URL"],
                              "db_schema": TEST_SCHEMA})
    opened = []

    def _open():
        c = db.connect(settings, attempts=1)
        opened.append(c)
        return c

    yield _open
    for c in opened:
        c.close()
