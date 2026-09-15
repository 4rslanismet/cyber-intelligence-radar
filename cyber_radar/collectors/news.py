"""Haber/tehdit istihbaratı toplayıcılar.

V0 kapsamı bilinçli olarak dar tutuldu: ağır HTML crawling / Playwright yok,
sadece RSS (feedparser) + CISA KEV JSON listesi. Bu, tek sunucuda kararlı
çalışan, bakım yükü düşük bir başlangıç noktası. Kaynak sayısını NEWS_FEEDS
üzerinden (.env) siz büyütürsünüz.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .. import config
from ..dedup import extract_cves
from ..security import is_safe_external_url

_TIMEOUT = httpx.Timeout(20.0)


def _parse_entry_date(entry: Any) -> datetime | None:
    for field in ("published", "updated"):
        raw = entry.get(field)
        if raw:
            try:
                return parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                continue
    return None


def fetch_rss_feed(feed_url: str, since: date) -> list[dict[str, Any]]:
    """Tek bir RSS/Atom feed'ini çeker, since tarihinden yeni girdileri döner.

    2026-09-15 (SSRF sertleştirmesi - bkz. src/security.py docstring'i):
    feedparser.parse() bir URL string'i aldığında dosya/FTP dahil pek çok
    şemayı sessizce kabul edebiliyor - NEWS_FEEDS bugün operatörün kendi
    .env'i ama public üründe kullanıcı-tanımlı bir kaynak listesi olacak,
    bu yüzden http(s) + yerel-olmayan hedef kontrolü BURADA, ağa hiç
    gitmeden yapılıyor."""
    if not is_safe_external_url(feed_url):
        raise ValueError(f"Güvenli olmayan/desteklenmeyen feed URL'si reddedildi: {feed_url!r}")
    parsed = feedparser.parse(feed_url)
    source_name = parsed.feed.get("title", feed_url)
    since_dt = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)

    results = []
    for entry in parsed.entries:
        published_dt = _parse_entry_date(entry)
        if published_dt and published_dt.tzinfo is None:
            published_dt = published_dt.replace(tzinfo=timezone.utc)
        if published_dt and published_dt < since_dt:
            continue

        title = entry.get("title", "")
        summary = entry.get("summary", "") or entry.get("description", "")
        raw_text = f"{title}\n{summary}"

        results.append({
            "title": title,
            "url": entry.get("link", ""),
            "summary": summary,
            "raw_text": raw_text,
            "published_at": published_dt.isoformat() if published_dt else None,
            "source": source_name,
            "cves": extract_cves(raw_text),
        })
    return results


def fetch_all_news(since: date) -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    for feed_url in config.NEWS_FEEDS:
        try:
            all_items.extend(fetch_rss_feed(feed_url, since))
        except Exception:
            # Tek bir feed'in çökmesi tüm koşuyu düşürmesin; hata run_pipeline
            # tarafında collector_runs tablosuna loglanır.
            raise
    return all_items


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=15))
def fetch_cisa_kev() -> set[str]:
    """CISA'nın aktif exploit edilen CVE listesini çeker. Öncelik skorlamasında
    kullanılır. Ağ erişimi yoksa ya da liste alınamazsa boş set döner (pipeline
    bu durumda o günkü koşuda KEV bonusunu es geçer, çökmez)."""
    try:
        resp = httpx.get(config.CISA_KEV_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return {v["cveID"] for v in data.get("vulnerabilities", []) if v.get("cveID")}
    except (httpx.HTTPError, ValueError, KeyError):
        return set()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=15))
def fetch_cisa_kev_full() -> list[dict[str, Any]]:
    """fetch_cisa_kev()'in aksine sadece CVE ID seti değil, tam kayıtları
    (vendor/product/isim/tarih) döner - src/kev_watch.py'ın Telegram
    uyarısında anlamlı bir mesaj üretebilmesi için gerekli. fetch_cisa_kev()
    ile aynı endpoint olduğu için aynı retry (429/5xx) politikası - kev_watch
    saatlik çalıştığı için bu eksikti, tek seferlik geçici bir hata gereksiz
    yere o saatlik koşuyu es geçtiriyordu (bkz. kev_watch.main() try/except -
    retry olmadan tek hata = tüm saatlik koşu boşa gider)."""
    resp = httpx.get(config.CISA_KEV_URL, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("vulnerabilities", [])
