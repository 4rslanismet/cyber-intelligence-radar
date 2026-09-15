"""Hallucination/provenance guard (bkz. src/llm/news_analyst.
_ground_against_source) - LLM'in kaynak metinde GERÇEKTEN olmayan CVE/CWE/
Event ID/IOC üretmesine karşı MEKANİK bir ikinci kontrol. Saf fonksiyon
testleri, gerçek Gemini çağrısı YOK."""
from __future__ import annotations

from cyber_radar.llm.news_analyst import _ground_against_source


def test_drops_hallucinated_cve_not_present_in_source_text():
    raw_text = "Bu haberde CVE-2026-1111 hakkında detaylar var."
    analysis = {"cves": ["CVE-2026-1111", "CVE-2026-9999"]}  # 9999 UYDURULMUŞ
    result = _ground_against_source(analysis, raw_text)
    assert result["cves"] == ["CVE-2026-1111"]


def test_drops_hallucinated_ioc_ip_not_in_source():
    raw_text = "Saldırgan 1.2.3.4 adresinden bağlandı."
    analysis = {"ioc": {"ips": ["1.2.3.4", "9.9.9.9"], "domains": [], "hashes": [], "urls": []}}
    result = _ground_against_source(analysis, raw_text)
    assert result["ioc"]["ips"] == ["1.2.3.4"]


def test_keeps_all_values_when_all_grounded():
    raw_text = "CVE-2026-2222 ve CWE-79 ile ilişkili XSS zafiyeti."
    analysis = {"cves": ["CVE-2026-2222"], "cwe": ["CWE-79"]}
    result = _ground_against_source(analysis, raw_text)
    assert result["cves"] == ["CVE-2026-2222"]
    assert result["cwe"] == ["CWE-79"]


def test_case_insensitive_matching():
    raw_text = "domain evil.example kötü amaçlı."
    analysis = {"ioc": {"ips": [], "domains": ["EVIL.EXAMPLE"], "hashes": [], "urls": []}}
    result = _ground_against_source(analysis, raw_text)
    assert result["ioc"]["domains"] == ["EVIL.EXAMPLE"]


def test_does_not_crash_when_fields_missing():
    assert _ground_against_source({}, "herhangi bir metin") == {}


def test_does_not_crash_when_ioc_is_not_a_dict():
    """Model şemayı bozup ioc'yi string dönerse guard ÇÖKMEMELİ."""
    analysis = {"ioc": "beklenmedik string"}
    result = _ground_against_source(analysis, "metin")
    assert result["ioc"] == "beklenmedik string"  # dokunulmadı, ama crash da etmedi


def test_event_ids_are_grounded_too():
    raw_text = "Sysmon Event ID 1 sürecinde tetiklendi."
    analysis = {"event_ids": ["1", "4688"]}
    result = _ground_against_source(analysis, raw_text)
    assert "1" in result["event_ids"]
    assert "4688" not in result["event_ids"]
