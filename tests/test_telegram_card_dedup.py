"""Telegram anchor-mesaj duplikasyon düzeltmesi (2026-09-11, bkz.
src/digest.PaperCard/build_all_paper_cards, run_pipeline.
_send_feedback_followups). Eskiden bir MUST_READ/Klasik makale HEM bulk
digest metninde tam olarak gösteriliyor HEM DE butonları taşımak için ayrı,
kısa bir "anchor" mesajı ("📚 Oku Şimdi: <title>") gönderiliyordu - aynı
makale ekranda iki kere görünüyordu. Bu testler: (1) makale TAM metni
bulk+kart toplamında TAM BİR KEZ geçmeli, (2) kısa "anchor-only" mesaj ARTIK
üretilmemeli, (3) interaktif mesajın reply_markup'ı (keyboard) doğru
paper_id'yi taşımalı. Gerçek Telegram/ağ çağrısı YOK."""
from __future__ import annotations

from unittest.mock import patch

from cyber_radar import digest
from cyber_radar.run_pipeline import _send_feedback_followups

_UNIQUE_MUST_READ_TITLE = "ZzTestUniqueMustReadPaperTitleZz"
_UNIQUE_CLASSIC_TITLE = "ZzTestUniqueClassicPaperTitleZz"


def _must_read_paper(paper_id=101) -> dict:
    return {
        "id": paper_id,
        "title": _UNIQUE_MUST_READ_TITLE,
        "publication_date": None,
        "cited_by_count": 0,
        "relevance": {"confidence": 0.9},
        "analysis": {
            "reading_priority": "MUST_READ",
            "why_read": "test nedeni",
            "turkish_summary": "test özeti",
            "paper_role": ["METHOD"],
        },
    }


def _classic_paper(paper_id=202) -> dict:
    return {
        "id": paper_id,
        "title": _UNIQUE_CLASSIC_TITLE,
        "publication_date": None,
        "cited_by_count": 100,
        "relevance": {"confidence": 0.9},
        "analysis": {
            "reading_priority": "SAVE",
            "turkish_summary": "klasik özet",
            "foundational_value_score": 8,
            "educational_value_score": 7,
        },
    }


def test_must_read_paper_appears_exactly_once_across_bulk_and_cards():
    p = _must_read_paper()
    brief = digest.generate_brief([], [p], [], {}, "Sabah")
    cards = digest.build_all_paper_cards([p])
    combined = brief + "\n" + "\n".join(c.text for c in cards)
    assert combined.count(_UNIQUE_MUST_READ_TITLE) == 1


def test_classic_paper_appears_exactly_once_across_bulk_and_cards():
    p = _classic_paper()
    brief = digest.generate_brief([], [], [p], {}, "Sabah")
    cards = digest.build_all_paper_cards([], historical_papers=[p])
    combined = brief + "\n" + "\n".join(c.text for c in cards)
    assert combined.count(_UNIQUE_CLASSIC_TITLE) == 1


def test_bulk_digest_does_not_contain_must_read_paper_at_all():
    p = _must_read_paper()
    brief = digest.generate_brief([], [p], [], {}, "Sabah")
    assert _UNIQUE_MUST_READ_TITLE not in brief


def test_bulk_digest_does_not_contain_classic_paper_at_all():
    p = _classic_paper()
    brief = digest.generate_brief([], [], [p], {}, "Sabah")
    assert _UNIQUE_CLASSIC_TITLE not in brief


def test_no_short_oku_simdi_anchor_only_message_is_sent(db_conn):
    """Eskiden gönderilen kısa etiket ("📚 Oku Şimdi: <title>", başka HİÇBİR
    içerik yok) artık ASLA üretilmemeli - gönderilen metin TAM kart olmalı."""
    pid = _insert_test_paper(db_conn, title=_UNIQUE_MUST_READ_TITLE, reading_priority="MUST_READ")
    current_papers = [dict(db_conn.execute("SELECT * FROM papers WHERE id=%s", (pid,)).fetchone())]

    with patch("cyber_radar.notify.send_interactive", return_value=None) as mock_send:
        _send_feedback_followups(db_conn, current_papers, [], [])

    assert mock_send.call_count == 1
    sent_text = mock_send.call_args[0][0]
    short_anchor = f"📚 Oku Şimdi: {_UNIQUE_MUST_READ_TITLE}"
    assert sent_text != short_anchor  # ARTIK sadece kısa etiket DEĞİL
    assert sent_text.startswith("📚 Oku Şimdi")  # başlık hâlâ var
    assert _UNIQUE_MUST_READ_TITLE in sent_text  # başlık TAM metnin içinde
    assert "test nedeni" in sent_text  # TAM kart içeriği (why_read) mesajda


