"""Tests de fumée des pages Streamlit (streamlit.testing.v1.AppTest), sans aucun appel réseau.

- Bulk Export V2 sans Supabase : message clair, pas de plantage.
- Bulk Export V2 avec la base de test : le Monitor affiche un export et ses événements.
- Application principale : les 4 entrées d'origine et Bulk Export V2 se chargent.
"""

import json
import os
import urllib.parse
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import requests  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FAKE_TOKEN = "FAKE_app_token_987654"
LISTS = {
    "/categories": {"categories": [{"category": "fake cat", "subcategories": ["fake sub"]}]},
    "/brands": {"brands": ["FAKE_BRAND"]}, "/countries": {"countries": ["France"]},
    "/sources": {"sources": ["Fake FR"]}, "/markets": {"markets": ["Fake market"]},
    "/attributes": {"attributes": ["Texture"]}, "/quotas": {"quota": 0}, "/metrics": {"nbDocs": 0},
    "/products": {"products": []}, "/ratings": {"ratings": [1, 2, 3, 4, 5]},
}


FAKE_DOCS = [{"id": str(n), "brand": "FAKE_BRAND", "date": "2024-11-28T10:00:00Z", "product": "fake",
              "content trad": f"fake verbatim {n}"} for n in range(1, 4)]


def _result(path, params):
    if path == "/reviews":  # 1 page de 3 mentions, puis page vide avec le même curseur (fin)
        cursor = params.get("nextCursorMark")
        if cursor == "*":
            return {"nbDocs": 3, "docs": FAKE_DOCS, "nextCursorMark": "C1"}
        return {"nbDocs": 3, "docs": [], "nextCursorMark": cursor}
    if path == "/metrics":
        return {"nbDocs": 3}
    return LISTS.get(path, {})


class _Resp:
    def __init__(self, path, params=None):
        body = {"status": "success", "result": _result(path, params or {})}
        self.status_code, self.headers = 200, {}
        self.content = json.dumps(body).encode()
        self.text = self.content.decode()

    def json(self):
        return json.loads(self.text)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fake_get(*args, **kwargs):
        url = args[-1] if isinstance(args[-1], str) else kwargs["url"]
        assert "127.0.0.1" not in url
        parts = urllib.parse.urlsplit(url)
        return _Resp(parts.path, dict(urllib.parse.parse_qsl(parts.query)))

    monkeypatch.setattr(requests, "get", lambda url, **kw: fake_get(url, **kw))
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: fake_get(url, **kw))
    monkeypatch.chdir(REPO)
    import streamlit as st
    st.cache_resource.clear()
    st.cache_data.clear()


def all_text(at):
    parts = []
    for kind in ("markdown", "info", "warning", "error", "success", "caption", "text", "title", "subheader"):
        parts += [str(getattr(e, "value", "")) for e in getattr(at, kind)]
    return "\n".join(parts)


def test_bulk_v2_sans_supabase_message_clair():
    at = AppTest.from_file(str(REPO / "module4_bulk_export_v2.py"), default_timeout=60)
    at.secrets["api"] = {"token": FAKE_TOKEN}
    at.run()
    assert not at.exception, at.exception
    text = all_text(at)
    assert "Connexion à Supabase impossible" in text and "Limite de la version 1" in text
    assert FAKE_TOKEN not in text
    # Le lancement est bloqué, avec la raison.
    assert any("Supabase" in i.value for i in at.info)


@pytest.mark.db
def test_bulk_v2_monitor_affiche_un_export(pg_conn):
    from bulk_export import state_store as ss
    from bulk_export.models import ExportConfig

    export_id = ss.create_export(pg_conn, ExportConfig(name="fake export affiché", filters={"brand": "FAKE"}),
                                 expected_count=10)
    ss.add_event(pg_conn, export_id, "WARNING", "fake avertissement visible")
    at = AppTest.from_file(str(REPO / "module4_bulk_export_v2.py"), default_timeout=60)
    at.secrets["api"] = {"token": FAKE_TOKEN}
    at.secrets["bulk_export"] = {"database_url": os.environ["BULK_EXPORT_TEST_DATABASE_URL"],
                                 "db_schema": "bulk_export_test"}
    at.session_state["bv2_tab"] = "Export Monitor"
    at.run()
    assert not at.exception, at.exception
    text = all_text(at)
    assert "fake export affiché" in text and "fake avertissement visible" in text
    assert "Connexion à Supabase impossible" not in text

    # New Export : formulaire chargé, lancement bloqué tant qu'il n'y a pas d'estimation.
    at.session_state["bv2_tab"] = "New Export"
    at.run()
    assert not at.exception, at.exception
    assert any("Estimez" in i.value for i in at.info)
    launch = [b for b in at.button if b.label == "Lancer l'export"][0]
    assert launch.disabled


def test_application_principale_toutes_les_entrees():
    at = AppTest.from_file(str(REPO / "main_app.py"), default_timeout=60)
    at.secrets["api"] = {"token": FAKE_TOKEN}
    at.run()
    assert not at.exception, at.exception
    nav = at.sidebar.radio[0]
    assert nav.options == ["🔍 Module 1 - Explorateur API", "🎯 Module 2 - Export Manuel", "🚀 Module 3 - Export Bulk",
                           "🧱 Bulk Export V2", "📋 Journal des exports"]
    for option in nav.options:
        at.sidebar.radio[0].set_value(option).run()
        assert not at.exception, (option, at.exception)


@pytest.mark.db
def test_bulk_v2_estimer_lancer_suivre(pg_conn):
    import time

    from bulk_export import state_store as ss

    at = AppTest.from_file(str(REPO / "module4_bulk_export_v2.py"), default_timeout=60)
    at.secrets["api"] = {"token": FAKE_TOKEN}
    at.secrets["bulk_export"] = {"database_url": os.environ["BULK_EXPORT_TEST_DATABASE_URL"],
                                 "db_schema": "bulk_export_test"}
    at.run()
    at.multiselect(key="bv2_brands").set_value(["FAKE_BRAND"]).run()
    at.button(key="bv2_estimate_btn").click().run()
    assert not at.exception, at.exception
    assert any(m.label == "Mentions (API /metrics)" and m.value == "3" for m in at.metric)
    launch = at.button(key="bv2_launch")
    assert not launch.disabled
    launch.click().run()
    assert not at.exception, at.exception
    assert at.session_state["bv2_tab"] == "Export Monitor"

    (export_id,) = [r[0] for r in pg_conn.execute("SELECT export_id FROM exports").fetchall()]
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and ss.get_export(pg_conn, export_id)["status"] != "INCOMPLETE":
        time.sleep(0.1)
    row = ss.get_export(pg_conn, export_id)
    assert row["status"] == "INCOMPLETE" and row["unique_count"] == 3 and row["expected_count"] == 3
    assert row["config_json"]["filters"]["brand"] == "FAKE_BRAND"

    # Un second lancement est bloqué tant qu'un export tourne : ici il est fini, donc le Monitor l'affiche.
    at.run()
    assert not at.exception, at.exception
    assert "Collecte terminée" in all_text(at)
