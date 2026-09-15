"""Citation snowballing (1-hop) - Semantic Scholar Graph API üzerinden.

Mimari (bkz. proje notları):

    keyword/boolean search (query_builder)
              |
        seed papers (relevance='relevant' olanlar)
              |
      +-------+-------+-------------------+
      |               |                   |
  references      citations       recommendations
  (backward)      (forward)        (S2'nin kendi
      |               |          benzerlik motoru)
      +-------+-------+-------------------+
              |
         dedup (mevcut _upsert_paper, doi/arxiv/title)
              |
          relevance screening (mevcut budget-aware döngü)

BİLİNÇLİ OLARAK 1-HOP: snowball sonuçlarından bir daha snowball YAPILMIYOR.
Birkaç seed'den başlayıp 2-hop'a çıkmak (referansın referansı, atıfın atıfı)
üstel büyür - birkaç düzine seed'den kolayca binlerce makaleye çığ gibi
büyüyebilir (bkz. proje notları: "2-hop yapmayalım, yoksa birkaç seed
paper'dan binlerce makale üretir").

academic.py'nin retry politikasını (429/5xx -> exponential backoff) ve
Semantic Scholar yardımcılarını (_parse_s2_paper, _s2_headers, _S2_FIELDS)
yeniden kullanıyoruz - snowballing de aynı API'nin bir başka uç noktası,
ayrı bir retry/parse mantığı icat etmeye gerek yok.
"""
from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .. import config
from .academic import _S2_FIELDS, _is_retryable, _parse_s2_paper, _s2_headers

_TIMEOUT = httpx.Timeout(20.0)
_RECOMMENDATIONS_URL = "https://api.semanticscholar.org/recommendations/v1/papers/"


def s2_id_for(doi: str | None, arxiv_id: str | None) -> str | None:
    """Semantic Scholar'ın harici-ID söz dizimi: 'DOI:...' ya da 'ARXIV:...'.
    İkisi de yoksa (ör. sadece OpenAlex/Crossref'ten gelmiş, DOI'siz bir
    kayıt) snowball edilemez - None döner, çağıran bu seed'i atlar."""
    if doi:
        return f"DOI:{doi}"
    if arxiv_id:
        return f"ARXIV:{arxiv_id}"
    return None


def _get(url: str, params: dict) -> httpx.Response:
    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=25),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    def _do() -> httpx.Response:
        resp = httpx.get(url, params=params, headers=_s2_headers(), timeout=_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return resp

    return _do()


def _post(url: str, json_body: dict, params: dict) -> httpx.Response:
    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=25),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    def _do() -> httpx.Response:
        resp = httpx.post(
            url, json=json_body, params=params, headers=_s2_headers(), timeout=_TIMEOUT, follow_redirects=True
        )
        resp.raise_for_status()
        return resp

    return _do()


def get_references(paper_id: str, limit: int = 30) -> list[dict[str, Any]]:
    """Backward snowballing: bu makalenin ATIF YAPTIĞI (kaynakça) makaleler."""
    resp = _get(
        f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/references",
        {"fields": _S2_FIELDS, "limit": limit},
    )
    out = []
    for item in resp.json().get("data", []):
        p = item.get("citedPaper")
        if p and p.get("paperId"):
            out.append(_parse_s2_paper(p, "semantic_scholar_snowball_ref"))
    return out


def get_citations(paper_id: str, limit: int = 30) -> list[dict[str, Any]]:
    """Forward snowballing: bu makaleye ATIF YAPAN (bu makaleyi kaynak
    gösteren) makaleler."""
    resp = _get(
        f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations",
        {"fields": _S2_FIELDS, "limit": limit},
    )
    out = []
    for item in resp.json().get("data", []):
        p = item.get("citingPaper")
        if p and p.get("paperId"):
            out.append(_parse_s2_paper(p, "semantic_scholar_snowball_cite"))
    return out


def get_recommended_papers(seed_paper_ids: list[str], limit: int = 25) -> list[dict[str, Any]]:
    """references/citations'tan FARKLI: atıf grafiği değil, Semantic
    Scholar'ın kendi embedding-tabanlı benzerlik/öneri motoru (ayrı bir
    'recommendations' API - farklı host path). Birden fazla seed tek
    istekte (positivePaperIds) birleştirilir - seed başına ayrı istek
    atmaya gerek yok, hem daha hızlı hem daha az rate-limit riski."""
    if not seed_paper_ids:
        return []
    resp = _post(
        _RECOMMENDATIONS_URL,
        {"positivePaperIds": seed_paper_ids[:20], "limit": limit},
        {"fields": _S2_FIELDS},
    )
    # Canlı testte doğrulandı: API "limit" alanını yok sayıp varsayılan
    # (~100) sonuç döndürebiliyor - burada Python tarafında da kesiyoruz,
    # API'nin davranışına güvenmiyoruz.
    data = (resp.json().get("recommendedPapers", []) or [])[:limit]
    return [_parse_s2_paper(p, "semantic_scholar_recommend") for p in data]


def snowball_from_seeds(seed_papers: list[dict[str, Any]], seed_limit: int) -> list[dict[str, Any]]:
    """seed_papers: papers tablosundan gelen satırlar (en azından doi/arxiv_id
    alanları olmalı) - ÇAĞIRAN tarafın bunları önceden 'relevance_status =
    relevant' olanlarla sınırlaması beklenir (bkz. proje notları: "top N
    high-confidence paper -> snowball"). Burada AYRICA seed_limit'e kesilir -
    çift güvence, snowballing'in API/istek maliyetini sınırlı tutmak için.

    Tek bir seed'in references/citations çağrısı başarısız olursa (ör. S2'de
    kaydı yok, 404) o seed atlanır, diğerleri etkilenmez - tek makalenin
    snowball'u tüm koşuyu düşürmesin (bkz. proje genelindeki aynı ilke)."""
    seeds = seed_papers[:seed_limit]
    s2_ids = [sid for sid in (s2_id_for(s.get("doi"), s.get("arxiv_id")) for s in seeds) if sid]

    collected: list[dict[str, Any]] = []
    for s2_id in s2_ids:
        try:
            collected.extend(get_references(s2_id))
        except httpx.HTTPError:
            pass
        try:
            collected.extend(get_citations(s2_id))
        except httpx.HTTPError:
            pass

    try:
        collected.extend(get_recommended_papers(s2_ids))
    except httpx.HTTPError:
        pass

    return collected
