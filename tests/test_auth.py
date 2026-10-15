"""Accès par mot de passe (spec du 15/10/2026) — tests T1 à T9 automatisables, avec l'outil de test de Streamlit.

Mot de passe 100 % factice. Aucun appel réseau : le moindre appel HTTP ou connexion à la base fait échouer le test
qui vérifie qu'on ne passe pas l'écran de mot de passe.
"""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FAKE_PASSWORD = "FAKE-mot-de-passe-de-test-tres-long-42"


@pytest.fixture
def interdire_reseau_et_base(monkeypatch):
    """Tout appel API ou connexion à la base avant connexion = échec du test (S3, T1)."""
    import psycopg
    import requests

    def interdit(*a, **k):
        raise AssertionError("Appel réseau ou base effectué avant l'authentification !")

    monkeypatch.setattr(requests, "get", interdit)
    monkeypatch.setattr(requests.Session, "request", interdit)
    monkeypatch.setattr(psycopg, "connect", interdit)
    import streamlit as st
    st.cache_resource.clear()
    st.cache_data.clear()


def app(script="main_app.py", password=FAKE_PASSWORD):
    at = AppTest.from_file(str(REPO / script), default_timeout=60)
    at.secrets["api"] = {"token": "FAKE_token_auth_123456"}
    if password is not None:
        at.secrets["APP_PASSWORD"] = password
    return at


def texts(at):
    return [str(e.value) for kind in ("error", "title", "markdown", "info") for e in getattr(at, kind)]


def login(at, password):
    at.text_input(key="mot_de_passe_saisi").input(password)
    at.button[0].click().run()  # bouton « Entrer » du formulaire
    return at


APP_MODULES = ("api_client", "utils", "module1_explorer", "module2_manual_export", "module3_bulk_export",
               "module4_bulk_export_v2")


def test_t1_aucun_module_ni_client_api_charge_avant_connexion(interdire_reseau_et_base, monkeypatch):
    import sys
    for name in APP_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    at = app().run()
    assert not at.exception, at.exception
    assert not [m for m in APP_MODULES if m in sys.modules], "module chargé avant le mot de passe (S3)"


@pytest.mark.parametrize("script", ["main_app.py", "module4_bulk_export_v2.py"])
def test_t1_seul_l_ecran_de_mot_de_passe_sans_appel(interdire_reseau_et_base, script):
    at = app(script).run()
    assert not at.exception, at.exception
    assert [t.value for t in at.title] == ["Accès protégé"]
    assert len(at.text_input) == 1
    from streamlit.proto.TextInput_pb2 import TextInput
    assert at.text_input[0].proto.type == TextInput.PASSWORD  # champ masqué
    assert len(at.button) == 1 and len(at.sidebar.radio) == 0  # « Entrer », rien d'autre


def test_t2_mauvais_mot_de_passe(interdire_reseau_et_base):
    at = login(app().run(), "mauvais")
    assert not at.exception, at.exception
    assert "Mot de passe incorrect." in texts(at) and len(at.sidebar.radio) == 0


def test_t3_bon_mot_de_passe_puis_t5_rafraichissement(monkeypatch):
    import requests

    class R:
        status_code, text, headers, content = 200, "", {}, b'{"status":"success","result":{}}'

        def json(self):
            return {"status": "success", "result": {}}

    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    at = login(app().run(), FAKE_PASSWORD)
    assert not at.exception, at.exception
    assert len(at.sidebar.radio) == 1 and "🧱 Bulk Export V2" in at.sidebar.radio[0].options  # T3
    assert "mot_de_passe_saisi" not in at.session_state  # S4 : saisie effacée
    fresh = app().run()  # T5 : nouvelle session (rafraîchissement) → mot de passe redemandé
    assert [t.value for t in fresh.title] == ["Accès protégé"]


def test_t4_blocage_apres_5_echecs(interdire_reseau_et_base):
    at = app().run()
    for _ in range(5):
        login(at, "mauvais")
    assert "Trop d'essais. Réessayez dans quelques minutes." in texts(at)
    assert len(at.text_input) == 0  # plus de champ de saisie pendant le blocage
    at.run()
    assert "Trop d'essais. Réessayez dans quelques minutes." in texts(at)  # même plus tard dans la session


def test_t6_deconnexion(monkeypatch):
    import requests

    class R:
        status_code, text, headers, content = 200, "", {}, b""

        def json(self):
            return {"status": "success", "result": {}}

    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    at = login(app().run(), FAKE_PASSWORD)
    at.sidebar.button(key="auth_deconnexion").click().run()
    assert not at.exception, at.exception
    assert [t.value for t in at.title] == ["Accès protégé"] and len(at.sidebar.radio) == 0


@pytest.mark.parametrize("password,message", [
    (None, "Configuration manquante : accès impossible."),
    ("", "Configuration manquante : accès impossible."),
    ("court-15-caract", "Configuration invalide"),
])
def test_t9_secret_absent_vide_ou_trop_court(interdire_reseau_et_base, password, message):
    at = app(password=password).run()
    assert not at.exception, at.exception
    assert any(t.startswith(message) for t in texts(at))
    assert len(at.text_input) == 0 and len(at.sidebar.radio) == 0


def test_comparaison_a_temps_constant():
    import inspect

    import auth
    assert "hmac.compare_digest" in inspect.getsource(auth._verifier)  # S2
