"""Akademik makale toplayıcılar.

Her fonksiyon aynı normalize sözlük şeklini döndürür:
{title, authors[], doi, arxiv_id, openalex_id, venue, publication_date,
 abstract, pdf_url, source_api}

Tasarım ilkesi (bkz. proje notları): "kaçırmamak" için tek kaynağa güvenmiyoruz,
aynı anahtar kelimeyi 4 kaynağa paralel soruyoruz; dedup katmanı DOI/arXiv ID
üzerinden DB'de zaten hallediyor.

Not: Bu fonksiyonlar gerçek API uç noktalarını kullanır ancak bu ortamda ağ
erişimi kapalı olduğu için test edilememiştir - kendi sunucunuzda ilk koşuda
`--dry-run` ile (bkz. run_pipeline.py) tek tek doğrulamanızı öneririz. Kaynak
siteler zaman zaman endpoint/parametre değiştirebilir.
"""
from __future__ import annotations

import fcntl
import os
import random
import time
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any

import fitz  # PyMuPDF
import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .. import config
from ..security import is_safe_external_url

_TIMEOUT = httpx.Timeout(20.0)
_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _is_retryable(exc: BaseException) -> bool:
    """Çoğu 4xx (ör. Unpaywall'da kayıtlı olmayan bir DOI için 404) kalıcı
    bir durumdur, tekrar denemek sonucu değiştirmez - sadece zaman
    kaybettirir. Ama 429 (rate limit, ör. API key'siz Semantic Scholar)
    tam tersi: TAM OLARAK retry+backoff için var olan geçici bir durum -
    onu 5xx'lerle birlikte retry ediyoruz."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return isinstance(exc, httpx.HTTPError)


def _retry_get(url: str, **kwargs) -> httpx.Response:
    @retry(
        # 3/15 canlıda Semantic Scholar'ın API key'liyken bile verdiği 429'larda
        # (30 günlük geniş taramada tekrar tekrar görüldü, collector_runs'ta
        # kayıtlı) bazen yetersiz kalıyordu - sadece zaten başarısız olan
        # isteklerde devreye girdiği için 4/25'e çıkarmanın başarılı isteklere
        # maliyeti yok.
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=25),
        retry=retry_if_exception(_is_retryable),
        # reraise=True olmadan tenacity, deneme hakları biterse orijinal
        # httpx.HTTPStatusError yerine tenacity.RetryError fırlatır - bu da
        # çağıranların "except httpx.HTTPError" bloklarını atlayıp pipeline'ı
        # çökertir (canlıda başımıza geldi). reraise=True her durumda son
        # gerçek istisnayı fırlatmasını garanti eder.
        reraise=True,
    )
    def _do() -> httpx.Response:
        # follow_redirects=True: httpx varsayılan olarak yönlendirmeyi takip
        # etmez, sonra raise_for_status() bunu "Redirect response" hatası
        # olarak fırlatır. arXiv'in http:// uç noktası https'e 301 atıyor -
        # bu olmadan arXiv kaynağı HER ZAMAN sessizce başarısız oluyordu
        # (canlıda başımıza geldi, arXiv'den hiç makale gelmiyordu).
        resp = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True, **kwargs)
        resp.raise_for_status()
        return resp

    return _do()


# ---------------------------------------------------------------------------
# Host-bazlı rate limiter - TÜM modlarda (normal incremental VE recovery)
# ortak, koşulsuz temel katman.
#
# 2026-09-14 ikinci tur temizliği (kullanıcı isteği - "rate limit
# mimarisini temizle"): önceki turda arXiv/OpenAlex'in güçlü limiter'ını
# normal pipeline'da da kullanabilmek için `recovery_mode` HER incremental
# koşuda True zorlanmıştı - bu, `recovery_mode`'un ANLAMINI bozdu (artık
# "gerçek recovery/backfill" değil, "limiter aç" anlamına gelmişti).
# Şimdi temiz ayrım: host-limiter (_ARXIV_LIMITER/_OPENALEX_LIMITER/
# _SEMANTIC_SCHOLAR_LIMITER, aşağıda) her İKİ modda da `_get_with_limiter`
# üzerinden KOŞULSUZ uygulanır; `recovery_mode` SADECE gerçek recovery/
# backfill'e özel EK, daha temkinli politikayı (daha uzun timeout +
# Retry-After'a uyan 30/60/120/300sn backoff merdiveni, bkz.
# `_recovery_backoff_get`) açar. Limiter'ı açıp kapatan bir switch DEĞİL.
#
# Min-interval değerleri canlı ölçümle kalibre edildi: arXiv 2026-09-11
# recovery pilotunda ~20 art arda sorguda 429'a düştü (12sn'de stabilize
# oldu), OpenAlex 2026-09-13 tam aylık koşuda %44 429 verdi (8sn), Semantic
# Scholar 2026-09-14'te normal incremental koşuda API key'liyken bile 429
# verdi (son 24 saatte 6 denemenin 2'si - 5sn ilk değer, canlı ölçümle
# ayarlanmadı, gerekirse güncellenir).
# ---------------------------------------------------------------------------
_RECOVERY_BACKOFF_LADDER = (30.0, 60.0, 120.0, 300.0)
_RECOVERY_TIMEOUT = httpx.Timeout(50.0)  # normal _TIMEOUT'tan (20s) kasıtlı daha uzun - SADECE recovery_mode


class _HostRequestLimiter:
    """Bir host için, TÜM profillerin (daily_cyber ve varsa research profile A/B) VE
    normal/recovery HER İKİ modun PAYLAŞTIĞI global "son çağrı ne zamandı"
    durumu.

    2026-09-15 CANLI ARIZA DÜZELTMESİ: bu sınıfın önceki hâli "bu projede
    zaten tek thread/senkron çalışıldığı için concurrency=1 otomatik
    sağlanıyor" varsayımıyla SADECE process-içi bellekte (`_last_call_
    monotonic`) durum tutuyordu. Bu varsayım TEK BİR process içinde doğru
    ama YANLIŞ bir genelleme yapıyordu: `src.run_pipeline` (günlük radar,
    systemd timer) ve `scripts.run_recovery` (manuel, uzun süre çalışan
    backfill) AYRI OS process'leri - her biri kendi belleğinde AYRI bir
    limiter nesnesi kurup "son çağrı" saatini SIFIRDAN sayıyordu. 2026-09-15
    08:43'teki canlı koşuda TAM OLARAK bu oldu: gece başlatılmış 2 aylık bir
    recovery taraması hâlâ arXiv'e istek atarken, 08:43'teki normal günlük
    koşu da AYNI ANDA arXiv'e gitti - iki process birbirinden habersiz,
    ikisi de "12 saniye oldu" sanıp eşzamanlı/yakın istek attı, arXiv'in
    sunucu tarafı bunu 429/timeout ile cezalandırdı (bkz. collector_runs,
    2026-09-15 run). Şimdi `lock_file` verilirse (üç canlı limiter da
    verir) durum `fcntl.flock` ile korunan KÜÇÜK bir dosyada tutulur -
    hangi process'ten geldiğine bakmaksızın GERÇEK global minimum aralığı
    garanti eder. `lock_file=None` (varsayılan, testlerde/tek-process
    senaryolarda) eski process-içi davranışa düşer."""

    def __init__(self, min_interval_seconds: float, lock_file: str | None = None):
        self.min_interval_seconds = min_interval_seconds
        self.lock_file = lock_file
        self._last_call_monotonic = 0.0

    def wait_for_slot(self) -> None:
        if self.lock_file:
            self._wait_for_slot_cross_process()
        else:
            self._wait_for_slot_in_process()

    def _wait_for_slot_in_process(self) -> None:
        elapsed = time.monotonic() - self._last_call_monotonic
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        self._last_call_monotonic = time.monotonic()

    def _wait_for_slot_cross_process(self) -> None:
        """`time.monotonic()` process'ler arası KARŞILAŞTIRILAMAZ (her
        process kendi başlangıcından sayar) - bu yüzden burada `time.time()`
        (duvar saati) kullanılır, lock dosyasında saklanır. `fcntl.flock`
        (LOCK_EX) hem "oku-hesapla-yaz" adımını atomik yapar hem de aynı
        anda birden fazla process'in çakışan bir bekleme hesaplamasını
        engeller - process A beklerken kilit AÇIK kalır (dosya kilitliyken
        sleep ediyoruz), process B'nin AYNI ANDA "henüz erken değil"
        sanıp erken istek atması yapısal olarak İMKANSIZ hale gelir."""
        os.makedirs(os.path.dirname(self.lock_file), exist_ok=True)
        with open(self.lock_file, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                raw = f.read().strip()
                try:
                    last_call = float(raw) if raw else 0.0
                except ValueError:
                    last_call = 0.0
                elapsed = time.time() - last_call
                if elapsed < self.min_interval_seconds:
                    time.sleep(self.min_interval_seconds - elapsed)
                f.seek(0)
                f.truncate()
                f.write(repr(time.time()))
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


_RATE_LIMIT_LOCK_DIR = os.path.join(config.DATA_DIR, "state")
_ARXIV_LIMITER = _HostRequestLimiter(12.0, lock_file=os.path.join(_RATE_LIMIT_LOCK_DIR, "ratelimit_arxiv.lock"))
_OPENALEX_LIMITER = _HostRequestLimiter(8.0, lock_file=os.path.join(_RATE_LIMIT_LOCK_DIR, "ratelimit_openalex.lock"))
_SEMANTIC_SCHOLAR_LIMITER = _HostRequestLimiter(
    5.0, lock_file=os.path.join(_RATE_LIMIT_LOCK_DIR, "ratelimit_semantic_scholar.lock")
)


# 2026-09-13: OpenAlex retry denemesinde ~52 dakika HİÇBİR collector_runs
# satırı üretmeden "askıda" kaldı (canlıda gözlemlendi, işlem elle
# durduruldu) - en olası açıklama: 429 yanıtındaki Retry-After header'ı
# kullanıcı isteğiyle ("Retry-After varsa ona uy") HARFİYEN uygulandı ama
# sunucu çok uzun (dakikalarca/saatlerce) bir değer istemiş olabilir -
# "kibar" davranış interaktif/oturum-bazlı bir koşu için PRATİK DEĞİL hale
# geldi. Bu yüzden Retry-After'a UYULUYOR ama merdivenin kendi tavanıyla
# (300sn) SINIRLANIYOR - sunucu daha uzun isterse bunu bir sonraki ayrı
# denemeye (deferred_external_limit -> ayrı catch-up job) bırakıyoruz,
# tek bir çağrıda süresiz beklemiyoruz.
_RETRY_AFTER_CAP_SECONDS = _RECOVERY_BACKOFF_LADDER[-1]


def _get_with_limiter(
    url: str, params: dict[str, Any], limiter: _HostRequestLimiter, headers: dict[str, str] | None = None
) -> httpx.Response:
    """2026-09-14: normal (incremental) VE recovery HER İKİSİ İÇİN ORTAK
    temel katman - host-limiter (min-interval spacing, `_ARXIV_LIMITER`/
    `_OPENALEX_LIMITER`/`_SEMANTIC_SCHOLAR_LIMITER`) + `_retry_get`'in
    bounded tenacity retry'ı (4 deneme, 2-25sn, 20sn timeout). `recovery_
    mode` bunu açıp kapatan bir switch DEĞİL - limiter burada HER ZAMAN
    aktif; gerçek recovery/backfill'in FARKI sadece `_recovery_backoff_get`
    (aşağıda) ile gelen EK, daha temkinli politika (daha uzun timeout +
    Retry-After'a uyan daha agresif backoff)."""
    limiter.wait_for_slot()
    return _retry_get(url, params=params, headers=headers)


def _recovery_backoff_get(
    url: str, params: dict[str, Any], limiter: _HostRequestLimiter, headers: dict[str, str] | None = None
) -> httpx.Response:
    """SADECE gerçek recovery/backfill/historical-recovery çağrıları için
    (bkz. run_pipeline.py'de `recovery_mode=True` geçilen yerler - normal
    günlük incremental koşu bu fonksiyona HİÇ girmez, `_get_with_limiter`
    kullanır). 429'da: Retry-After header'ı varsa ona uy (ama
    _RETRY_AFTER_CAP_SECONDS'la SINIRLI - bkz. yukarıdaki not), yoksa
    30/60/120/300sn merdiveni (+ küçük jitter). Timeout'ta da AYNI
    merdivenle retry - ama SONSUZ DEĞİL, merdiven biterse gerçek istisna
    yukarı fırlatılır (çağıran _collect_profile zaten tek-kaynak hatasını
    yutup diğer kaynaklara devam ediyor - bkz. proje ilkesi)."""
    last_exc: Exception | None = None
    for wait_before_giveup in (*_RECOVERY_BACKOFF_LADDER, None):
        limiter.wait_for_slot()
        try:
            resp = httpx.get(url, params=params, timeout=_RECOVERY_TIMEOUT, follow_redirects=True, headers=headers)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            last_exc = e
            if e.response.status_code != 429 or wait_before_giveup is None:
                raise
            retry_after = e.response.headers.get("Retry-After")
            try:
                wait_s = min(float(retry_after), _RETRY_AFTER_CAP_SECONDS) if retry_after else wait_before_giveup
            except ValueError:
                # Retry-After bazen saniye yerine bir HTTP-date string'i
                # olabilir (RFC 7231) - parse etmeye uğraşmak yerine
                # merdivenin kendi değerine düş, güvenli varsayılan.
                wait_s = wait_before_giveup
        except httpx.TimeoutException as e:
            last_exc = e
            if wait_before_giveup is None:
                raise
            wait_s = wait_before_giveup
        wait_s += random.uniform(0, wait_s * 0.1)  # küçük jitter - senkronize retry dalgalarını dağıt
        time.sleep(wait_s)
    raise last_exc or RuntimeError("recovery backoff merdiveni tükendi")  # pragma: no cover - unreachable


def search_openalex(
    keyword: str, since: date, per_page: int = 25, until: date | None = None, recovery_mode: bool = False
) -> list[dict[str, Any]]:
    """https://docs.openalex.org/api-entities/works/search-works

    `until`: 2026-09-13 recovery backfill için eklendi (bkz. src/recovery/) -
    OpenAlex sunucu tarafında gerçek bir date-range filtresi destekliyor
    (to_publication_date). Normal günlük pipeline çağrıları HİÇBİR ZAMAN
    `until` geçmez (varsayılan None = eskisiyle BİREBİR aynı açık-uçlu
    davranış - "mevcut çalışan mimariyi bozma" ilkesi).

    `recovery_mode`: 2026-09-13 tam aylık recovery pilotunda OpenAlex 100
    denemenin 44'ünde 429 aldı (arXiv kadar ağır değil ama gerçek). 2026-
    09-14 temizliği: `_OPENALEX_LIMITER` (host-limiter, 8sn) artık BU
    parametreden bağımsız HER ZAMAN uygulanıyor (bkz. _get_with_limiter) -
    `recovery_mode=True` SADECE EK bir politika açar (daha uzun timeout +
    Retry-After'a uyan backoff merdiveni, bkz. _recovery_backoff_get)."""
    filter_parts = [f"from_publication_date:{since.isoformat()}"]
    if until is not None:
        filter_parts.append(f"to_publication_date:{until.isoformat()}")
    params = {
        "search": keyword,
        "filter": ",".join(filter_parts),
        "per-page": per_page,
        "sort": "publication_date:desc",
    }
    if config.CONTACT_EMAIL:
        params["mailto"] = config.CONTACT_EMAIL

    url = "https://api.openalex.org/works"
    resp = (
        _recovery_backoff_get(url, params, _OPENALEX_LIMITER)
        if recovery_mode
        else _get_with_limiter(url, params, _OPENALEX_LIMITER)
    )
    results = []
    for w in resp.json().get("results", []):
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
            "source_api": "openalex",
            **_openalex_journal_meta(w),
        })
    return results


def _openalex_journal_meta(w: dict[str, Any]) -> dict[str, Any]:
    """journal_registry doğrulaması (bkz. research/journal_lookup.py) için
    ISSN/yayıncı/doküman türü - CANLI doğrulandı (issn_l + issn listesi +
    host_organization_name + type alanları gerçekten dönüyor). Not: OpenAlex
    print/electronic ISSN'i AYIRMIYOR, `issn` listesinde ikisi de olabilir -
    issn_l birincil (representative) olanı, listedeki farklı bir eleman
    varsa onu eissn olarak alıyoruz (best-effort, journal_registry eşleşmesi
    için yeterli - SCIE/quartile gibi KESİN bir yargı burada ÜRETİLMİYOR)."""
    src = (w.get("primary_location") or {}).get("source") or {}
    issn_list = src.get("issn") or []
    issn_l = src.get("issn_l")
    eissn = next((i for i in issn_list if i != issn_l), None)
    return {
        "issn": issn_l or (issn_list[0] if issn_list else None),
        "eissn": eissn,
        "publisher": src.get("host_organization_name"),
        "document_type": w.get("type"),
    }


def _reconstruct_openalex_abstract(inverted_index: dict[str, list[int]] | None) -> str | None:
    """OpenAlex abstract'ı ters index olarak döner (telif nedeniyle); burada
    düz metne geri çeviriyoruz."""
    if not inverted_index:
        return None
    positions: dict[int, str] = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word
    if not positions:
        return None
    return " ".join(positions[i] for i in sorted(positions))


def search_openalex_historical(
    keyword: str, before: date, per_page: int = 5, candidate_pool: int = 25
) -> list[dict[str, Any]]:
    """"Geçmişten Öne Çıkanlar" için: `before` tarihinden ESKİ, aynı anahtar
    kelimeyle konu olarak gerçekten eşleşen makelelerden en çok atıf alanları
    döner.

    Bilinçli iki aşamalı seçim: doğrudan `sort=cited_by_count:desc` ile
    aramak, "cybersecurity" gibi geniş bir kelimeyle SciPy/edgeR/Massive MIMO
    gibi konuyla alakasız ama dev atıf sayılı makaleleri döndürüyor (OpenAlex
    saf metin eşleşmesini gevşek yapıyor, atıf sırası konu alaka düzeyini hiç
    hesaba katmıyor - gerçek bir koşuda başımıza geldi). Bunun yerine önce
    OpenAlex'in varsayılan relevance skoruyla (sort parametresi YOK) geniş bir
    aday havuzu (`candidate_pool`, varsayılan 25) çekilir, sonra bu havuz
    içinde Python tarafında `cited_by_count`'a göre yeniden sıralanıp en
    tepedeki `per_page` kadarı alınır - yani "konuyla gerçekten ilgili olanlar
    arasından en çok atıf alanlar", "internette en çok atıf alan her ne olursa
    olsun" değil."""
    params = {
        "search": keyword,
        "filter": f"to_publication_date:{before.isoformat()}",
        "per-page": candidate_pool,
    }
    if config.CONTACT_EMAIL:
        params["mailto"] = config.CONTACT_EMAIL

    # 2026-09-14: AYNI host (api.openalex.org) - search_openalex ile AYNI
    # _OPENALEX_LIMITER'ı paylaşır, ayrı bir "historical" limiter icat
    # edilmedi (tek host, tek gerçek rate-limit penceresi).
    resp = _get_with_limiter("https://api.openalex.org/works", params, _OPENALEX_LIMITER)
    candidates = sorted(
        resp.json().get("results", []),
        key=lambda w: w.get("cited_by_count") or 0,
        reverse=True,
    )[:per_page]
    results = []
    for w in candidates:
        oa = w.get("open_access") or {}
        doi = (w.get("doi") or "").replace("https://doi.org/", "") or None
        abstract = _reconstruct_openalex_abstract(w.get("abstract_inverted_index"))
        if not abstract and doi:
            # Eski/kapalı erişim (özellikle Elsevier) yayınlarda OpenAlex'in
            # abstract_inverted_index'i çoğu zaman boş geliyor - Türkçe özet
            # üretilebilmesi için Semantic Scholar'dan DOI ile tek seferlik
            # bir fallback deniyoruz. Bulunamazsa sessizce None kalır, uydurma
            # yapılmaz (paper_analyst zaten "özet yok" durumunu ayrı ele alıyor).
            abstract = _fetch_abstract_by_doi(doi)
        results.append({
            "title": w.get("title") or "",
            "authors": [
                a.get("author", {}).get("display_name", "")
                for a in w.get("authorships", [])
                if a.get("author")
            ],
            "doi": doi,
            "arxiv_id": None,
            "openalex_id": w.get("id"),
            "venue": (w.get("primary_location") or {}).get("source", {}).get("display_name")
                if (w.get("primary_location") or {}).get("source") else None,
            "publication_date": w.get("publication_date"),
            "abstract": abstract,
            "pdf_url": oa.get("oa_url"),
            "source_api": "openalex_historical",
            **_openalex_journal_meta(w),
            "cited_by_count": w.get("cited_by_count"),
        })
    return results


def _fetch_abstract_by_doi(doi: str) -> str | None:
    """Semantic Scholar'da DOI ile tekil makale araması - sadece abstract
    fallback'i için. Hata/404/rate-limit durumunda None döner, çağıranı
    (search_openalex_historical) hiç etkilemez."""
    try:
        headers = {"x-api-key": config.SEMANTIC_SCHOLAR_API_KEY} if config.SEMANTIC_SCHOLAR_API_KEY else {}
        resp = httpx.get(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
            params={"fields": "abstract"},
            headers=headers,
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("abstract")
    except httpx.HTTPError:
        return None


def search_crossref(keyword: str, since: date, rows: int = 25, until: date | None = None) -> list[dict[str, Any]]:
    """https://api.crossref.org/swagger-ui/index.html

    `until`: bkz. search_openalex docstring'i - AYNI gerekçe/geriye
    uyumluluk garantisi (normal koşu asla geçmez)."""
    filter_parts = [f"from-pub-date:{since.isoformat()}"]
    if until is not None:
        filter_parts.append(f"until-pub-date:{until.isoformat()}")
    params = {
        "query": keyword,
        "filter": ",".join(filter_parts),
        "rows": rows,
        "sort": "published",
        "order": "desc",
    }
    headers = {}
    if config.CONTACT_EMAIL:
        headers["User-Agent"] = f"CyberIntelligenceRadar/0.1 (mailto:{config.CONTACT_EMAIL})"

    resp = _retry_get("https://api.crossref.org/works", params=params, headers=headers)
    results = []
    for item in resp.json().get("message", {}).get("items", []):
        date_parts = (item.get("published") or item.get("issued") or {}).get("date-parts", [[None]])
        pub_date = _date_parts_to_iso(date_parts[0]) if date_parts else None
        results.append({
            "title": (item.get("title") or [""])[0],
            "authors": [
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in item.get("author", [])
            ],
            "doi": item.get("DOI"),
            "arxiv_id": None,
            "openalex_id": None,
            "venue": (item.get("container-title") or [None])[0],
            "publication_date": pub_date,
            "abstract": item.get("abstract"),
            "pdf_url": None,
            "source_api": "crossref",
            **_crossref_journal_meta(item),
        })
    return results


def _crossref_journal_meta(item: dict[str, Any]) -> dict[str, Any]:
    """journal_registry doğrulaması için ISSN/yayıncı/doküman türü - CANLI
    doğrulandı (`issn-type` alanı print/electronic'i AÇIKÇA ayırıyor, OpenAlex'in
    aksine). issn-type yoksa (çoğu kayıt) ilk ISSN'i genel `issn` say."""
    issn_list = item.get("ISSN") or []
    issn_type = item.get("issn-type") or []
    eissn = next((t["value"] for t in issn_type if t.get("type") == "electronic"), None)
    issn = next((t["value"] for t in issn_type if t.get("type") == "print"), None) or (
        issn_list[0] if issn_list else None
    )
    return {
        "issn": issn,
        "eissn": eissn,
        "publisher": item.get("publisher"),
        "document_type": item.get("type"),
    }


def _date_parts_to_iso(parts: list[int | None]) -> str | None:
    if not parts or parts[0] is None:
        return None
    y = parts[0]
    m = parts[1] if len(parts) > 1 else 1
    d = parts[2] if len(parts) > 2 else 1
    try:
        return date(y, m or 1, d or 1).isoformat()
    except ValueError:
        return f"{y:04d}-01-01"


def _parse_arxiv_response(resp_text: str, since: date, until: date | None = None) -> list[dict[str, Any]]:
    root = ET.fromstring(resp_text)
    results = []
    for entry in root.findall("atom:entry", _ARXIV_NS):
        published = entry.findtext("atom:published", default="", namespaces=_ARXIV_NS)
        pub_date = published[:10] if published else None
        if pub_date and pub_date < since.isoformat():
            continue
        # arXiv API sunucu tarafında date-range desteklemiyor - `until` client-
        # side filtreleniyor (bkz. search_openalex docstring'indeki gerekçe).
        if until is not None and pub_date and pub_date > until.isoformat():
            continue
        arxiv_url = entry.findtext("atom:id", default="", namespaces=_ARXIV_NS)
        arxiv_id = arxiv_url.rsplit("/", 1)[-1] if arxiv_url else None
        pdf_url = None
        for link in entry.findall("atom:link", _ARXIV_NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href")
        results.append({
            "title": (entry.findtext("atom:title", default="", namespaces=_ARXIV_NS) or "").strip(),
            "authors": [
                a.findtext("atom:name", default="", namespaces=_ARXIV_NS)
                for a in entry.findall("atom:author", _ARXIV_NS)
            ],
            "doi": None,
            "arxiv_id": arxiv_id,
            "openalex_id": None,
            "venue": "arXiv",
            "publication_date": pub_date,
            "abstract": (entry.findtext("atom:summary", default="", namespaces=_ARXIV_NS) or "").strip(),
            "pdf_url": pdf_url,
            "source_api": "arxiv",
        })
    return results


def search_arxiv(
    keyword: str, since: date, max_results: int = 25, until: date | None = None, recovery_mode: bool = False
) -> list[dict[str, Any]]:
    """https://info.arxiv.org/help/api/user-manual.html
    arXiv API tarih filtresi desteklemiyor; en yeniye göre sıralayıp
    sonradan `since`/`until` ile Python tarafında filtreliyoruz (`until`:
    bkz. search_openalex docstring'indeki gerekçe - recovery backfill için,
    normal koşu asla geçmez). `recovery_mode`: 2026-09-14 temizliği -
    `_ARXIV_LIMITER` (host-limiter, 12sn) artık BU parametreden bağımsız
    HER ZAMAN uygulanıyor (bkz. _get_with_limiter); `recovery_mode=True`
    SADECE EK bir politika açar (bkz. _recovery_backoff_get docstring'i)."""
    params = {
        "search_query": f'all:"{keyword}" AND cat:cs.CR',
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    url = "https://export.arxiv.org/api/query"
    resp = (
        _recovery_backoff_get(url, params, _ARXIV_LIMITER)
        if recovery_mode
        else _get_with_limiter(url, params, _ARXIV_LIMITER)
    )
    return _parse_arxiv_response(resp.text, since, until)


def search_arxiv_query(
    search_query: str, since: date, max_results: int = 25, until: date | None = None, recovery_mode: bool = False
) -> list[dict[str, Any]]:
    """search_arxiv()'ten farkı: `search_query`'yi OLDUĞU GİBİ (zaten alan
    öneki + AND/OR/parantez içeren, bkz. research/query_builder.build_arxiv)
    gönderir - search_arxiv gibi `all:"..."` içine SARMAZ, sarma boolean
    yapıyı bozardı. `until`: bkz. _parse_arxiv_response (client-side).
    `recovery_mode`: bkz. search_arxiv docstring'i."""
    params = {
        "search_query": search_query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    url = "https://export.arxiv.org/api/query"
    resp = (
        _recovery_backoff_get(url, params, _ARXIV_LIMITER)
        if recovery_mode
        else _get_with_limiter(url, params, _ARXIV_LIMITER)
    )
    return _parse_arxiv_response(resp.text, since, until)


_S2_FIELDS = "title,authors,externalIds,venue,publicationDate,abstract,openAccessPdf"


def _s2_headers() -> dict[str, str]:
    return {"x-api-key": config.SEMANTIC_SCHOLAR_API_KEY} if config.SEMANTIC_SCHOLAR_API_KEY else {}


def _parse_s2_paper(p: dict[str, Any], source_api: str) -> dict[str, Any]:
    ext = p.get("externalIds") or {}
    oa_pdf = p.get("openAccessPdf") or {}
    return {
        "title": p.get("title") or "",
        "authors": [a.get("name", "") for a in p.get("authors", [])],
        "doi": ext.get("DOI"),
        "arxiv_id": ext.get("ArXiv"),
        "openalex_id": None,
        "venue": p.get("venue"),
        "publication_date": p.get("publicationDate"),
        "abstract": p.get("abstract"),
        "pdf_url": oa_pdf.get("url"),
        "source_api": source_api,
        "s2_paper_id": p.get("paperId"),
    }


def search_semantic_scholar(
    keyword: str, since: date, limit: int = 25, until: date | None = None
) -> list[dict[str, Any]]:
    """https://api.semanticscholar.org/api-docs/graph - düz metin arama,
    boolean YOK (bkz. research/query_builder.py docstring). `until`: S2
    `publicationDateOrYear` gerçek bir "from:to" aralığını destekliyor -
    verilirse sunucu tarafında uygulanır (bkz. search_openalex docstring)."""
    params = {
        "query": keyword,
        "limit": limit,
        "fields": _S2_FIELDS,
        "publicationDateOrYear": f"{since.isoformat()}:{until.isoformat() if until else ''}",
    }
    # 2026-09-14: bkz. _SEMANTIC_SCHOLAR_LIMITER tanımı - API key'liyken bile
    # 429 ölçüldüğü için host-limiter'a taşındı. `_get_with_limiter` (base
    # katman) kullanılıyor - S2 için ayrı bir "recovery policy" bu projede
    # hiç var olmadı (bkz. section 8 ilkesi: recovery politikası SADECE
    # gerçekten recovery/backfill olan yollara özel), bilinçli olarak
    # koşulsuz/tek yol.
    resp = _get_with_limiter(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params, _SEMANTIC_SCHOLAR_LIMITER, headers=_s2_headers(),
    )
    return [_parse_s2_paper(p, "semantic_scholar") for p in resp.json().get("data", [])]


def search_semantic_scholar_bulk(
    query: str, since: date, limit: int = 100, until: date | None = None
) -> list[dict[str, Any]]:
    """https://api.semanticscholar.org/graph/v1/paper/search/bulk - boolean
    destekli uç nokta (`+`=AND, `|`=OR, `"..."`=phrase, bkz.
    research/query_builder.build_semantic_scholar_bulk). Normal /paper/search
    bu söz dizimini YORUMLAMAZ, karakterleri düz metin sanır - bu yüzden
    search_semantic_scholar()'dan AYRI, farklı bir uç noktaya gidiyor.
    Sayfalama `token` ile yapılır ama bir koşuda tek sayfa (limit kadar)
    yeterli - profile başına zaten çoklu query + snowball var, tüm
    sonuçları çekmeye çalışmak günlük Gemini bütçesini (relevance filtresi
    her yeni satır için 1 çağrı tüketiyor) anlamsızca şişirir."""
    params = {
        "query": query,
        "fields": _S2_FIELDS,
        "publicationDateOrYear": f"{since.isoformat()}:{until.isoformat() if until else ''}",
    }
    # 2026-09-14: bkz. search_semantic_scholar - AYNI gerekçe/limiter.
    resp = _get_with_limiter(
        "https://api.semanticscholar.org/graph/v1/paper/search/bulk",
        params, _SEMANTIC_SCHOLAR_LIMITER, headers=_s2_headers(),
    )
    data = resp.json().get("data", []) or []
    return [_parse_s2_paper(p, "semantic_scholar_bulk") for p in data[:limit]]


def resolve_pdf(doi: str | None, arxiv_id: str | None) -> tuple[str | None, str | None]:
    """FULL_TEXT çözümleme: önce Unpaywall (DOI varsa), sonra arXiv PDF linki.
    Paywall bypass yapılmaz - sadece açık erişim sürümleri aranır.
    Döner: (pdf_url, source) ya da (None, None)."""
    if doi and config.CONTACT_EMAIL:
        try:
            resp = _retry_get(
                f"https://api.unpaywall.org/v2/{doi}",
                params={"email": config.CONTACT_EMAIL},
            )
            data = resp.json()
            best = data.get("best_oa_location") or {}
            if best.get("url_for_pdf"):
                return best["url_for_pdf"], "unpaywall"
        except httpx.HTTPError:
            pass
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}", "arxiv"
    return None, None


# 2026-09-15 (download safety - bkz. proje notları/master plan): tek bir
# devasa ya da kötü niyetli PDF yanıtı belleği/diski şişirmesin diye sert
# tavan. 4GB RAM'li tek sunucuda 50MB zaten çoğu akademik PDF'in kat kat
# üstü - normal kullanımı ETKİLEMEZ, anormal bir yanıtı erken keser.
_MAX_PDF_BYTES = 50 * 1024 * 1024


def download_and_extract_pdf(pdf_url: str, paper_key: str) -> tuple[str | None, str | None]:
    """PDF'i indirir, diske kaydeder (data/academic/pdf/{key}.pdf) ve
    PyMuPDF ile düz metne çevirir. Başarısız olursa (None, None) döner -
    bu durumda çağıran taraf ABSTRACT_ONLY seviyesinde devam eder.
    Döner: (local_path, extracted_text)

    2026-09-15: pdf_url (Unpaywall/arXiv'den geliyor - bkz. resolve_pdf)
    fetch'ten ÖNCE SSRF kontrolünden geçer (bkz. src/security.py); yanıt
    RAM'e tek seferde alınmadan STREAM edilir ve _MAX_PDF_BYTES'ı aşan bir
    gövde erken kesilir (download safety)."""
    if not is_safe_external_url(pdf_url):
        return None, None
    try:
        with httpx.stream("GET", pdf_url, timeout=_TIMEOUT, follow_redirects=True) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "").lower()
            if "pdf" not in content_type and not pdf_url.lower().endswith(".pdf"):
                return None, None
            content_length = resp.headers.get("content-length")
            if content_length and int(content_length) > _MAX_PDF_BYTES:
                return None, None
            chunks = bytearray()
            for chunk in resp.iter_bytes():
                chunks.extend(chunk)
                if len(chunks) > _MAX_PDF_BYTES:
                    return None, None
    except (httpx.HTTPError, ValueError):
        return None, None

    os.makedirs(config.PDF_DIR, exist_ok=True)
    safe_key = "".join(c if c.isalnum() or c in "-._" else "_" for c in paper_key)[:150]
    local_path = os.path.join(config.PDF_DIR, f"{safe_key}.pdf")
    with open(local_path, "wb") as f:
        f.write(chunks)

    try:
        doc = fitz.open(local_path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
    except Exception:
        text = None

    return local_path, (text or None)


COLLECTORS = {
    "openalex": search_openalex,
    "crossref": search_crossref,
    "arxiv": search_arxiv,
    "semantic_scholar": search_semantic_scholar,
}
