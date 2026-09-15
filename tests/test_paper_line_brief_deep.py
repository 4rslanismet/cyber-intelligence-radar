"""BRIEF/DEEP iki görünümlü makale sunumu (bkz. src/digest._paper_line,
Phase 2 madde 9): "Telegram yalnızca presentation layer, detay DB'de
saklanır". Saf fonksiyon testleri."""
from __future__ import annotations

from cyber_radar.digest import _paper_line

_BASE = {
    "title": "Test Paper",
    "relevance": {"confidence": 0.5},
    "analysis": {
        "reading_priority": "READ",
        "paper_role": ["METHOD"],
        "why_read": "Çünkü ilginç.",
        "turkish_summary": "Kısa özet.",
        "paper_type": "EXPERIMENTAL",
        "foundational_value_score": 0,
    },
}


def test_brief_view_shows_decision_role_title_reason_summary_and_score():
    lines = "\n".join(_paper_line(dict(_BASE), detailed=False))
    assert "[READ]" in lines          # karar
    assert "[METHOD]" in lines        # role
    assert "Test Paper" in lines      # başlık
    assert "Neden: Çünkü ilginç." in lines
    assert "Kısa özet." in lines
    assert "relevance: 50%" in lines  # relevance score


def test_brief_view_omits_deep_fields():
    p = dict(_BASE)
    p["analysis"] = dict(p["analysis"], difficulty_label="Advanced", must_see=["Figure 1"])
    lines = "\n".join(_paper_line(p, detailed=False))
    assert "Zorluk" not in lines
    assert "Özellikle" not in lines


def test_deep_view_includes_extra_fields_when_detailed_true():
    p = dict(_BASE)
    p["analysis"] = dict(
        p["analysis"], difficulty_label="Advanced", difficulty_score=4,
        must_see=["Figure 1"],
    )
    lines = "\n".join(_paper_line(p, detailed=True))
    assert "Zorluk" in lines
    assert "Özellikle: Figure 1" in lines


def test_must_read_auto_upgrades_to_deep_view_even_if_not_requested():
    p = dict(_BASE)
    p["analysis"] = dict(p["analysis"], reading_priority="MUST_READ", must_see=["Table 2"])
    lines = "\n".join(_paper_line(p, detailed=False))
    assert "Özellikle: Table 2" in lines  # DEEP alanı basıldı


def test_very_high_relevance_auto_upgrades_to_deep_view():
    p = dict(_BASE)
    p["relevance"] = {"confidence": 0.95}
    p["analysis"] = dict(p["analysis"], must_see=["Table 9"])
    lines = "\n".join(_paper_line(p, detailed=False))
    assert "Özellikle: Table 9" in lines


def test_medium_relevance_stays_brief_view():
    p = dict(_BASE)
    p["relevance"] = {"confidence": 0.6}
    p["analysis"] = dict(p["analysis"], must_see=["Table 9"])
    lines = "\n".join(_paper_line(p, detailed=False))
    assert "Özellikle" not in lines


def test_no_relevance_score_line_when_confidence_missing():
    p = dict(_BASE)
    p["relevance"] = {}
    lines = "\n".join(_paper_line(p, detailed=False))
    assert "relevance:" not in lines


def test_learning_path_stage_labels_span_foundation_to_current():
    """PHASE 10 (docs/FUNCTIONAL_GAP_ANALYSIS.md H1): kronolojik olarak
    sıralı bir listeye deterministik aşama etiketleri atanır - ilk
    (en eski) FOUNDATION, son (en yeni) CURRENT olmalı."""
    from cyber_radar.digest import _learning_path_stage_labels

    papers = [{"id": i} for i in range(5)]  # zaten eskiden yeniye sıralı varsayılır
    labels = _learning_path_stage_labels(papers)
    assert len(labels) == 5
    assert labels[0] == "FOUNDATION"
    assert labels[-1] == "CURRENT"
    assert labels == sorted(labels, key=["FOUNDATION", "DEVELOPMENT", "MODERN_METHOD", "STATE_OF_THE_ART", "CURRENT"].index)


def test_learning_path_stage_labels_handles_fewer_than_five_papers():
    from cyber_radar.digest import _learning_path_stage_labels

    labels = _learning_path_stage_labels([{"id": 1}, {"id": 2}])
    assert len(labels) == 2
    assert labels[0] == "FOUNDATION"


def test_learning_path_stage_labels_empty_list():
    from cyber_radar.digest import _learning_path_stage_labels

    assert _learning_path_stage_labels([]) == []
