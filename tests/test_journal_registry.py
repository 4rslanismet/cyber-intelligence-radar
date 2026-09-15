"""journal_registry doğrulaması: SCIE/WoS/Scopus durumu ASLA bibliyografik
metadata'dan TAHMİN EDİLMEZ - sadece journal_registry'de GERÇEK bir eşleşme
varsa dolar (bkz. src/research/journal_lookup.py). Test DB kullanır."""
from __future__ import annotations

import inspect

from cyber_radar.research import journal_lookup
from cyber_radar.run_pipeline import _upsert_paper


def test_journal_registry_empty_means_unverified(db_conn, sample_paper_item):
    """journal_registry BOŞ iken (varsayılan durum, hiçbir CSV import
    edilmemiş) hiçbir paper journal_verified=true OLAMAZ - false/null kalır,
    SCIE/Q1/Q2 asla otomatik üretilmez."""
    empty_count = db_conn.execute("SELECT count(*) AS c FROM journal_registry").fetchone()["c"]
    assert empty_count == 0

    item = dict(sample_paper_item, issn="1234-5678", eissn=None)
    _upsert_paper(db_conn, item)

    row = db_conn.execute(
        "SELECT journal_verified, wos_index, journal_quartile FROM papers WHERE doi = %s",
        (sample_paper_item["doi"],),
    ).fetchone()
    assert row["journal_verified"] is False
    assert row["wos_index"] is None
    assert row["journal_quartile"] is None


def test_verified_journal_match(db_conn, sample_paper_item):
    """journal_registry'de GERÇEK bir eşleşme varsa (elle/CSV ile girilmiş)
    papers.journal_verified/wos_index/journal_quartile doğru dolmalı."""
    db_conn.execute(
        """
        INSERT INTO journal_registry (issn, journal_name, wos_index, jcr_quartile, source)
        VALUES (%s, %s, %s, %s, %s)
        """,
        ("1936-1270", "Test Journal for SCIE Fixture", "SCIE", "Q1", "unit_test_fixture"),
    )

    item = dict(sample_paper_item, issn="1936-1270", eissn=None)
    _upsert_paper(db_conn, item)

    row = db_conn.execute(
        "SELECT journal_verified, wos_index, journal_quartile FROM papers WHERE doi = %s",
        (sample_paper_item["doi"],),
    ).fetchone()
    assert row["journal_verified"] is True
    assert row["wos_index"] == "SCIE"
    assert row["journal_quartile"] == "Q1"


def test_journal_lookup_no_match_returns_none(db_conn):
    assert journal_lookup.lookup(db_conn, "0000-0000", None) is None


def test_journal_lookup_with_no_issn_returns_none(db_conn):
    assert journal_lookup.lookup(db_conn, None, None) is None


def test_doaj_does_not_affect_relevance_score():
    """doaj_indexed=true olması TEK BAŞINA relevance/quality/SCI skorunu
    DEĞİŞTİRMEMELİ - kod tabanındaki gerçek puanlama/relevance fonksiyonları
    doaj_indexed'i parametre olarak ALMAMALI (statik denetim, gerçek
    fonksiyon imzalarını okuyor - ileride biri yanlışlıkla bağlarsa bu
    test kırılır)."""
    from cyber_radar import digest
    from cyber_radar.llm import news_analyst, relevance

    for fn in (digest.historical_score, news_analyst.compute_priority, relevance.classify_paper, relevance.classify_news):
        assert "doaj" not in inspect.signature(fn).parameters
