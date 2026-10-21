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
    "auto_resume": "BULK_EXPORT_AUTO_RESUME",
    "purge_raw_after_validation": "BULK_EXPORT_PURGE_RAW",
    "alerte_taille_base_go": "BULK_EXPORT_ALERTE_TAILLE_BASE_GO",
}


def _as_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "oui", "on"):
        return True
    if text in ("", "0", "false", "no", "non", "off"):
        return False
    raise SettingsError(f"Paramètre invalide : {name} (vrai/faux attendu).")


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
    # Durée de conservation des fichiers dans Storage, en jours. 0 = ne jamais les supprimer (défaut, lot 1A).
    retention_days: int = 0
    # Relancer automatiquement un export interrompu par un redémarrage (désactivé par défaut).
    auto_resume: bool = False
    # Effacer les mentions brutes de la base après COMPLETED (désactivé par défaut : le brut est conservé).
    purge_raw_after_validation: bool = False
    # Taille de la base (en Go) au-delà de laquelle l'onglet Export History affiche un avertissement.
    alerte_taille_base_go: float = 6.0


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
        retention = int(raw.get("retention_days", 0))
    except (TypeError, ValueError):
        raise SettingsError("Paramètre invalide : retention_days (nombre de jours attendu).") from None
    if retention < 0:
        raise SettingsError("Paramètre invalide : retention_days (0 = ne jamais supprimer les fichiers, "
                            "sinon un nombre de jours positif).")

    try:
        size_alert = float(raw.get("alerte_taille_base_go", 6))
    except (TypeError, ValueError):
        raise SettingsError("Paramètre invalide : alerte_taille_base_go (nombre de Go attendu).") from None
    if not size_alert > 0:
        raise SettingsError("Paramètre invalide : alerte_taille_base_go (nombre de Go positif attendu).")

    settings = Settings(
        database_url=str(raw["database_url"]),
        db_schema=schema,
        supabase_url=raw.get("supabase_url") or None,
        # Espaces ou retour à la ligne copiés avec la clé : retirés (sinon « eyJ… » n'est pas reconnu, cf. storage.py).
        supabase_service_key=str(raw.get("supabase_service_key") or "").strip() or None,
        storage_bucket=str(raw.get("storage_bucket") or "bulk-exports"),
        retention_days=retention,
        auto_resume=_as_bool(raw.get("auto_resume", False), "auto_resume"),
        purge_raw_after_validation=_as_bool(raw.get("purge_raw_after_validation", False),
                                            "purge_raw_after_validation"),
        alerte_taille_base_go=size_alert,
    )
    # Dès qu'un secret est connu, il est masqué dans tous les messages.
    register_secret(settings.database_url)
    try:
        register_secret(urlsplit(settings.database_url).password)
    except ValueError:
        pass
    register_secret(settings.supabase_service_key)
    return settings


# ─── Accès à l'API Ratings & Reviews ──────────────────────────────────────────

@dataclass(frozen=True)
class ApiCredentials:
    token: str = field(repr=False)
    base_url: str = "https://api-pf.ratingsandreviews-beauty.com"


def _api_token_from_streamlit() -> str | None:
    try:
        import streamlit as st
        return str(st.secrets["api"]["token"]) or None  # même section que l'application actuelle
    except Exception:
        return None


def load_api_credentials(source: Mapping[str, Any] | None = None, *,
                         use_streamlit: bool = True) -> ApiCredentials:
    """Token de l'API : secrets Streamlit ``[api] token`` (comme l'application actuelle),
    sinon variable d'environnement ``BULK_EXPORT_API_TOKEN``. Jamais affiché."""
    if source is not None:
        token = source.get("token")
        base_url = source.get("base_url")
    else:
        token = (_api_token_from_streamlit() if use_streamlit else None) or os.environ.get("BULK_EXPORT_API_TOKEN")
        base_url = os.environ.get("BULK_EXPORT_API_BASE_URL")
    if not token:
        raise SettingsError("Paramètre manquant : token de l'API (secrets Streamlit [api] token "
                            "ou variable d'environnement BULK_EXPORT_API_TOKEN).")
    register_secret(str(token))
    creds = ApiCredentials(token=str(token))
    if base_url:
        # https obligatoire, sauf vers la machine locale (faux serveur des tests).
        local = str(base_url).startswith(("http://127.0.0.1:", "http://localhost:"))
        if not (str(base_url).startswith("https://") or local):
            raise SettingsError("Paramètre invalide : base_url (https:// obligatoire).")
        creds = ApiCredentials(token=str(token), base_url=str(base_url).rstrip("/"))
    return creds
