"""PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md W1): digest
sonunda TEK bir "📚 Oku Şimdi" önerisi. Gerçek ağ/Gemini/Telegram çağrısı
YOK - test DB kullanır, notify.send_interactive mock'lanır."""
from __future__ import annotations

import json
from unittest.mock import patch

from cyber_radar import digest
from cyber_radar.run_pipeline import _select_read_now_recommendation, _send_feedback_followups


def _insert_paper(conn, **fields) -> dict:
    defaults = dict(
        title=f"Paper {fields.get('_uid', id(fields))}",
        normalized_title=f"rn-{fields.get('_uid', id(fields))}",
        abstract="abs", publication_date="2024-01-01", document_type="journal-article",
        relevance_status="relevant", analyzed_at="now()", is_historical=False,
        reading_status="unread",
        analysis=json.dumps({}),
        relevance=None,
    )
    defaults.update({k: v for k, v in fields.items() if not k.startswith("_")})
    return conn.execute(
        """
        INSERT INTO papers (title, normalized_title, abstract, publication_date, document_type,
                             relevance_status, analyzed_at, is_historical, reading_status, analysis, relevance)
        VALUES (%(title)s, %(normalized_title)s, %(abstract)s, %(publication_date)s, %(document_type)s,
                %(relevance_status)s, %(analyzed_at)s, %(is_historical)s, %(reading_status)s,
                %(analysis)s::jsonb, %(relevance)s::jsonb)
        RETURNING *
        """,
        defaults,
    ).fetchone()


def test_no_recommendation_when_no_candidates(db_conn):
    _insert_paper(db_conn, _uid=1, analysis=json.dumps({"reading_priority": "SKIM"}))
    assert _select_read_now_recommendation(db_conn) is None


def test_recommends_must_read_paper(db_conn):
    p = _insert_paper(db_conn, _uid=1, analysis=json.dumps({"reading_priority": "MUST_READ", "why_read": "Kritik bir yöntem sunuyor."}))
    result = _select_read_now_recommendation(db_conn)
    assert result is not None
    assert result["id"] == p["id"]
    assert result["_read_now_reason"] == "Kritik bir yöntem sunuyor."


def test_recommends_high_relevance_paper_without_must_read(db_conn):
    p = _insert_paper(db_conn, _uid=1, relevance=json.dumps({"confidence": 0.95}))
    result = _select_read_now_recommendation(db_conn)
    assert result is not None
    assert result["id"] == p["id"]
    assert "relevance: 95%" in result["_read_now_reason"]


def test_does_not_recommend_low_relevance_non_must_read_paper(db_conn):
    _insert_paper(db_conn, _uid=1, relevance=json.dumps({"confidence": 0.3}))
    assert _select_read_now_recommendation(db_conn) is None


def test_recommends_high_sci_relevance_paper(db_conn):
    p = _insert_paper(
        db_conn, _uid=1,
        analysis=json.dumps({"profile_extraction": {"sci_relevance_score": 9, "why_relevant": "Kök neden lokalizasyonuna katkı."}}),
    )
    result = _select_read_now_recommendation(db_conn)
    assert result is not None
    assert result["id"] == p["id"]
    assert result["_read_now_reason"] == "Kök neden lokalizasyonuna katkı."


def test_recommends_high_thesis_relevance_paper(db_conn):
    p = _insert_paper(
        db_conn, _uid=1,
        analysis=json.dumps({"profile_extraction": {"thesis_relevance_score": 8, "thesis_relevance_reason": "Grounded açıklamaya doğrudan katkı."}}),
    )
    result = _select_read_now_recommendation(db_conn)
    assert result is not None
    assert result["id"] == p["id"]
    assert result["_read_now_reason"] == "Grounded açıklamaya doğrudan katkı."


def test_excludes_ids_already_shown_elsewhere_in_digest(db_conn):
    p = _insert_paper(db_conn, _uid=1, analysis=json.dumps({"reading_priority": "MUST_READ"}))
    assert _select_read_now_recommendation(db_conn, exclude_ids={p["id"]}) is None


