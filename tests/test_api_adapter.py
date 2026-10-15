"""Adaptateur de pagination Ratings & Reviews et règle de fin (réglable)."""

import copy

import pytest

from bulk_export.api_adapter import (
    INITIAL_CURSOR, PaginationError, RatingsReviewsAdapter, max_pages, merged_pagination,
)
from bulk_export.api_http import ApiAuthError, ApiSchemaError, ApiTransientError, RatingsReviewsHttpClient
from bulk_export.models import ConfigError, ExportConfig
from bulk_export.retry import RetryPolicy
from tests.fake_api import FAKE_TOKEN, FakeResponse, FakeSession, conn_error, fake_doc, ok, page

fake_filters = {"brand": "FAKE_BRAND,Fake & Co", "start-date": "2024-01-01", "country": "France"}


def adapter(*responses, **kw):
    session = FakeSession(responses)
    http = RatingsReviewsHttpClient(FAKE_TOKEN, session=session)
    waits = []
    a = RatingsReviewsAdapter(http, fake_filters, sleep=waits.append, **kw)
    return a, session, waits


# ─── Paramètres envoyés ───────────────────────────────────────────────────────

def test_memes_filtres_pour_metrics_et_reviews():
    a, s, _ = adapter(ok({"nbDocs": 2}), page([fake_doc(1)], "C1"))
    assert a.expected_count() == 2
    a.fetch_page(INITIAL_CURSOR)
    (_, metrics, *_), (_, reviews, *_) = s.calls
    techniques = {"rows", "nextCursorMark", "token"}
    assert {k: v for k, v in reviews.items() if k not in techniques} == \
           {k: v for k, v in metrics.items() if k != "token"} == fake_filters
    assert reviews["rows"] == "1000" and reviews["nextCursorMark"] == "*"
    assert "random" not in metrics and "random" not in reviews


@pytest.mark.parametrize("cle", ["random", "rows", "nextCursorMark", "token"])
def test_parametres_techniques_interdits_dans_les_filtres(cle):
    http = RatingsReviewsHttpClient(FAKE_TOKEN, session=FakeSession([]))
    with pytest.raises(ValueError):
        RatingsReviewsAdapter(http, {**fake_filters, cle: "1"})


# ─── Pages et règle de fin ────────────────────────────────────────────────────

def test_page_normale_mentions_intactes():
    docs = [fake_doc(1), fake_doc(2)]
    original = copy.deepcopy(docs)
    a, _, _ = adapter(page(docs, "C1", nb=5))
    p = a.fetch_page("*")
    assert p.records == original
    assert (p.cursor_sent, p.next_cursor, p.is_last, p.warnings) == ("*", "C1", False, ())
    assert p.raw_meta["nb_docs"] == 5 and p.raw_meta["records"] == 2 and p.raw_meta["size_bytes"] > 0


def test_fin_normale_curseur_identique_page_vide():
    a, _, _ = adapter(page([], "C9"))
    p = a.fetch_page("C9")
    assert p.is_last and p.records == [] and p.warnings == ()


def test_curseur_identique_avec_mentions_par_defaut_fin_signalee():
    a, _, _ = adapter(page([fake_doc(1)], "C9"))
    p = a.fetch_page("C9")
    assert p.is_last and len(p.records) == 1 and p.warnings


def test_curseur_identique_avec_mentions_reglage_erreur():
    a, _, _ = adapter(page([fake_doc(1)], "C9"), pagination={"on_same_cursor_with_records": "error"})
    with pytest.raises(PaginationError):
        a.fetch_page("C9")


@pytest.mark.parametrize("cursor", ["C10", None])
def test_page_vide_inattendue_par_defaut_fin_signalee(cursor):
    a, _, _ = adapter(page([], cursor))
    p = a.fetch_page("C9")
    assert p.is_last and p.warnings


def test_page_vide_inattendue_reglage_erreur():
    a, _, _ = adapter(page([], "C10"), pagination={"on_empty_page": "error"})
    with pytest.raises(PaginationError):
        a.fetch_page("C9")


