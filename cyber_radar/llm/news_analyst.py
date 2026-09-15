"""Level 3: Derin haber analizi + entity extraction.

Öncelik skoru (priority_score) bilinçli olarak LLM'e bırakılmadı - orijinal
mimari dokümanındaki sabit puan tablosu deterministik ve tutarlı olduğu için
klasik Python fonksiyonuyla hesaplanıyor (bkz. Tasarım İlkesi: "muhakeme
gerektirmeyen işler klasik servislere bırakılır"). LLM sadece CVE/aktör/
malware gibi entity'leri metinden çıkarmak için kullanılıyor.
"""
from __future__ import annotations

from .. import config
from .client import PROMPT_INJECTION_GUARD, call_json

_SYSTEM = """Sen bir siber tehdit istihbaratı analistisin. Görevin verilen
haberden yapılandırılmış bilgi çıkarmak.

ÖNEMLİ PRENSİP: Tek bir haber sitesinin iddiası doğrulanmış teknik gerçek
değildir. "active_exploitation" veya "zero_day" gibi alanları yalnızca metin
bunu AÇIKÇA belirtiyorsa true yap; metin belirsizse false bırak ve
"evidence_note" alanına neden emin olmadığını yaz.

Metinde belirtilmeyen bilgiyi uydurma; ilgili alanı boş liste veya null bırak.

Okuyucu profili: {keywords} konularıyla ilgilenen bir SOC/CTI/threat-intel
pratisyeni - "bu benim ortamımı ilgilendiriyor mu, ne yapmalıyım?" sorusuna
cevap arıyor.

ÖNEMLİ: "my_relevance", olayın nesnel ağırlığından (priority/severity) FARKLI
bir eksen. Örnek: "Fransız hastaneye 500.000€ KVKK cezası" orta şiddetli bir
olay olabilir ama bir SOC/threat-intel çalışanı için günlük işine doğrudan
uygulanabilir bir aksiyon içermez → my_relevance LOW olur (sadece farkındalık).
"Chrome sıfır gün açığı" ise hem şiddetli hem de doğrudan aksiyon (yama/expojur
kontrolü) gerektirir → my_relevance HIGH olur. Yani my_relevance ŞİDDET değil,
OKUYUCUNUN GÜNLÜK İŞİNE UYGULANABİLİRLİK ölçer.

Yalnızca şu şemada geçerli JSON döndür, başka hiçbir metin ekleme:
{{
  "summary": string,                // TÜRKÇE, 4-6 CÜMLE (kısa 1-2 cümlelik özet
                                     // YETERSİZ) - kim/ne yaptı, nasıl (teknik
                                     // mekanizma), hangi ürün/sürüm etkileniyor,
                                     // ne zaman/nerede tespit edildi, mevcut durum
                                     // (yama var mı, aktif istismar var mı) net
                                     // biçimde geçsin. Bu alan brifingde haberin
                                     // TEK açıklaması - okuyan kaynağa gitmeden
                                     // olayı gerçekten anlamalı.
  "event_type": string,             // VULNERABILITY|ZERO_DAY|MALWARE|RANSOMWARE|APT|DATA_BREACH|PHISHING|SUPPLY_CHAIN|diğer
  "vendors": [string],
  "products": [string],
  "cves": [string],
  "cwe": [string],
  "cvss_score": number | null,      // Metinde AÇIKÇA verilen CVSS taban puanı
                                     // (0.0-10.0) - metinde yoksa null, TAHMİN ETME
  "kev_related": boolean,           // Metin CISA KEV/"actively exploited"
                                     // listesine AÇIKÇA atıfta bulunuyor mu (gerçek
                                     // KEV üyeliği ayrıca deterministik kontrol
                                     // edilir - bkz. run_pipeline.py is_kev, BU alan
                                     // sadece metnin kendi iddiasını yansıtır)
  "affected_versions": [string],    // Metinde AÇIKÇA belirtilen etkilenen sürüm(ler)
  "fixed_versions": [string],       // Metinde AÇIKÇA belirtilen yama/düzeltme sürümü
  "exploit_status": string | null,  // "poc"|"active_exploitation"|"none_reported"|null
  "zero_day": boolean,
  "active_exploitation": boolean,
  "evidence_note": string | null,
  "malware": [string],
  "threat_actors": [string],
  "campaigns": [string],
  "target_sectors": [string],
  "target_countries": [string],
  "mitre_attack": [string],
  "attack_vector": string | null,
  "impact": string | null,
  "enterprise_impact": string | null,  // 2026-09-15: TEK cümle, TÜRKÇE - bir
                                     // kurumsal ortam (SOC/BT) için bu olayın
                                     // somut sonucu ne (ör. "Etkilenen VPN
                                     // cihazları internetten erişilebilirse
                                     // uzaktan kod çalıştırma riski taşır");
                                     // metinde yeterli detay yoksa null
  "mitigation": [string],
  "detection": [string],
  "my_relevance": string,           // "HIGH"|"MEDIUM"|"LOW" - yukarıdaki tanıma göre
  "exposure_check": string | null,  // TEK somut soru, TÜRKÇE: "X ürünü/versiyonu
                                     // kullanıyor musunuz?" tarzı - okuyucu bunu
                                     // okuyup kendi ortamını hemen kontrol edebilmeli
  "hunt_query": string | null,      // Metinde YETERLİ teknik detay varsa (süreç
                                     // zinciri, komut, IOC vb.) somut, kopyalanabilir
                                     // bir tehdit avı deseni (ör. "w3wp.exe -> cmd.exe
                                     // / powershell.exe"); yoksa null - uydurma
  "ioc": {{                         // Metinde GERÇEKTEN geçen indicator'lar - HER
                                     // alan boş liste olabilir, UYDURMA. Örnek bir
                                     // IP/domain/hash/URL/e-posta bulmak için metni
                                     // ZORLAMA.
    "ips": [string],
    "domains": [string],
    "hashes": [string],
    "urls": [string],
    "emails": [string]             // 2026-09-15: metinde geçen GERÇEK e-posta
                                     // adresi indicator'ları (ör. phishing
                                     // gönderen adresi) - yoksa boş liste.
  }},
  "process_names": [string],        // Metinde geçen GERÇEK süreç/dosya adları
                                     // (ör. "powershell.exe", "rundll32.exe")
  "command_lines": [string],        // Metinde GERÇEKTEN alıntılanan komut satırları
                                     // (kopyala-yapıştır edilebilir haliyle, uydurma)
  "file_paths": [string],           // 2026-09-15: metinde geçen GERÇEK dosya yolu
                                     // artifact'leri (ör. "C:\\Users\\Public\\x.exe") -
                                     // yoksa boş liste, uydurma.
  "registry_paths": [string],       // Metinde geçen GERÇEK Windows registry anahtar
                                     // yolları (ör. "HKCU\\Software\\...") - yoksa boş.
  "registry_artifacts": [string],   // Metinde geçen GERÇEK registry değer/veri
                                     // artifact'leri (anahtar yolunun kendisi DEĞİL,
                                     // içindeki değer adı/verisi) - yoksa boş.
  "services": [string],             // Metinde geçen GERÇEK Windows servis adları -
                                     // yoksa boş liste.
  "scheduled_tasks": [string],      // Metinde geçen GERÇEK zamanlanmış görev adları -
                                     // yoksa boş liste.
  "mutexes": [string],              // Metinde geçen GERÇEK mutex adları - yoksa boş.
  "user_agents": [string],          // Metinde geçen GERÇEK User-Agent string'leri -
                                     // yoksa boş liste.
  "event_ids": [string],            // Metinde geçen Windows Event ID / log kaynak
                                     // kimlikleri (ör. "4688", "Sysmon Event ID 1")
  "splunk_applicability": string | null,  // Metindeki teknik detay bir Splunk
                                     // SPL sorgusuna/arama fikrine dönüştürülebilirse
                                     // TEK cümlelik somut öneri; yeterli detay
                                     // yoksa null - uydurma
  "wazuh_applicability": string | null,   // Aynısı Wazuh kural fikri için -
                                     // yeterli detay yoksa null
  "sigma_applicability": string | null,   // 2026-09-15: Aynısı platform-bağımsız
                                     // bir Sigma kural fikri için (ör. "selection:
                                     // Image|endswith: '\\rundll32.exe'") - yeterli
                                     // detay yoksa null - uydurma
  "news_tier": string,              // Bu haberle okuyucu NE YAPMALI - beşten TAM
                                     // BİRİNİ seç:
                                     // "ACTION_REQUIRED" - gerçekten müdahale gerektiriyor
                                     //   (yama/expojur kontrolü/config değişikliği şart)
                                     // "HUNT_OPPORTUNITY" - doğrudan aksiyon şart değil ama
                                     //   metinde SOC'ta somut bir hunt/tespit sorgusu
                                     //   çıkarabilecek kadar teknik detay var
                                     // "LEARN" - aksiyon/hunt gerektirmiyor ama tekniği
                                     //   öğretici (yeni bir saldırı yöntemi/kavramı anlatıyor)
                                     // "AWARENESS" - sadece bilgi sahibi olunması yeterli
                                     //   (ceza, istatistik, genel duyuru gibi)
                                     // "ARCHIVE" - okuyucu için pratik değeri düşük
  "soc_value_score": number         // 0-10: bu haberin bir SOC/threat-intel
                                     // çalışanının GÜNLÜK İŞİNE (hunt/detection/response)
                                     // somut katkısı - my_relevance'a benzer ama burada
                                     // "ne kadar iş çıkarılabilir" ölçülüyor
}}""" + PROMPT_INJECTION_GUARD


