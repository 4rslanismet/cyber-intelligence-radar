"""Faz 3 "okuma sistemi": günün öğrenme teması.

Bilinçli olarak KÜÇÜK bir çağrı: bu koşuda zaten seçilmiş MUST_READ +
"Bugünün Klasiği" makalelerinin başlık/why_read/domain skorlarından bir tema
sentezliyor - yeni bir makale aramıyor, yeni bir iddia üretmiyor, sadece
elimizdeki gerçek seçimin ortak paydasını özetliyor. Girdi boşsa (bu koşuda
hiç MUST_READ/klasik yoksa) LLM çağrısı hiç yapılmıyor.
"""
from __future__ import annotations

import json

from .. import config
from .client import PROMPT_INJECTION_GUARD, LLMJSONError, call_json

_SYSTEM = """Sana bugün bir siber güvenlik okuma sisteminin seçtiği birkaç
makalenin başlığı, "neden okunmalı" notu ve hangi alanlara katkı sağladığı
verilecek. Görevin bunların ORTAK PAYDASINI bulup tek bir günlük öğrenme
teması önermek.

KURAL: Sadece verilen makalelerden çıkarılabilecek bir tema öner. Verilmeyen
bir makale/kavram/istatistik uydurma. Makaleler arasında gerçek bir ortak
tema yoksa (ör. tamamen alakasız konular) "theme" alanını null bırak, zorla
bir bağlantı kurma.

Yalnızca şu şemada geçerli JSON döndür, başka hiçbir metin ekleme:
{
  "theme": string | null,           // TÜRKÇE, kısa (ör. "Threat Intelligence → Knowledge Graph")
  "learn_today": [string],          // theme null değilse: 3-5 maddelik, TÜRKÇE,
                                     // bugün verilen makalelerden çıkan somut alt-konular
                                     // (ör. "CTI extraction", "Entity normalization")
  "reading_order_note": string | null // TÜRKÇE, TEK cümle: verilen makaleleri hangi
                                     // sırayla okumak mantıklı olur ve neden (ör.
                                     // "önce X ile temel kavramı, sonra Y ile güncel
                                     // uygulamasını gör") - sıralama önerisi yoksa null
}""" + PROMPT_INJECTION_GUARD


def daily_theme(items: list[dict]) -> dict | None:
    """items: [{"title": str, "why_read": str|None, "domain_contribution_scores": dict|None}]
    En az 1 öğe gerekir; boşsa hiç çağrı yapılmadan None döner (gereksiz
    LLM maliyeti yok)."""
    if not items:
        return None
    content = json.dumps(items, ensure_ascii=False, indent=2)
    try:
        return call_json(config.RELEVANCE_MODEL, _SYSTEM, content, max_output_tokens=600)
    except LLMJSONError:
        return None


_WEEKLY_SYSTEM = """Sana bu hafta bir siber güvenlik radar sisteminin topladığı
en değerli makalelerin başlık/alan bilgisi, en sık görülen haber türleri ve
vendor'lar verilecek. Görevin BUNLARDAN çıkan gerçek örüntüleri özetlemek ve
gelecek hafta için bir okuma planı önermek.

KURAL: Yalnızca verilen veriden çıkarılabilecek gözlemler yaz. Verilmeyen bir
istatistik/olay/makale uydurma - "bu hafta X arttı" gibi bir trend iddiası
ancak verilen frekans verisiyle destekleniyorsa yazılabilir.

Yalnızca şu şemada geçerli JSON döndür, başka hiçbir metin ekleme:
{
  "learned_this_week": [string], // 3-5 madde, TÜRKÇE - verilen makale
                                  // başlıkları/alanları ve haber türü
                                  // frekanslarından çıkan gerçek gözlemler
  "reading_plan": [{"day": string, "focus": string}]
                                  // Pazartesi-Cuma (5 öğe), TÜRKÇE - verilen
                                  // makaleler arasından bir haftaya yayılmış
                                  // mantıklı bir okuma sırası (temelden
                                  // güncele doğru gidebilir)
}""" + PROMPT_INJECTION_GUARD


def weekly_synthesis(top_papers: list[dict], news_event_types: list[tuple[str, int]], vendors: list[tuple[str, int]]) -> dict | None:
    """top_papers: [{"title", "domain_contribution_scores"}] (bkz. weekly_digest._top_papers)
    news_event_types / vendors: [(isim, sayı), ...] - zaten deterministik hesaplanmış
    frekanslar (bkz. weekly_digest._vendor_frequency benzeri). Girdi tamamen
    boşsa None döner."""
    if not top_papers and not news_event_types:
        return None
    content = json.dumps(
        {
            "top_papers": top_papers,
            "news_event_types": news_event_types,
            "vendors": vendors,
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    try:
        return call_json(config.RELEVANCE_MODEL, _WEEKLY_SYSTEM, content, max_output_tokens=3000)
    except LLMJSONError:
        return None
