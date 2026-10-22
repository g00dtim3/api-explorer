"""Non-régression : l'affichage des résultats des modules 2 et 3 (version « legacy »).

Bug du 19/10/2026 sur Streamlit Cloud : pandas 3 a supprimé ``DataFrame.applymap``, utilisé par les modules 2 et 3
(que la règle n°1 interdit de modifier). Ce test fait afficher des résultats par le module 3 et par le module 2.
Données synthétiques fake_*, aucun appel réseau.
"""

import json
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
fake_docs = [{"id": str(n), "brand": "FAKE", "date": "2024-11-28T10:00:00Z", "product": "fake",
              "content trad": f"fake {n}", "attributes": ["Texture"], "rating": 5} for n in range(1, 4)]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import requests

    class R:
        status_code, text, headers, content = 200, "", {}, b""

        def json(self):
            return {"status": "success", "result": {}}

    monkeypatch.setattr(requests, "get", lambda *a, **k: R())


@pytest.mark.parametrize("module", ["Export par segment", "Export manuel"])
def test_affichage_des_resultats_legacy(module):
    at = AppTest.from_file(str(REPO / "main_app.py"), default_timeout=60)
    at.secrets["api"] = {"token": "FAKE_token_legacy_123456"}
    at.secrets["APP_PASSWORD"] = "FAKE-mot-de-passe-de-test-tres-long-42"
    at.session_state["authentifie"] = True
    at.run()
    at.sidebar.radio[0].set_value(module).run()
    at.session_state["apply_filters"] = True
    at.session_state["filters"] = {"brand": ["FAKE"], "start_date": "2024-01-01", "end_date": "2024-12-31",
                                   "category": "ALL", "subcategory": "ALL", "country": [], "source": [],
                                   "market": [], "attributes": [], "attributes_positive": [],
                                   "attributes_negative": []}
    at.session_state["all_docs"] = json.loads(json.dumps(fake_docs))
    at.session_state["selected_product_ids"] = ["fake"]
    at.run()
    assert not at.exception, at.exception[0].message if at.exception else ""
