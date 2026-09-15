"""OpenAIRE Graph API v3 - publication + dataset/software/project bağlantıları.

CANLI doğrulandı (gerçek response şemasıyla field-by-field kontrol edildi).
Anonim erişim kabul ediyor - API key GEREKMİYOR (bkz. proje notları:
"free/no-key-first"). v3 kullanılıyor - v4 hâlâ beta.

Yalnızca 'publication' türü sonuçları döner - dataset/software/project
ilişkileri (tezin "kod/dataset var mı?" sorusu için) BİLİNÇLİ OLARAK bu
pass'te entegre EDİLMEDİ, ayrı bir enrichment adımı (henüz yazılmadı)."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from .academic import _retry_get

_JATS_TAG = re.compile(r"<[^>]+>")


def _strip_jats(text: str | None) -> str | None:
    """descriptions[] çoğu zaman JATS XML etiketleri içeriyor (<jats:p>...),
    canlı doğrulandı - düz metne çeviriyoruz."""
    if not text:
        return None
    return _JATS_TAG.sub(" ", text).strip() or None


def search(query: str, since: date, page_size: int = 25, until: date | None = None) -> list[dict[str, Any]]:
    """`until`: 2026-09-13 recovery backfill için eklendi (bkz.
    src/collectors/academic.search_openalex docstring'indeki gerekçe) -
    OpenAIRE Graph API `toPublicationDate`'i `fromPublicationDate`'in
    simetriği olarak destekliyor. Normal koşu asla geçmez."""
    params = {"search": query, "type": "publication", "fromPublicationDate": since.isoformat(), "pageSize": page_size}
    if until is not None:
        params["toPublicationDate"] = until.isoformat()
    resp = _retry_get(
        "https://api.openaire.eu/graph/v1/researchProducts",
        params=params,
    )
    results = []
    for w in resp.json().get("results", []) or []:
        pids = {p.get("scheme"): p.get("value") for p in (w.get("pids") or []) if p.get("scheme")}
        descs = w.get("descriptions") or []
        container = w.get("container") or {}
        results.append({
            "title": w.get("mainTitle") or "",
            "authors": [a.get("fullName", "") for a in w.get("authors") or []],
            "doi": pids.get("doi"),
            "arxiv_id": None,
            "openalex_id": None,
            "venue": container.get("name"),
            "publication_date": w.get("publicationDate"),
            "abstract": _strip_jats(descs[0] if descs else None),
            "pdf_url": None,
            "source_api": "openaire",
            "issn": container.get("issnPrinted") or container.get("issnLinking"),
            "eissn": container.get("issnOnline"),
            "publisher": w.get("publisher"),
            "document_type": w.get("type"),
        })
    return results
