"""Règles de la page Bulk Export V2 (sans affichage). Données synthétiques fake_*."""

import datetime as dt
import json

import pytest

pytest.importorskip("streamlit")  # utils.build_filter_params dépend de Streamlit

from bulk_export import ui_logic as u  # noqa: E402
from bulk_export.models import ConfigError, ExportConfig  # noqa: E402

fake_config = ExportConfig(name="fake", filters={"brand": "FAKE"})


def test_filtres_identiques_au_module_1():
    filters = u.form_to_filters(start_date=dt.date(2024, 1, 1), end_date=dt.date(2024, 6, 30), category="ALL",
                                subcategory="ALL", brands=["FAKE A", "Fake & Co"], countries=["ALL"],
                                sources=["Fake FR"], attributes_positive=["Texture"])
    assert filters == {"start-date": "2024-01-01", "end-date": "2024-06-30", "brand": "FAKE A,Fake & Co",
                       "source": "Fake FR", "attribute-positive": "Texture"}
    ExportConfig(name="fake", filters=filters)  # accepté tel quel par la configuration figée


def test_import_format_v2():
    imported = u.parse_import_json(ExportConfig(name="fake v2", filters={"brand": "FAKE"}, batch_size=10_000).to_json())
    assert imported.source_format == "v2" and imported.filters == {"brand": "FAKE"}
    assert imported.options["batch_size"] == 10_000 and imported.options["name"] == "fake v2"


def test_import_ancien_format_modules_1_a_3():
    old = {"start-date": "2025-01-01", "end-date": "2025-04-30", "brand": "AVÈNE,aderma", "category": "bodycare",
           "subcategory": "ALL", "country": ["France"], "source": [], "attributes": ["Texture"],
           "selected_products": ["P1"], "export_mode": "BULK_BY_BRAND"}
    imported = u.parse_import_json(json.dumps(old))
    assert imported.source_format == "ancien"
    assert imported.filters == {"start-date": "2025-01-01", "end-date": "2025-04-30", "brand": "AVÈNE,aderma",
                                "category": "bodycare", "country": "France", "attribute": "Texture"}
    assert any("produits ignorée" in w for w in imported.warnings)


@pytest.mark.parametrize("texte", [
    '{"brand": "FAKE", "token": "FAKE_secret_123"}',
    '{"name": "x", "filters": {"brand": "FAKE"}, "api_key": "x"}',
    '{pas du json', '[1, 2]', '{"inconnu": 1}',
])
def test_import_refuse(texte):
    with pytest.raises((ValueError, ConfigError)):
        u.parse_import_json(texte)


def test_estimation_sans_mesure_reelle_pas_de_duree_ni_d_espace():
    e = u.compute_estimate(fake_config, 25_500, None)
    assert (e.pages, e.batches, e.seconds, e.raw_bytes) == (26, 2, None, None)
    peu = u.Measures(seconds_per_page=2.0, page_intervals=2, bytes_per_mention=900.0, mentions_measured=50)
    e = u.compute_estimate(fake_config, 25_500, peu)
    assert e.seconds is None and e.raw_bytes is None  # trop peu de mesures


def test_estimation_avec_mesures_reelles():
    m = u.Measures(seconds_per_page=2.0, page_intervals=10, bytes_per_mention=900.0, mentions_measured=5_000)
    e = u.compute_estimate(fake_config, 500_000, m)
    assert e.pages == 500 and e.seconds == 1000.0 and e.raw_bytes == 450_000_000


def test_blocages():
    est = u.compute_estimate(fake_config, 10)
    ok = dict(config=fake_config, config_error=None, estimate=est, active_export=None, db_ok=True)
    assert u.launch_blockers(**ok) == []
    assert u.launch_blockers(**{**ok, "db_ok": False})
    assert u.launch_blockers(**{**ok, "runner_ok": False})
    assert u.launch_blockers(**{**ok, "config": None, "config_error": "nom manquant"})
    assert u.launch_blockers(**{**ok, "estimate": None})
    assert u.launch_blockers(**{**ok, "active_export": "exp_x"})
    assert u.launch_blockers(**{**ok, "estimate": u.compute_estimate(fake_config, 0)})
    autre = ExportConfig(name="fake", filters={"brand": "AUTRE"})
    assert "Estimez" in u.launch_blockers(**{**ok, "estimate": u.compute_estimate(autre, 10)})[0]


def test_avertissement_volume():
    assert u.launch_warnings(u.compute_estimate(fake_config, 500_001))
    assert not u.launch_warnings(u.compute_estimate(fake_config, 500_000))


def test_progression_plafonnee():
    assert u.progress(50, 100) == (0.5, -50)
    assert u.progress(120, 100) == (1.0, 20)
    assert u.progress(5, None) == (0.0, None)


def test_formats():
    assert u.format_duration(3725) == "1 h 02 min" and u.format_duration(65) == "1 min 05 s"
    assert u.format_duration(None) == "—"
    assert u.format_bytes(10) == "10 octets" and u.format_bytes(1536) == "1.5 Ko"


def test_orphelin_et_choix_export():
    now = dt.datetime(2026, 10, 15, 12, tzinfo=dt.timezone.utc)
    assert u.is_orphan({"status": "RUNNING", "lease_expires_at": now - dt.timedelta(seconds=1)}, now)
    assert not u.is_orphan({"status": "RUNNING", "lease_expires_at": now + dt.timedelta(seconds=60)}, now)
    assert not u.is_orphan({"status": "PAUSED", "lease_expires_at": None}, now)
    exports = [{"export_id": "a"}, {"export_id": "b"}]
    assert u.choose_export(exports, active="b", preferred=None) == "b"
    assert u.choose_export(exports, active="b", preferred="a") == "a"
    assert u.choose_export(exports, active=None, preferred="zz") == "a"
    assert u.choose_export([], None, None) is None