def test_excludes_non_unread_papers(db_conn):
    _insert_paper(db_conn, _uid=1, reading_status="reading", analysis=json.dumps({"reading_priority": "MUST_READ"}))
    assert _select_read_now_recommendation(db_conn) is None


def test_respects_cooldown_after_recent_recommendation(db_conn):
    from datetime import datetime, timezone

    p = _insert_paper(db_conn, _uid=1, analysis=json.dumps({"reading_priority": "MUST_READ"}))
    db_conn.execute("UPDATE papers SET last_recommended_at = %s WHERE id = %s", (datetime.now(timezone.utc), p["id"]))
    assert _select_read_now_recommendation(db_conn) is None


def test_picks_highest_scoring_candidate_among_several(db_conn):
    _insert_paper(db_conn, _uid=1, relevance=json.dumps({"confidence": 0.85}))
    best = _insert_paper(db_conn, _uid=2, analysis=json.dumps({"reading_priority": "MUST_READ"}), relevance=json.dumps({"confidence": 0.9}))
    result = _select_read_now_recommendation(db_conn)
    assert result["id"] == best["id"]


def test_send_feedback_followups_sends_read_now_exactly_once_and_starts_cooldown(db_conn):
    p = _insert_paper(db_conn, _uid=1, analysis=json.dumps({"reading_priority": "MUST_READ", "why_read": "test"}))
    read_now = _select_read_now_recommendation(db_conn)
    assert read_now is not None

    with patch("cyber_radar.notify.send_interactive", return_value=999) as mock_send:
        _send_feedback_followups(db_conn, [], [], [], read_now=read_now)

    assert mock_send.call_count == 1
    sent_text = mock_send.call_args[0][0]
    assert sent_text.startswith("📚 Oku Şimdi")
    row = db_conn.execute("SELECT last_recommended_at FROM papers WHERE id = %s", (p["id"],)).fetchone()
    assert row["last_recommended_at"] is not None


def test_read_now_not_duplicated_when_also_a_must_read_current_paper(db_conn):
    """read_now bir current_papers MUST_READ makalesiyle AYNI id'ye sahip
    olursa (normalde exclude_ids ile önlenir, ama savunma amaçlı) TEK
    mesaj gönderilmeli, iki kez DEĞİL."""
    p = _insert_paper(db_conn, _uid=1, analysis=json.dumps({"reading_priority": "MUST_READ", "why_read": "test"}))
    current = dict(p)
    read_now = dict(p)
    read_now["_read_now_reason"] = "test"

    with patch("cyber_radar.notify.send_interactive", return_value=999) as mock_send:
        _send_feedback_followups(db_conn, [current], [], [], read_now=read_now)

    assert mock_send.call_count == 1


def test_generate_brief_includes_read_now_section_header():
    brief = digest.generate_brief([], [], [], {}, "Sabah", read_now={"id": 1, "title": "X", "_read_now_reason": "y"})
    assert "📚 Oku Şimdi" in brief
    assert "X" not in brief  # bulk'ta TAM başlık yok - kendi kartında


def test_generate_brief_omits_read_now_section_when_none():
    brief = digest.generate_brief([], [], [], {}, "Sabah", read_now=None)
    assert "📚 Oku Şimdi" not in brief


def test_build_all_paper_cards_includes_reason_and_full_card_for_read_now():
    p = {"id": 1, "title": "Recommended Paper", "analysis": {"turkish_summary": "özet"}, "_read_now_reason": "Çok ilgili."}
    cards = digest.build_all_paper_cards([], read_now=p)
    assert len(cards) == 1
    assert cards[0].category == "READ_NOW"
    assert "📚 Oku Şimdi" in cards[0].text
    assert "Çok ilgili." in cards[0].text
    assert "Recommended Paper" in cards[0].text
