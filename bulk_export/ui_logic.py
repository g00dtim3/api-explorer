"""
bulk_export/ui_logic.py
──────────────────────────────────────────────────────────────
Règles de la page « Bulk Export V2 » qui ne dépendent pas de l'affichage (donc testables seules) :
construction de la configuration, lecture d'un JSON importé (format V2 ou ancien format des modules 1 à 3),
estimation, règles de blocage du lancement, progression.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from bulk_export.models import ExportConfig, _reject_secret_keys

VOLUME_WARNING = 500_000
# Durées entre deux pages au-delà desquelles on considère qu'il y a eu une pause (exclues des mesures).
MAX_PAGE_INTERVAL_S = 600


# ─── Filtres ──────────────────────────────────────────────────────────────────

def _as_text(value: Any) -> Any:
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()[:10]
    return value


def form_to_filters(*, start_date, end_date, category="ALL", subcategory="ALL", brands=(), countries=(),
                    sources=(), markets=(), attributes=(), attributes_positive=(),
                    attributes_negative=()) -> dict[str, str]:
    """Paramètres d'API construits par la fonction EXISTANTE ``utils.build_filter_params`` (mêmes règles
    que les modules 1 à 3), puis convertis en texte (dates au format AAAA-MM-JJ)."""
    from utils import build_filter_params  # import tardif : utils dépend de Streamlit

    filters = {
        "start_date": start_date, "end_date": end_date, "category": category, "subcategory": subcategory,
        "brand": list(brands), "country": list(countries), "source": list(sources), "market": list(markets),
        "attributes": list(attributes), "attributes_positive": list(attributes_positive),
        "attributes_negative": list(attributes_negative),
    }
    params = build_filter_params(filters)
    return {k: str(_as_text(v)) for k, v in params.items() if v not in (None, "")}


# ─── Import JSON ──────────────────────────────────────────────────────────────

@dataclass
class ImportedConfig:
    filters: dict[str, str]
    options: dict[str, Any] = field(default_factory=dict)   # name, batch_size, output_formats…
    warnings: list[str] = field(default_factory=list)
    source_format: str = "v2"                               # "v2" ou "ancien"


# ancien format (modules 1 à 3) → paramètre d'API
_LEGACY_KEYS = {
    "start-date": "start-date", "end-date": "end-date", "category": "category", "subcategory": "subcategory",
    "brand": "brand", "country": "country", "source": "source", "market": "market",
    "attributes": "attribute", "attributes_positive": "attribute-positive",
    "attributes_negative": "attribute-negative",
}
_LEGACY_IGNORED = {"selected_products", "export_mode", "note", "export_date", "export_timestamp"}


def _legacy_value(value: Any) -> str | None:
    if isinstance(value, list):
        items = [str(v).strip() for v in value if str(v).strip()]
        if not items or "ALL" in items:
            return None
        return ",".join(items)
    text = str(value).strip() if value is not None else ""
    return None if text in ("", "ALL") else text


def parse_import_json(text: str) -> ImportedConfig:
    """Lit une configuration collée par l'utilisateur. Refuse tout champ ressemblant à un secret."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON illisible (ligne {exc.lineno}, position {exc.colno}).") from None
    if not isinstance(data, dict):
        raise ValueError("La configuration doit être un objet JSON ({ … }).")
    _reject_secret_keys(data)

    if "filters" in data:  # format Bulk Export V2
        config = ExportConfig.from_dict(data)
        options = {k: v for k, v in config.to_dict().items() if k != "filters"}
        return ImportedConfig(dict(config.filters), options, [], "v2")

    filters: dict[str, str] = {}
    warnings: list[str] = []
    for key, value in data.items():
        if key in _LEGACY_KEYS:
            text_value = _legacy_value(value)
            if text_value is not None:
                filters[_LEGACY_KEYS[key]] = text_value
        elif key == "selected_products" and value:
            warnings.append("Sélection de produits ignorée : Bulk Export V2 exporte toutes les mentions "
                            "des filtres (comme le module 3).")
        elif key not in _LEGACY_IGNORED:
            warnings.append(f"Champ « {key} » ignoré (inconnu).")
    if not filters:
        raise ValueError("Aucun filtre reconnu dans ce JSON.")
    ExportConfig(name="vérification", filters=filters)  # même contrôle que pour un vrai export
    return ImportedConfig(filters, {}, warnings, "ancien")


# ─── Estimation ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Measures:
    """Mesures tirées d'exports RÉELS déjà faits (jamais de valeur supposée)."""
    seconds_per_page: float | None
    page_intervals: int
    bytes_per_mention: float | None
    mentions_measured: int


@dataclass(frozen=True)
class Estimate:
    config_hash: str
    expected: int
    pages: int
    batches: int
    seconds: float | None = None       # None tant qu'aucune mesure réelle n'existe
    raw_bytes: float | None = None


def compute_estimate(config: ExportConfig, expected: int, measures: Measures | None = None) -> Estimate:
    pages = math.ceil(expected / config.rows) if expected else 0
    batches = math.ceil(expected / config.batch_size) if expected else 0
    seconds = raw_bytes = None
    if measures and measures.seconds_per_page is not None and measures.page_intervals >= 3:
        seconds = pages * measures.seconds_per_page
    if measures and measures.bytes_per_mention is not None and measures.mentions_measured >= 100:
        raw_bytes = expected * measures.bytes_per_mention
    return Estimate(config.config_hash, expected, pages, batches, seconds, raw_bytes)


