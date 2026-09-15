<!--
This is example output from `cyber-radar demo` - entirely synthetic
fixture data (see cyber_radar/cli/demo.py). No real news, papers, or
API calls were used to produce this file.
-->

# Cyber Intelligence Radar — Sabah Brifingi
_2026-09-15 18:36_

## 🚨 Aksiyon Gerekli
- **[CRITICAL · ACTION:HIGH] Example VPN vendor: actively exploited zero-day in appliance OS** (Global Severity: CRITICAL, My Relevance: HIGH, CVE: CVE-2026-0001)
  _A zero-day in a widely deployed VPN appliance OS is being actively exploited, allowing unauthenticated remote code execution on internet-facing devices._
  Etki: Affected appliances can be fully compromised remotely.
  Kurumsal etki: Internet-facing VPN appliances should be isolated or patched immediately.
  Kontrol et: Are you running the affected appliance OS version?
  CVE: CVE-2026-0001 (CVSS: 9.8)
  CWE: CWE-787
  KEV: Evet (CISA Known Exploited Vulnerabilities)
  Vendor/Product: ExampleVPN, ExampleOS
  Etkilenen sürümler: 9.0-9.2
  Düzeltilen sürüm: 9.3
  Tespit: VPN authentication log anomalies
  Aksiyon: Apply the emergency patch immediately.
  Hunt: `Unusual session establishment patterns in VPN logs outside business hours`
  MITRE ATT&CK: T1190
  IOC: IP: 203.0.113.10
  Event ID: 4625
  Splunk: index=vpn sourcetype=example_vpn_logs
  Wazuh: rule.group=authentication_failed
  Sigma: selection: EventID: 4625
----

## 🕵️ Hunt Fırsatı
- **Threat actor group uses novel PowerShell loader in phishing campaign** _[BACKFILL]_
  _A phishing campaign delivers a novel PowerShell-based loader that establishes C2 communication._
  Teknik: Phishing -> PowerShell loader -> C2
  Bakılacak loglar: Sysmon Event ID 1
  MITRE ATT&CK: T1059.001, T1566.001
  Süreç: powershell.exe
  Komut: `powershell.exe -enc SGVsbG8=`
  Hunt: `Processes spawning powershell.exe with -enc argument`
  Splunk: index=sysmon EventCode=1 CommandLine=*-enc*
  Wazuh: rule.id=61603
  Sigma: selection: CommandLine|contains: '-enc'
  SOC değeri: 8/10
----

## 📚 Öğretici
- **Detection Engineering 101: Writing Sigma Rules from ATT&CK Techniques**
  _A practical walkthrough of deriving Sigma detection rules directly from ATT&CK techniques._
----

## 👀 Farkındalık
- **Large retailer discloses breach affecting 2M customer records** _[BACKFILL]_
  _A large retailer disclosed a breach affecting approximately 2 million customer records._
----

## 🆕 5 Güncel Makale
_1 makale — her biri kendi butonlarıyla ayrı mesaj olarak gönderildi._

## 🧭 Temelden Güncele — Son 5 Yıl
_2 makale — her biri kendi butonlarıyla ayrı mesaj olarak gönderildi._

## 🏛️ Bugünün Klasiği / 📚 Geçmişten Öne Çıkanlar
_2 makale — her biri kendi butonlarıyla ayrı mesaj olarak gönderildi._

## 🔬 Research Profile A (1)
_1 paper — her biri kendi butonlarıyla ayrı mesaj olarak gönderildi._

## 🎓 Research Profile B (1)
_1 paper — her biri kendi butonlarıyla ayrı mesaj olarak gönderildi._

## 📚 Oku Şimdi — Bugünün Önerisi
_1 makale — her biri kendi butonlarıyla ayrı mesaj olarak gönderildi._

## NotebookLM İçin Güncellenen Dosyalar
_Aşağıdaki dosyaları ilgili NotebookLM notebook'unuza manuel yükleyin:_
- **SOC_SIEM**: `example-topic.md`


(8 interactive per-item messages follow - each would be its own Telegram message with feedback buttons)

--- [MUST_READ] ---
📚 Oku Şimdi

- [MUST_READ] [METHOD] **Graph Neural Networks for SOC Alert Triage** — ~25 dk (relevance: 92%)
  Neden: Directly applicable to SOC/threat-hunting work.
  _A GNN-based approach to SOC alert triage._
  Zorluk: 3/5 - Advanced
  Sana katkısı: SOC_SIEM 9/10
  Okuma sonrası sorular:
    1. How was the dataset collected?

--- [TIMELINE] ---
🧭 Temelden Güncele

- (2022) **Foundations of SIEM Correlation Rules** (relevance: 70%)
  _Foundational concepts in SIEM correlation rules._
  Öğrenme aşaması: FOUNDATION

--- [TIMELINE] ---
🧭 Temelden Güncele

- (2026) **LLM-Assisted Threat Hunting in Practice** (relevance: 85%)
  _Applying LLMs to practical threat hunting workflows._
  Öğrenme aşaması: MODERN_METHOD

--- [CLASSIC] ---
🏛️ Bugünün Klasiği

- **The STIX Standardization Paper** (relevance: 60%)
  Sana katkısı: Threat_Intelligence 9/10
  Historical score: 8.2/10 (atıf: 10, temel eser: 9, öğrenme değeri: 8)

--- [HISTORICAL] ---
📚 Geçmişten Öne Çıkanlar

- **An Early Survey of Intrusion Detection Approaches** (relevance: 50%)
  Historical score: 6.0/10

--- [RESEARCH_PROFILE_A] ---
🔬 Research Profile A

- **Example: Root-Cause Localization in Security Evidence Graphs**
  Relevance score: 9/10
  Why relevant: Directly addresses root-cause localization.
  Strongest dimensions: Alert triage relevance, Detection engineering relevance
  Practical takeaway: Graph-based localization could be piloted against our own alert graph.
  Tooling mentioned: Neo4j
  Research gap: Evaluation on multi-fault scenarios is limited.

--- [RESEARCH_PROFILE_B] ---
🎓 Research Profile B

- **Example: Reproducible Benchmarks for Applied Security Research**
  Relevance score: 8/10
  Why relevant: Directly relevant to reproducible security research methodology.
  Strongest dimensions: Methodology rigor, Reproducibility, Practical applicability
  Methodology summary: Introduces a reproducible benchmark harness for security detection methods.
  Dataset or benchmark: Public benchmark corpus (synthetic)
  Research gap: Limited coverage of adversarial evasion scenarios.

--- [READ_NOW] ---
📚 Oku Şimdi — Bugünün Önerisi

  _High relevance to your configured profile and not yet read (relevance: 91%)._

- [READ] **Example: A Practical Guide to Evidence-Grounded Explanations**
  _A practical guide to building evidence-grounded explanations._

