"""Level 3-4: Derin makale analizi.

Orijinal mimarideki Paper Analyst Agent + Research Agent'ı tek bir güçlü model
çağrısında birleştiriyoruz (tek sunucuda her makale için 2 ayrı reasoning
çağrısı yapmak maliyeti gereksiz yere ikiye katlar; alanlar yeterince
ayrıştırılmış olduğu için tek çağrı pratikte yeterli sonuç verir).

full_text verilirse (PDF çözüldüyse) ona öncelik verilir; verilmezse yalnızca
abstract ile ABSTRACT_ONLY seviyesinde analiz yapılır - bu durum modele açıkça
belirtilir ki alanları abstract'tan uydurmasın.
"""
from __future__ import annotations

from .. import config
from ..research.extraction_schema import to_prompt_text, validate as validate_extraction
from .client import PROMPT_INJECTION_GUARD, call_json

_SYSTEM = """Sen bir siber güvenlik akademik makale analistisin. Görevin verilen
makaleden yapılandırılmış bilgi çıkarmak VE okuyucunun "bunu gerçekten okumalı
mıyım?" sorusunu cevaplamak.

Okuyucu profili: {keywords} konularıyla ilgilenen bir SOC/CTI/threat-intel
pratisyeni - akademisyen değil, günlük operasyonuna/araştırmasına doğrudan
uygulayabileceği şeyi arıyor.

KURAL: Metinde açıkça belirtilmeyen hiçbir bilgiyi uydurma. Bir alan için bilgi
yoksa o alanı boş liste ([]) ya da null bırak, tahmin üretme.

ÖNEMLİ: "reading_priority" ve "why_read", "novelty_score"dan TAMAMEN BAĞIMSIZ
değerlendirilmeli. Eski/klasik bir STIX standardizasyon makalesi veya bir
survey'in novelty_score'u 0 olabilir - ama okuyucu bu alana yeniyse veya bir
temel kavramı öğrenmesi gerekiyorsa reading_priority yine de MUST_READ olabilir.
"Bu makale yeni bir şey mi buluyor?" ile "Bu okuyucu bunu okumalı mı?" FARKLI
sorulardır.

Yalnızca şu şemada geçerli JSON döndür, başka hiçbir metin ekleme:
{{
  "research_problem": string | null,
  "objective": string | null,
  "contributions": [string],
  "methodology": string | null,
  "datasets": [string],
  "tools": [string],
  "models": [string],
  "baselines": [string],
  "metrics": [string],
  "key_results": [string],
  "limitations": [string],
  "future_work": [string],
  "research_gap": [string],
  "potential_research_ideas": [string],
  "code_repository": string | null,
  "novelty_score": number,          // 0-10, sadece metinden çıkarılabiliyorsa
  "academic_value_score": number,   // 0-10
  "reproducibility": string | null, // "high" | "medium" | "low" | null
  "turkish_summary": string,        // TÜRKÇE, 3-5 cümle. Brifingde okuyacak kişi
                                     // makaleyi açmayacak - bu alan tek başına yeterli
                                     // olmalı: (1) makale ne problemi ele alıyor/amacı ne
                                     // (özet/abstract'tan), (2) FULL_TEXT ise sonuç/bulgu
                                     // (key_results/conclusion) kısmından somut bulgular,
                                     // ABSTRACT_ONLY ise özetten çıkarılabilen kadarı.
                                     // Metinde olmayan sayı/oran/iddia uydurma.
  "paper_type": string,             // "SURVEY"|"SYSTEM"|"EXPERIMENTAL"|"DATASET"|
                                     // "BENCHMARK"|"FRAMEWORK"|"CONCEPTUAL"|"CASE_STUDY"
  "reading_priority": string,       // "MUST_READ"|"READ"|"SKIM"|"SAVE"|"IGNORE" -
                                     // yukarıdaki okuyucu profiline göre PRATİK okuma
                                     // değeri, novelty_score'dan bağımsız (yukarı bak)
  "why_read": string | null,        // TEK cümle, TÜRKÇE: bu okuyucu NEDEN bu makaleyi
                                     // okumalı (ör. "SOC tarafında CTI verisinin knowledge
                                     // graph'a nasıl dönüştürülebileceğini gösterdiği için")
  "foundational_value_score": number, // 0-10: bu çalışma alanında hâlâ referans
                                       // gösterilen TEMEL bir çalışma mı - yeni olmasından
                                       // bağımsız (STIX'in ilk standardizasyon makalesi gibi)
  "educational_value_score": number,  // 0-10: bunu okuyan biri konuyu ÖĞRENMEK için ne
                                       // kadar değer kazanır - klasik/survey makaleler
                                       // burada yüksek çıkabilir, novelty düşük olsa da
  "reading_guide": [{{"section": string, "action": string}}],
                                     // YALNIZCA FULL_TEXT ise doldur (metindeki GERÇEK
                                     // bölüm başlıklarını kullan, uydurma). action:
                                     // "READ"|"SKIM"|"SKIP"|"SAVE". ABSTRACT_ONLY ise []
  "must_see": [string],             // YALNIZCA FULL_TEXT ise: metinde GERÇEKTEN var olan,
                                     // atlanmaması gereken spesifik referanslar (ör.
                                     // "Section 3.2", "Table 3", "Figure 5") - uydurma,
                                     // yoksa []. ABSTRACT_ONLY ise []
  "prerequisites": [{{"topic": string, "importance": string}}],
                                     // Bu makaleyi anlamak için okuyucunun önceden bilmesi
                                     // gereken kavramlar. importance: "essential" (bilmeden
                                     // anlaşılmaz) | "helpful" (bilmeden de okunur ama yardımcı
                                     // olur). Metinden/konudan makul şekilde çıkarılabilir,
                                     // bu alan için "uydurma yok" kuralı gevşek - genel bilinen
                                     // ön koşul kavramları önerebilirsin (ör. "STIX/TAXII",
                                     // "Graph Neural Networks")
  "difficulty_score": number,       // 1-5: 1=Beginner, 2=Intermediate, 3=Advanced,
                                     // 4-5=Research-heavy (bkz. difficulty_label)
  "difficulty_label": string,       // "Beginner"|"Intermediate"|"Advanced"|"Research-heavy"
  "technical_depth_score": number,  // 0-5: teorik/teknik derinlik
  "math_intensity_score": number,   // 0-5: matematiksel/formal yoğunluk
  "implementation_value_score": number, // 0-5: doğrudan uygulanabilir/koda dökülebilir mi
  "domain_contribution_scores": {{  // Aşağıdaki HER anahtar için 0-10 (ilgisizse 0):
    {domain_keys}
  }},
  "paper_role": [string],           // Bu makale İLERİDE nasıl kullanılır - paper_type'tan
                                     // FARKLI bir soru ("ne tür bir çalışma" değil, "sana ne
                                     // işe yarayacak"). Birden fazla olabilir. Değerler:
                                     // "FOUNDATION"|"SURVEY"|"METHOD"|"DATASET"|"BENCHMARK"|
                                     // "IMPLEMENTATION"|"REFERENCE"|"RESEARCH_GAP_SOURCE"
                                     // (ör. "Bana CTI'de foundation paper getir" diye
                                     // sorgulanabilmesi için)
  "foundation_for": [string],       // YALNIZCA foundational_value_score yüksekse doldur:
                                     // bu çalışmanın hangi GÜNCEL alt-konulara/araştırma
                                     // çizgilerine temel oluşturduğu (ör. "Network anomaly
                                     // detection", "ML-based IDS") - metinden/konudan makul
                                     // çıkarım yapılabilir, foundational değilse []
  "post_reading_questions": [string], // TAM 3 soru, TÜRKÇE - okuyucu makaleyi
                                       // bitirdikten sonra kendi kendine sorup
                                       // gerçekten anlayıp anlamadığını test etsin
                                       // (ör. "Kullanılan dataset neden seçilmiş?")
  "explain_to_analyst_prompt": string | null, // TÜRKÇE, TEK cümle: "Bu makaleyi bir
                                       // SOC analistine 3 dakikada nasıl anlatırdın?"
                                       // tarzı, makaleye ÖZEL bir Feynman-tekniği istemi
  "practical_application": string | null // Yalnızca implementation_value_score
                                       // yeterince yüksekse (aksi halde null): bu
                                       // yöntemin Wazuh/Splunk/gerçek bir SOC ortamında
                                       // nasıl denenebileceğine dair TEK somut öneri
}}""" + PROMPT_INJECTION_GUARD


