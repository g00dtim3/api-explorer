"""Formats dérivés : fichier plat (identique au code existant) et Excel (mêmes valeurs que le CSV).

Données synthétiques fake_*.
"""

import io
import json

import pytest

pytest.importorskip("streamlit")  # utils dépend de Streamlit
pytest.importorskip("openpyxl")

from bulk_export import derived, downloads  # noqa: E402

fake_records = [
    {"id": "1", "attributes": ["Texture", "Scent"], "attributes positive": ["Texture"], "attributes negative": None,
     "brand": "FAKE", "business indicator": "Sampling Rate", "category": "c", "content origin": "o1",
     "content trad": "Texte; avec \"guillemets\"\net retour", "country": "France", "date": "2024-11-28T15:45:28Z",
     "opinion": "positive", "product": "p", "rating": 5, "source": "s", "subcategory": "x"},
    {"id": "2", "attributes": None, "attributes positive": None, "attributes negative": ["Price"], "brand": "FAKE 🙂",
     "business indicator": None, "category": "c", "content origin": "o2", "content trad": "=SOMME(A1)",
     "country": "Italy", "date": "2023-02-03T00:10:00Z", "opinion": "negative", "product": "p2", "rating": None,
     "source": None, "subcategory": "x"},
    {"id": "3", "attributes": ["Safety", "Composition"], "attributes positive": ["Safety"],
     "attributes negative": ["Composition"], "brand": "FAKE", "business indicator": None, "category": "c",
     "content origin": "o3", "content trad": "t3", "country": "France", "date": "2024-01-31T23:59:59Z",
     "opinion": "neutral", "product": "p", "rating": 3, "source": "s", "subcategory": "x", "champ rare": "z"},
    {"id": "4", "attributes": [], "attributes positive": None, "attributes negative": None, "brand": "FAKE",
     "business indicator": "Autre", "category": "c", "content origin": "o4", "content trad": "t4",
     "country": "France", "date": "2024-05-01T08:00:00Z", "opinion": "positive", "product": "p", "rating": 4,
     "source": "s", "subcategory": "x", "imbriqué": {"a": 1, "b": {"c": "d"}}},
]


def mentions(records=fake_records):
    return lambda: iter([(i + 1, f"h{i}", json.dumps(r, ensure_ascii=False)) for i, r in enumerate(records)])


def legacy_flat(records) -> str:
    """Chaîne existante des modules 2/3 : json_normalize + str() des listes + postprocess_reviews + to_csv."""
    import pandas as pd

    from utils import postprocess_reviews

    df = pd.json_normalize(records)
    conv = lambda x: str(x) if isinstance(x, (dict, list)) else x  # noqa: E731
    df = df.map(conv) if hasattr(df, "map") else df.applymap(conv)
    return postprocess_reviews(df.copy()).to_csv(index=False, sep=";")


@pytest.mark.parametrize("chunk", [1, 2, 3, 1000])
def test_plat_par_paquets_identique_au_code_existant(tmp_path, chunk):
    dest = tmp_path / "plat.csv"
    rows = derived.write_plat(mentions(), dest, chunk=chunk)
    assert rows == len(fake_records)
    assert dest.read_bytes().startswith(b"\xef\xbb\xbf")
    assert dest.read_text(encoding="utf-8-sig") == legacy_flat(fake_records)


def test_plat_note_entiere_partout_si_aucune_manquante(tmp_path):
    records = [dict(r, rating=5) for r in fake_records]
    dest = tmp_path / "plat.csv"
    derived.write_plat(mentions(records), dest, chunk=1)
    assert dest.read_text(encoding="utf-8-sig") == legacy_flat(records)


COLONNES_DEMANDEES = [  # ordre demandé le 26/11/2026, pour l'Excel et le fichier plat
    "guid", "brand", "country", "date", "opinion", "product_name_SEMANTIWEB", "rating", "source", "verbatim_content",
    "sampling", "attribute_Efficiency", "attribute_Packaging", "attribute_Price", "attribute_Quality",
    "attribute_Scent", "attribute_Taste", "attribute_Texture", "attribute_Safety", "attribute_Composition",
    "categorie interne", "sous categorie interne", "photo",
]
# Colonnes obligatoires de l'import Compass (compass_import/config.toml, required_columns).
COMPASS_OBLIGATOIRES = ["guid", "brand", "country", "date", "opinion", "product_name_SEMANTIWEB", "rating", "source",
                        "verbatim_content", "sampling"]


