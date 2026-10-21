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


def test_cle_storage_sans_espaces_autour():
    s = load_settings({"database_url": fake_url, "supabase_service_key": "  eyJFAKE.jwt.key\n"})
    assert s.supabase_service_key == "eyJFAKE.jwt.key"


def test_conservation_par_defaut():
    """Lot 1A : brut conservé en base et fichiers jamais supprimés, sauf réglage contraire."""
    s = load_settings({"database_url": fake_url})
    assert s.retention_days == 0 and s.purge_raw_after_validation is False and s.alerte_taille_base_go == 6


def test_retention_negative_refusee():
    with pytest.raises(SettingsError, match="retention_days"):
        load_settings({"database_url": fake_url, "retention_days": -1})


def test_purge_et_seuil_depuis_l_environnement(monkeypatch):
    monkeypatch.setenv("BULK_EXPORT_DATABASE_URL", fake_url)
    monkeypatch.setenv("BULK_EXPORT_PURGE_RAW", "true")
    monkeypatch.setenv("BULK_EXPORT_ALERTE_TAILLE_BASE_GO", "7.5")
    s = load_settings(use_streamlit=False)
    assert s.purge_raw_after_validation is True and s.alerte_taille_base_go == 7.5


@pytest.mark.parametrize("key,value", [("purge_raw_after_validation", "peut-être"),
                                       ("alerte_taille_base_go", "beaucoup"), ("alerte_taille_base_go", 0)])
def test_reglages_conservation_invalides(key, value):
    with pytest.raises(SettingsError, match=key):
        load_settings({"database_url": fake_url, key: value})


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
