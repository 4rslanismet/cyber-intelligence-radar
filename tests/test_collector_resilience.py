"""Bir kaynağın HTTP hatası (403/429/timeout/connection error) tüm akademik
toplama koşusunu DÜŞÜRMEMELİ - _collect_profile'daki per-collector
try/except (bkz. src/run_pipeline.py) diğer kaynaklarla devam etmeli."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import httpx
import pytest

from cyber_radar.research.profiles import ResearchProfile
from cyber_radar.run_pipeline import _collect_profile


def _daily_profile() -> ResearchProfile:
    return ResearchProfile(
        id="test_resilience",
        title="Test",
        mode="daily",
        concept_groups={"cybersecurity": ["cybersecurity"]},
        queries=[["cybersecurity"]],
    )


@pytest.mark.parametrize(
    "make_error",
    [
        lambda: httpx.HTTPStatusError("403 Forbidden", request=MagicMock(), response=MagicMock(status_code=403)),
        lambda: httpx.HTTPStatusError("429 Too Many Requests", request=MagicMock(), response=MagicMock(status_code=429)),
        lambda: httpx.TimeoutException("timed out"),
        lambda: httpx.ConnectError("connection refused"),
    ],
    ids=["403", "429", "timeout", "connection_error"],
)
def test_collector_http_failure_isolated(db_conn, monkeypatch, make_error):
    """4 kaynaktan (openalex/crossref/arxiv/semantic_scholar) BİRİ (openalex)
    her denemede bu hatayı fırlatsın - diğer 3 kaynak yine de çalışmalı,
    toplam koşu çökmemeli, hata collector_runs'a loglanmalı."""

    def failing(*args, **kwargs):
        raise make_error()

    def fake_ok(keyword, since, **kwargs):
        return []  # diğer kaynaklar "başarılı ama 0 sonuç" davranır

    # NOT: academic.COLLECTORS modül yüklenirken fonksiyon REFERANSLARINI
    # yakalıyor (bkz. src/collectors/academic.py) - academic.search_openalex
    # adını monkeypatch'lemek COLLECTORS dict'indeki referansı değiştirmez,
    # dict'in kendisini patch'lemek gerekir.
    monkeypatch.setattr(
        "cyber_radar.collectors.academic.COLLECTORS",
        {"openalex": failing, "crossref": fake_ok, "arxiv": fake_ok, "semantic_scholar": fake_ok},
    )

    total = _collect_profile(db_conn, _daily_profile(), date(2020, 1, 1))

    assert total == 0  # hiçbir gerçek sonuç yok ama HATA FIRLATILMADI
    error_rows = db_conn.execute(
        "SELECT source, error FROM collector_runs WHERE source = 'openalex' AND error IS NOT NULL"
    ).fetchall()
    assert len(error_rows) == 1
    ok_rows = db_conn.execute(
        "SELECT source FROM collector_runs WHERE source IN ('crossref','arxiv','semantic_scholar') AND error IS NULL"
    ).fetchall()
    assert len(ok_rows) == 3


def test_one_query_failure_does_not_stop_other_queries(db_conn, monkeypatch):
    """SCI/tez modunda (birden fazla built query) bir sorgunun hatası
    diğer sorguları etkilememeli."""
    call_count = {"n": 0}

    def flaky_openalex(query, since, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectError("boom")
        return []

    monkeypatch.setattr("cyber_radar.collectors.academic.search_openalex", flaky_openalex)
    monkeypatch.setattr("cyber_radar.collectors.academic.search_crossref", lambda *a, **k: [])
    monkeypatch.setattr("cyber_radar.collectors.academic.search_arxiv_query", lambda *a, **k: [])
    monkeypatch.setattr("cyber_radar.collectors.academic.search_semantic_scholar_bulk", lambda *a, **k: [])

    profile = ResearchProfile(
        id="test_multi_query",
        title="Test",
        mode="sci",
        concept_groups={"a": ["term1"], "b": ["term2"]},
        queries=[["a"], ["b"]],
    )
    total = _collect_profile(db_conn, profile, date(2020, 1, 1))
    assert total == 0
    assert call_count["n"] == 2  # her iki query için de openalex denendi


# ---------------------------------------------------------------------------
# DBLP: degraded_optional (bkz. ACCEPTANCE-02) - varsayılan KAPALI, her
# koşuda boşuna tekrar tekrar denenmemeli.
# ---------------------------------------------------------------------------
def test_dblp_disabled_by_default_and_not_called(db_conn, monkeypatch):
    from cyber_radar.collectors import dblp

    monkeypatch.setattr("cyber_radar.config.DBLP_ENABLED", False)
    dblp_mock = MagicMock(side_effect=AssertionError("DBLP_ENABLED=false iken dblp.search HİÇ ÇAĞRILMAMALI"))
    monkeypatch.setattr(dblp, "search", dblp_mock)
    monkeypatch.setattr("cyber_radar.collectors.academic.search_openalex", lambda *a, **k: [])
    monkeypatch.setattr("cyber_radar.collectors.academic.search_crossref", lambda *a, **k: [])
    monkeypatch.setattr("cyber_radar.collectors.academic.search_arxiv_query", lambda *a, **k: [])
    monkeypatch.setattr("cyber_radar.collectors.academic.search_semantic_scholar_bulk", lambda *a, **k: [])
    monkeypatch.setattr("cyber_radar.collectors.openaire.search", lambda *a, **k: [])
    monkeypatch.setattr("cyber_radar.collectors.openreview.search", lambda *a, **k: [])

    profile = ResearchProfile(id="test_dblp_off", title="Test", mode="sci", concept_groups={"a": ["term1"]}, queries=[["a"]])
    _collect_profile(db_conn, profile, date(2020, 1, 1))

    dblp_mock.assert_not_called()
    logged = db_conn.execute(
        "SELECT error FROM collector_runs WHERE source = 'dblp' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert logged["error"] == "disabled_degraded_optional"


def test_dblp_failure_when_enabled_does_not_stop_pipeline(db_conn, monkeypatch):
    """DBLP_ENABLED=true iken bile bir DBLP hatası tüm koşuyu DÜŞÜRMEMELİ -
    per-collector try/except ile AYNI izolasyon."""
    monkeypatch.setattr("cyber_radar.config.DBLP_ENABLED", True)
    monkeypatch.setattr("cyber_radar.collectors.dblp.search", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("blocked")))
    monkeypatch.setattr("cyber_radar.collectors.academic.search_openalex", lambda *a, **k: [])
    monkeypatch.setattr("cyber_radar.collectors.academic.search_crossref", lambda *a, **k: [])
    monkeypatch.setattr("cyber_radar.collectors.academic.search_arxiv_query", lambda *a, **k: [])
    monkeypatch.setattr("cyber_radar.collectors.academic.search_semantic_scholar_bulk", lambda *a, **k: [])
    monkeypatch.setattr("cyber_radar.collectors.openaire.search", lambda *a, **k: [])
    monkeypatch.setattr("cyber_radar.collectors.openreview.search", lambda *a, **k: [])

    profile = ResearchProfile(id="test_dblp_on_fail", title="Test", mode="sci", concept_groups={"a": ["term1"]}, queries=[["a"]])
    total = _collect_profile(db_conn, profile, date(2020, 1, 1))  # crash ETMEMELİ
    assert total == 0
    error_row = db_conn.execute(
        "SELECT error FROM collector_runs WHERE source = 'dblp' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert error_row["error"] not in (None, "disabled_degraded_optional")  # gerçek bir hata loglandı