# NotebookLM konu taksonomisiyle aynı anahtarlar kullanılıyor (config.py) ki
# "domain_contribution_scores" ile notebooklm_topic aynı dili konuşsun; ayrıca
# akademik/genel iki anahtar daha ekleniyor (her makale bir SOC alt-alanına
# girmeyebilir ama "Academic_Research"/"Implementation" değeri taşıyabilir).
_DOMAIN_KEYS = list(config.NOTEBOOKLM_TOPICS.keys()) + ["Academic_Research", "Implementation"]


def _estimate_reading(full_text: str | None, abstract: str | None) -> tuple[int, str]:
    """Okuma süresi LLM'e tahmin ettirilmiyor - kelime sayısından deterministik
    hesaplanıyor (bkz. proje ilkesi: muhakeme gerektirmeyen iş klasik koda
    bırakılır). Ortalama okuma hızı ~200 kelime/dk. Döner: (dakika, dayanak)."""
    if full_text:
        words = len(full_text.split())
        return max(1, round(words / 200)), "full_text"
    words = len((abstract or "").split())
    return max(1, round(words / 200)), "abstract_only"


def analyze_paper(
    title: str,
    abstract: str | None,
    full_text: str | None,
    analysis_type: str,
    extraction_schema: dict | None = None,
) -> dict:
    """extraction_schema: V1.1 research profiles (bkz. src/research/profiles.py,
    src/research/extraction_schema.py) için PROFİL-ÖZEL ek çıkarım alanları
    - GERÇEK bir JSON Schema (ör. profiles/examples/*.yaml'ın extraction_schema'sı).
    Verilirse tek çağrıda (2. bir Gemini isteği AÇILMAZ - bkz. proje ilkesi:
    agent'ları tek çağrıda birleştirme) sonuç JSON'ına AYRI bir
    "profile_extraction" anahtarı eklenir - base şemayla karışmaz, profile
    aktif değilken hiçbir şey değişmez (None ise davranış birebir eskisiyle
    aynı).

    Gemini yanıtı geldikten SONRA `profile_extraction` AYNI şemayla runtime'da
    doğrulanır (extraction_schema.validate) - model yanlış tip döndürürse
    (ör. boolean alan yerine sayı) DB'ye KÖRLEMESİNE yazılmaz: alan None'a
    düşürülür, `profile_extraction_status`/`_errors` ile işaretlenir (bkz.
    altta) - hem paper kaydı kaybolmaz hem yanlış veri bilimsel analize
    karışmaz."""
    if full_text:
        body = f"[TAM METİN - analysis_type=FULL_TEXT]\n\n{full_text[:60000]}"
    else:
        body = (
            f"[YALNIZCA ÖZET - analysis_type=ABSTRACT_ONLY. Tam metin yok, "
            f"yalnızca başlık ve özetten çıkarılabilecek kadarını doldur, "
            f"kalanları null/[] bırak.]\n\nÖzet: {abstract or '(özet yok)'}"
        )
    content = f"Başlık: {title}\n\n{body}"
    domain_keys = ",\n    ".join(f'"{k}": number' for k in _DOMAIN_KEYS)
    system = _SYSTEM.format(
        keywords=", ".join(config.KEYWORDS) or "genel siber güvenlik",
        domain_keys=domain_keys,
    )
    max_tokens = 7500
    if extraction_schema:
        # Base şemadan SONRA, ayrı bir bölüm olarak ekleniyor - .format()
        # brace-escaping riskine girmeden (to_prompt_text zaten kaçışlı JSON
        # örneği üretiyor). Üçlü true/false/null semantiği AÇIKÇA anlatılıyor
        # - aksi halde model "bilmiyorum" ile "hayır" arasında ayrım yapmaz,
        # bu da Evidence Matrix/Gap Analysis'te yanlış negatif-kanıt
        # yüzdelerine yol açar (bkz. proje notları).
        system += (
            "\n\nAYRICA (profile-specific extraction): Yukarıdaki temel alanlara "
            "EK OLARAK, sonuç JSON'ına \"profile_extraction\" adında bir alan daha "
            "ekle. Bu alan SADECE metinde GERÇEKTEN geçen bilgilerden doldurulur - "
            "UYDURMA. Boolean alanlarda (true/false/null) ÜÇ FARKLI durumu KESİNLİKLE "
            "birbirine karıştırma: true = metinde AÇIK kanıt var; false = metinde "
            "AÇIKÇA kullanılMADIĞI/yapılMADIĞI belirtiliyor; null = mevcut metinden "
            "belirlenemiyor (ör. sadece özet var, ya da konu hiç geçmiyor). "
            "'Bilmiyorum' ASLA false ile karıştırılmaz - null kullan. Şema:\n"
            + to_prompt_text(extraction_schema)
        )
        # Daha fazla alan = daha fazla çıktı tokenı gerekir (bkz. altta
        # 7500'ün zaten sınırda olduğuna dair not) - payı büyütüyoruz.
        max_tokens = 10000
    # 5500 canlıda yetersiz kaldı: zengin FULL_TEXT makalelerde (çok sayıda
    # contribution/reading_guide bölümü/prerequisite) model JSON'u bitiremeden
    # kesiliyor, call_json de bunu "geçerli JSON değil" diye reddediyordu -
    # makale hiç analiz edilmemiş gibi kalıyordu (collector_runs'ta görüldü).
    result = call_json(config.ANALYSIS_MODEL, system, content, max_output_tokens=max_tokens)
    result["_analysis_type"] = analysis_type
    minutes, basis = _estimate_reading(full_text, abstract)
    result["estimated_reading_minutes"] = minutes

    if extraction_schema:
        # Runtime doğrulama: model şemaya uymayan bir tip döndürürse (ör.
        # mitre_attack_used=82) bu HAM veriyi bilimsel analize/DB'ye
        # KÖRLEMESİNE yazmıyoruz - bkz. fonksiyon docstring'i.
        extraction = result.get("profile_extraction")
        ok, errors = validate_extraction(extraction, extraction_schema)
        if ok:
            result["profile_extraction_status"] = "valid"
        else:
            result["profile_extraction"] = None
            result["profile_extraction_status"] = "validation_failed"
            result["profile_extraction_errors"] = errors
    result["reading_time_basis"] = basis
    if full_text and result.get("must_see"):
        # Hallucination/provenance guard (proje notları): "must_see" (ör.
        # "Figure 5", "Table 3") FULL_TEXT'te GERÇEKTEN geçmiyorsa uydurulmuş
        # olabilir - mekanik bir ikinci kontrol, prompt disiplinine tek
        # başına güvenmiyoruz. ABSTRACT_ONLY'de must_see zaten [] olmalı
        # (prompt kuralı) - bu kontrol yalnızca FULL_TEXT'te anlamlı.
        haystack = full_text.lower()
        result["must_see"] = [m for m in result["must_see"] if m and str(m).lower() in haystack]
    if not full_text:
        # PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md P1): ABSTRACT_
        # ONLY'de reading_guide/must_see'nin [] olması ŞİMDİYE KADAR sadece
        # prompt disiplinine bırakılmıştı (bir model regresyonu sessizce
        # uydurma figür/tablo/bölüm üretebilirdi). Diğer hallucination
        # guard'larla (must_see FULL_TEXT'te grounding, news_analyst._ground_
        # against_source) AYNI ilke - mekanik olarak ZORLA boşalt, tek başına
        # prompt'a güvenme.
        result["reading_guide"] = []
        result["must_see"] = []
    return result
