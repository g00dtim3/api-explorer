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
            "content trad": f"fake verbatim é {n}", "rating": 5, "attributes": None}


def page(docs, cursor, nb=None):
    return ok({"nbDocs": nb if nb is not None else len(docs), "docs": docs, "nextCursorMark": cursor})


def conn_error():
    # Le message d'une vraie erreur requests contient l'adresse, donc le token.
    return requests.ConnectionError(f"Max retries exceeded with url: /reviews?token={FAKE_TOKEN}")


class FakePagedServer:
    """Faux serveur /metrics + /reviews paginé par curseur, comme l'API réelle (supposée).

    ``pages`` : liste de listes de mentions. Le curseur de la page i est "*" puis "C1", "C2"…
    Après la dernière page, l'API renvoie une page vide avec le même curseur (fin normale).
    ``failures`` : {(chemin, curseur): [réponses ou exceptions à servir avant la vraie réponse]}.
    """

    def __init__(self, pages, nb_docs=None, failures=None):
        self.pages = pages
        self.nb_docs = nb_docs if nb_docs is not None else sum(len(p) for p in pages)
        self.failures = {k: list(v) for k, v in (failures or {}).items()}
        self.calls = []

    @staticmethod
    def cursor_for(i):
        return "*" if i == 0 else f"C{i}"

    def get(self, url, headers=None, timeout=None):
        parsed = urllib.parse.urlsplit(url)
        params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        path, cursor = parsed.path, params.get("nextCursorMark")
        self.calls.append((path, cursor))
        queued = self.failures.get((path, cursor))
        if queued:
            nxt = queued.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt
        if path == "/metrics":
            return ok({"nbDocs": self.nb_docs})
        if path == "/quotas":
            return ok({"quota": 0})
        index = 0 if cursor == "*" else int(cursor[1:])
        if index >= len(self.pages):
            return page([], cursor, nb=self.nb_docs)
        return page(self.pages[index], self.cursor_for(index + 1), nb=self.nb_docs)


class SlowServer:
    """Enveloppe un faux serveur : chaque appel /reviews attend ``delay`` secondes (temps réel)."""

    def __init__(self, inner, delay):
        self.inner, self.delay = inner, delay

    def get(self, url, headers=None, timeout=None):
        import time
        if "/reviews" in url:
            time.sleep(self.delay)
        return self.inner.get(url, headers=headers, timeout=timeout)


def serve_http(fake_server, port=0):
    """Expose un faux serveur sur http://127.0.0.1:<port> (pour les tests en processus séparé).
    Renvoie (httpd, base_url) ; arrêter avec httpd.shutdown()."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            resp = fake_server.get(f"http://127.0.0.1{self.path}")
            self.send_response(resp.status_code)
            for k, v in resp.headers.items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp.content)))
            self.end_headers()
            self.wfile.write(resp.content)

        def log_message(self, *args):  # silence
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"
