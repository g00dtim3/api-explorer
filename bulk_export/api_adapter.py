"""
bulk_export/api_adapter.py
──────────────────────────────────────────────────────────────
Contrat de pagination : le reste du moteur ne connaît que « une page », « la fin » ou « une erreur ».
Il ignore tout de ``nextCursorMark``, ce qui permettra plus tard de brancher une autre API.

Règle de fin pour Ratings & Reviews : la documentation ne la décrit pas (audit_api.md §5).
Elle est donc RÉGLABLE (règle n°10) ; les réglages sont figés dans la configuration de chaque export.
Quelle que soit la façon dont la pagination s'arrête, la complétude est vérifiée plus tard (validation).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from bulk_export.api_http import ApiError, ApiSchemaError, RatingsReviewsHttpClient
from bulk_export.retry import RetryPolicy, call_with_retry

INITIAL_CURSOR = "*"

# Valeurs possibles d'une situation ambiguë :
#   "end_with_warning" : on considère que c'est la fin, et on le signale au journal ;
#   "error"            : on s'arrête en erreur (export FAILED, reprenable).
DEFAULT_PAGINATION: Mapping[str, Any] = {
    # Le curseur renvoyé est identique à celui envoyé ET la page contient des mentions.
    "on_same_cursor_with_records": "end_with_warning",
    # La page est vide alors que le curseur a changé (ou est absent).
    "on_empty_page": "end_with_warning",
    # Plafond de pages : ceil(attendu / rows) × facteur + supplément.
    "page_margin_factor": 1.2,
    "page_margin_extra": 10,
}
_CHOICES = ("end_with_warning", "error")


class PaginationError(Exception):
    """Fin de pagination anormale : ce n'est PAS une fin normale."""


