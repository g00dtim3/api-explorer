"""
bulk_export/api_http.py
──────────────────────────────────────────────────────────────
Appel HTTP « strict » à l'API Ratings & Reviews, pour Bulk Export V2 uniquement.

Différences avec ``api_client.APIClient`` (laissé intact pour les modules 1 à 3) :
- pas de cache : chaque appel interroge réellement l'API ;
- délais maximaux de connexion et de lecture ;
- une erreur est une EXCEPTION typée, jamais une réponse vide ``{}`` ;
- le token n'apparaît dans aucun message (l'adresse appelée n'est jamais affichée) ;
- fonctionne sans Streamlit (ligne de commande).

L'adresse de l'API et l'encodage des paramètres sont les mêmes que dans ``api_client.py``
(encodage strict : tous les caractères spéciaux, dont ``&`` et ``,``, sont encodés).
"""

from __future__ import annotations

import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping

import requests

from bulk_export.logging_utils import mask, register_secret

DEFAULT_BASE_URL = "https://api-pf.ratingsandreviews-beauty.com"
DEFAULT_TIMEOUT = (10.0, 120.0)  # (connexion, lecture) en secondes
_BODY_EXCERPT = 200


# ─── Erreurs typées ───────────────────────────────────────────────────────────

class ApiError(Exception):
    """Erreur d'appel à l'API. Le message est déjà masqué et ne contient pas l'adresse."""

    def __init__(self, message: str, *, endpoint: str = "", status_code: int | None = None):
        super().__init__(mask(message))
        self.endpoint = endpoint
        self.status_code = status_code


class ApiAuthError(ApiError):
    """401 / 403 : token refusé. Jamais de nouvelle tentative."""


class ApiRateLimitError(ApiError):
    """429 : trop de requêtes. ``retry_after`` = secondes d'attente demandées (ou None)."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kw):
        super().__init__(message, **kw)
        self.retry_after = retry_after


class ApiTransientError(ApiError):
    """Panne passagère : 5xx, délai dépassé, coupure réseau, réponse tronquée."""


class ApiClientError(ApiError):
    """Autre 4xx : requête refusée (paramètre invalide…). Pas de nouvelle tentative."""


class ApiSchemaError(ApiError):
    """Réponse reçue mais de forme inattendue. Pas de nouvelle tentative."""


# ─── Réponse ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ApiResponse:
    payload: dict[str, Any]
    status_code: int
    elapsed_ms: float          # temps de réponse mesuré
    size_bytes: int            # taille du corps reçu (mesure de volumétrie)
    headers: Mapping[str, str] = field(default_factory=dict)  # en-têtes utiles uniquement


# En-têtes conservés pour le journal (quota, débit). Les autres sont ignorés.
_USEFUL_HEADERS = ("retry-after", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset")


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """``Retry-After`` en secondes : nombre (« 3 ») ou date HTTP. Illisible → None."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max(0.0, (when - now).total_seconds())


def _quote_strict(string, safe="/", encoding=None, errors=None):
    """Même encodage que ``api_client.APIClient._quote_strict``."""
    return urllib.parse.quote(string, safe="", encoding=encoding, errors=errors)


class RatingsReviewsHttpClient:
    def __init__(self, token: str, *, base_url: str = DEFAULT_BASE_URL,
                 timeout: tuple[float, float] = DEFAULT_TIMEOUT,
                 session: requests.Session | None = None,
                 clock: Callable[[], float] = time.monotonic):
        if not token:
            raise ValueError("Token API absent.")
        register_secret(token)
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = session or requests.Session()
        self._clock = clock

    def __repr__(self) -> str:  # ne jamais afficher le token
        return f"RatingsReviewsHttpClient(base_url={self._base_url!r})"

    def build_url(self, endpoint: str, params: Mapping[str, Any]) -> str:
        """Adresse complète. CONTIENT LE TOKEN : ne jamais l'afficher ni la journaliser."""
        query = dict(params)
        query["token"] = self._token
        qs = urllib.parse.urlencode(query, doseq=True, quote_via=_quote_strict)
        return f"{self._base_url}{endpoint}?{qs}"

    def get(self, endpoint: str, params: Mapping[str, Any] | None = None) -> ApiResponse:
        url = self.build_url(endpoint, params or {})
        start = self._clock()
        try:
            resp = self._session.get(url, headers={"Accept": "application/json"}, timeout=self._timeout)
        except requests.Timeout:
            raise ApiTransientError(f"{endpoint} : délai dépassé.", endpoint=endpoint) from None
        except requests.ConnectionError:
            raise ApiTransientError(f"{endpoint} : connexion impossible ou coupée.", endpoint=endpoint) from None
        except requests.RequestException as exc:
            # Le message de requests peut contenir l'adresse : on ne garde que le type d'erreur.
            raise ApiTransientError(f"{endpoint} : erreur réseau ({type(exc).__name__}).",
                                    endpoint=endpoint) from None
        elapsed_ms = (self._clock() - start) * 1000.0
        body = resp.content or b""
        headers = {k.lower(): v for k, v in resp.headers.items() if k.lower() in _USEFUL_HEADERS}
        code = resp.status_code

        if code != 200:
            excerpt = body[:_BODY_EXCERPT].decode("utf-8", errors="replace")
            msg = f"{endpoint} : HTTP {code}. Début de la réponse : {excerpt!r}"
            if code in (401, 403):
                raise ApiAuthError(msg, endpoint=endpoint, status_code=code)
            if code == 429:
                raise ApiRateLimitError(msg, endpoint=endpoint, status_code=code,
                                        retry_after=parse_retry_after(headers.get("retry-after")))
            if code >= 500:
                raise ApiTransientError(msg, endpoint=endpoint, status_code=code)
            raise ApiClientError(msg, endpoint=endpoint, status_code=code)

        try:
            payload = resp.json()
        except ValueError:
            # Corps illisible avec un code 200 : le plus souvent un transfert interrompu.
            raise ApiTransientError(f"{endpoint} : réponse JSON illisible ({len(body)} octets).",
                                    endpoint=endpoint, status_code=code) from None
        if not isinstance(payload, dict):
            raise ApiSchemaError(f"{endpoint} : la réponse n'est pas un objet JSON.", endpoint=endpoint,
                                 status_code=code)
        if payload.get("status") != "success":
            raise ApiSchemaError(f"{endpoint} : status = {str(payload.get('status'))[:50]!r} (attendu : 'success').",
                                 endpoint=endpoint, status_code=code)
        if not isinstance(payload.get("result"), dict):
            raise ApiSchemaError(f"{endpoint} : champ « result » absent ou invalide.", endpoint=endpoint,
                                 status_code=code)
        return ApiResponse(payload=payload, status_code=code, elapsed_ms=elapsed_ms,
                           size_bytes=len(body), headers=headers)
