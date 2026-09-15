"""Geriye dönük uyumluluk garantisi: ACTIVE_RESEARCH_PROFILES=daily_cyber
(varsayılan) iken, tüm research architecture (profiles/query_builder/
federasyon) yüklü olsa bile eski günlük radar davranışı BİREBİR korunmalı -
academic.COLLECTORS'ın düz-keyword fonksiyonları değişmeden çağrılmalı,
hiçbir federasyon kaynağı (openaire/dblp/openreview/opencitations/doaj)
devreye girmemeli."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from cyber_radar.research.profiles import ResearchProfile, load_active_profiles
from cyber_radar.run_pipeline import _collect_profile


def test_daily_cyber_backward_compatibility(db_conn, monkeypatch):
    calls = []

    def make_recorder(name):
        def _fn(keyword, since_date, **kwargs):
            calls.append((name, keyword))
            return []
        return _fn

    # NOT: academic.COLLECTORS modül yüklenirken fonksiyon REFERANSLARINI
    # yakalıyor - tek tek isim patch'lemek yerine dict'in kendisini
    # patch'liyoruz (bkz. test_collector_resilience.py'deki aynı not).
    monkeypatch.setattr(
        "cyber_radar.collectors.academic.COLLECTORS",
        {
            "openalex": make_recorder("openalex"),
            "crossref": make_recorder("crossref"),
            "arxiv": make_recorder("arxiv"),
            "semantic_scholar": make_recorder("semantic_scholar"),
        },
    )

    # Federasyon fonksiyonları hiç çağrılırsa test PATLAMALI (autouse
    # block_real_network zaten engeller ama burada ayrıca açıkça iddia
    # ediyoruz - "hiç çağrılmadı" pozitif kontrolü).
    openaire_mock = MagicMock(side_effect=AssertionError("daily_cyber modunda openaire ÇAĞRILMAMALI"))
    dblp_mock = MagicMock(side_effect=AssertionError("daily_cyber modunda dblp ÇAĞRILMAMALI"))
    openreview_mock = MagicMock(side_effect=AssertionError("daily_cyber modunda openreview ÇAĞRILMAMALI"))
    monkeypatch.setattr("cyber_radar.collectors.openaire.search", openaire_mock)
    monkeypatch.setattr("cyber_radar.collectors.dblp.search", dblp_mock)
    monkeypatch.setattr("cyber_radar.collectors.openreview.search", openreview_mock)

    monkeypatch.setattr("cyber_radar.config.KEYWORDS", ["cybersecurity", "threat intelligence", "SOC"])
    monkeypatch.setattr("cyber_radar.config.ACTIVE_RESEARCH_PROFILES", ["daily_cyber"])

    active = load_active_profiles()
    assert len(active) == 1
    assert active[0].mode == "daily"

    total = _collect_profile(db_conn, active[0], date(2020, 1, 1))

    assert total == 0
    called_sources = {name for name, _ in calls}
    assert called_sources == {"openalex", "crossref", "arxiv", "semantic_scholar"}
    called_keywords = {kw for _, kw in calls}
    assert called_keywords == {"cybersecurity", "threat intelligence", "SOC"}
    openaire_mock.assert_not_called()
    dblp_mock.assert_not_called()
    openreview_mock.assert_not_called()


def test_daily_cyber_profile_mode_field():
    p = ResearchProfile(id="daily_cyber", title="x", mode="daily")
    assert p.snowball is False
    assert p.extraction_schema is None
