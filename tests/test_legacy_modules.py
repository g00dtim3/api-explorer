"""Filet de sécurité pour l'existant : les modules 1 à 3 s'importent et `api_client` répond comme avant.

Lancé dans un processus séparé, avec un dossier `.streamlit/secrets.toml` FACTICE, pour ne pas
mélanger l'état de Streamlit avec les autres tests. Aucun appel réseau : `requests.get` est remplacé.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

SCRIPT = textwrap.dedent("""
    import json, sys, urllib.parse
    import requests

    calls = []

    class FakeResponse:
        status_code = 200
        text = ""
        def json(self):
            return {"status": "success", "result": {"nbDocs": 1, "docs": [{"id": "1"}], "nextCursorMark": "C1"}}

    def fake_get(url, headers=None, **kw):
        calls.append(url)
        return FakeResponse()

    requests.get = fake_get

    import api_client, utils, module1_explorer, module2_manual_export, module3_bulk_export  # noqa: F401
    import module3_bulk_export as m3
    assert hasattr(m3, "execute_bulk_export") and hasattr(m3, "main")

    result = api_client.api_client.get_reviews(brand=["Fake & Co", "B"], rows=10, nextCursorMark="*",
                                               country="ALL")
    assert result == {"nbDocs": 1, "docs": [{"id": "1"}], "nextCursorMark": "C1"}, result
    url = calls[0]
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert url.startswith("https://api-pf.ratingsandreviews-beauty.com/reviews?"), url
    assert query == {"brand": "Fake & Co,B", "rows": "10", "nextCursorMark": "*",
                     "token": "FAKE_legacy_token_42"}, query

    params = utils.build_filter_params({"brand": ["FAKE"], "start_date": "2024-01-01", "country": ["ALL"]})
    assert params == {"brand": "FAKE", "start-date": "2024-01-01"}, params
    print("OK")
""")


def test_modules_existants_inchanges(tmp_path):
    pytest.importorskip("streamlit")
    (tmp_path / ".streamlit").mkdir()
    (tmp_path / ".streamlit" / "secrets.toml").write_text('[api]\ntoken = "FAKE_legacy_token_42"\n')
    proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=tmp_path, capture_output=True, text=True,
                          env={"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
                          timeout=120)
    assert proc.returncode == 0 and proc.stdout.strip().endswith("OK"), proc.stderr[-2000:]
