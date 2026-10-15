"""Empreintes des mentions (decision_identifiant.md).

Toutes les mentions ici sont de FAUSSES données (fake_*), jamais des verbatims réels.
"""

import copy
import hashlib

import pytest

from bulk_export.fingerprints import (
    MissingDateError, compass_id, compass_verbatim_hash, compute, content_key, merged_settings, raw_hash,
)

fake_mention = {
    "id": "1", "attributes": None, "attributes positive": None, "attributes negative": None,
    "brand": "FAKE_BRAND", "business indicator": None, "category": "makeup", "country": "France",
    "date": "2024-11-28T15:45:28Z", "opinion": "positive", "product": "fake product - mascara",
    "rating": 5, "source": "Fake Source FR", "subcategory": "eyes",
    "content trad": "  Mon épouse est ravie  ", "content origin": "x",
}
fake_mention_2 = {
    "id": "2", "attributes": ["Texture"], "attributes positive": ["Texture"], "attributes negative": None,
    "brand": "Fake & Co", "business indicator": "Sampling Rate", "category": "skin", "country": "Italy",
    "date": "2023-02-03T00:10:00Z", "opinion": "negative", "product": "FAKE Cream; 50ml",
    "rating": None, "source": None, "subcategory": "face",
    "content trad": "Ligne1\nLigne2; \"quote\"", "content origin": "y",
}
fake_mention_3 = {
    "id": "3", "attributes": None, "attributes positive": None, "attributes negative": None,
    "brand": "FAKE_BRAND", "business indicator": None, "category": "makeup", "country": "France",
    "date": "2024-01-31T23:59:59Z", "opinion": "neutral", "product": "fake", "rating": 3, "source": "S",
    "subcategory": "eyes", "content trad": "NA", "content origin": "z",
}

# Valeurs de référence obtenues le 15/10/2026 en faisant passer ces fausses mentions par la
# chaîne réelle : format plat de l'application (utils.postprocess_reviews + to_csv), puis
# Compass (core.importer.parse_csv + normalize_batch, dépôt g00dtim3/mvp_verbatim_import).
COMPASS_REFERENCE = [
    (fake_mention, "8c9117c4eb038fcbcb6a00070ad1636a013a68ebaeaf01afd96a99d67a24f0c8"),
    (fake_mention_2, "9b68defddd4430a0c9c7b481e9377105d82a8b1bab867247c5c2c24755eaf38f"),
    (fake_mention_3, "80a2d393061171ecef19e38ee3f2329735a4d82a85b4323fb445a489e8f628d5"),
]


# ─── Méthode Compass ──────────────────────────────────────────────────────────

def test_copie_compass_identique_a_la_reference():
    # Valeur calculée par compass_import/core/hasher.py::verbatim_hash.
    assert compass_verbatim_hash("brand", "2024-01-15", "product", "content", "FR", "Amazon", "4") \
        == "81d5bf1e86024058e3132c2d11403ff27779c56d712727f497a1bbfecf8d9b88"
    assert compass_verbatim_hash("brand", "2024-01-15", "product", "content") \
        == hashlib.sha256(b"brand2024-01-15productcontent").hexdigest()


@pytest.mark.parametrize("mention,attendu", COMPASS_REFERENCE)
def test_compass_id_identique_a_compass(mention, attendu):
    assert compass_id(mention) == attendu


def test_compass_id_absent_si_champ_verbatim_absent():
    m = {k: v for k, v in fake_mention.items() if k != "content trad"}
    assert compass_id(m) is None


def test_compass_id_date_au_mois():
    autre_jour = {**fake_mention, "date": "2024-11-02T08:00:00Z"}
    assert compass_id(autre_jour) == compass_id(fake_mention)


# ─── content_key ──────────────────────────────────────────────────────────────

def test_content_key_date_au_jour():
    autre_jour = {**fake_mention, "date": "2024-11-02T08:00:00Z"}
    assert content_key(autre_jour, "content trad") != content_key(fake_mention, "content trad")


def test_content_key_ignore_id_casse_et_espaces():
    variante = {**fake_mention, "id": "999", "brand": "fake_brand", "content trad": "mon épouse est ravie"}
    assert content_key(variante, "content trad") == content_key(fake_mention, "content trad")


def test_content_key_champ_verbatim_reglable():
    assert content_key(fake_mention, "content trad") != content_key(fake_mention, "content origin")


# ─── raw_hash ─────────────────────────────────────────────────────────────────

def test_raw_hash_ignore_id():
    assert raw_hash({**fake_mention, "id": "autre"}) == raw_hash(fake_mention)


def test_raw_hash_ignore_ordre_des_champs():
    inverse = dict(reversed(list(fake_mention.items())))
    assert raw_hash(inverse) == raw_hash(fake_mention)


@pytest.mark.parametrize("champ,valeur", [
    ("opinion", "negative"), ("attributes", ["Texture"]), ("content trad", "Mon épouse est ravie"),
    ("rating", 5.0), ("rating", "5"), ("nouveau champ", None),
])
def test_raw_hash_change_des_qu_une_valeur_change(champ, valeur):
    assert raw_hash({**fake_mention, champ: valeur}) != raw_hash(fake_mention)


def test_raw_hash_inclut_id_si_reglage_vide():
    assert raw_hash({**fake_mention, "id": "autre"}, exclude=()) != raw_hash(fake_mention, exclude=())


# ─── compute ──────────────────────────────────────────────────────────────────

def test_compute_ne_modifie_pas_la_mention():
    original = copy.deepcopy(fake_mention_2)
    compute(fake_mention_2)
    assert fake_mention_2 == original


def test_compute_trois_empreintes():
    fp = compute(fake_mention, {"verbatim_field": "content trad"})
    assert len(fp.raw_hash) == len(fp.content_key) == len(fp.compass_id) == 64
    assert fp.compass_id == COMPASS_REFERENCE[0][1]


@pytest.mark.parametrize("date", [None, "", "  ", "NA", "28/11/2024", "pas une date"])
def test_mention_sans_date_erreur_explicite(date):
    with pytest.raises(MissingDateError):
        compute({**fake_mention, "date": date})


def test_mention_sans_champ_date():
    m = {k: v for k, v in fake_mention.items() if k != "date"}
    with pytest.raises(MissingDateError):
        compute(m)


def test_reglage_inconnu_refuse():
    with pytest.raises(ValueError):
        merged_settings({"inconnu": 1})
