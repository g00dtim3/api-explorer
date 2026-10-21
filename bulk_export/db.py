"""
bulk_export/db.py
──────────────────────────────────────────────────────────────
Connexion à Postgres (Supabase, chaîne « Session pooler ») et application des migrations.

- délai maximal de connexion et de requête ;
- quelques nouvelles tentatives si la connexion échoue (coupure passagère) ;
- messages d'erreur toujours masqués (l'adresse de connexion contient le mot de passe).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import psycopg

from bulk_export.logging_utils import get_logger, mask
from bulk_export.settings import SCHEMA_RE, Settings

logger = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
CONNECT_TIMEOUT_S = 10
STATEMENT_TIMEOUT_MS = 60_000


class DatabaseError(RuntimeError):
    """Erreur de base de données, message déjà masqué."""


def connect(settings: Settings, *, schema: str | None = None, attempts: int = 3,
            wait_s: float = 2.0) -> psycopg.Connection:
    """Ouvre une connexion en mode « autocommit » : chaque écriture groupée se fait
    explicitement dans ``with conn.transaction():`` (tout ou rien)."""
    schema = schema or settings.db_schema
    if not SCHEMA_RE.fullmatch(schema):
        raise DatabaseError("Nom de schéma invalide.")

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            conn = psycopg.connect(
                settings.database_url,
                connect_timeout=CONNECT_TIMEOUT_S,
                autocommit=True,
                # Pas de requêtes préparées côté serveur : compatible avec les poolers Supabase.
                prepare_threshold=None,
            )
            # search_path et délai réglés après connexion : le pooler ne transmet pas toujours
            # les options passées au démarrage.
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{schema}"')
                cur.execute(f"SET statement_timeout = {int(STATEMENT_TIMEOUT_MS)}")
            return conn
        except psycopg.OperationalError as exc:
            last_error = exc
            logger.warning("Connexion à la base impossible (tentative %d/%d) : %s",
                           attempt, attempts, mask(exc))
            if attempt < attempts:
                time.sleep(wait_s * attempt)
    raise DatabaseError(f"Connexion à la base impossible après {attempts} tentatives : {mask(last_error)}")


def migration_sql(name: str = "001_init.sql", schema: str = "bulk_export") -> str:
    """Texte d'une migration, avec le nom du schéma remplacé si besoin (tests)."""
    if not SCHEMA_RE.fullmatch(schema):
        raise DatabaseError("Nom de schéma invalide.")
    sql = (MIGRATIONS_DIR / name).read_text(encoding="utf-8")
    if schema != "bulk_export":
        sql = re.sub(r"\bbulk_export\b", schema, sql)
    return sql


def apply_migration(conn: psycopg.Connection, name: str = "001_init.sql",
                    schema: str = "bulk_export") -> None:
    """Exécute une migration (le fichier gère lui-même BEGIN/COMMIT)."""
    try:
        conn.execute(migration_sql(name, schema))
    except psycopg.Error as exc:
        raise DatabaseError(f"Échec de la migration {name} : {mask(exc)}") from None


def migration_names() -> list[str]:
    """Migrations dans l'ordre (001_…, 002_…)."""
    return sorted(p.name for p in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def apply_all_migrations(conn: psycopg.Connection, schema: str = "bulk_export") -> None:
    for name in migration_names():
        apply_migration(conn, name, schema)