@pytest.mark.parametrize("cursor", [None, ""])
def test_mentions_sans_curseur_erreur_pas_fin(cursor):
    a, _, _ = adapter(page([fake_doc(1)], cursor))
    with pytest.raises(PaginationError, match="sans curseur"):
        a.fetch_page("*")


@pytest.mark.parametrize("result", [
    {"nbDocs": 1, "nextCursorMark": "C1"},                       # pas de docs
    {"docs": "pas une liste", "nextCursorMark": "C1"},
    {"docs": [fake_doc(1), "texte"], "nextCursorMark": "C1"},
    {"docs": [fake_doc(1)], "nextCursorMark": 42},
])
def test_reponse_reviews_mal_formee(result):
    a, _, _ = adapter(ok(result))
    with pytest.raises(ApiSchemaError):
        a.fetch_page("*")


@pytest.mark.parametrize("nb", [None, "12", -1, True])
def test_metrics_invalide(nb):
    a, _, _ = adapter(ok({"nbDocs": nb}))
    with pytest.raises(ApiSchemaError):
        a.expected_count()


# ─── Erreurs et nouvelles tentatives à travers l'adaptateur ───────────────────

def test_coupure_puis_succes():
    a, s, waits = adapter(conn_error(), FakeResponse(503, body=b""), page([fake_doc(1)], "C1"))
    p = a.fetch_page("*")
    assert len(p.records) == 1 and len(s.calls) == 3 and len(waits) == 2


def test_401_arret_immediat():
    a, s, waits = adapter(FakeResponse(401, body=b"unauthorized"), page([fake_doc(1)], "C1"))
    with pytest.raises(ApiAuthError):
        a.fetch_page("*")
    assert len(s.calls) == 1 and waits == []


def test_503_permanent():
    a, s, _ = adapter(*[FakeResponse(503, body=b"")] * 3, retry_policy=RetryPolicy(max_attempts=3))
    with pytest.raises(ApiTransientError):
        a.fetch_page("*")
    assert len(s.calls) == 3


def test_429_retry_after_a_travers_l_adaptateur():
    a, _, waits = adapter(FakeResponse(429, body=b"", headers={"Retry-After": "3"}), page([fake_doc(1)], "C1"))
    a.fetch_page("*")
    assert waits == [3.0]


def test_quota_information_seulement():
    a, _, _ = adapter(ok({"quota": 100000, "remaining volume": 5}))
    assert a.quota()["remaining volume"] == 5
    a, _, _ = adapter(FakeResponse(404, body=b""))
    assert a.quota() is None


# ─── Plafond de pages et réglages ─────────────────────────────────────────────

def test_plafond_de_pages():
    assert max_pages(500_000, 1000) == 610           # 500 × 1,2 + 10
    assert max_pages(0, 1000) == 10
    assert max_pages(1, 1000, {"page_margin_factor": 1, "page_margin_extra": 1}) == 2


@pytest.mark.parametrize("reglage", [
    {"on_empty_page": "continuer"}, {"page_margin_factor": 0.5}, {"page_margin_extra": 0}, {"inconnu": 1},
])
def test_reglage_pagination_invalide(reglage):
    with pytest.raises(ValueError):
        merged_pagination(reglage)
    with pytest.raises(ConfigError):
        ExportConfig(name="fake", filters={"brand": "FAKE"}, pagination=reglage)


def test_reglages_figes_dans_la_configuration():
    c = ExportConfig(name="fake", filters={"brand": "FAKE"}, pagination={"on_empty_page": "error"})
    relu = ExportConfig.from_json(c.to_json())
    assert relu.pagination["on_empty_page"] == "error"
    # Les valeurs par défaut sont écrites en toutes lettres dans la configuration.
    assert relu.pagination["on_same_cursor_with_records"] == "end_with_warning"
    assert relu.fingerprint["verbatim_field"] == "content trad"
    assert '"verbatim_field":"content trad"' in c.to_json()
    assert c.config_hash != ExportConfig(name="fake", filters={"brand": "FAKE"}).config_hash
