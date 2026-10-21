"""Masquage des secrets (règle n°8). Tous les secrets ici sont faux."""

import logging

import pytest

from bulk_export.logging_utils import SecretMaskingFilter, get_logger, mask, register_secret

fake_token = "FAKE_tok_9f8e7d6c5b4a"


@pytest.mark.parametrize("texte", [
    f"Erreur 401 sur https://api.example.test/reviews?brand=X&token={fake_token}&rows=10",
    f"https://api.example.test/reviews?token={fake_token}",
    f"url: /reviews?brand=A%26B&token%3D{fake_token}",
    f'{{"token": "{fake_token}"}}',
    f"Authorization: Bearer {fake_token}",
])
def test_token_masque_sans_enregistrement(texte):
    out = mask(texte)
    assert fake_token not in out
    assert "***" in out


def test_mot_de_passe_dans_url_postgres():
    out = mask("connexion impossible : postgresql://postgres.abcd:FAKE_p%40ss-w0rd@aws-0-eu.pooler.supabase.com:5432/postgres")
    assert "FAKE_p%40ss-w0rd" not in out
    assert "postgres.abcd:***@aws-0-eu.pooler.supabase.com" in out


def test_jwt_masque():
    fake_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.FAKEsignatureFAKEsig"
    assert fake_jwt not in mask(f"clé : {fake_jwt}")


def test_secret_enregistre_masque_partout():
    register_secret("FAKE-secret-value-42")
    assert mask("le secret est FAKE-secret-value-42, voilà") == "le secret est ***, voilà"


def test_secret_trop_court_ignore():
    register_secret("abc")
    assert mask("abc") == "abc"


def test_texte_normal_inchange():
    texte = "Page 12 : 1000 mentions reçues, curseur AoJ4pL7I4ZIDKDk2ODM2MTAw"
    assert mask(texte) == texte


def test_filtre_logging(caplog):
    logger = get_logger("bulk_export.test")
    with caplog.at_level(logging.INFO, logger="bulk_export.test"):
        logger.info("appel %s", f"https://x.test/r?token={fake_token}")
    assert fake_token not in caplog.text
    assert any(isinstance(f, SecretMaskingFilter) for f in logger.filters)
