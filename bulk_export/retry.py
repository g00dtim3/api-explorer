"""
bulk_export/retry.py
──────────────────────────────────────────────────────────────
Nouvelles tentatives limitées après une erreur passagère.

- délai qui double à chaque essai (2 s, 4 s, 8 s…), plafonné, plus une part de hasard (« jitter »)
  pour ne pas relancer tous au même instant ;
- sur un 429, on attend exactement ce que demande ``Retry-After`` ; si l'API demande d'attendre
  plus que le plafond autorisé, on abandonne plutôt que de bloquer l'export des heures ;
- jamais de nouvelle tentative sur un accès refusé, une requête refusée ou une réponse mal formée.

Le hasard ici ne sert qu'à étaler les attentes : il n'a rien à voir avec le paramètre `random` de l'API.
"""

from __future__ import annotations

import random as _jitter_source
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

from bulk_export.api_http import ApiError, ApiRateLimitError, ApiTransientError
from bulk_export.logging_utils import get_logger, mask

logger = get_logger(__name__)
T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5          # essais au total (le premier compris)
    base_delay_s: float = 2.0
    max_delay_s: float = 60.0
    max_retry_after_s: float = 300.0
    jitter: float = 0.5            # +0 % à +50 % sur le délai calculé

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts doit valoir au moins 1.")


def backoff_delay(attempt: int, policy: RetryPolicy, rand: Callable[[], float]) -> float:
    """Délai avant l'essai ``attempt + 1`` (``attempt`` = numéro de l'essai qui vient d'échouer)."""
    delay = min(policy.base_delay_s * (2 ** (attempt - 1)), policy.max_delay_s)
    return delay * (1.0 + policy.jitter * rand())


def call_with_retry(fn: Callable[[], T], policy: RetryPolicy = RetryPolicy(), *,
                    description: str = "appel API",
                    sleep: Callable[[float], None] = time.sleep,
                    rand: Callable[[], float] = _jitter_source.random,
                    on_retry: Callable[[int, float, ApiError], None] | None = None) -> T:
    """Exécute ``fn`` ; réessaie seulement sur ApiTransientError et ApiRateLimitError.

    ``on_retry(numéro_essai_échoué, attente_s, erreur)`` permet au moteur d'écrire l'événement
    dans le journal de l'export. Après le dernier essai, l'erreur d'origine est relancée."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except (ApiTransientError, ApiRateLimitError) as exc:
            if attempt >= policy.max_attempts:
                logger.error("%s : échec définitif après %d essais : %s", description, attempt, mask(exc))
                raise
            if isinstance(exc, ApiRateLimitError) and exc.retry_after is not None:
                if exc.retry_after > policy.max_retry_after_s:
                    logger.error("%s : l'API demande d'attendre %.0f s (plafond %.0f s) : abandon.",
                                 description, exc.retry_after, policy.max_retry_after_s)
                    raise
                wait = exc.retry_after
            else:
                wait = backoff_delay(attempt, policy, rand)
            logger.warning("%s : essai %d/%d échoué (%s). Nouvel essai dans %.1f s.",
                           description, attempt, policy.max_attempts, mask(exc), wait)
            if on_retry is not None:
                on_retry(attempt, wait, exc)
            sleep(wait)
