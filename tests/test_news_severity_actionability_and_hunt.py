"""2026-09-14 kök neden raporu:
  - madde 4 (Hunt Fırsatı neden sürekli boş?) - "aktif exploit var ama
    doğrulanabilir artifact yok" ile "bu dönem hiç exploit haberi yok"
    ayrımı.
  - madde 5 (Severity ile Actionability karışıyor mu?) - iki alan zaten
    BAĞIMSIZ (priority_label=Global Severity, analysis.my_relevance=
    operasyonel önem); bu testler SADECE render/etiketleme davranışını
    doğrular, ranking/seçim mantığına DOKUNULMADI.
Gerçek ağ/Gemini/DB çağrısı YOK - saf digest.generate_brief() render testi."""
from __future__ import annotations

from cyber_radar import digest


def _news(title, priority_label, news_tier, my_relevance, cisa_kev=False, cves=None, hunt_query=None):
    return {
        "title": title,
        "priority_label": priority_label,
        "cisa_kev": cisa_kev,
        "cves": cves or [],
        "analysis": {
            "news_tier": news_tier,
            "my_relevance": my_relevance,
            "summary": "test özeti",
            "hunt_query": hunt_query,
        },
    }


# ---------------------------------------------------------------------------
# Madde 5: Severity ≠ Actionability
# ---------------------------------------------------------------------------
def test_action_required_tag_shows_both_when_severity_and_relevance_differ():
    """Canlı örnek: '[LOW] Fake IT Calls Target Executives...' ama 🚨 Aksiyon
    Gerekli altında - severity LOW, operasyonel önem HIGH olduğu için
    oradaydı (BUG DEĞİL, news_tier() bilinçli olarak ikisinden birini
    yeterli sayıyor). Etiket artık ikisini de göstersin."""
    brief = digest.generate_brief(
        [_news("Fake IT Calls Target Executives", "LOW", "ACTION_REQUIRED", "HIGH")], [], [], {}, "Sabah"
    )
    assert "[LOW · ACTION:HIGH]" in brief
    assert "Global Severity: LOW" in brief
    assert "My Relevance: HIGH" in brief


def test_action_required_tag_stays_simple_when_severity_and_relevance_match():
    brief = digest.generate_brief(
        [_news("Critical RCE in the wild", "HIGH", "ACTION_REQUIRED", "HIGH")], [], [], {}, "Sabah"
    )
    assert "[HIGH]" in brief
    assert "ACTION:" not in brief


def test_ranking_selection_unchanged_low_severity_high_relevance_still_action_required():
    """Ranking/seçim mantığına DOKUNULMADI kontrolü - news_tier() hâlâ
    my_relevance=HIGH tek başına yeterli sayıyor."""
    assert digest.news_tier(_news("x", "LOW", None, "HIGH")) == "ACTION_REQUIRED"


# ---------------------------------------------------------------------------
# Madde 4: Hunt Fırsatı - verified-artifact kuralı
# ---------------------------------------------------------------------------
def test_hunt_section_explains_missing_artifact_when_active_exploit_has_no_hunt_query():
    n = _news("Actively exploited vendor flaw", "HIGH", "ACTION_REQUIRED", "MEDIUM", cisa_kev=True, cves=["CVE-2026-0001"])
    brief = digest.generate_brief([n], [], [], {}, "Sabah")
    assert "1 aktif exploit haberi bulundu" in brief
    assert "doğrulanabilir IOC/process/command-line artifact olmadığından otomatik hunt sorgusu üretilmedi" in brief
    # Uydurma YOK: gerçek bir hunt_query hâlâ basılmıyor.
    assert "Hunt: `" not in brief


def test_hunt_section_counts_multiple_active_exploit_items_without_artifact():
    news_items = [
        _news("Exploit 1", "HIGH", "ACTION_REQUIRED", "MEDIUM", cisa_kev=True),
        _news("Exploit 2", "HIGH", "ACTION_REQUIRED", "MEDIUM", cisa_kev=True),
    ]
    brief = digest.generate_brief(news_items, [], [], {}, "Sabah")
    assert "2 aktif exploit haberi bulundu" in brief


def test_hunt_section_generic_message_when_nothing_exploit_related_at_all():
    n = _news("Genel farkındalık haberi", "LOW", "AWARENESS", "LOW")
    brief = digest.generate_brief([n], [], [], {}, "Sabah")
    assert "somut bir hunt deseni çıkarılabilecek haber yok" in brief
    assert "aktif exploit haberi bulundu" not in brief


def test_hunt_section_shows_real_query_when_verified_artifact_exists():
    n = _news("Teknik detaylı saldırı", "MEDIUM", "HUNT_OPPORTUNITY", "MEDIUM", hunt_query="w3wp.exe -> cmd.exe")
    brief = digest.generate_brief([n], [], [], {}, "Sabah")
    assert "w3wp.exe -> cmd.exe" in brief
    assert "aktif exploit haberi bulundu" not in brief
