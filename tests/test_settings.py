"""Lecture des paramètres : jamais de valeur dans les messages."""

import pytest

from bulk_export.logging_utils import mask
from bulk_export.settings import SettingsError, load_settings

fake_url = "postgresql://postgres.fakeproj:FAKE_db_pass_123@aws-0-eu.pooler.supabase.com:5432/postgres"


def test_parametre_manquant_message_sans_valeur():
    with pytest.raises(SettingsError, match="database_url") as exc:
        load_settings({"supabase_service_key": "FAKE_service_key_xyz"})
    assert "FAKE_service_key_xyz" not in str(exc.value)


def test_variables_environnement(monkeypatch):
    monkeypatch.setenv("BULK_EXPORT_DATABASE_URL", fake_url)
    monkeypatch.setenv("BULK_EXPORT_DB_SCHEMA", "bulk_export_test")
    s = load_settings(use_streamlit=False)
    assert s.db_schema == "bulk_export_test"


def test_valeurs_absentes_de_l_affichage():
    s = load_settings({"database_url": fake_url, "supabase_service_key": "FAKE_service_key_xyz"})
    assert "FAKE_db_pass_123" not in repr(s)
    assert "FAKE_service_key_xyz" not in repr(s)


def test_secrets_enregistres_pour_masquage():
    load_settings({"database_url": fake_url, "supabase_service_key": "FAKE_service_key_xyz"})
    assert "FAKE_db_pass_123" not in mask("mot de passe FAKE_db_pass_123")
    assert "FAKE_service_key_xyz" not in mask("clé FAKE_service_key_xyz")


@pytest.mark.parametrize("schema", ["Bulk", "bulk-export", 'x"; DROP SCHEMA public; --', "1abc"])
def test_schema_invalide(schema):
    with pytest.raises(SettingsError, match="db_schema"):
        load_settings({"database_url": fake_url, "db_schema": schema})


def test_retention_invalide():
    with pytest.raises(SettingsError, match="retention_days"):
        load_settings({"database_url": fake_url, "retention_days": "beaucoup"})


# ─── Token de l'API ───────────────────────────────────────────────────────────

from bulk_export.settings import load_api_credentials  # noqa: E402


def test_token_api_depuis_environnement(monkeypatch):
    monkeypatch.setenv("BULK_EXPORT_API_TOKEN", "FAKE_env_token_123")
    creds = load_api_credentials(use_streamlit=False)
    assert creds.token == "FAKE_env_token_123"
    assert "FAKE_env_token_123" not in repr(creds)
    assert "FAKE_env_token_123" not in mask("appel ?x=FAKE_env_token_123")


def test_token_api_manquant(monkeypatch):
    monkeypatch.delenv("BULK_EXPORT_API_TOKEN", raising=False)
    with pytest.raises(SettingsError, match="token"):
        load_api_credentials(use_streamlit=False)


def test_base_url_https_obligatoire():
    with pytest.raises(SettingsError, match="base_url"):
        load_api_credentials({"token": "FAKE_tok_456789", "base_url": "http://exemple.test"})