def test_plat_colonnes_exactes_dans_l_ordre(tmp_path):
    import csv

    from utils import PLAT_COLUMNS
    assert PLAT_COLUMNS == COLONNES_DEMANDEES
    dest = tmp_path / "plat.csv"
    derived.write_plat(mentions(), dest, chunk=2)
    with open(dest, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh, delimiter=";"))
    assert rows[0] == COLONNES_DEMANDEES
    assert set(COMPASS_OBLIGATOIRES) <= set(rows[0])
    body = [dict(zip(rows[0], r)) for r in rows[1:]]
    assert [r["guid"] for r in body] == ["1", "2", "3", "4"]
    assert [r["sampling"] for r in body] == ["1", "0", "0", "0"]
    assert all(r["categorie interne"] == r["sous categorie interne"] == r["photo"] == "" for r in body)
    assert body[0]["verbatim_content"] == fake_records[0]["content trad"]
    assert body[0]["date"] == "01/11/2024"
    assert body[0]["attribute_Texture"] == "positive" and body[0]["attribute_Scent"] == "neutre"
    assert body[2]["attribute_Safety"] == "positive" and body[2]["attribute_Composition"] == "negative"


def test_excel_identique_au_fichier_plat(tmp_path):
    import csv

    from openpyxl import load_workbook

    plat = tmp_path / "plat.csv"
    derived.write_plat(mentions(), plat)
    xlsx = tmp_path / "e.xlsx"
    stats = derived.write_excel(mentions(), xlsx, len(fake_records), chunk=3)
    assert stats.rows == 4 and stats.truncated_cells == 0 and stats.removed_control_chars == 0
    rows = list(load_workbook(xlsx, read_only=True)["Data"].iter_rows(values_only=True))
    assert list(rows[0]) == COLONNES_DEMANDEES
    with open(plat, encoding="utf-8-sig", newline="") as fh:
        plat_rows = list(csv.reader(fh, delimiter=";"))[1:]

    def same(v, text):
        if v is None:
            return text == ""
        if isinstance(v, (int, float)) and not isinstance(v, bool):  # Excel relit 5.0 comme 5 : même nombre
            return float(text) == float(v)
        return str(v) == text

    for row, expected in zip(rows[1:], plat_rows):
        row = list(row) + [None] * (len(COLONNES_DEMANDEES) - len(row))  # cellules vides en fin de ligne omises
        assert all(same(v, t) for v, t in zip(row, expected)), (row, expected)
    assert rows[2][COLONNES_DEMANDEES.index("verbatim_content")] == "=SOMME(A1)"  # texte, pas une formule


def test_excel_cellule_trop_longue_et_caracteres_interdits(tmp_path):
    from openpyxl import load_workbook

    records = [dict(fake_records[0], **{"content trad": "x" * 40_000, "brand": "FAKE\x01\x02"})]
    xlsx = tmp_path / "e.xlsx"
    stats = derived.write_excel(mentions(records), xlsx, 1)
    assert stats.truncated_cells == 1 and stats.removed_control_chars == 2
    row = list(load_workbook(xlsx, read_only=True)["Data"].iter_rows(values_only=True))[1]
    assert len(row[COLONNES_DEMANDEES.index("verbatim_content")]) == derived.EXCEL_MAX_CELL
    assert row[COLONNES_DEMANDEES.index("brand")] == "FAKE"


def test_excel_trop_de_lignes_refuse(tmp_path):
    with pytest.raises(derived.ExcelTooLarge):
        derived.write_excel(mentions([]), tmp_path / "e.xlsx", derived.EXCEL_MAX_ROWS)


def test_boutons_legacy_excel_et_plat_au_nouveau_format_csv_inchange(monkeypatch):
    """Modules 2 et 3 : utils.display_download_buttons (boutons CSV, Excel, format plat)."""
    import contextlib
    import csv
    import io

    import pandas as pd
    from openpyxl import load_workbook

    import utils

    captured = {}

    class FakeSt:
        def columns(self, n):
            return [contextlib.nullcontext() for _ in range(n)]

        def download_button(self, label, data, file_name, **kw):
            captured[file_name] = data

        def warning(self, msg):
            raise AssertionError(msg)

        def error(self, msg):
            raise AssertionError(msg)

    monkeypatch.setattr(utils, "st", FakeSt())
    df = pd.json_normalize(fake_records)
    df = df.map(lambda x: str(x) if isinstance(x, (dict, list)) else x)
    utils.display_download_buttons(df, "fake", mode="complet")

    csv_data = captured["fake_complet.csv"]
    assert next(csv.reader(io.StringIO(csv_data.lstrip("﻿")))) == list(df.columns)  # CSV brut inchangé
    plat = list(csv.reader(io.StringIO(captured["fake_complet_plat.csv"].lstrip("﻿")), delimiter=";"))
    assert plat[0] == COLONNES_DEMANDEES and len(plat) == 5
    if utils.EXCEL_AVAILABLE:
        ws = load_workbook(io.BytesIO(captured["fake_complet.xlsx"]), read_only=True).active
        assert list(next(ws.iter_rows(values_only=True))) == COLONNES_DEMANDEES
