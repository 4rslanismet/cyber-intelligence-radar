"""DBLP Search API - bilgisayar bilimi conference/journal kapsaması.

DOĞRULANAMADI: bu sandbox'ın IP'si DBLP'nin bot-koruması (Anubis/xess
challenge sayfası) tarafından engellendi - hem User-Agent'lı hem User-Agent'sız
denendi, ikisi de HTML challenge sayfası döndürdü, gerçek JSON yanıtı hiç
alınamadı. Üretim sunucusunun (farklı IP/ağ itibarı) engellenip
engellenmeyeceği BİLİNMİYOR - bkz. proje notları / academic.py'nin kendi
üst docstring'indeki aynı durum: "kendi sunucunuzda ilk koşuda tek tek
doğrulamanızı öneririz."

Aşağıdaki alan eşlemesi resmi DBLP API dokümantasyonuna
(https://dblp.org/faq/13501473.html) dayanıyor, CANLI yanıtla teyit
EDİLEMEDİ - ilk üretim koşusunda hata/boş sonuç alırsanız (collector_runs
tablosunda 'dblp' kaynağı altında görürsünüz) alan adlarını gerçek yanıtla
karşılaştırıp düzeltin."""
from __future__ import annotations

from datetime import date
from typing import Any

from .academic import _retry_get


def search(query: str, since: date, hits: int = 25) -> list[dict[str, Any]]:
    resp = _retry_get(
        "https://dblp.org/search/publ/api",
        params={"q": query, "format": "json", "h": hits},
    )
    hits_list = (resp.json().get("result", {}).get("hits", {}) or {}).get("hit", []) or []
    results = []
    for h in hits_list:
        info = h.get("info") or {}
        year = info.get("year")
        if year and since and int(year) < since.year:
            continue
        authors_raw = (info.get("authors") or {}).get("author") or []
        if isinstance(authors_raw, dict):  # tek yazarsa DBLP list yerine dict döner
            authors_raw = [authors_raw]
        results.append({
            "title": info.get("title") or "",
            "authors": [a.get("text", a) if isinstance(a, dict) else str(a) for a in authors_raw],
            "doi": info.get("doi"),
            "arxiv_id": None,
            "openalex_id": None,
            "venue": info.get("venue"),
            "publication_date": f"{year}-01-01" if year else None,
            "abstract": None,  # DBLP metadata-only, abstract vermiyor
            "pdf_url": info.get("ee"),  # genelde yayıncı/DOI linki, doğrudan PDF olmayabilir
            "source_api": "dblp",
            "document_type": info.get("type"),
        })
    return results