def test_no_short_classic_anchor_only_message_is_sent(db_conn):
    pid = _insert_test_paper(db_conn, title=_UNIQUE_CLASSIC_TITLE, is_historical=True, relevance_status="relevant")
    db_conn.execute(
        "UPDATE papers SET analyzed_at = now(), analysis = %s::jsonb WHERE id = %s",
        ('{"turkish_summary": "klasik özet", "foundational_value_score": 8, "educational_value_score": 7}', pid),
    )
    historical = [dict(db_conn.execute("SELECT * FROM papers WHERE id=%s", (pid,)).fetchone())]

    with patch("cyber_radar.notify.send_interactive", return_value=None) as mock_send:
        _send_feedback_followups(db_conn, [], historical, [])

    assert mock_send.call_count == 1
    sent_text = mock_send.call_args[0][0]
    short_anchor = f"🏛️ Bugünün Klasiği: {_UNIQUE_CLASSIC_TITLE}"
    assert sent_text != short_anchor
    assert sent_text.startswith("🏛️ Bugünün Klasiği")
    assert _UNIQUE_CLASSIC_TITLE in sent_text
    assert "klasik özet" in sent_text


def test_interactive_message_keyboard_has_correct_paper_id(db_conn):
    pid = _insert_test_paper(db_conn, title=_UNIQUE_MUST_READ_TITLE, reading_priority="MUST_READ")
    current_papers = [dict(db_conn.execute("SELECT * FROM papers WHERE id=%s", (pid,)).fetchone())]

    with patch("cyber_radar.notify.send_interactive", return_value=None) as mock_send:
        _send_feedback_followups(db_conn, current_papers, [], [])

    buttons = mock_send.call_args[0][1]
    all_callbacks = [data for row in buttons for _label, data in row]
    assert any(f":{pid}:" in cb for cb in all_callbacks)  # doğru paper_id callback'lerde var
    assert all(cb.startswith("p:") for cb in all_callbacks)  # makale prefix'i


def test_paper_card_text_and_keyboard_never_split_across_messages():
    """Telegram inline keyboard tek bir mesajın reply_markup'ına bağlıdır -
    text ve keyboard ASLA farklı mesajlara bölünmemeli. send_interactive
    tek bir _post_telegram çağrısı yapar (text+reply_markup AYNI payload) -
    bu, dolaylı olarak bölünmediğini kanıtlar."""
    from cyber_radar.notify import send_interactive

    long_text = "kelime " * 2000  # kesinlikle 4096'yı aşan uzunlukta
    with patch("cyber_radar.notify._post_telegram") as mock_post, \
         patch("cyber_radar.notify.config.TELEGRAM_BOT_TOKEN", "x"), \
         patch("cyber_radar.notify.config.TELEGRAM_CHAT_ID", "1"):
        send_interactive(long_text, [[("👍", "p:1:u")]])

    assert mock_post.call_count == 1  # TEK mesaj - text+keyboard birlikte
    payload = mock_post.call_args[0][1]
    assert len(payload["text"]) <= 4096
    assert "reply_markup" in payload
    # kelimenin ORTASINDA kesilmedi - son kelime TAM "kelime" olmalı, "kelim" gibi bir parça DEĞİL.
    assert payload["text"].rstrip().split(" ")[-1] == "kelime"


def test_send_feedback_followups_sends_a_card_for_every_paper_category(db_conn):
    """2026-09-11 genişletmesi: SADECE MUST_READ/Klasik değil, o koşuda
    gösterilen current/timeline/historical HER makale kendi kartıyla
    gönderilmeli."""
    current_id = _insert_test_paper(db_conn, title="Current Non-MustRead")
    timeline_id = _insert_test_paper(db_conn, title="Timeline Paper")
    historical_id = _insert_test_paper(db_conn, title="Historical Paper", is_historical=True)

    current = [dict(db_conn.execute("SELECT * FROM papers WHERE id=%s", (current_id,)).fetchone())]
    timeline = [dict(db_conn.execute("SELECT * FROM papers WHERE id=%s", (timeline_id,)).fetchone())]
    historical = [dict(db_conn.execute("SELECT * FROM papers WHERE id=%s", (historical_id,)).fetchone())]

    with patch("cyber_radar.notify.send_interactive", return_value=None) as mock_send:
        _send_feedback_followups(db_conn, current, historical, [], learning_path_papers=timeline)

    assert mock_send.call_count == 3
    sent_ids = {call.args[1][0][0][1].split(":")[1] for call in mock_send.call_args_list}
    assert sent_ids == {str(current_id), str(timeline_id), str(historical_id)}


def _insert_test_paper(conn, title: str, **fields) -> int:
    defaults = dict(
        title=title, normalized_title=title.lower(), abstract="test abstract",
        publication_date="2022-01-01", document_type="journal-article",
        relevance_status="relevant", matched_profiles=[], is_historical=False,
        reading_status="unread",
    )
    reading_priority = fields.pop("reading_priority", None)
    defaults.update(fields)
    row = conn.execute(
        """
        INSERT INTO papers (title, normalized_title, abstract, publication_date, document_type,
                             relevance_status, matched_profiles, is_historical, reading_status)
        VALUES (%(title)s, %(normalized_title)s, %(abstract)s, %(publication_date)s, %(document_type)s,
                %(relevance_status)s, %(matched_profiles)s, %(is_historical)s, %(reading_status)s)
        RETURNING id
        """,
        defaults,
    ).fetchone()
    pid = row["id"]
    if reading_priority:
        conn.execute(
            "UPDATE papers SET analyzed_at = now(), analysis = %s::jsonb WHERE id = %s",
            ('{"reading_priority": "%s", "why_read": "test nedeni", "turkish_summary": "test özeti"}' % reading_priority, pid),
        )
    return pid
