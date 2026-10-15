"""
bulk_export/fingerprints.py
──────────────────────────────────────────────────────────────
Empreintes d'une mention (docs/bulk_v2/decision_identifiant.md) :

- ``raw_hash``    : SHA-256 de la mention complète SAUF ``id`` → clé d'unicité de l'export ;
- ``content_key`` : méthode Compass (7 champs), date au JOUR → repère les avis jumeaux ;
- ``compass_id``  : reproduction exacte de l'``id`` calculé par Compass sur le format plat
                    (date au 1er du mois) → lien futur avec le projet Compass.

La mention reçue n'est jamais modifiée : les empreintes sont calculées sur une copie.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

# Réglages par défaut. Ils sont configurables (règle n°10) car le nom réel du champ
# verbatim n'est pas confirmé (audit_api.md, écart C).
DEFAULT_SETTINGS: Mapping[str, Any] = {
    # Champs ignorés pour raw_hash : l'API régénère `id` à chaque export.
    "raw_hash_exclude": ("id",),
    # Champ verbatim utilisé pour content_key (nom documenté par le fournisseur).
    "verbatim_field": "verbatim content",
    # Champ verbatim que lit Compass : le format plat renomme `content trad` en `verbatim_content`.
    "compass_verbatim_field": "content trad",
}


class MissingDateError(ValueError):
    """Mention sans date exploitable : erreur explicite (règle n°6)."""


@dataclass(frozen=True)
class Fingerprints:
    raw_hash: str
    content_key: str
    compass_id: str | None  # None si Compass ne pourrait pas calculer d'id (champ verbatim absent)


def merged_settings(settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    if settings:
        unknown = set(settings) - set(DEFAULT_SETTINGS)
        if unknown:
            raise ValueError(f"Réglages d'empreinte inconnus : {sorted(unknown)}.")
        out.update(settings)
    out["raw_hash_exclude"] = tuple(out["raw_hash_exclude"])
    return out


# ─── raw_hash ─────────────────────────────────────────────────────────────────

def canonical_json(record: Mapping[str, Any], exclude: tuple[str, ...] = ()) -> str:
    """JSON aux clés triées, sans espace, caractères non ASCII gardés tels quels.
    Les valeurs ne sont pas modifiées ; seuls les champs ``exclude`` sont retirés."""
    kept = {k: v for k, v in record.items() if k not in exclude}
    return json.dumps(kept, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def raw_hash(record: Mapping[str, Any], exclude: tuple[str, ...] = ("id",)) -> str:
    return hashlib.sha256(canonical_json(record, exclude).encode("utf-8")).hexdigest()


# ─── Méthode Compass ──────────────────────────────────────────────────────────

def compass_verbatim_hash(brand, date, product_name, verbatim_content,
                          country="", source="", rating="") -> str:
    """COPIE FIGÉE de ``compass_import/core/hasher.py::verbatim_hash`` (scénario B),
    dépôt g00dtim3/mvp_verbatim_import. Ne pas modifier : toute différence casserait
    le lien entre les deux projets. Un test vérifie le résultat sur des valeurs connues."""
    parts = [
        str(brand).strip().lower(),
        str(date).strip().lower(),
        str(product_name).strip().lower(),
        str(verbatim_content).strip().lower(),
        str(country).strip().lower(),
        str(source).strip().lower(),
        str(rating).strip().lower(),
    ]
    raw = "".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# Valeurs que pandas (read_csv, keep_default_na=True) transforme en « vide » à la
# relecture du CSV plat par Compass. Liste de pandas.
_PANDAS_NA_STRINGS = frozenset({
    "", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan", "1.#IND",
    "1.#QNAN", "<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a", "nan", "null",
})


def _as_compass_text(value: Any) -> str:
    """Valeur telle que Compass la voit après le passage par le CSV plat :
    vide → "", texte reconnu comme « manquant » par pandas → "", sinon str().strip()."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value)
    if text in _PANDAS_NA_STRINGS:
        return ""
    return text.strip()


def _as_compass_rating(value: Any) -> str:
    """Même règle que Compass : entier de 1 à 5, sinon vide."""
    try:
        r = int(float(_as_compass_text(value)))
    except (ValueError, TypeError, OverflowError):
        return ""
    return str(r) if 1 <= r <= 5 else ""


def _parse_date(value: Any) -> datetime:
    """Date ISO de l'API (ex. ``2024-11-28T15:45:28Z``). Absente ou illisible → erreur explicite."""
    text = _as_compass_text(value)
    if not text:
        raise MissingDateError("Mention sans date.")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise MissingDateError("Date illisible (format ISO attendu).") from None


def _compass_fields(record: Mapping[str, Any], verbatim: Any, date_text: str) -> tuple:
    return (
        _as_compass_text(record.get("brand")),
        date_text,
        _as_compass_text(record.get("product")),
        _as_compass_text(verbatim),
        _as_compass_text(record.get("country")),
        _as_compass_text(record.get("source")),
        _as_compass_rating(record.get("rating")),
    )


def content_key(record: Mapping[str, Any], verbatim_field: str = "verbatim content") -> str:
    """Méthode Compass, mais avec la date au jour (``AAAA-MM-JJ``, dans le fuseau de la donnée)."""
    day = _parse_date(record.get("date")).date().isoformat()
    return compass_verbatim_hash(*_compass_fields(record, record.get(verbatim_field), day))


def compass_id(record: Mapping[str, Any], compass_verbatim_field: str = "content trad") -> str | None:
    """L'``id`` que Compass calculerait pour cette mention après passage par le format plat.

    Le format plat ramène la date au 1er du mois. Si le champ verbatim lu par Compass est
    absent de la mention, Compass refuserait le fichier (colonne obligatoire manquante) :
    on renvoie None plutôt qu'une empreinte trompeuse."""
    if compass_verbatim_field not in record:
        return None
    d = _parse_date(record.get("date"))
    month = f"{d.year:04d}-{d.month:02d}-01"
    return compass_verbatim_hash(*_compass_fields(record, record.get(compass_verbatim_field), month))


def compute(record: Mapping[str, Any], settings: Mapping[str, Any] | None = None) -> Fingerprints:
    """Calcule les trois empreintes. Lève MissingDateError si la date manque."""
    s = merged_settings(settings)
    return Fingerprints(
        raw_hash=raw_hash(record, s["raw_hash_exclude"]),
        content_key=content_key(record, s["verbatim_field"]),
        compass_id=compass_id(record, s["compass_verbatim_field"]),
    )