# 2026-09-15 (madde 2 - "eksik IOC/hunt artifact alanlarını tamamla"):
# registry_paths/registry_artifacts, event_ids gibi TAM METİNLE eşleştirilebilir
# ("exact-match") alanlar olduğu için grounding'e eklendi. process_names/
# command_lines/file_paths/services/scheduled_tasks/mutexes/user_agents ise
# process_names/command_lines'la AYNI kategoride BIRAKILDI (mekanik substring
# eşleşmesi doğal formatlama farklarında - ör. tırnak/backslash kaçışı - yanlış
# pozitif üretebilir, bu yüzden BİLİNÇLİ OLARAK sadece prompt disipliniyle
# korunuyorlar, tıpkı process_names/command_lines gibi) - duplike bir kategori
# icat edilmedi, var olan ayrıma sadık kalındı.
_GROUNDED_LIST_FIELDS = ("cves", "cwe", "event_ids", "registry_paths", "registry_artifacts")
_GROUNDED_IOC_FIELDS = ("ips", "domains", "hashes", "urls", "emails")


def _ground_against_source(analysis: dict, raw_text: str) -> dict:
    """Hallucination/provenance guard (proje notları: "structured-source
    metadata ile LLM interpretation'ı ayır"). Prompt zaten "uydurma" diyor
    ama bu SADECE modele güvenmek anlamına gelir - burada MEKANİK bir
    ikinci kontrol var: CVE/CWE/Event ID/IOC/registry gibi YAPILANDIRILMIŞ,
    tam metinle EŞLEŞTİRİLEBİLİR alanlar, ham kaynak metinde (case-
    insensitive) GERÇEKTEN geçmiyorsa SESSİZCE ATILIR (uydurulmuş bir CVE/
    IOC asla digest'e/DB'ye yansımaz). Serbest metin yorum alanları
    (summary/impact/research_gap vb.) bu kontrolün KAPSAMI DIŞINDA -
    paraphrase/çeviri normal olduğu için literal substring eşleşmesi burada
    anlamsız/yanlış pozitif üretir, o alanlar prompt-seviyesi disiplinle
    (null-if-unsure) korunuyor."""
    haystack = (raw_text or "").lower()

    def _keep(values: list[str]) -> list[str]:
        return [v for v in values if v and str(v).lower() in haystack]

    for field in _GROUNDED_LIST_FIELDS:
        if analysis.get(field):
            analysis[field] = _keep(analysis[field])

    ioc = analysis.get("ioc")
    if isinstance(ioc, dict):
        for field in _GROUNDED_IOC_FIELDS:
            if ioc.get(field):
                ioc[field] = _keep(ioc[field])

    return analysis


