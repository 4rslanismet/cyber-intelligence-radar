"""PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md F1): akademik
digest seçim fonksiyonlarının (Current/Timeline/Classic+Historical)
DAHA ÖNCE hiç dedicated testi yoktu - sadece SCI/tez tarafı test
edilmişti. Bu dosya _select_current_papers/_select_learning_path/
_select_historical_highlights'ın "yeterli aday varsa TAM hedef kadar,
yoksa UYDURMADAN daha az" davranışını doğrular. Gerçek ağ/Gemini çağrısı
YOK, test DB kullanır."""
from __future__ import annotations

import json

from cyber_radar.run_pipeline import (
    _select_current_papers,
    _select_historical_highlights,
    _select_learning_path,
    _top_n_papers,
)


def _insert_paper(conn, **fields) -> dict:
    defaults = dict(
        title=f"Test Paper {fields.get('_uid', id(fields))}",
        normalized_title=f"tp-{fields.get('_uid', id(fields))}",
        abstract="An abstract.",
        publication_date="2024-01-01",
        document_type="journal-article",
        relevance_status="relevant",
        analyzed_at="now()",
        is_historical=False,
        analysis=json.dumps({"novelty_score": 5, "academic_value_score": 5}),
    )
    defaults.update({k: v for k, v in fields.items() if not k.startswith("_")})
    row = conn.execute(
        """
        INSERT INTO papers (title, normalized_title, abstract, publication_date, document_type,
                             relevance_status, analyzed_at, is_historical, analysis)
        VALUES (%(title)s, %(normalized_title)s, %(abstract)s, %(publication_date)s, %(document_type)s,
                %(relevance_status)s, %(analyzed_at)s, %(is_historical)s, %(analysis)s::jsonb)
        RETURNING *
        """,
        defaults,
    ).fetchone()
    return row


def test_select_current_papers_returns_exactly_target_when_candidates_exist(db_conn):
    this_run = [_insert_paper(db_conn, _uid=i, analysis=json.dumps({"novelty_score": i, "academic_value_score": i})) for i in range(8)]
    result = _select_current_papers(db_conn, this_run, limit=5)
    assert len(result) == 5


def test_select_current_papers_never_fabricates_beyond_real_candidates(db_conn):
    this_run = [_insert_paper(db_conn, _uid=i) for i in range(2)]
    result = _select_current_papers(db_conn, this_run, limit=5)
    assert len(result) == 2


def test_select_current_papers_backfills_from_db_when_this_run_is_short(db_conn):
    """Bu koşu sadece 1 makale getirdi ama DB'de son 30 günde 4 tane daha
    relevant/analiz edilmiş makale var - backfill 5'e tamamlamalı."""
    this_run = [_insert_paper(db_conn, _uid=0, title="Bu koşunun makalesi")]
    for i in range(1, 5):
        _insert_paper(db_conn, _uid=i, title=f"Havuzdaki makale {i}")
    result = _select_current_papers(db_conn, this_run, limit=5)
    assert len(result) == 5


def test_select_learning_path_returns_exactly_target_when_candidates_exist(db_conn):
    for i in range(8):
        _insert_paper(db_conn, _uid=i, publication_date="2023-06-01")
    result = _select_learning_path(db_conn, target_domain=None, exclude_ids=set(), limit=5)
    assert len(result) == 5


def test_select_learning_path_never_fabricates_beyond_real_candidates(db_conn):
    for i in range(2):
        _insert_paper(db_conn, _uid=i, publication_date="2023-06-01")
    result = _select_learning_path(db_conn, target_domain=None, exclude_ids=set(), limit=5)
    assert len(result) == 2


def test_select_learning_path_excludes_given_ids(db_conn):
    rows = [_insert_paper(db_conn, _uid=i, publication_date="2023-06-01") for i in range(5)]
    excluded = {rows[0]["id"]}
    result = _select_learning_path(db_conn, target_domain=None, exclude_ids=excluded, limit=5)
    assert rows[0]["id"] not in {p["id"] for p in result}


def test_select_learning_path_prefers_dominant_domain_papers(db_conn):
    """target_domain verildiğinde o domain'e >=5 katkısı olan makaleler
    ÖNCE seçilir - kademeli gevşetme (bkz. fonksiyon docstring'i)."""
    for i in range(3):
        _insert_paper(
            db_conn, _uid=f"match-{i}", publication_date="2023-06-01",
            analysis=json.dumps({"domain_contribution_scores": {"SOC": 8}}),
        )
    for i in range(3):
        _insert_paper(
            db_conn, _uid=f"nomatch-{i}", publication_date="2023-06-01",
            analysis=json.dumps({"domain_contribution_scores": {"SOC": 0}}),
        )
    result = _select_learning_path(db_conn, target_domain="SOC", exclude_ids=set(), limit=3)
    assert len(result) == 3
    assert all(((p.get("analysis") or {}).get("domain_contribution_scores") or {}).get("SOC", 0) >= 5 for p in result)


def test_select_historical_highlights_returns_exactly_classic_plus_historical_target(db_conn):
    for i in range(8):
        _insert_paper(db_conn, _uid=i, is_historical=True)
    result = _select_historical_highlights(db_conn, limit=6)  # 1 klasik + 5 historical
    assert len(result) == 6


def test_select_historical_highlights_never_fabricates_beyond_real_candidates(db_conn):
    for i in range(2):
        _insert_paper(db_conn, _uid=i, is_historical=True)
    result = _select_historical_highlights(db_conn, limit=6)
    assert len(result) == 2


def test_select_historical_highlights_rotates_so_same_paper_is_not_repeated(db_conn):
    for i in range(12):
        _insert_paper(db_conn, _uid=i, is_historical=True)
    first = _select_historical_highlights(db_conn, limit=6)
    second = _select_historical_highlights(db_conn, limit=6)
    assert {p["id"] for p in first} != {p["id"] for p in second}


def test_select_historical_highlights_excludes_non_historical_papers(db_conn):
    _insert_paper(db_conn, _uid=0, is_historical=False)
    result = _select_historical_highlights(db_conn, limit=6)
    assert result == []


def test_top_n_papers_ranks_by_novelty_and_value_score(db_conn):
    papers = [
        {"id": 1, "analysis": {"novelty_score": 1, "academic_value_score": 1}},
        {"id": 2, "analysis": {"novelty_score": 9, "academic_value_score": 9}},
        {"id": 3, "analysis": {"novelty_score": 5, "academic_value_score": 5}},
    ]
    result = _top_n_papers(papers, n=2)
    assert [p["id"] for p in result] == [2, 3]


def test_top_n_papers_boosts_topic_affinity_over_generic_relevance(db_conn):
    """PHASE 10 (docs/FUNCTIONAL_GAP_ANALYSIS.md G1): aynı novelty/value
    skoruna sahip iki makaleden SOC/threat-intel/malware/LLM-security/DFIR/
    network-security alanlarından birine yüksek katkısı olanı öne çıkmalı -
    "sadece yeni olduğu için ilgisiz paper seçme" gereksinimi."""
    from cyber_radar.run_pipeline import _top_n_papers

    generic = {
        "id": 1,
        "analysis": {"novelty_score": 5, "academic_value_score": 5, "domain_contribution_scores": {"Academic_Research": 8}},
    }
    soc_relevant = {
        "id": 2,
        "analysis": {"novelty_score": 5, "academic_value_score": 5, "domain_contribution_scores": {"SOC_SIEM": 9}},
    }
    result = _top_n_papers([generic, soc_relevant], n=1)
    assert result[0]["id"] == 2
