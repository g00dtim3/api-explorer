"""Nouvelles tentatives : temps simulé (aucune vraie attente)."""

import logging

import pytest

from bulk_export.api_http import (
    ApiAuthError, ApiClientError, ApiRateLimitError, ApiSchemaError, ApiTransientError,
)
from bulk_export.retry import RetryPolicy, backoff_delay, call_with_retry
from tests.fake_api import FAKE_TOKEN


class Script:
    """Fonction qui lève les erreurs prévues puis renvoie « ok »."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        nxt = self.outcomes.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def run(fn, policy=RetryPolicy(), **kw):
    waits = []
    result = call_with_retry(fn, policy, sleep=waits.append, rand=lambda: 0.0, **kw)
    return result, waits


def test_429_retry_after_respecte():
    fn = Script(ApiRateLimitError("429", retry_after=3.0), "ok")
    assert run(fn) == ("ok", [3.0])


def test_503_puis_succes():
    fn = Script(ApiTransientError("503"), ApiTransientError("503"), "ok")
    result, waits = run(fn)
    assert result == "ok" and waits == [2.0, 4.0] and fn.calls == 3


def test_503_permanent_abandon_apres_n_essais():
    fn = Script(*[ApiTransientError("503")] * 5)
    waits = []
    with pytest.raises(ApiTransientError):
        call_with_retry(fn, RetryPolicy(max_attempts=5), sleep=waits.append, rand=lambda: 0.0)
    assert fn.calls == 5 and waits == [2.0, 4.0, 8.0, 16.0]


@pytest.mark.parametrize("err", [ApiAuthError("401"), ApiSchemaError("forme"), ApiClientError("400"),
                                 ValueError("bug")])
def test_pas_de_nouvel_essai(err):
    fn = Script(err, "ok")
    with pytest.raises(type(err)):
        run(fn)
    assert fn.calls == 1


def test_retry_after_trop_long_abandon():
    fn = Script(ApiRateLimitError("429", retry_after=3600.0), "ok")
    with pytest.raises(ApiRateLimitError):
        run(fn)
    assert fn.calls == 1


def test_429_sans_retry_after_utilise_le_backoff():
    fn = Script(ApiRateLimitError("429", retry_after=None), "ok")
    assert run(fn) == ("ok", [2.0])


def test_backoff_plafonne_et_jitter():
    p = RetryPolicy(base_delay_s=2, max_delay_s=10, jitter=0.5)
    assert backoff_delay(10, p, rand=lambda: 0.0) == 10
    assert backoff_delay(1, p, rand=lambda: 1.0) == 3.0


def test_chaque_essai_signale_sans_secret(caplog):
    seen = []
    fn = Script(ApiTransientError(f"panne token={FAKE_TOKEN}"), "ok")
    with caplog.at_level(logging.WARNING):
        run(fn, on_retry=lambda n, wait, exc: seen.append((n, wait, str(exc))))
    assert seen and seen[0][0] == 1
    assert FAKE_TOKEN not in caplog.text and FAKE_TOKEN not in seen[0][2]


def test_politique_invalide():
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
