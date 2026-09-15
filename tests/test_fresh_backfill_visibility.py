"""PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md U1): bir digest
kaydının bu koşuda mı toplandığı (FRESH) yoksa daha önceki bir koşudan mı
geldiği (BACKFILL) - önceden internal olarak biliniyordu ama hiçbir yerde
gösterilmiyordu. Gerçek ağ/Gemini çağrısı YOK, test DB kullanır."""
from __future__ import annotations

import json

from cyber_radar import digest
from cyber_radar.run_pipeline import _select_current_papers, _select_news_for_digest


def _insert_news(conn, tier: str, title: str) -> int:
    row = conn.execute(
        """
        INSERT INTO news_events (title, dedup_key, analysis, analyzed_at, relevance_status)
        VALUES (%(title)s, %(dedup_key)s, %(analysis)s::jsonb, now(), 'relevant')
        RETURNING id
        """,
        {"title": title, "dedup_key": title.lower(), "analysis": json.dumps({"news_tier": tier, "summary": "t"})},
    ).fetchone()
    return row["id"]


def test_this_run_news_is_tagged_fresh(db_conn):
    nid = _insert_news(db_conn, "AWARENESS", "Bu koşunun haberi")
    row = db_conn.execute("SELECT * FROM news_events WHERE id = %s", (nid,)).fetchone()
    result = _select_news_for_digest(db_conn, analyzed_news=[row], target_per_tier=1)
    assert result[0]["_digest_source"] == "FRESH"


def test_backfilled_news_is_tagged_backfill(db_conn):
    _insert_news(db_conn, "AWARENESS", "Havuzdan gelen haber")
    result = _select_news_for_digest(db_conn, analyzed_news=[], target_per_tier=1)
    assert result[0]["_digest_source"] == "BACKFILL"


def test_source_tag_renders_backfill_marker():
    assert digest._source_tag({"_digest_source": "BACKFILL"}) == " _[BACKFILL]_"


def test_source_tag_renders_nothing_for_fresh():
    assert digest._source_tag({"_digest_source": "FRESH"}) == ""


def test_source_tag_renders_nothing_when_absent():
    assert digest._source_tag({}) == ""


def test_generate_brief_shows_backfill_tag_on_awareness_item():
    news = [{"id": 1, "title": "Eski haber", "cves": [], "cisa_kev": False, "analysis": {"news_tier": "AWARENESS", "summary": "s"}, "_digest_source": "BACKFILL"}]
    brief = digest.generate_brief(news, [], [], {}, "Sabah")
    assert "Eski haber" in brief
    assert "[BACKFILL]" in brief


def test_generate_brief_omits_tag_for_fresh_news():
    news = [{"id": 1, "title": "Yeni haber", "cves": [], "cisa_kev": False, "analysis": {"news_tier": "AWARENESS", "summary": "s"}, "_digest_source": "FRESH"}]
    brief = digest.generate_brief(news, [], [], {}, "Sabah")
    assert "[BACKFILL]" not in brief


def _insert_paper(conn, **fields) -> dict:
    defaults = dict(
        title=f"Paper {fields.get('_uid', id(fields))}",
        normalized_title=f"tp-{fields.get('_uid', id(fields))}",
        abstract="abs", publication_date="2024-01-01", document_type="journal-article",
        relevance_status="relevant", analyzed_at="now()", is_historical=False,
        analysis=json.dumps({"novelty_score": 5, "academic_value_score": 5}),
    )
    defaults.update({k: v for k, v in fields.items() if not k.startswith("_")})
    return conn.execute(
        """
        INSERT INTO papers (title, normalized_title, abstract, publication_date, document_type,
                             relevance_status, analyzed_at, is_historical, analysis)
        VALUES (%(title)s, %(normalized_title)s, %(abstract)s, %(publication_date)s, %(document_type)s,
                %(relevance_status)s, %(analyzed_at)s, %(is_historical)s, %(analysis)s::jsonb)
        RETURNING *
        """,
        defaults,
    ).fetchone()


def test_current_papers_this_run_tagged_fresh(db_conn):
    p = _insert_paper(db_conn, _uid=1)
    result = _select_current_papers(db_conn, [p], limit=1)
    assert result[0]["_digest_source"] == "FRESH"


def test_current_papers_backfilled_from_pool_tagged_backfill(db_conn):
    _insert_paper(db_conn, _uid=1)
    result = _select_current_papers(db_conn, [], limit=1)
    assert result[0]["_digest_source"] == "BACKFILL"
