"""PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md B2/B5/B6/B8/C1/C2):
haber teknik enrichment - enterprise_impact/sigma_applicability alanları,
registry/servis/mutex/user-agent/e-posta artifact'lerinin digest'te
görünürlüğü, ve compute_priority()'nin privilege-escalation/supply-chain/
emergency-patch/high-value-vendor sinyalleri. Gerçek LLM/ağ çağrısı YOK."""
from __future__ import annotations

from cyber_radar import digest
from cyber_radar.llm.news_analyst import compute_priority


def test_priority_weights_privilege_escalation():
    analysis = {"impact": "Allows local privilege escalation to SYSTEM."}
    score, _ = compute_priority(analysis, cisa_kev=False)
    assert score >= 10


def test_priority_weights_supply_chain_compromise():
    analysis = {"impact": "A supply chain compromise affecting downstream packages."}
    score, _ = compute_priority(analysis, cisa_kev=False)
    assert score >= 10


def test_priority_weights_emergency_patch():
    analysis = {"mitigation": ["Apply the emergency patch immediately."]}
    score, _ = compute_priority(analysis, cisa_kev=False)
    assert score >= 5


def test_priority_weights_high_value_vendor():
    analysis = {"vendors": ["Fortinet"], "products": ["FortiOS"]}
    score, _ = compute_priority(analysis, cisa_kev=False)
    assert score >= 5


def test_priority_no_bonus_for_unlisted_vendor():
    analysis = {"vendors": ["SomeNicheVendor"], "products": ["ObscureTool"]}
    score, _ = compute_priority(analysis, cisa_kev=False)
    assert score == 0


def test_priority_high_value_vendor_matching_is_case_insensitive():
    analysis = {"vendors": ["microsoft"], "products": []}
    score, _ = compute_priority(analysis, cisa_kev=False)
    assert score >= 5


def _news(analysis: dict) -> dict:
    return {"id": 1, "title": "Test", "cves": [], "cisa_kev": False, "analysis": analysis}


def test_so_what_block_renders_enterprise_impact():
    lines = digest._so_what_block(_news({"enterprise_impact": "VPN cihazları RCE riski taşıyor."}))
    assert any("Kurumsal etki: VPN cihazları RCE riski taşıyor." in l for l in lines)


def test_so_what_block_omits_enterprise_impact_when_absent():
    lines = digest._so_what_block(_news({}))
    assert not any("Kurumsal etki" in l for l in lines)


def test_detection_tooling_block_renders_sigma():
    lines = digest._detection_tooling_block(_news({"sigma_applicability": "selection: Image|endswith: '\\rundll32.exe'"}))
    assert any("Sigma:" in l for l in lines)


def test_detection_tooling_block_omits_sigma_when_absent():
    lines = digest._detection_tooling_block(_news({}))
    assert not any("Sigma:" in l for l in lines)


def test_mitre_ioc_block_renders_email_ioc():
    lines = digest._mitre_ioc_block(_news({"ioc": {"emails": ["phisher@evil.example"]}}))
    assert any("E-posta: phisher@evil.example" in l for l in lines)


def test_mitre_ioc_block_renders_registry_and_service_artifacts():
    lines = digest._mitre_ioc_block(_news({
        "registry_paths": ["HKCU\\Software\\Evil"],
        "registry_artifacts": ["RunOnce value"],
        "services": ["EvilSvc"],
        "scheduled_tasks": ["UpdaterTask"],
        "mutexes": ["Global\\EvilMutex"],
        "user_agents": ["EvilBot/1.0"],
    }))
    text = "\n".join(lines)
    assert "HKCU\\Software\\Evil" in text
    assert "RunOnce value" in text
    assert "EvilSvc" in text
    assert "UpdaterTask" in text
    assert "Global\\EvilMutex" in text
    assert "EvilBot/1.0" in text


def test_mitre_ioc_block_omits_all_new_artifacts_when_absent():
    lines = digest._mitre_ioc_block(_news({}))
    assert lines == []
