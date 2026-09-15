"""`cyber-radar demo` - renders a full, realistic sample digest from fixed
example data. No API keys, no network, no database, no Telegram, no
Drive - safe to run in CI or right after `git clone`, before any
configuration at all. Exercises every digest section (Action/Hunt/
Tutorial/Awareness, Current/Timeline/Classic/Historical, Research Profile
A/B, and Oku Şimdi/"Read Now") so a new user can see the actual output
shape immediately.
"""
from __future__ import annotations

import argparse
import datetime
import sys


def _build_fixture_data():
    news_events = [
        {
            "id": 1, "title": "Example VPN vendor: actively exploited zero-day in appliance OS",
            "cves": ["CVE-2026-0001"], "cisa_kev": True, "priority_label": "CRITICAL",
            "_digest_source": "FRESH",
            "analysis": {
                "news_tier": "ACTION_REQUIRED", "my_relevance": "HIGH",
                "summary": "A zero-day in a widely deployed VPN appliance OS is being actively exploited, allowing unauthenticated remote code execution on internet-facing devices.",
                "impact": "Affected appliances can be fully compromised remotely.",
                "enterprise_impact": "Internet-facing VPN appliances should be isolated or patched immediately.",
                "exposure_check": "Are you running the affected appliance OS version?",
                "cvss_score": 9.8, "cwe": ["CWE-787"], "kev_related": True,
                "vendors": ["ExampleVPN"], "products": ["ExampleOS"],
                "affected_versions": ["9.0-9.2"], "fixed_versions": ["9.3"],
                "mitigation": ["Apply the emergency patch immediately."], "detection": ["VPN authentication log anomalies"],
                "hunt_query": "Unusual session establishment patterns in VPN logs outside business hours",
                "mitre_attack": ["T1190"], "event_ids": ["4625"],
                "ioc": {"ips": ["203.0.113.10"], "domains": [], "hashes": [], "urls": [], "emails": []},
                "splunk_applicability": "index=vpn sourcetype=example_vpn_logs",
                "wazuh_applicability": "rule.group=authentication_failed",
                "sigma_applicability": "selection: EventID: 4625",
            },
        },
        {
            "id": 2, "title": "Threat actor group uses novel PowerShell loader in phishing campaign",
            "cves": [], "cisa_kev": False, "priority_label": "MEDIUM",
            "_digest_source": "BACKFILL",
            "analysis": {
                "news_tier": "HUNT_OPPORTUNITY", "my_relevance": "HIGH",
                "summary": "A phishing campaign delivers a novel PowerShell-based loader that establishes C2 communication.",
                "attack_vector": "Phishing -> PowerShell loader -> C2",
                "detection": ["Sysmon Event ID 1"], "hunt_query": "Processes spawning powershell.exe with -enc argument",
                "mitre_attack": ["T1059.001", "T1566.001"],
                "process_names": ["powershell.exe"], "command_lines": ["powershell.exe -enc SGVsbG8="],
                "soc_value_score": 8,
                "splunk_applicability": "index=sysmon EventCode=1 CommandLine=*-enc*",
                "wazuh_applicability": "rule.id=61603",
                "sigma_applicability": "selection: CommandLine|contains: '-enc'",
            },
        },
        {
            "id": 3, "title": "Detection Engineering 101: Writing Sigma Rules from ATT&CK Techniques",
            "cves": [], "cisa_kev": False, "priority_label": "LOW", "_digest_source": "FRESH",
            "analysis": {"news_tier": "LEARN", "my_relevance": "MEDIUM", "summary": "A practical walkthrough of deriving Sigma detection rules directly from ATT&CK techniques."},
        },
        {
            "id": 4, "title": "Large retailer discloses breach affecting 2M customer records",
            "cves": [], "cisa_kev": False, "priority_label": "MEDIUM", "_digest_source": "BACKFILL",
            "analysis": {"news_tier": "AWARENESS", "my_relevance": "LOW", "summary": "A large retailer disclosed a breach affecting approximately 2 million customer records."},
        },
    ]

    current_papers = [
        {
            "id": 101, "title": "Graph Neural Networks for SOC Alert Triage", "publication_date": None,
            "relevance": {"confidence": 0.92}, "_digest_source": "FRESH",
            "analysis": {
                "novelty_score": 8, "academic_value_score": 7, "turkish_summary": "A GNN-based approach to SOC alert triage.",
                "reading_priority": "MUST_READ", "why_read": "Directly applicable to SOC/threat-hunting work.",
                "domain_contribution_scores": {"SOC_SIEM": 9}, "paper_role": ["METHOD"],
                "difficulty_score": 3, "difficulty_label": "Advanced", "estimated_reading_minutes": 25,
                "post_reading_questions": ["How was the dataset collected?"],
            },
        },
    ]
    learning_path_papers = [
        {"id": 201, "title": "Foundations of SIEM Correlation Rules", "publication_date": datetime.date(2022, 3, 1), "relevance": {"confidence": 0.7}, "analysis": {"turkish_summary": "Foundational concepts in SIEM correlation rules."}},
        {"id": 202, "title": "LLM-Assisted Threat Hunting in Practice", "publication_date": datetime.date(2026, 6, 1), "relevance": {"confidence": 0.85}, "analysis": {"turkish_summary": "Applying LLMs to practical threat hunting workflows."}},
    ]
    historical_papers = [
        {"id": 301, "title": "The STIX Standardization Paper", "cited_by_count": 1500, "analysis": {"foundational_value_score": 9, "educational_value_score": 8, "domain_contribution_scores": {"Threat_Intelligence": 9}}, "relevance": {"confidence": 0.6}},
        {"id": 302, "title": "An Early Survey of Intrusion Detection Approaches", "cited_by_count": 300, "analysis": {"foundational_value_score": 6, "educational_value_score": 7}, "relevance": {"confidence": 0.5}},
    ]

    profile_a_papers = [
        {
            "id": 401, "title": "Example: Root-Cause Localization in Security Evidence Graphs",
            "analysis": {
                "profile_extraction_status": "valid",
                "profile_extraction": {
                    "relevance_score": 9, "why_relevant": "Directly addresses root-cause localization.",
                    "relevance_dimensions": {"alert_triage_relevance": 7, "detection_engineering_relevance": 9, "automation_relevance": 3},
                    "digest_bridge": {
                        "practical_takeaway": "Graph-based localization could be piloted against our own alert graph.",
                        "tooling_mentioned": "Neo4j",
                        "research_gap": "Evaluation on multi-fault scenarios is limited.",
                    },
                },
            },
        },
    ]
    profile_b_papers = [
        {
            "id": 501, "title": "Example: Reproducible Benchmarks for Applied Security Research",
            "analysis": {
                "profile_extraction_status": "valid",
                "profile_extraction": {
                    "relevance_score": 8, "why_relevant": "Directly relevant to reproducible security research methodology.",
                    "relevance_dimensions": {"methodology_rigor": 9, "reproducibility": 8, "novelty": 5, "practical_applicability": 6},
                    "digest_bridge": {
                        "methodology_summary": "Introduces a reproducible benchmark harness for security detection methods.",
                        "dataset_or_benchmark": "Public benchmark corpus (synthetic)",
                        "research_gap": "Limited coverage of adversarial evasion scenarios.",
                    },
                },
            },
        },
    ]
    read_now = {
        "id": 601, "title": "Example: A Practical Guide to Evidence-Grounded Explanations",
        "_read_now_reason": "High relevance to your configured profile and not yet read (relevance: 91%).",
        "analysis": {"turkish_summary": "A practical guide to building evidence-grounded explanations.", "reading_priority": "READ"},
    }
    return dict(
        news_events=news_events, current_papers=current_papers, learning_path_papers=learning_path_papers,
        historical_papers=historical_papers, profile_a_papers=profile_a_papers, profile_b_papers=profile_b_papers,
        read_now=read_now,
    )


def run_demo() -> tuple[str, list]:
    from .. import digest

    data = _build_fixture_data()
    brief = digest.generate_brief(
        data["news_events"], data["current_papers"], data["historical_papers"], {"SOC_SIEM": ["example-topic.md"]},
        "Sabah", learning_path_papers=data["learning_path_papers"], profile_a_papers=data["profile_a_papers"],
        profile_b_papers=data["profile_b_papers"], read_now=data["read_now"],
    )
    cards = digest.build_all_paper_cards(
        data["current_papers"], data["learning_path_papers"], data["historical_papers"],
        data["profile_a_papers"], data["profile_b_papers"], read_now=data["read_now"],
    )
    return brief, cards


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cyber-radar demo")
    parser.add_argument("--cards-only", action="store_true", help="Only print the interactive per-item cards")
    args = parser.parse_args(argv)

    brief, cards = run_demo()
    if not args.cards_only:
        print(brief)
        print()
        print(f"({len(cards)} interactive per-item messages follow - each would be its own Telegram message with feedback buttons)")
        print()
    for c in cards:
        print(f"--- [{c.category}] ---")
        print(c.text)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
