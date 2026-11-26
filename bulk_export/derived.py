"""
bulk_export/derived.py
──────────────────────────────────────────────────────────────
Formats DÉRIVÉS, fabriqués en flux à partir des mentions en base (la référence brute reste le JSONL) :

- ``export_complete.xlsx`` : AU FORMAT PLAT (mêmes colonnes, même ordre, mêmes valeurs que ``export_plat.csv``),
  une feuille « Data » (demande du 26/11/2026).
  Deux limites d'Excel, traitées DANS L'EXCEL SEULEMENT et comptées dans le manifeste :
  une cellule de plus de 32 767 caractères est coupée ; les caractères de contrôle interdits sont retirés.
  Un texte qui commence par « = » reste du texte (jamais une formule).
- ``export_plat.csv`` : le format « plat » existant, produit par ``utils.postprocess_reviews`` (réutilisée telle
  quelle), séparateur « ; », UTF-8 avec BOM. Traitement par paquets de 5 000 mentions, avec les mêmes colonnes
  et les mêmes types que si toutes les mentions étaient traitées d'un coup (comme dans les modules 2 et 3).

Jamais toutes les mentions en mémoire (règle n°2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from bulk_export.downloads import CSV_ENCODING, csv_cell

EXCEL_MAX_CELL = 32_767          # limite d'Excel par cellule
EXCEL_MAX_ROWS = 1_048_576       # limite d'Excel par feuille (en-tête compris)
PLAT_CHUNK = 5_000


# ─── Excel ────────────────────────────────────────────────────────────────────

@dataclass
class ExcelStats:
    rows: int = 0
    truncated_cells: int = 0
    removed_control_chars: int = 0

    def as_dict(self) -> dict:
        return {"rows": self.rows, "truncated_cells": self.truncated_cells,
                "removed_control_chars": self.removed_control_chars, "max_cell_chars": EXCEL_MAX_CELL}


class ExcelTooLarge(ValueError):
    """Plus de lignes que n'en accepte une feuille Excel."""


def _excel_value(value: Any, stats: ExcelStats) -> Any:
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    text = value if isinstance(value, str) else csv_cell(value)  # listes / objets : texte JSON, comme le CSV
    cleaned, n = ILLEGAL_CHARACTERS_RE.subn("", text)
    stats.removed_control_chars += n
    if len(cleaned) > EXCEL_MAX_CELL:
        cleaned = cleaned[:EXCEL_MAX_CELL]
        stats.truncated_cells += 1
    return cleaned


def _python_value(value: Any) -> Any:
    """Valeur d'une cellule de DataFrame → valeur Python (vide pour NaN)."""
    import pandas as pd

    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value.item() if hasattr(value, "item") else value


def write_excel(mentions_factory: Callable[[], Iterator[tuple]], dest: Path, expected_rows: int,
                chunk: int = PLAT_CHUNK) -> ExcelStats:
    """Excel au FORMAT PLAT (mêmes colonnes, même ordre et mêmes valeurs que ``export_plat.csv``),
    écrit en flux par paquets (mode « écriture seule » d'openpyxl)."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell

    from utils import PLAT_COLUMNS

    if expected_rows + 1 > EXCEL_MAX_ROWS:
        raise ExcelTooLarge(f"{expected_rows} mentions : au-delà de la limite d'une feuille Excel "
                            f"({EXCEL_MAX_ROWS - 1} lignes).")
    stats = ExcelStats()
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Data")
    ws.append(PLAT_COLUMNS)
    for flat in plat_chunks(mentions_factory, chunk):
        for values in flat.itertuples(index=False, name=None):
            row = []
            for raw in values:
                value = _excel_value(_python_value(raw), stats)
                if isinstance(value, str) and value.startswith("="):
                    cell = WriteOnlyCell(ws, value=value)
                    cell.data_type = "s"  # texte, jamais une formule
                    value = cell
                row.append(value)
            ws.append(row)
            stats.rows += 1
    wb.save(dest)
    return stats


# ─── Fichier plat (postprocess_reviews existante) ─────────────────────────────

def _flat_keys(record: dict, prefix: str = "") -> Iterator[str]:
    """Colonnes produites par ``pd.json_normalize`` : objets imbriqués aplatis en « a.b », listes gardées."""
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            yield from _flat_keys(value, f"{name}.")
        else:
            yield name


def _profile(mentions_factory: Callable[[], Iterator[tuple]]) -> tuple[list[str], dict[str, set]]:
    """Un passage sur toutes les mentions : colonnes (ordre d'apparition) et sortes de valeurs par colonne
    (« none » si la valeur manque ou est absente d'au moins une mention), pour reproduire le typage de pandas."""
    columns: dict[str, None] = {}
    kinds: dict[str, set] = {}
    present: dict[str, int] = {}
    total = 0
    for _, _, raw_json in mentions_factory():
        total += 1
        for name, value in _flat_values(json.loads(raw_json)):
            columns.setdefault(name, None)
            kinds.setdefault(name, set()).add(_kind(value))
            present[name] = present.get(name, 0) + 1
    for name in columns:
        if present[name] < total:
            kinds[name].add("none")
    return list(columns), kinds


def _flat_values(record: dict, prefix: str = "") -> Iterator[tuple[str, Any]]:
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            yield from _flat_values(value, f"{name}.")
        else:
            yield name, value


def _kind(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "other"


def _harmonize(df, columns: list[str], kinds: dict[str, set]):
    """Impose à un paquet les colonnes et les types qu'aurait donnés le traitement de toutes les mentions d'un coup
    (ex. une note entière devient 5.0 dans tout le fichier dès qu'une seule note manque, comme avec pandas)."""
    df = df.reindex(columns=columns)
    for col in columns:
        k = kinds[col]
        if k <= {"int", "float", "none"} and k & {"int", "float"} and k & {"float", "none"}:
            df[col] = df[col].astype("float64")
    return df


def plat_chunks(mentions_factory: Callable[[], Iterator[tuple]], chunk: int = PLAT_CHUNK):
    """Les mentions au format plat (``utils.postprocess_reviews``), par paquets de ``chunk`` mentions, avec les
    colonnes et les types qu'aurait donnés le traitement de toutes les mentions d'un coup."""
    import pandas as pd

    from utils import postprocess_reviews  # fonction existante, réutilisée telle quelle

    columns, kinds = _profile(mentions_factory)
    buffer: list[dict] = []
    for _, _, raw_json in mentions_factory():
        buffer.append(json.loads(raw_json))
        if len(buffer) >= chunk:
            yield postprocess_reviews(_harmonize(_str_lists(pd.json_normalize(buffer)), columns, kinds).copy())
            buffer = []
    if buffer:
        yield postprocess_reviews(_harmonize(_str_lists(pd.json_normalize(buffer)), columns, kinds).copy())


def write_plat(mentions_factory: Callable[[], Iterator[tuple]], dest: Path, chunk: int = PLAT_CHUNK) -> int:
    """Fichier plat (« ; », UTF-8 avec BOM), par paquets. Renvoie le nombre de lignes écrites."""
    rows, first = 0, True
    with open(dest, "w", encoding=CSV_ENCODING, newline="") as fh:
        for flat in plat_chunks(mentions_factory, chunk):
            fh.write(flat.to_csv(index=False, sep=";", header=first))
            first = False
            rows += len(flat)
    return rows


def _str_lists(df):
    """Même conversion que les modules 2 et 3 : listes et objets écrits avec ``str()``."""
    convert = lambda x: str(x) if isinstance(x, (dict, list)) else x  # noqa: E731
    return df.map(convert) if hasattr(df, "map") else df.applymap(convert)
