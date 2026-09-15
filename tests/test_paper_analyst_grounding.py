"""Hallucination/provenance guard - paper_analyst.analyze_paper'ın
"must_see" (Figure/Table/Algorithm referansları) alanı FULL_TEXT'te
GERÇEKTEN geçmiyorsa mekanik olarak atılır. Gerçek Gemini çağrısı YOK -
call_json mock'lanır."""
from __future__ import annotations

from unittest.mock import patch

from cyber_radar.llm import paper_analyst

_BASE_RESPONSE = {
    "research_problem": None, "objective": None, "contributions": [], "methodology": None,
    "datasets": [], "tools": [], "models": [], "baselines": [], "metrics": [], "key_results": [],
    "limitations": [], "future_work": [], "research_gap": [], "potential_research_ideas": [],
    "code_repository": None, "novelty_score": 5, "academic_value_score": 5, "reproducibility": None,
    "turkish_summary": "özet", "paper_type": "EXPERIMENTAL", "reading_priority": "READ", "why_read": None,
    "foundational_value_score": 0, "educational_value_score": 0, "reading_guide": [],
    "prerequisites": [], "difficulty_score": 2, "difficulty_label": "Intermediate",
    "technical_depth_score": 2, "math_intensity_score": 1, "implementation_value_score": 1,
    "domain_contribution_scores": {}, "paper_role": [], "foundation_for": [],
    "post_reading_questions": [], "explain_to_analyst_prompt": None, "practical_application": None,
}


def test_must_see_hallucinated_reference_is_dropped_when_not_in_full_text():
    full_text = "Bu makalede Figure 2 ve Table 1 ile bulgular sunulmaktadır."
    response = dict(_BASE_RESPONSE, must_see=["Figure 2", "Figure 99"])  # Figure 99 UYDURULMUŞ
    with patch("cyber_radar.llm.paper_analyst.call_json", return_value=dict(response)):
        result = paper_analyst.analyze_paper("T", "abstract", full_text, "FULL_TEXT")
    assert result["must_see"] == ["Figure 2"]


def test_must_see_all_grounded_kept_intact():
    full_text = "Figure 1, Figure 2 ve Table 3 metinde geçiyor."
    response = dict(_BASE_RESPONSE, must_see=["Figure 1", "Table 3"])
    with patch("cyber_radar.llm.paper_analyst.call_json", return_value=dict(response)):
        result = paper_analyst.analyze_paper("T", "abstract", full_text, "FULL_TEXT")
    assert result["must_see"] == ["Figure 1", "Table 3"]


def test_must_see_guard_skipped_when_no_full_text():
    """ABSTRACT_ONLY'de full_text yok - guard hiç ÇALIŞMAZ (must_see zaten
    prompt kuralınca [] olmalı, guard'ın burada bir işi yok, crash da
    etmemeli)."""
    response = dict(_BASE_RESPONSE, must_see=[])
    with patch("cyber_radar.llm.paper_analyst.call_json", return_value=dict(response)):
        result = paper_analyst.analyze_paper("T", "abstract", None, "ABSTRACT_ONLY")
    assert result["must_see"] == []


def test_abstract_only_mechanically_clears_reading_guide_and_must_see_even_if_model_misbehaves():
    """PHASE 10 (docs/FUNCTIONAL_GAP_ANALYSIS.md P1): prompt "ABSTRACT_ONLY'de
    [] doldur" der ama BUNA TEK BAŞINA GÜVENİLMEZ (bkz. must_see FULL_TEXT
    grounding guard'ıyla AYNI ilke) - model bir regresyonla uydurma figür/
    bölüm döndürse bile mekanik olarak temizlenir."""
    response = dict(
        _BASE_RESPONSE,
        reading_guide=[{"section": "Uydurma Bölüm 3.2", "action": "READ"}],
        must_see=["Uydurma Figure 7"],
    )
    with patch("cyber_radar.llm.paper_analyst.call_json", return_value=dict(response)):
        result = paper_analyst.analyze_paper("T", "abstract", None, "ABSTRACT_ONLY")
    assert result["reading_guide"] == []
    assert result["must_see"] == []


def test_full_text_reading_guide_is_not_touched_by_abstract_only_guard():
    full_text = "Section 1 ve Section 2 metinde geçiyor."
    response = dict(_BASE_RESPONSE, reading_guide=[{"section": "Section 1", "action": "READ"}], must_see=["Section 1"])
    with patch("cyber_radar.llm.paper_analyst.call_json", return_value=dict(response)):
        result = paper_analyst.analyze_paper("T", "abstract", full_text, "FULL_TEXT")
    assert result["reading_guide"] == [{"section": "Section 1", "action": "READ"}]
    assert result["must_see"] == ["Section 1"]
