"""Faux serveur API pour les tests (aucun appel réseau). Données 100 % synthétiques (fake_*)."""

import json
import urllib.parse

import requests

FAKE_TOKEN = "FAKE_api_token_0123456789"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, body=None, headers=None):
        self.status_code = status_code
        if body is None:
            body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        self.content = body
        self.headers = headers or {}

    def json(self):
        return json.loads(self.content.decode("utf-8"))


class FakeSession:
    """Remplace requests.Session : renvoie les réponses préparées, dans l'ordre, et garde les appels."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []  # (endpoint, params décodés)

    def get(self, url, headers=None, timeout=None):
        parsed = urllib.parse.urlsplit(url)
        params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        self.calls.append((parsed.path, params, url, timeout))
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def ok(result):
    return FakeResponse(200, {"status": "success", "result": result})


def fake_doc(n):
    return {"id": str(n), "brand": "FAKE_BRAND", "date": "2024-11-28T15:45:28Z", "product": "fake product",
            "verbatim content": f"fake verbatim é {n}", "rating": 5, "attributes": None}


def page(docs, cursor, nb=None):
    return ok({"nbDocs": nb if nb is not None else len(docs), "docs": docs, "nextCursorMark": cursor})


def conn_error():
    # Le message d'une vraie erreur requests contient l'adresse, donc le token.
    return requests.ConnectionError(f"Max retries exceeded with url: /reviews?token={FAKE_TOKEN}")
