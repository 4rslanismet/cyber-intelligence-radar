"""OpenReview API v2 - AI/ML/LLM konferans + review metadata. CANLI doğrulandı
(field-by-field kontrol edildi: content.title/abstract/authors/venue/pdf,
her biri {"value": ...} sarmalı). API key GEREKMİYOR.

Amaç: arXiv'in yakalamayabileceği, konferans review sürecinden geçmiş LLM/ML
güvenlik çalışmalarını bulmak (bkz. ör. bir profilin 'llm'/'rag' concept_groups'u).
DOI genelde YOK (bu bir review platformu, yayıncı değil) - doi=None kalır,
dedup normalized_title üzerinden _upsert_paper'da zaten çalışıyor."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from .academic import _retry_get


def _ms_to_iso(ms: int | None) -> str | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()
    except (ValueError, OSError):
        return None


def search(query: str, since: date, limit: int = 25, until: date | None = None) -> list[dict[str, Any]]:
    """`until`: OpenReview API'de sunucu tarafı date-range yok, `since` gibi
    client-side filtreleniyor (bkz. academic.search_openalex docstring'indeki
    gerekçe - recovery backfill için, normal koşu asla geçmez)."""
    resp = _retry_get(
        "https://api2.openreview.net/notes/search",
        params={"term": query, "content": "all", "group": "all", "source": "forum", "limit": limit},
    )
    results = []
    for n in resp.json().get("notes", []) or []:
        c = n.get("content") or {}
        pub_date = _ms_to_iso(n.get("pdate") or n.get("cdate"))
        if pub_date and pub_date < since.isoformat():
            continue
        if until is not None and pub_date and pub_date > until.isoformat():
            continue
        title = (c.get("title") or {}).get("value") or ""
        if not title:
            continue
        pdf_url = (c.get("pdf") or {}).get("value")
        if pdf_url and pdf_url.startswith("/"):
            # OpenReview'da kendi barındırdığı PDF'ler için göreli yol -
            # academic.download_and_extract_pdf mutlak URL bekliyor.
            pdf_url = f"https://openreview.net{pdf_url}"
        results.append({
            "title": title,
            "authors": (c.get("authors") or {}).get("value") or [],
            "doi": None,
            "arxiv_id": None,
            "openalex_id": None,
            "venue": (c.get("venue") or {}).get("value"),
            "publication_date": pub_date,
            "abstract": (c.get("abstract") or {}).get("value"),
            "pdf_url": pdf_url,
            "source_api": "openreview",
        })
    return results
