"""DataCite REST API - dataset/software DOI'leri. CANLI doğrulandı. API key
GEREKMİYOR.

BİLİNÇLİ OLARAK henüz pipeline'a (run_pipeline.py) BAĞLANMADI - tezin
"dataset/kod mevcut mu?" reproducibility sorusu zaten paper_analyst.py'nin
research profile extraction_schema'sındaki 'dataset_available'/
'code_available' alanlarıyla (LLM'in metinden çıkardığı) kısmen
cevaplanıyor. Bu modül, o LLM çıkarımını DOI-tabanlı gerçek bir kayıtla
DOĞRULAMAK isteyen bir SONRAKİ adım için hazır - search() fonksiyonu
academic.py'nin normalize sözlük şeklini döner, hazır olduğunda
_collect_profile'a bağlanabilir."""
from __future__ import annotations

from datetime import date
from typing import Any

from .academic import _retry_get


def search(query: str, since: date, page_size: int = 25, until: date | None = None) -> list[dict[str, Any]]:
    """`since`/`until` DataCite'ın `published` filtresi sunucu tarafında
    aralık kabul etmediği için (CANLI test edildi, `[2022 TO *]` sözdizimi
    0 sonuç döndürdü) Python tarafında `publicationYear` üzerinden
    (yıl hassasiyetinde) uygulanır - 2026-09-13 recovery backfill için
    `until` eklendi (bkz. academic.search_openalex docstring'indeki
    gerekçe), normal koşu asla geçmez."""
    resp = _retry_get(
        "https://api.datacite.org/dois",
        params={"query": query, "page[size]": page_size},
    )
    results = []
    for item in resp.json().get("data", []) or []:
        attrs = item.get("attributes") or {}
        titles = attrs.get("titles") or []
        creators = attrs.get("creators") or []
        year = attrs.get("publicationYear")
        if year and since and year < since.year:
            continue
        if year and until and year > until.year:
            continue
        results.append({
            "title": (titles[0].get("title") if titles else "") or "",
            "authors": [c.get("name", "") for c in creators],
            "doi": attrs.get("doi"),
            "arxiv_id": None,
            "openalex_id": None,
            "venue": attrs.get("publisher"),
            "publication_date": f"{attrs.get('publicationYear')}-01-01" if attrs.get("publicationYear") else None,
            "abstract": None,
            "pdf_url": None,
            "source_api": "datacite",
            "document_type": (attrs.get("types") or {}).get("resourceTypeGeneral"),  # 'Dataset' | 'Software' | ...
        })
    return results
