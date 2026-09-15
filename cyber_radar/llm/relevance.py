"""Level 1: İlgililik filtresi.

Ucuz/hızlı modelle çalışır. Amaç: her yeni kaydı üç kovaya ayırmak:
  - relevant   (confidence >= RELEVANCE_THRESHOLD_HIGH)
  - uncertain  (arada kalan her şey -> review_queue, ASLA otomatik silinmez)
  - irrelevant (confidence düşük VE model net "ilgisiz" diyor)

"Kaçırmamak" önceliği burada somutlaşıyor: belirsiz olan hiçbir şey sessizce
atılmıyor.
"""
from __future__ import annotations

from typing import Literal

from .. import config
from .client import PROMPT_INJECTION_GUARD, LLMJSONError, call_json

RelevanceStatus = Literal["relevant", "uncertain", "irrelevant"]

_PAPER_SYSTEM = """Sen bir siber güvenlik akademik makale sınıflandırma asistanısın.
Sana bir makalenin başlığı ve özeti verilecek. Görevin bu çalışmanın siber
güvenlikle ilgili olup olmadığını değerlendirmek.

Yalnızca şu şemada geçerli JSON döndür, başka hiçbir metin ekleme:
{
  "cybersecurity_relevant": boolean,
  "confidence": number,          // 0.0 - 1.0 arası
  "primary_domain": string,      // örn. "Threat Detection", "Malware Analysis", "Cryptography"
  "secondary_domains": [string]
}
Emin değilsen confidence'ı düşük tut, uydurma yüksek güven verme.""" + PROMPT_INJECTION_GUARD

_NEWS_SYSTEM = """Sen bir siber güvenlik haber/olay sınıflandırma asistanısın.
Sana bir haberin başlığı ve özeti verilecek. Görevin bu içeriğin operasyonel
olarak önemli bir siber güvenlik gelişmesi olup olmadığını değerlendirmek
(pazarlama içeriği, genel teknoloji haberi, alakasız içerik "ilgisiz" sayılır).

Yalnızca şu şemada geçerli JSON döndür, başka hiçbir metin ekleme:
{
  "cybersecurity_relevant": boolean,
  "confidence": number,          // 0.0 - 1.0 arası
  "news_type": string,           // örn. "Vulnerability", "Ransomware", "APT", "Data Breach"
  "priority_hint": string        // "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" - ilk izlenim
}
Emin değilsen confidence'ı düşük tut.""" + PROMPT_INJECTION_GUARD


def _classify(system: str, content: str) -> tuple[dict, RelevanceStatus]:
    try:
        result = call_json(config.RELEVANCE_MODEL, system, content, max_output_tokens=300)
    except LLMJSONError:
        # Model çağrısı başarısız olursa item'ı kaybetmemek için uncertain'a düşürüyoruz,
        # irrelevant'a değil.
        return {"cybersecurity_relevant": None, "confidence": 0.0, "reason": "llm_call_failed"}, "uncertain"

    confidence = float(result.get("confidence", 0.0) or 0.0)
    relevant = bool(result.get("cybersecurity_relevant"))

    if relevant and confidence >= config.RELEVANCE_THRESHOLD_HIGH:
        status: RelevanceStatus = "relevant"
    elif not relevant and confidence >= config.RELEVANCE_THRESHOLD_HIGH:
        status = "irrelevant"
    else:
        status = "uncertain"

    return result, status


def classify_paper(title: str, abstract: str | None) -> tuple[dict, RelevanceStatus]:
    content = f"Başlık: {title}\n\nÖzet: {abstract or '(özet yok)'}"
    return _classify(_PAPER_SYSTEM, content)


def classify_news(title: str, summary: str | None) -> tuple[dict, RelevanceStatus]:
    content = f"Başlık: {title}\n\nİçerik: {summary or '(özet yok)'}"
    return _classify(_NEWS_SYSTEM, content)
