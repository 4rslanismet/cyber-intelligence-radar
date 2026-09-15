"""2026-09-11 (kullanıcı isteği: "kayıt butonları tam her makale altında
olsun") - digest.build_all_paper_cards artık current/timeline/historical
(klasik+geri kalan)/SCI/tez KATEGORİLERİNİN HEPSİNDEKİ makaleler için kart
üretir, sadece MUST_READ/Klasik için değil. generate_brief() bu makalelerin
HİÇBİRİNİ artık bulk metne TAM yazmıyor. Saf fonksiyon testleri."""
from __future__ import annotations

from cyber_radar import digest


def _paper(pid, title, **analysis_extra):
    return {
        "id": pid, "title": title, "publication_date": None, "cited_by_count": 5,
        "relevance": {"confidence": 0.8},
        "analysis": {"reading_priority": "READ", "turkish_summary": "özet", **analysis_extra},
    }


def test_every_current_paper_gets_a_card_not_just_must_read():
    papers = [_paper(1, "Current A"), _paper(2, "Current B", reading_priority="MUST_READ")]
    cards = digest.build_all_paper_cards(papers)
    assert len(cards) == 2
    categories = {c.paper_id: c.category for c in cards}
    assert categories[1] == "CURRENT"
    assert categories[2] == "MUST_READ"


def test_every_timeline_paper_gets_a_card():
    timeline = [_paper(10, "Timeline A"), _paper(11, "Timeline B")]
    cards = digest.build_all_paper_cards([], learning_path_papers=timeline)
    assert len(cards) == 2
    assert all(c.category == "TIMELINE" for c in cards)
    assert all(c.text.startswith("🧭 Temelden Güncele") for c in cards)


def test_classic_and_rest_historical_both_get_cards():
    historical = [
        _paper(20, "Old but gold", foundational_value_score=9, educational_value_score=9),
        _paper(21, "Also historical", foundational_value_score=1, educational_value_score=1),
        _paper(22, "Another one", foundational_value_score=1, educational_value_score=1),
    ]
    cards = digest.build_all_paper_cards([], historical_papers=historical)
    assert len(cards) == 3
    by_id = {c.paper_id: c for c in cards}
    assert by_id[20].category == "CLASSIC"
    assert by_id[20].text.startswith("🏛️ Bugünün Klasiği")
    assert by_id[21].category == "HISTORICAL"
    assert by_id[21].text.startswith("📚 Geçmişten Öne Çıkanlar")
    assert by_id[22].category == "HISTORICAL"


def test_profile_a_and_b_papers_get_their_own_cards():
    profile_a = [{"id": 30, "title": "Profile A candidate", "analysis": None}]
    profile_b = [{"id": 31, "title": "Profile B candidate", "analysis": None}]
    cards = digest.build_all_paper_cards([], profile_a_papers=profile_a, profile_b_papers=profile_b)
    assert len(cards) == 2
    by_id = {c.paper_id: c for c in cards}
    assert by_id[30].category == "RESEARCH_PROFILE_A"
    assert "Profile A candidate" in by_id[30].text
    assert by_id[31].category == "RESEARCH_PROFILE_B"
    assert "Profile B candidate" in by_id[31].text


def test_generate_brief_shows_only_header_and_count_note_for_all_categories():
    """Bulk metinde artık HİÇBİR akademik makalenin TAM içeriği yok - sadece
    "N makale ... ayrı mesaj olarak gönderildi" notu."""
    current = [_paper(1, "Zz-Current-Unique")]
    timeline = [_paper(2, "Zz-Timeline-Unique")]
    historical = [_paper(3, "Zz-Historical-Unique")]
    brief = digest.generate_brief(
        [], current, historical, {}, "Sabah", learning_path_papers=timeline,
    )
    for title in ("Zz-Current-Unique", "Zz-Timeline-Unique", "Zz-Historical-Unique"):
        assert title not in brief
    assert "ayrı mesaj olarak gönderildi" in brief


def test_total_card_count_matches_total_paper_count_across_all_categories():
    current = [_paper(1, "A"), _paper(2, "B", reading_priority="MUST_READ")]
    timeline = [_paper(3, "C")]
    historical = [_paper(4, "D"), _paper(5, "E")]
    sci = [{"id": 6, "title": "F", "analysis": None}]
    thesis = [{"id": 7, "title": "G", "analysis": None}]
    cards = digest.build_all_paper_cards(current, timeline, historical, sci, thesis)
    assert len(cards) == 7
    assert {c.paper_id for c in cards} == {1, 2, 3, 4, 5, 6, 7}
