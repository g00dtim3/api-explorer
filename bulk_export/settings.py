"""
bulk_export/settings.py
──────────────────────────────────────────────────────────────
Paramètres de connexion Supabase, lus :
1. dans les secrets Streamlit, section ``[bulk_export]`` (application) ;
2. sinon dans les variables d'environnement ``BULK_EXPORT_*`` (ligne de commande, tests).

Les valeurs ne sont jamais affichées : un paramètre manquant est signalé par son NOM seulement.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit
from dataclasses import dataclass, field
from typing import Any, Mapping

from bulk_export.logging_utils import register_secret

SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
DEFAULT_SCHEMA = "bulk_export"

# nom du paramètre → variable d'environnement correspondante
_ENV_NAMES = {
    "database_url": "BULK_EXPORT_DATABASE_URL",
    "db_schema": "BULK_EXPORT_DB_SCHEMA",
    "supabase_url": "BULK_EXPORT_SUPABASE_URL",
    "supabase_service_key": "BULK_EXPORT_SUPABASE_SERVICE_KEY",
    "storage_bucket": "BULK_EXPORT_STORAGE_BUCKET",
    "retention_days": "BULK_EXPORT_RETENTION_DAYS",
}


class SettingsError(RuntimeError):
    """Paramètre absent ou invalide (le message ne contient jamais de valeur)."""


@dataclass(frozen=True)
class Settings:
    # repr=False : la valeur n'apparaît pas si l'objet est affiché par erreur.
    database_url: str = field(repr=False)
    db_schema: str = DEFAULT_SCHEMA
    supabase_url: str | None = None
    supabase_service_key: str | None = field(default=None, repr=False)
    storage_bucket: str = "bulk-exports"
    retention_days: int = 30


def _from_streamlit() -> Mapping[str, Any] | None:
    try:
        import streamlit as st  # import tardif : le paquet marche sans Streamlit
        section = st.secrets.get("bulk_export")
        return dict(section) if section else None
    except Exception:
        return None


def load_settings(source: Mapping[str, Any] | None = None, *, use_streamlit: bool = True) -> Settings:
    """Construit les paramètres. ``source`` permet aux tests de fournir un dictionnaire."""
    raw: dict[str, Any] = {}
    if source is not None:
        raw = dict(source)
    elif use_streamlit and (st_section := _from_streamlit()):
        raw = st_section
    else:
        raw = {k: os.environ[env] for k, env in _ENV_NAMES.items() if os.environ.get(env)}

    if not raw.get("database_url"):
        raise SettingsError(
            "Paramètre manquant : database_url (secrets Streamlit [bulk_export] "
            f"ou variable d'environnement {_ENV_NAMES['database_url']})."
        )

    schema = str(raw.get("db_schema") or DEFAULT_SCHEMA)
    if not SCHEMA_RE.fullmatch(schema):
        raise SettingsError("Paramètre invalide : db_schema (lettres minuscules, chiffres et _ uniquement).")

    try:
        retention = int(raw.get("retention_days", 30))
    except (TypeError, ValueError):
        raise SettingsError("Paramètre invalide : retention_days (nombre de jours attendu).") from None

    settings = Settings(
        database_url=str(raw["database_url"]),
        db_schema=schema,
        supabase_url=raw.get("supabase_url") or None,
        supabase_service_key=raw.get("supabase_service_key") or None,
        storage_bucket=str(raw.get("storage_bucket") or "bulk-exports"),
        retention_days=retention,
    )
    # Dès qu'un secret est connu, il est masqué dans tous les messages.
    register_secret(settings.database_url)
    try:
        register_secret(urlsplit(settings.database_url).password)
    except ValueError:
        pass
    register_secret(settings.supabase_service_key)
    return settings
