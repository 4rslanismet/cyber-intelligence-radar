"""Haber teknik zenginleştirme (bkz. src/llm/news_analyst.py şema
genişletmesi: cvss_score/kev_related/affected_versions/fixed_versions/ioc/
process_names/command_lines/event_ids/splunk_applicability/
wazuh_applicability) ve src/digest.py render fonksiyonları
(_technical_block/_mitre_ioc_block/_detection_tooling_block). Saf fonksiyon
testleri - gerçek Gemini/ağ çağrısı YOK. Veri yoksa hiçbir satır
UYDURULMAMALI."""
from __future__ import annotations

from cyber_radar.digest import _detection_tooling_block, _hunt_block, _mitre_ioc_block, _so_what_block, _technical_block


def test_technical_block_renders_only_present_fields():
    n = {
        "cves": ["CVE-2026-1234"],
        "cisa_kev": True,
        "analysis": {
            "cvss_score": 9.8,
            "vendors": ["Microsoft"],
            "products": ["Exchange Server"],
            "affected_versions": ["2019 CU12"],
            "fixed_versions": ["2019 CU13"],
        },
    }
    lines = "\n".join(_technical_block(n))
    assert "CVE-2026-1234" in lines
    assert "9.8" in lines
    assert "KEV: Evet" in lines
    assert "Microsoft" in lines and "Exchange Server" in lines
    assert "2019 CU12" in lines and "2019 CU13" in lines


def test_technical_block_empty_when_no_data():
    """Veri yoksa HİÇBİR satır uydurulmamalı - boş liste dönmeli."""
    assert _technical_block({"cves": [], "analysis": {}}) == []


def test_technical_block_omits_cvss_when_not_present_but_shows_cve():
    n = {"cves": ["CVE-2026-9999"], "analysis": {}}
    lines = "\n".join(_technical_block(n))
    assert "CVE-2026-9999" in lines
    assert "CVSS" not in lines  # uydurulmadı


def test_mitre_ioc_block_renders_ioc_and_process_and_event_id():
    n = {
        "analysis": {
            "mitre_attack": ["T1059.001"],
            "ioc": {"ips": ["1.2.3.4"], "domains": ["evil.example"], "hashes": [], "urls": []},
            "process_names": ["powershell.exe"],
            "command_lines": ["powershell -enc ..."],
            "event_ids": ["4688"],
        }
    }
    lines = "\n".join(_mitre_ioc_block(n))
    assert "T1059.001" in lines
    assert "1.2.3.4" in lines and "evil.example" in lines
    assert "powershell.exe" in lines
    assert "4688" in lines


def test_mitre_ioc_block_empty_when_nothing_present():
    assert _mitre_ioc_block({"analysis": {}}) == []


def test_detection_tooling_block_shows_splunk_and_wazuh_only_if_present():
    assert _detection_tooling_block({"analysis": {}}) == []
    lines = "\n".join(_detection_tooling_block({"analysis": {"splunk_applicability": "index=win EventCode=4688"}}))
    assert "Splunk" in lines
    assert "Wazuh" not in lines


def test_so_what_block_includes_technical_and_ioc_enrichment():
    n = {
        "cves": ["CVE-2026-1111"],
        "analysis": {
            "impact": "RCE riski.",
            "cvss_score": 8.1,
            "ioc": {"ips": ["9.9.9.9"], "domains": [], "hashes": [], "urls": []},
            "splunk_applicability": "index=proxy dest_ip=9.9.9.9",
        },
    }
    text = "\n".join(_so_what_block(n))
    assert "CVE-2026-1111" in text
    assert "8.1" in text
    assert "9.9.9.9" in text
    assert "index=proxy" in text


def test_hunt_block_includes_mitre_ioc_and_wazuh():
    n = {
        "analysis": {
            "attack_vector": "Phishing eki.",
            "mitre_attack": ["T1566.001"],
            "ioc": {"ips": [], "domains": [], "hashes": ["deadbeef"], "urls": []},
            "wazuh_applicability": "rule_id 100500 önerisi",
        }
    }
    text = "\n".join(_hunt_block(n))
    assert "T1566.001" in text
    assert "deadbeef" in text
    assert "rule_id 100500" in text