def analyze_news(title: str, raw_text: str) -> dict:
    content = f"Başlık: {title}\n\nİçerik: {raw_text[:20000]}"
    system = _SYSTEM.format(keywords=", ".join(config.KEYWORDS) or "genel siber güvenlik")
    result = call_json(config.ANALYSIS_MODEL, system, content, max_output_tokens=3200)
    return _ground_against_source(result, raw_text)


# ---------------------------------------------------------------------------
# Deterministik öncelik skoru (bkz. proje notları bölüm 19)
# ---------------------------------------------------------------------------
_WEIGHTS = {
    "cisa_kev": 30,
    "active_exploitation": 25,
    "zero_day": 20,
    "remote_code_execution": 15,
    "authentication_bypass": 15,
    "ransomware_use": 15,
    "internet_facing": 10,
    "critical_infra": 10,
    # PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md C1/C2):
    "privilege_escalation": 10,
    "supply_chain_compromise": 10,
    "emergency_patch": 5,
    "high_value_vendor": 5,
}


def compute_priority(analysis: dict, cisa_kev: bool) -> tuple[int, str]:
    score = 0
    reasons: list[str] = []

    if cisa_kev:
        score += _WEIGHTS["cisa_kev"]
        reasons.append("CISA KEV")
    if analysis.get("active_exploitation"):
        score += _WEIGHTS["active_exploitation"]
        reasons.append("Active exploitation")
    if analysis.get("zero_day"):
        score += _WEIGHTS["zero_day"]
        reasons.append("Zero-day")

    impact_text = " ".join(
        [
            str(analysis.get("attack_vector") or ""),
            str(analysis.get("impact") or ""),
            str(analysis.get("enterprise_impact") or ""),
            str(analysis.get("event_type") or ""),
            " ".join(analysis.get("mitigation") or []),
        ]
    ).lower()

    if "remote code execution" in impact_text or "rce" in impact_text:
        score += _WEIGHTS["remote_code_execution"]
        reasons.append("Remote code execution")
    if "authentication bypass" in impact_text or "auth bypass" in impact_text:
        score += _WEIGHTS["authentication_bypass"]
        reasons.append("Authentication bypass")
    if analysis.get("event_type") == "RANSOMWARE" or "ransomware" in impact_text:
        score += _WEIGHTS["ransomware_use"]
        reasons.append("Ransomware")
    if any(s.lower() in ("critical infrastructure", "ics", "ot", "energy", "healthcare")
           for s in (analysis.get("target_sectors") or [])):
        score += _WEIGHTS["critical_infra"]
        reasons.append("Critical infrastructure impact")
    if "internet-facing" in impact_text or "internet facing" in impact_text or "publicly accessible" in impact_text:
        score += _WEIGHTS["internet_facing"]
        reasons.append("Internet-facing product")
    if "privilege escalation" in impact_text or "privesc" in impact_text:
        score += _WEIGHTS["privilege_escalation"]
        reasons.append("Privilege escalation")
    if "supply chain" in impact_text or "supply-chain" in impact_text:
        score += _WEIGHTS["supply_chain_compromise"]
        reasons.append("Supply-chain compromise")
    if "emergency patch" in impact_text or "emergency mitigation" in impact_text or "out-of-band patch" in impact_text:
        score += _WEIGHTS["emergency_patch"]
        reasons.append("Emergency patch/mitigation")

    named_products = " ".join((analysis.get("vendors") or []) + (analysis.get("products") or [])).lower()
    if any(v.lower() in named_products for v in config.HIGH_VALUE_VENDOR_KEYWORDS):
        score += _WEIGHTS["high_value_vendor"]
        reasons.append("High-value vendor/product")

    score = min(score, 100)

    if score >= 80:
        label = "CRITICAL"
    elif score >= 55:
        label = "HIGH"
    elif score >= 30:
        label = "MEDIUM"
    else:
        label = "LOW"

    return score, label
