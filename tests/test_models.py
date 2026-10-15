"""Statuts, transitions, configuration figée, identifiant d'export."""

import json

import pytest

from bulk_export.models import (
    ALLOWED_TRANSITIONS, ConfigError, ExportConfig, ExportStatus as S, InvalidTransitionError,
    check_transition, new_export_id, validate_export_id,
)

fake_filters = {"brand": "FAKE_BRAND", "start-date": "2024-01-01", "end-date": "2024-06-30"}


# ─── Transitions ──────────────────────────────────────────────────────────────

def test_parcours_normal_autorise():
    chemin = [S.PENDING, S.RUNNING, S.STOPPING, S.PAUSED, S.RUNNING, S.INCOMPLETE, S.VALIDATING, S.COMPLETED]
    for a, b in zip(chemin, chemin[1:]):
        check_transition(a, b)


def test_completed_uniquement_depuis_validating():
    for status in S:
        if status is S.VALIDATING:
            check_transition(status, S.COMPLETED)
        else:
            with pytest.raises(InvalidTransitionError):
                check_transition(status, S.COMPLETED)


def test_completed_est_final():
    assert ALLOWED_TRANSITIONS[S.COMPLETED] == frozenset()
    with pytest.raises(InvalidTransitionError):
        check_transition(S.COMPLETED, S.RUNNING)


def test_reprise_possible_apres_echec_ou_pause():
    check_transition(S.FAILED, S.RUNNING)
    check_transition(S.PAUSED, S.RUNNING)


def test_transition_interdite_message_clair():
    with pytest.raises(InvalidTransitionError, match="PENDING → VALIDATING"):
        check_transition("PENDING", "VALIDATING")


def test_tous_les_statuts_ont_une_regle():
    assert set(ALLOWED_TRANSITIONS) == set(S)


# ─── Identifiant d'export ─────────────────────────────────────────────────────

def test_export_id_valide_et_unique():
    a, b = new_export_id(), new_export_id()
    assert validate_export_id(a) == a
    assert a != b


@pytest.mark.parametrize("malicieux", [
    "../../etc/passwd", "exp_20261015T143000Z_9f3a1c2b/../x", "exp_20261015T143000Z_9F3A1C2B",
    "exp_x", "", "exp_20261015T143000Z_9f3a1c2b; DROP TABLE exports", None, 42,
])
def test_export_id_malicieux_refuse(malicieux):
    with pytest.raises(ValueError):
        validate_export_id(malicieux)


# ─── Configuration ────────────────────────────────────────────────────────────

def test_meme_config_meme_empreinte():
    a = ExportConfig(name="fake", filters=dict(fake_filters))
    b = ExportConfig(name="fake", filters=dict(reversed(list(fake_filters.items()))))
    assert a.config_hash == b.config_hash
    assert len(a.config_hash) == 64


def test_config_differente_empreinte_differente():
    a = ExportConfig(name="fake", filters=fake_filters)
    b = ExportConfig(name="fake", filters={**fake_filters, "country": "France"})
    assert a.config_hash != b.config_hash


def test_config_figee():
    c = ExportConfig(name="fake", filters=fake_filters)
    with pytest.raises(Exception):
        c.rows = 10
    with pytest.raises(TypeError):
        c.filters["brand"] = "AUTRE"


def test_random_interdit():
    with pytest.raises(ConfigError, match="random"):
        ExportConfig(name="fake", filters=fake_filters, random=True)


@pytest.mark.parametrize("cle", ["token", "rows", "nextCursorMark", "random", "inconnu"])
def test_filtre_technique_ou_inconnu_refuse(cle):
    with pytest.raises(ConfigError):
        ExportConfig(name="fake", filters={**fake_filters, cle: "x"})


@pytest.mark.parametrize("kwargs", [
    {"batch_size": 12_345}, {"rows": 0}, {"rows": 1_001}, {"output_formats": ("xlsx",)},
    {"output_formats": ()}, {"name": "  "},
])
def test_valeurs_invalides_refusees(kwargs):
    base = {"name": "fake", "filters": fake_filters}
    with pytest.raises(ConfigError):
        ExportConfig(**{**base, **kwargs})


def test_aller_retour_json():
    c = ExportConfig(name="fake", filters=fake_filters, batch_size=10_000,
                     fingerprint={"verbatim_field": "content trad"})
    assert ExportConfig.from_json(c.to_json()) == c
    assert ExportConfig.from_json(c.to_json()).config_hash == c.config_hash


@pytest.mark.parametrize("donnees", [
    {"name": "fake", "filters": fake_filters, "token": "fake_token_123"},
    {"name": "fake", "filters": fake_filters, "fingerprint": {"api_key": "x"}},
    {"name": "fake", "filters": {**fake_filters, "Token": "x"}},
])
def test_import_json_refuse_les_secrets(donnees):
    with pytest.raises(ValueError, match="secret|Champ"):
        ExportConfig.from_json(json.dumps(donnees))


def test_import_json_illisible():
    with pytest.raises(ConfigError, match="JSON illisible"):
        ExportConfig.from_json("{pas du json")


def test_import_json_champ_inconnu():
    with pytest.raises(ConfigError, match="inconnus"):
        ExportConfig.from_dict({"name": "fake", "filters": fake_filters, "autre": 1})
