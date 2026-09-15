"""OpenCitations Index v2 - Semantic Scholar'dan BAĞIMSIZ ikinci bir citation
graph kaynağı (bkz. proje notları: "iki bağımsız citation graph kaynağımız
olmuş olur"). CANLI doğrulandı.

ÖNEMLİ FARK: OpenCitations sadece DOI EDGE'LERİNİ verir (cited/citing DOI'ler
- title/abstract YOK), Semantic Scholar'ın aksine tam metadata dönmüyor. Bu
yüzden burada iki adımlı bir akış var: (1) OpenCitations'tan referans/atıf
DOI listesi, (2) OpenAlex'in TEK istekte çoklu-DOI filtresiyle (`filter=doi:
d1|d2|...`, CANLI doğrulandı) bu DOI'leri gerçek makale kayıtlarına çözmek -
N ayrı istek yerine DOI başına 1 batch istek."""
from __future__ import annotations

import re
from typing import Any

from .academic import _openalex_journal_meta, _reconstruct_openalex_abstract, _retry_get

_DOI_RE = re.compile(r"doi:(\S+)")
_BASE = "https://api.opencitations.net/index/v2"
_BATCH_SIZE = 50


def _extract_doi(field: str | None) -> str | None:
    m = _DOI_RE.search(field or "")
    return m.group(1) if m else None


def get_reference_dois(doi: str) -> list[str]:
    """Backward: bu DOI'nin ATIF YAPTIĞI (kaynakça) makalelerin DOI'leri."""
    resp = _retry_get(f"{_BASE}/references/doi:{doi}", params={})
    return [d for d in (_extract_doi(item.get("cited")) for item in resp.json() or []) if d]


def get_citation_dois(doi: str) -> list[str]:
    """Forward: bu DOI'ye ATIF YAPAN makalelerin DOI'leri."""
    resp = _retry_get(f"{_BASE}/citations/doi:{doi}", params={})
    return [d for d in (_extract_doi(item.get("citing")) for item in resp.json() or []) if d]


def resolve_dois(dois: list[str]) -> list[dict[str, Any]]:
    """DOI listesini OpenAlex üzerinden gerçek makale kayıtlarına çözer -
    academic.py'nin normalize sözlük şeklini (title/authors/abstract/...)
    kullanır ki _upsert_paper değişmeden ÇALIŞSIN."""
    results: list[dict[str, Any]] = []
    for i in range(0, len(dois), _BATCH_SIZE):
        batch = dois[i : i + _BATCH_SIZE]
        resp = _retry_get(
            "https://api.openalex.org/works",
            params={"filter": "doi:" + "|".join(batch), "per-page": len(batch)},
        )
        for w in resp.json().get("results", []) or []:
            oa = w.get("open_access") or {}
            results.append({
                "title": w.get("title") or "",
                "authors": [
                    a.get("author", {}).get("display_name", "")
                    for a in w.get("authorships", [])
                    if a.get("author")
                ],
                "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
                "arxiv_id": None,
                "openalex_id": w.get("id"),
                "venue": (w.get("primary_location") or {}).get("source", {}).get("display_name")
                    if (w.get("primary_location") or {}).get("source") else None,
                "publication_date": w.get("publication_date"),
                "abstract": _reconstruct_openalex_abstract(w.get("abstract_inverted_index")),
                "pdf_url": oa.get("oa_url"),
                "source_api": "opencitations_snowball",
                **_openalex_journal_meta(w),
            })
    return results
