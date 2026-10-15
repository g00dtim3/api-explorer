"""Tri des mentions d'une page (sans base). Données synthétiques fake_*."""

import copy
import json

from bulk_export import dedup
from bulk_export.fingerprints import compute

fake_a = {"id": "1", "brand": "FAKE", "date": "2024-11-28T15:45:28Z", "product": "p", "rating": 5,
          "content trad": "fake a"}
fake_b = {**fake_a, "id": "2", "content trad": "fake b"}


def classify(records, known_raw=(), known_content=None):
    return dedup.classify(dedup.prepare(records), known_raw=set(known_raw), known_content=known_content or {})


def test_nouvelles_mentions():
    page = classify([fake_a, fake_b])
    assert len(page.new_mentions) == 2 and not page.conflicts and not page.rejected


def test_doublon_dans_la_meme_page_id_different():
    copie = {**fake_a, "id": "99"}
    page = classify([fake_a, copie])
    assert len(page.new_mentions) == 1
    (c,) = page.conflicts
    assert c.kind == "duplicate" and c.api_id == "99" and c.mention_id == page.new_mentions[0].mention_id


def test_doublon_deja_en_base():
    page = classify([fake_a], known_raw={compute(fake_a).raw_hash})
    assert not page.new_mentions and page.conflicts[0].kind == "duplicate"


def test_jumelles_gardees_et_collision_notee():
    jumelle = {**fake_a, "id": "3", "opinion": "negative"}
    page = classify([fake_a, jumelle])
    assert len(page.new_mentions) == 2
    (c,) = page.conflicts
    assert c.kind == "collision" and c.other_mention_id == page.new_mentions[0].mention_id


def test_jumelle_d_une_mention_deja_en_base():
    jumelle = {**fake_a, "opinion": "negative"}
    fp = compute(fake_a)
    page = classify([jumelle], known_content={fp.content_key: fp.raw_hash})
    assert len(page.new_mentions) == 1 and page.conflicts[0].other_mention_id == fp.raw_hash


def test_sans_date_rejetee_et_gardee_telle_quelle():
    sans_date = {**fake_b, "date": None}
    page = classify([fake_a, sans_date])
    assert len(page.new_mentions) == 1
    (r,) = page.rejected
    assert json.loads(r.raw_json) == sans_date and r.api_id == "2" and "date" in r.reason


def test_mentions_jamais_modifiees_et_json_fidele():
    record = {**fake_a, "content trad": "  é è 🙂 \"guillemets\"\n; retour  ", "liste": [1, None]}
    original = copy.deepcopy(record)
    page = classify([record])
    assert record == original
    stored = page.new_mentions[0].raw_json
    assert json.loads(stored) == original
    assert list(json.loads(stored)) == list(original)  # ordre des champs conservé


def test_id_api_repetes_pour_mentions_differentes():
    autre = {**fake_b, "id": "1"}  # même id que fake_a, contenu différent
    assert classify([fake_a, autre]).repeated_api_ids == 1
    assert classify([fake_a, {**fake_a}]).repeated_api_ids == 0  # vrai doublon : pas compté ici
