"""Client HTTP strict : erreurs typées, token jamais visible, mesures."""

from datetime import datetime, timezone

import pytest
import requests

from bulk_export.api_http import (
    ApiAuthError, ApiClientError, ApiRateLimitError, ApiSchemaError, ApiTransientError,
    RatingsReviewsHttpClient, parse_retry_after,
)
from tests.fake_api import FAKE_TOKEN, FakeResponse, FakeSession, conn_error, ok


def client(*responses):
    session = FakeSession(responses)
    ticks = iter([0.0, 0.25] * 50)
    return RatingsReviewsHttpClient(FAKE_TOKEN, session=session, clock=lambda: next(ticks)), session


def test_succes_mesure_temps_et_taille():
    c, _ = client(ok({"nbDocs": 3}))
    r = c.get("/metrics", {"brand": "FAKE"})
    assert r.payload["result"]["nbDocs"] == 3
    assert r.elapsed_ms == 250.0 and r.size_bytes > 0


def test_encodage_identique_a_l_application():
    c, s = client(ok({}))
    c.get("/reviews", {"brand": "Fake & Co,AUTRE", "rows": 1000, "nextCursorMark": "*"})
    _, params, url, timeout = s.calls[0]
    assert "brand=Fake%20%26%20Co%2CAUTRE" in url and "nextCursorMark=%2A" in url
    assert params["brand"] == "Fake & Co,AUTRE" and params["token"] == FAKE_TOKEN
    assert timeout == (10.0, 120.0)


@pytest.mark.parametrize("code,exc", [
    (401, ApiAuthError), (403, ApiAuthError), (429, ApiRateLimitError), (500, ApiTransientError),
    (503, ApiTransientError), (400, ApiClientError), (404, ApiClientError),
])
def test_codes_http(code, exc):
    c, _ = client(FakeResponse(code, body=f"erreur token={FAKE_TOKEN}".encode()))
    with pytest.raises(exc) as info:
        c.get("/reviews", {"brand": "FAKE"})
    assert info.value.status_code == code
    assert FAKE_TOKEN not in str(info.value)


def test_429_retry_after():
    c, _ = client(FakeResponse(429, body=b"", headers={"Retry-After": "3"}))
    with pytest.raises(ApiRateLimitError) as info:
        c.get("/reviews")
    assert info.value.retry_after == 3.0


@pytest.mark.parametrize("err", [requests.Timeout("token=" + FAKE_TOKEN), conn_error(),
                                 requests.RequestException("url?token=" + FAKE_TOKEN)])
def test_reseau_erreur_passagere_sans_token(err):
    c, _ = client(err)
    with pytest.raises(ApiTransientError) as info:
        c.get("/reviews")
    assert FAKE_TOKEN not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_json_tronque_est_passager():
    c, _ = client(FakeResponse(200, body=b'{"status": "success", "result": {"docs": [{"id"'))
    with pytest.raises(ApiTransientError, match="illisible"):
        c.get("/reviews")


@pytest.mark.parametrize("payload", [
    [1, 2], {"status": "error", "result": {}}, {"status": "success"}, {"status": "success", "result": []},
])
def test_reponse_mal_formee(payload):
    c, _ = client(FakeResponse(200, payload))
    with pytest.raises(ApiSchemaError):
        c.get("/reviews")


def test_token_jamais_affiche():
    c, _ = client()
    assert FAKE_TOKEN not in repr(c)


def test_parse_retry_after():
    now = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_retry_after("3") == 3.0
    assert parse_retry_after("Thu, 15 Oct 2026 12:00:30 GMT", now=now) == 30.0
    assert parse_retry_after("n'importe quoi") is None
    assert parse_retry_after(None) is None
    assert parse_retry_after("-5") == 0.0