def read_measures(conn) -> Measures:
    """Temps médian entre deux pages consécutives (pauses exclues) et taille moyenne d'une mention,
    mesurés sur les exports réels déjà présents en base."""
    sec, intervals = conn.execute(
        """SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY d), count(*) FROM (
               SELECT extract(epoch FROM committed_at - lag(committed_at)
                      OVER (PARTITION BY export_id ORDER BY page_no)) AS d
               FROM pages) x
           WHERE d IS NOT NULL AND d > 0 AND d < %s""",
        (MAX_PAGE_INTERVAL_S,),
    ).fetchone()
    avg_bytes, mentions = conn.execute(
        "SELECT avg(octet_length(raw_json)), count(*) FROM (SELECT raw_json FROM raw_mentions LIMIT 20000) s"
    ).fetchone()
    if not mentions or mentions < 100:
        # Après COMPLETED, les mentions sont effacées : on reprend la mesure gardée par la validation.
        total_bytes, total_mentions = conn.execute(
            """SELECT sum((validation_json #>> '{stats,content_bytes}')::bigint),
                      sum((validation_json #>> '{stats,mentions}')::bigint)
               FROM exports WHERE validation_json ? 'stats'"""
        ).fetchone()
        if total_mentions:
            avg_bytes, mentions = float(total_bytes) / float(total_mentions), int(total_mentions)
    return Measures(float(sec) if sec is not None else None, int(intervals or 0),
                    float(avg_bytes) if avg_bytes is not None else None, int(mentions or 0))


# ─── Règles de lancement ──────────────────────────────────────────────────────

def launch_blockers(*, config: ExportConfig | None, config_error: str | None, estimate: Estimate | None,
                    active_export: str | None, db_ok: bool, runner_ok: bool = True) -> list[str]:
    """Raisons qui EMPÊCHENT le lancement (liste vide = lancement possible)."""
    reasons: list[str] = []
    if not db_ok:
        reasons.append("Connexion à Supabase impossible.")
    if not runner_ok:
        reasons.append("Accès à l'API indisponible (token manquant ?).")
    if config is None:
        reasons.append(f"Configuration invalide : {config_error or 'à compléter'}.")
    elif estimate is None or estimate.config_hash != config.config_hash:
        reasons.append("Estimez d'abord le volume pour ces filtres (l'estimation doit correspondre aux filtres actuels).")
    elif estimate.expected == 0:
        reasons.append("Aucune mention ne correspond à ces filtres.")
    if active_export:
        reasons.append(f"Un export est déjà en cours ({active_export}). Une seule opération à la fois.")
    return reasons


def launch_warnings(estimate: Estimate | None) -> list[str]:
    if estimate and estimate.expected > VOLUME_WARNING:
        return [f"Volume supérieur à {VOLUME_WARNING:,} mentions ({estimate.expected:,}) : au-delà de la "
                "capacité visée par la V1. L'export reste possible, mais il sera long.".replace(",", " ")]
    return []


# ─── Affichage du suivi ───────────────────────────────────────────────────────

def progress(unique: int, expected: int | None) -> tuple[float, int | None]:
    """(fraction 0–1 plafonnée, écart uniques − attendus). Sans volume attendu : (0, None)."""
    if not expected:
        return 0.0, None
    return min(unique / expected, 1.0), unique - expected


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"


def format_bytes(n: float | None) -> str:
    if n is None:
        return "—"
    units = ["octets", "Ko", "Mo", "Go", "To"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{n:.0f} {units[i]}" if i == 0 else f"{n:.1f} {units[i]}"


def default_name(filters: Mapping[str, str]) -> str:
    brand = filters.get("brand", "toutes marques")
    brand = brand if len(brand) <= 40 else brand[:37] + "…"
    period = f"{filters.get('start-date', '…')} → {filters.get('end-date', '…')}"
    return f"{brand} · {period}"


def is_orphan(row: Mapping[str, Any], now: _dt.datetime) -> bool:
    """RUNNING/STOPPING sans bail valide : l'application qui le faisait tourner s'est arrêtée."""
    if row.get("status") not in ("RUNNING", "STOPPING"):
        return False
    expires = row.get("lease_expires_at")
    return expires is None or expires <= now


def choose_export(exports: Sequence[Mapping[str, Any]], active: str | None, preferred: str | None) -> str | None:
    ids = [e["export_id"] for e in exports]
    for candidate in (preferred, active):
        if candidate and candidate in ids:
            return candidate
    return ids[0] if ids else None


# ─── Conservation du brut (lot 1A) ────────────────────────────────────────────

GO = 1024 ** 3  # même unité que format_bytes


def raw_status(row: Mapping[str, Any]) -> str:
    """Colonne « Brut en base » de l'historique."""
    purged = row.get("raw_purged_at")
    return f"effacé le {purged:%Y-%m-%d}" if purged else "conservé"


def size_warning(database_bytes: int | None, threshold_go: float) -> str | None:
    """Message d'avertissement si la base dépasse le seuil réglable ``alerte_taille_base_go``."""
    if database_bytes is None or database_bytes < threshold_go * GO:
        return None
    return (f"La base occupe {format_bytes(database_bytes)}, au-delà du seuil d'alerte de {threshold_go:g} Go "
            "(8 Go inclus dans le plan Supabase Pro). Le brut conservé grossit à chaque export : décider "
            "d'un archivage avant d'atteindre la limite.")