def merged_pagination(settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    out = dict(DEFAULT_PAGINATION)
    if settings:
        unknown = set(settings) - set(DEFAULT_PAGINATION)
        if unknown:
            raise ValueError(f"Réglages de pagination inconnus : {sorted(unknown)}.")
        out.update(settings)
    for key in ("on_same_cursor_with_records", "on_empty_page"):
        if out[key] not in _CHOICES:
            raise ValueError(f"Réglage {key} invalide : {out[key]!r} (valeurs : {_CHOICES}).")
    if not (isinstance(out["page_margin_factor"], (int, float)) and out["page_margin_factor"] >= 1):
        raise ValueError("page_margin_factor doit être un nombre ≥ 1.")
    if not (isinstance(out["page_margin_extra"], int) and out["page_margin_extra"] >= 1):
        raise ValueError("page_margin_extra doit être un entier ≥ 1.")
    return out


def max_pages(expected_count: int, rows: int, settings: Mapping[str, Any] | None = None) -> int:
    """Nombre maximal de pages avant de considérer qu'il y a une boucle (remplace les 1 000 fixes)."""
    s = merged_pagination(settings)
    return int(math.ceil(max(expected_count, 0) / rows) * s["page_margin_factor"]) + s["page_margin_extra"]


@dataclass(frozen=True)
class PageResult:
    records: list[dict[str, Any]]     # mentions brutes, non modifiées
    cursor_sent: str                  # curseur qui a servi à lire cette page
    next_cursor: str | None           # curseur pour la page suivante
    is_last: bool                     # fin selon la règle de fin (réglable)
    raw_meta: dict[str, Any] = field(default_factory=dict)  # mesures, total annoncé… sans secret
    warnings: tuple[str, ...] = ()    # situations ambiguës acceptées, à écrire au journal


class PaginationAdapter(Protocol):
    def initial_cursor(self) -> str: ...
    def fetch_page(self, cursor: str) -> PageResult: ...
    def expected_count(self) -> int: ...
    def quota(self) -> dict[str, Any] | None: ...
    def max_pages(self, expected_count: int) -> int: ...


class RatingsReviewsAdapter:
    """Pagination ``nextCursorMark`` de l'API Ratings & Reviews.

    ``filters`` = filtres figés de l'export (``ExportConfig.filters``), envoyés à l'identique
    à ``/metrics`` et à ``/reviews``. ``random`` n'est jamais envoyé."""

    def __init__(self, http: RatingsReviewsHttpClient, filters: Mapping[str, str], *, rows: int = 1000,
                 pagination: Mapping[str, Any] | None = None,
                 retry_policy: RetryPolicy = RetryPolicy(),
                 sleep: Callable[[float], None] | None = None,
                 on_retry: Callable[[int, float, ApiError], None] | None = None):
        forbidden = {"random", "rows", "nextCursorMark", "token"} & set(filters)
        if forbidden:
            raise ValueError(f"Paramètres interdits dans les filtres : {sorted(forbidden)}.")
        self._http = http
        self._filters = dict(filters)
        self._rows = rows
        self._pagination = merged_pagination(pagination)
        self._retry_policy = retry_policy
        self._retry_kw: dict[str, Any] = {"on_retry": on_retry}
        if sleep is not None:
            self._retry_kw["sleep"] = sleep

    def _get(self, endpoint: str, params: Mapping[str, Any]):
        return call_with_retry(lambda: self._http.get(endpoint, params), self._retry_policy,
                               description=endpoint, **self._retry_kw)

    def metrics_params(self) -> dict[str, str]:
        return dict(self._filters)

    def reviews_params(self, cursor: str) -> dict[str, Any]:
        return {**self._filters, "rows": self._rows, "nextCursorMark": cursor}

    def initial_cursor(self) -> str:
        return INITIAL_CURSOR

    def max_pages(self, expected_count: int) -> int:
        return max_pages(expected_count, self._rows, self._pagination)

    def expected_count(self) -> int:
        resp = self._get("/metrics", self.metrics_params())
        nb = resp.payload["result"].get("nbDocs")
        if not isinstance(nb, int) or isinstance(nb, bool) or nb < 0:
            raise ApiSchemaError("/metrics : nbDocs absent ou invalide.", endpoint="/metrics")
        return nb

    def quota(self) -> dict[str, Any] | None:
        """Information seulement (quota illimité) : une erreur ici ne bloque rien."""
        try:
            return dict(self._get("/quotas", {}).payload["result"])
        except ApiError:
            return None

    def fetch_page(self, cursor: str) -> PageResult:
        resp = self._get("/reviews", self.reviews_params(cursor))
        result = resp.payload["result"]
        docs = result.get("docs")
        if not isinstance(docs, list) or not all(isinstance(d, dict) for d in docs):
            raise ApiSchemaError("/reviews : « docs » absent ou n'est pas une liste de mentions.",
                                 endpoint="/reviews")
        next_cursor = result.get("nextCursorMark")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise ApiSchemaError("/reviews : nextCursorMark invalide.", endpoint="/reviews")
        next_cursor = next_cursor or None

        meta = {
            "nb_docs": result.get("nbDocs"),
            "records": len(docs),
            "elapsed_ms": round(resp.elapsed_ms, 1),
            "size_bytes": resp.size_bytes,
            "headers": dict(resp.headers),
        }
        is_last, warnings = self._end_rule(cursor, next_cursor, has_records=bool(docs))
        return PageResult(records=docs, cursor_sent=cursor, next_cursor=next_cursor, is_last=is_last,
                          raw_meta=meta, warnings=tuple(warnings))

    def _end_rule(self, sent: str, received: str | None, *, has_records: bool) -> tuple[bool, list[str]]:
        """Applique la règle de fin (audit_api.md §5). Renvoie (fin ?, avertissements)."""
        p = self._pagination
        if received == sent:
            if not has_records:
                return True, []                                    # fin normale
            if p["on_same_cursor_with_records"] == "error":
                raise PaginationError("Curseur identique alors que la page contient des mentions.")
            return True, ["Curseur identique avec des mentions : mentions gardées, fin de pagination supposée."]
        if not has_records:
            if p["on_empty_page"] == "error":
                raise PaginationError("Page vide alors que le curseur a changé ou est absent.")
            return True, ["Page vide sans curseur identique : fin de pagination supposée."]
        if received is None:
            raise PaginationError("Mentions reçues sans curseur pour la page suivante.")
        return False, []
