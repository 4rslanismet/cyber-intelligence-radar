"""DOAJ (Directory of Open Access Journals) - açık erişim dergi doğrulaması.
CANLI doğrulandı. API key GEREKMİYOR.

journal_registry (bkz. src/research/journal_lookup.py) SCIE/WoS/Scopus için
KESİN, elle kürate edilmiş bir kaynak - DOAJ ise KENDİSİ canlı, otoriter bir
API olduğu için (WoS/Scopus'un aksine, statik bir export'a ihtiyaç duymadan)
per-makale gerçek zamanlı sorgulanabilir. İkisi FARKLI sorular cevaplıyor:
journal_registry "SCIE/Q1 mi?", DOAJ "gerçek, meşru bir açık erişim dergi
mi?" - biri diğerinin yerine geçmez."""
from __future__ import annotations

from typing import Any

from .academic import _retry_get


def check_journal(issn: str | None, eissn: str | None) -> dict[str, Any] | None:
    """ISSN/eISSN'i DOAJ'da arar, bibjson.eissn/pissn ile TAM eşleşen ilk
    sonucu döner (arama metin-tabanlı olduğu için yanlış pozitifi önlemek
    adına eşleşme doğrulanıyor). Bulamazsa None - "DOAJ'da değil" ile
    "sorgu başarısız oldu" birbirinden ayrılmaz burada, ikisi de None;
    çağıran taraf zaten "bulunamadıysa hiçbir şey yapma" ilkesiyle çalışıyor."""
    query = issn or eissn
    if not query:
        return None
    resp = _retry_get(f"https://doaj.org/api/search/journals/{query}", params={})
    for r in resp.json().get("results", []) or []:
        bj = r.get("bibjson") or {}
        if query in (bj.get("eissn"), bj.get("pissn")):
            return {
                "doaj_id": r.get("id"),
                "title": bj.get("title"),
                "eissn": bj.get("eissn"),
                "pissn": bj.get("pissn"),
            }
    return None
