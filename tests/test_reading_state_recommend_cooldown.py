"""Madde 10 (okuma durumu): aynı MUST_READ makale sürekli "Oku Şimdi"
olarak önerilmemeli (bkz. src/run_pipeline._send_feedback_followups,
papers.last_recommended_at). Gerçek Telegram/ağ çağrısı YOK - notify.
send_interactive mock'lanır."""
from __future__ import annotations

from unittest.mock import patch

from cyber_radar.run_pipeline import _send_feedback_followups


def _insert_must_read_paper(conn, reading_status="unread", last_recommended_at=None, **fields) -> int:
    row = conn.execute(
        """
        INSERT INTO papers (title, normalized_title, matched_profiles, analysis, reading_status, last_recommended_at)
        VALUES (%(title)s, %(title)s, '{}', %(analysis)s::jsonb, %(reading_status)s, %(last_recommended_at)s)
        RETURNING id
        """,
        {
            "title": fields.get("title", "MUST_READ Paper"),
            "analysis": '{"reading_priority": "MUST_READ"}',
            "reading_status": reading_status,
            "last_recommended_at": last_recommended_at,
        },
    ).fetchone()
    return row["id"]


def test_recommends_must_read_paper_never_recommended_before(db_conn):
    pid = _insert_must_read_paper(db_conn)
    paper = {"id": pid, "title": "MUST_READ Paper", "analysis": {"reading_priority": "MUST_READ"}}
    with patch("cyber_radar.notify.send_interactive", return_value=999) as mock_send:
        _send_feedback_followups(db_conn, [paper], [], [])
    assert mock_send.call_count == 1
    row = db_conn.execute("SELECT last_recommended_at FROM papers WHERE id = %s", (pid,)).fetchone()
    assert row["last_recommended_at"] is not None


def test_does_not_recommend_again_within_cooldown(db_conn):
    pid = _insert_must_read_paper(db_conn)
    paper = {"id": pid, "title": "MUST_READ Paper", "analysis": {"reading_priority": "MUST_READ"}}
    with patch("cyber_radar.notify.send_interactive", return_value=999):
        _send_feedback_followups(db_conn, [paper], [], [])  # 1. öneri
        with patch("cyber_radar.notify.send_interactive", return_value=999) as mock_send_2:
            _send_feedback_followups(db_conn, [paper], [], [])  # 2. koşu, hemen sonra
    mock_send_2.assert_not_called()


def test_does_not_recommend_when_user_already_interacted(db_conn):
    """reading_status 'unread' DIŞINDA (ör. 'reading') ise - kullanıcı
    zaten etkileşime girmiş, tekrar "Oku Şimdi" önerisi ANLAMSIZ."""
    pid = _insert_must_read_paper(db_conn, reading_status="reading")
    paper = {"id": pid, "title": "MUST_READ Paper", "analysis": {"reading_priority": "MUST_READ"}}
    with patch("cyber_radar.notify.send_interactive") as mock_send:
        _send_feedback_followups(db_conn, [paper], [], [])
    mock_send.assert_not_called()


def test_recommends_again_after_cooldown_expires(db_conn):
    from datetime import datetime, timedelta, timezone

    old_ts = datetime.now(timezone.utc) - timedelta(days=20)  # cooldown (14 gün) geçmiş
    pid = _insert_must_read_paper(db_conn, last_recommended_at=old_ts)
    paper = {"id": pid, "title": "MUST_READ Paper", "analysis": {"reading_priority": "MUST_READ"}}
    with patch("cyber_radar.notify.send_interactive", return_value=999) as mock_send:
        _send_feedback_followups(db_conn, [paper], [], [])
    mock_send.assert_called_once()


def test_does_not_recommend_when_already_read_completed(db_conn):
    """PHASE 10 (docs/FUNCTIONAL_GAP_ANALYSIS.md V2): reading_status='completed'
    (READ) ise yeniden ana öneri OLMAMALI."""
    pid = _insert_must_read_paper(db_conn, reading_status="completed")
    paper = {"id": pid, "title": "MUST_READ Paper", "analysis": {"reading_priority": "MUST_READ"}}
    with patch("cyber_radar.notify.send_interactive") as mock_send:
        _send_feedback_followups(db_conn, [paper], [], [])
    mock_send.assert_not_called()


def test_does_not_recommend_when_skipped(db_conn):
    """PHASE 10 (docs/FUNCTIONAL_GAP_ANALYSIS.md V2): reading_status='skipped'
    ise sürekli geri gelmemeli."""
    pid = _insert_must_read_paper(db_conn, reading_status="skipped")
    paper = {"id": pid, "title": "MUST_READ Paper", "analysis": {"reading_priority": "MUST_READ"}}
    with patch("cyber_radar.notify.send_interactive") as mock_send:
        _send_feedback_followups(db_conn, [paper], [], [])
    mock_send.assert_not_called()
