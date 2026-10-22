"""Règle n°8 : quand l'API échoue, les messages affichés par `api_client` ne contiennent jamais le token.

Même méthode que test_legacy_modules : processus séparé, secrets factices, aucun appel réseau.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FAKE_TOKEN = "FAKE_secret_token_8642"

SCRIPT = textwrap.dedent("""
    import requests
    import streamlit as st

    shown = []
    st.error = lambda body, **kw: shown.append(str(body))

    class FakeError:
        status_code = 500
        text = "erreur interne pour token=FAKE_secret_token_8642"

    mode = {"value": "http"}

    def fake_get(url, headers=None, **kw):
        if mode["value"] == "http":
            return FakeError()
        raise requests.ConnectionError(f"Max retries exceeded with url: {url}")

    requests.get = fake_get

    import api_client

    params = {"brand": "FAKE"}
    assert api_client.api_client.fetch("/brands", params) == {}
    assert params == {"brand": "FAKE"}, params  # le dictionnaire de l'appelant ne reçoit pas le token
    mode["value"] = "reseau"
    assert api_client.api_client.fetch("/countries", [("country", "France")]) == {}

    assert len(shown) == 3, shown
    assert any("Erreur 500 sur https://api-pf.ratingsandreviews-beauty.com/brands?" in m for m in shown), shown
    assert any("Erreur de connexion" in m for m in shown), shown
    assert not [m for m in shown if "FAKE_secret_token_8642" in m], shown
    print("OK")
""")


def test_erreurs_api_sans_token(tmp_path):
    pytest.importorskip("streamlit")
    (tmp_path / ".streamlit").mkdir()
    (tmp_path / ".streamlit" / "secrets.toml").write_text(f'[api]\ntoken = "{FAKE_TOKEN}"\n')
    proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=tmp_path, capture_output=True, text=True,
                          env={"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
                          timeout=120)
    assert proc.returncode == 0 and proc.stdout.strip().endswith("OK"), proc.stderr[-2000:]
