"""Cyber Intelligence Radar - ana pipeline.

Çalıştırma: proje kök dizininden
    python3 -m src.run_pipeline

Akış: topla -> dedup -> ilgililik filtrele -> derin analiz -> NotebookLM
export -> brifing üret -> Telegram'a gönder -> pipeline_state güncelle.

Her adım kendi try/except'iyle sarılı: tek bir kaynağın/feed'in çökmesi tüm
koşuyu düşürmez, hata collector_runs tablosuna loglanır.
"""
from __future__ import annotations

import os
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from . import config, db, digest, notify, notebooklm_export, retention
from .collectors import (
    academic, citation_graph, datacite, dblp, doaj, news as news_collector, openaire, opencitations, openreview,
)
from .dedup import (
    has_new_deterministic_ioc_evidence,
    is_material_news_update,
    is_same_event,
    merge_news_analysis,
    normalize_title,
)
from .llm import curriculum, news_analyst, paper_analyst, relevance
from .llm.budget import NamedBudget
from .research import citation_relationships, journal_lookup, profiles as research_profiles, query_builder
from .research.profiles import ResearchProfile


# ---------------------------------------------------------------------------
# Akademik: upsert + dedup
# ---------------------------------------------------------------------------
def _upsert_paper(conn, item: dict, is_historical: bool = False, matched_profile: str | None = None) -> None:
    norm_title = normalize_title(item.get("title", ""))
    if not norm_title:
        return

    existing = conn.execute(
        """
        SELECT id, source_apis, matched_profiles, journal_verified FROM papers
        WHERE (doi IS NOT NULL AND doi = %(doi)s)
           OR (arxiv_id IS NOT NULL AND arxiv_id = %(arxiv_id)s)
           OR (openalex_id IS NOT NULL AND openalex_id = %(openalex_id)s)
           OR normalized_title = %(norm_title)s
        LIMIT 1
        """,
        {
            "doi": item.get("doi"),
            "arxiv_id": item.get("arxiv_id"),
            "openalex_id": item.get("openalex_id"),
            "norm_title": norm_title,
        },
    ).fetchone()

    if existing:
        source_apis = sorted(set(existing["source_apis"] or []) | {item["source_api"]})
        matched_profiles = sorted(set(existing["matched_profiles"] or []) | ({matched_profile} if matched_profile else set()))
        conn.execute(
            """
            UPDATE papers
            SET source_apis = %(source_apis)s, matched_profiles = %(matched_profiles)s,
                -- COALESCE: bu makale daha önce ISSN'siz bir kaynaktan (ör.
                -- arXiv) gelmişse, şimdi ISSN'li bir kaynaktan (OpenAlex/
                -- Crossref) geldiğinde metadata'yı ZENGİNLEŞTİR - var olan
                -- dolu bir değeri asla BOŞLA ÜZERİNE YAZMA.
                issn = COALESCE(papers.issn, %(issn)s),
                eissn = COALESCE(papers.eissn, %(eissn)s),
                publisher = COALESCE(papers.publisher, %(publisher)s),
                document_type = COALESCE(papers.document_type, %(document_type)s)
            WHERE id = %(id)s
            """,
            {
                "source_apis": source_apis,
                "matched_profiles": matched_profiles,
                "issn": item.get("issn"),
                "eissn": item.get("eissn"),
                "publisher": item.get("publisher"),
                "document_type": item.get("document_type"),
                "id": existing["id"],
            },
        )
        if not existing.get("journal_verified") and (item.get("issn") or item.get("eissn")):
            journal_lookup.verify_and_apply(conn, existing["id"], item.get("issn"), item.get("eissn"))
        return

    row = conn.execute(
        """
        INSERT INTO papers (doi, arxiv_id, openalex_id, title, normalized_title, authors,
                             venue, publication_date, abstract, pdf_url, source_apis, is_historical,
                             cited_by_count, matched_profiles, issn, eissn, publisher, document_type)
        VALUES (%(doi)s, %(arxiv_id)s, %(openalex_id)s, %(title)s, %(norm_title)s, %(authors)s::jsonb,
                %(venue)s, %(publication_date)s, %(abstract)s, %(pdf_url)s, %(source_apis)s, %(is_historical)s,
                %(cited_by_count)s, %(matched_profiles)s, %(issn)s, %(eissn)s, %(publisher)s, %(document_type)s)
        RETURNING id
        """,
        {
            "doi": item.get("doi"),
            "arxiv_id": item.get("arxiv_id"),
            "openalex_id": item.get("openalex_id"),
            "title": (item.get("title") or "")[:1000],
            "norm_title": norm_title,
            "authors": db.to_jsonb(item.get("authors") or []),
            "venue": item.get("venue"),
            "publication_date": item.get("publication_date") or None,
            "abstract": item.get("abstract"),
            "pdf_url": item.get("pdf_url"),
            "source_apis": [item["source_api"]],
            "is_historical": is_historical,
            "cited_by_count": item.get("cited_by_count"),
            "matched_profiles": [matched_profile] if matched_profile else [],
            "issn": item.get("issn"),
            "eissn": item.get("eissn"),
            "publisher": item.get("publisher"),
            "document_type": item.get("document_type"),
        },
    ).fetchone()
    if item.get("issn") or item.get("eissn"):
        journal_lookup.verify_and_apply(conn, row["id"], item.get("issn"), item.get("eissn"))


# ---------------------------------------------------------------------------
# V1.1 research profiles: profil başına toplama (bkz. src/research/profiles.py,
# src/research/query_builder.py)
# ---------------------------------------------------------------------------
def _collect_profile(
    conn,
    profile: ResearchProfile,
    since_date: date,
    until_date: date | None = None,
    run_type: str = "incremental",
    recovery_run_id: int | None = None,
    sources: set[str] | None = None,
) -> int:
    """mode='daily' (varsayılan aktif profil) için academic.COLLECTORS'ın
    düz-keyword fonksiyonlarını DEĞİŞTİRMEDEN çağırır - mevcut günlük radar
    davranışı birebir korunur. mode='sci'/'thesis' için query_builder'ın
    ürettiği, her kaynağın GERÇEKTEN desteklediği sorgu string'ini kullanır.
    Döner: bu profilde toplanan toplam kayıt sayısı.

    `until_date`/`run_type`/`recovery_run_id`: 2026-09-13 recovery backfill
    için eklendi (bkz. src/recovery/) - normal pipeline çağrıları bunları
    HİÇBİR ZAMAN geçirmez (varsayılanlar None/'incremental'/None = eskisiyle
    BİREBİR aynı davranış).

    Her kaynak çağrısı arasına RECOVERY_INTER_CALL_DELAY_SECONDS kadar
    bekleme eklenir (spec F: "API'lere yüzlerce paralel request atma - rate
    limiter kullan"). Başlangıçta SADECE run_type != 'incremental' dalında
    çalışıyordu - gerekçe "normal günlük koşu tek bir kelime işliyor, bu
    sorunu hiç yaşamıyor" idi (bkz. 2026-09-11 doğrulama turu: arXiv art
    arda ~20 sorguda 429'a düşmüştü, ama o an KEYWORDS tek kelimeydi).

    2026-09-14 güncellemesi: bu varsayım artık GEÇERSİZ - KEYWORDS (.env) o
    tarihten beri 3 kelimeye çıkmış durumda ("cybersecurity,threat
    intelligence,SOC"), yani normal incremental koşu da artık kaynak başına
    3 ayrı sorgu atıyor. collector_runs, 13-14 Eylül'deki ART ARDA
    incremental koşularda arXiv/OpenAlex/Semantic Scholar'ın tekrar tekrar
    429 verdiğini gösterdi. Bu yüzden gecikme artık run_type'tan BAĞIMSIZ,
    HER koşuda uygulanıyor - arXiv'in resmi kılavuzu zaten "3 saniyede 1
    istek"i önerdiği için mevcut varsayılan (3.0s) ek bir ayara gerek
    kalmadan hem recovery hem normal koşu için yeterli TÜM kaynaklar arası
    genel bir taban oluşturuyor (crossref/openaire/openreview/datacite gibi
    kendi host-limiter'ı OLMAYAN kaynaklar için).

    2026-09-14 ikinci tur (rate limit mimarisi temizliği): arXiv/OpenAlex/
    Semantic Scholar'ın kendi ÖLÇÜLMÜŞ, daha sıkı host-limiter'ları (12sn/
    8sn/5sn) artık bu genel gecikmeden AYRI, academic.py içinde `recovery_
    mode`'dan bağımsız HER ZAMAN uygulanıyor (bkz. academic._get_with_
    limiter) - `recovery_mode` parametresi (aşağıda) artık SADECE gerçek
    recovery/backfill'e özel EK politikayı (daha uzun timeout + Retry-
    After'a uyan backoff merdiveni) açıp kapatıyor, limiter'ın kendisini
    DEĞİL.

    `sources`: verilirse SADECE bu isimlerdeki kaynaklar çağrılır (diğerleri
    hiç denenmez, log'a bile yazılmaz) - 2026-09-13 eklendi (bkz.
    src/recovery/collect.py): arXiv kendi ayrı, çok daha yavaş/temkinli
    checkpoint'ine sahip olsun diye diğer kaynaklardan AYRI çağrılabiliyor
    (`sources={'arxiv'}` / `sources=ALL - {'arxiv'}`). None = eskisiyle
    BİREBİR aynı (hepsi çağrılır) - normal pipeline hiç kullanmıyor."""
    total = 0
    for built in query_builder.build_all(profile):
        if profile.mode == "daily":
            # built.groups == [keyword] (bkz. profiles.load_active_profiles) -
            # eski `for keyword in config.KEYWORDS` döngüsüyle birebir aynı.
            keyword = built.groups[0]
            for name, fn in academic.COLLECTORS.items():
                if sources is not None and name not in sources:
                    continue
                # 2026-09-14: run_type gate'i kaldırıldı - bkz. bu fonksiyonun
                # docstring'i, normal incremental koşu da artık 429 alıyor.
                time.sleep(config.RECOVERY_INTER_CALL_DELAY_SECONDS)
                # 2026-09-14 ikinci tur temizliği (kullanıcı isteği - "rate
                # limit mimarisini temizle"): recovery_mode artık SADECE
                # gerçek recovery/backfill anlamına geliyor - host-limiter
                # (12sn/8sn arXiv/OpenAlex için) academic.py içinde HER
                # koşulda koşulsuz uygulanıyor (bkz. academic._get_with_
                # limiter), bu satır SADECE recovery'ye özel EK politikayı
                # (daha uzun timeout + Retry-After'a uyan backoff merdiveni)
                # açıp kapatıyor.
                kwargs = (
                    {"recovery_mode": True}
                    if name in ("arxiv", "openalex") and run_type != "incremental"
                    else {}
                )
                try:
                    items = fn(keyword, since_date, until=until_date, **kwargs)
                    for item in items:
                        _upsert_paper(conn, item, matched_profile=profile.id)
                    db.log_collector_run(
                        conn, name, "academic", f"[{profile.id}] {keyword}", len(items),
                        run_type=run_type, recovery_run_id=recovery_run_id,
                    )
                    total += len(items)
                except Exception as e:  # noqa: BLE001 - bir kaynağın hatası taramayı durdurmasın
                    db.log_collector_run(
                        conn, name, "academic", f"[{profile.id}] {keyword}", None, str(e),
                        run_type=run_type, recovery_run_id=recovery_run_id,
                    )
            continue

        per_collector = {
            "openalex": lambda: academic.search_openalex(
                built.openalex, since_date, per_page=profile.per_query_max_results, until=until_date,
                recovery_mode=(run_type != "incremental"),  # bkz. _collect_profile'daki 2026-09-14 notu
            ),
            "crossref": lambda: academic.search_crossref(
                built.crossref, since_date, rows=profile.per_query_max_results, until=until_date
            ),
            "arxiv": lambda: academic.search_arxiv_query(
                built.arxiv, since_date, max_results=profile.per_query_max_results, until=until_date,
                recovery_mode=(run_type != "incremental"),  # bkz. _collect_profile'daki 2026-09-14 notu
            ),
            "semantic_scholar": lambda: academic.search_semantic_scholar_bulk(
                built.semantic_scholar_bulk, since_date, limit=profile.per_query_max_results, until=until_date
            ),
            # V1.1 free/no-key federasyon eklemeleri (bkz. proje notları).
            # Üçü de GERÇEK boolean desteği CANLI doğrulanmadı (OpenAlex/arXiv'in
            # aksine) - bu yüzden bag-of-words (build_crossref ile AYNI string,
            # Crossref'in zaten kabul ettiği yaklaşım) kullanıyoruz: hiçbir zaman
            # kırılmaz, precision'ı Level 1 relevance filtresine bırakır.
            "openaire": lambda: openaire.search(
                built.crossref, since_date, page_size=profile.per_query_max_results, until=until_date
            ),
            "openreview": lambda: openreview.search(
                built.crossref, since_date, limit=profile.per_query_max_results, until=until_date
            ),
            # DataCite artık bağlı (research profile'lar... ayrıca
            # DataCite kullan") - src/collectors/datacite.py daha önce bilinçli
            # olarak pipeline'a bağlanmamıştı (bkz. o modülün docstring'i),
            # V1 finalizasyonuyla eksik parça tamamlandı. dataset/software DOI
            # kayıtları - tezin/SCI'nin "dataset mevcut mu?" sorusuna DOI-tabanlı
            # gerçek bir doğrulama katkısı.
            "datacite": lambda: datacite.search(
                built.crossref, since_date, page_size=profile.per_query_max_results, until=until_date
            ),
        }
        # DBLP: bkz. ACCEPTANCE-02 - production host'tan da bot-korumasına
        # takıldığı doğrulandı (dış, kod-dışı bir engel). BİLİNÇLİ OLARAK
        # varsayılan KAPALI (config.DBLP_ENABLED=false) - her koşuda boşuna
        # tekrar tekrar denenmesin diye. 'disabled_degraded_optional' olarak
        # loglanır (credential eksikliğinden AYRI bir kategori - bkz.
        # config.OPTIONAL_ACADEMIC_SOURCES/_log_disabled_optional_sources).
        # DBLP erişimi düzelirse DBLP_ENABLED=true ile tekrar açılabilir,
        # kod DEĞİŞTİRİLMEDEN. (until_date desteklemiyor - recovery
        # backfill'de de bilinçli olarak kapalı kalır, spec E.)
        if sources is None or "dblp" in sources:
            if config.DBLP_ENABLED:
                per_collector["dblp"] = lambda: dblp.search(built.crossref, since_date, hits=profile.per_query_max_results)
            else:
                db.log_collector_run(
                    conn, "dblp", "academic", f"[{profile.id}] {built.label}", None, "disabled_degraded_optional",
                    run_type=run_type, recovery_run_id=recovery_run_id,
                )
        for name, fn in per_collector.items():
            if sources is not None and name not in sources:
                continue
            # 2026-09-14: run_type gate'i kaldırıldı - bkz. bu fonksiyonun
            # docstring'i, normal incremental koşu da artık 429 alıyor.
            time.sleep(config.RECOVERY_INTER_CALL_DELAY_SECONDS)
            query_label = f"[{profile.id}] {built.label}"
            try:
                items = fn()
                for item in items:
                    _upsert_paper(conn, item, matched_profile=profile.id)
                db.log_collector_run(
                    conn, name, "academic", query_label, len(items),
                    run_type=run_type, recovery_run_id=recovery_run_id,
                )
                total += len(items)
            except Exception as e:  # noqa: BLE001 - bir sorgunun hatası taramayı durdurmasın
                db.log_collector_run(
                    conn, name, "academic", query_label, None, str(e),
                    run_type=run_type, recovery_run_id=recovery_run_id,
                )
    return total


def _snowball_profile(conn, profile: ResearchProfile) -> int:
    """Bu profille eşleşmiş, relevance_status='relevant' olan makalelerden
    (en yüksek confidence'lı snowball_seed_limit kadarı) 1-hop citation
    snowballing yapar (bkz. src/collectors/citation_graph.py). YALNIZCA
    profile.snowball=True olan profiller için çağrılır (bkz. main()) -
    daily_cyber ASLA snowball etmez. Döner: eklenen yeni kayıt sayısı."""
    if not profile.snowball:
        return 0
    seeds = conn.execute(
        """
        SELECT id, doi, arxiv_id, title
        FROM papers
        WHERE relevance_status = 'relevant' AND %s = ANY(matched_profiles)
        ORDER BY (relevance->>'confidence')::numeric DESC NULLS LAST
        LIMIT %s
        """,
        (profile.id, profile.snowball_seed_limit),
    ).fetchall()
    if not seeds:
        return 0
    try:
        snowballed = citation_graph.snowball_from_seeds(list(seeds), profile.snowball_seed_limit)
    except Exception as e:  # noqa: BLE001 - snowball hatası tüm koşuyu düşürmesin
        db.log_collector_run(conn, "citation_graph", "academic", f"[{profile.id}] snowball", None, str(e))
        snowballed = []

    # OpenCitations: Semantic Scholar'dan BAĞIMSIZ ikinci bir citation graph
    # kaynağı (bkz. src/collectors/opencitations.py, proje notları). Sadece
    # DOI'si olan seed'ler için anlamlı (OpenCitations DOI-tabanlı çalışıyor).
    try:
        oc_dois: list[str] = []
        for s in seeds:
            if s.get("doi"):
                oc_dois.extend(opencitations.get_reference_dois(s["doi"]))
                oc_dois.extend(opencitations.get_citation_dois(s["doi"]))
        if oc_dois:
            oc_papers = opencitations.resolve_dois(list(dict.fromkeys(oc_dois))[:100])
            snowballed.extend(oc_papers)
            db.log_collector_run(conn, "opencitations", "academic", f"[{profile.id}] snowball", len(oc_papers))
    except Exception as e:  # noqa: BLE001
        db.log_collector_run(conn, "opencitations", "academic", f"[{profile.id}] snowball", None, str(e))

    for item in snowballed:
        _upsert_paper(conn, item, matched_profile=profile.id)
    db.log_collector_run(conn, "citation_graph", "academic", f"[{profile.id}] snowball", len(snowballed))
    return len(snowballed)


def _log_disabled_optional_sources(conn) -> None:
    """Credential gerektiren kaynaklar için (bkz. config.OPTIONAL_ACADEMIC_SOURCES)
    HENÜZ collector yazılmadı - bunları sessizce atlamak yerine her koşuda
    collector_runs'a 'disabled_missing_credentials' yazıyoruz ki coverage
    raporunda "bu kaynak 0 katkı yaptı" ile "bu kaynak hiç denenmedi, key
    yok" birbirine karışmasın."""
    for name, env_var in config.OPTIONAL_ACADEMIC_SOURCES.items():
        if not os.getenv(env_var):
            db.log_collector_run(conn, name, "academic", None, None, "disabled_missing_credentials")


# ---------------------------------------------------------------------------
# "Geçmişten Öne Çıkanlar": KEYWORDS için en çok atıf almış, güncel olmayan
# makaleleri bulur. Her koşuda değil - HISTORICAL_SCAN_INTERVAL'da bir
# tetiklenir (klasik/temel makaleler zaten değişmiyor, her 2 saatte bir
# aynı sonuçları tekrar sorgulamanın OpenAlex'e karşı bir anlamı yok).
# ---------------------------------------------------------------------------
HISTORICAL_SCAN_INTERVAL = timedelta(days=7)
HISTORICAL_CUTOFF_DAYS = 180
HISTORICAL_PER_KEYWORD = 3


def _maybe_collect_historical(conn) -> int:
    last_str = db.get_state(conn, "last_historical_scan_at")
    last_dt = datetime.fromisoformat(last_str) if last_str else None
    if last_dt and datetime.now(timezone.utc) - last_dt < HISTORICAL_SCAN_INTERVAL:
        return 0

    cutoff = date.today() - timedelta(days=HISTORICAL_CUTOFF_DAYS)
    total = 0
    for keyword in config.KEYWORDS:
        try:
            items = academic.search_openalex_historical(keyword, cutoff, per_page=HISTORICAL_PER_KEYWORD)
            for item in items:
                _upsert_paper(conn, item, is_historical=True)
            db.log_collector_run(conn, "openalex_historical", "academic", keyword, len(items))
            total += len(items)
        except Exception as e:  # noqa: BLE001 - bir anahtar kelimenin hatası taramayı durdurmasın
            db.log_collector_run(conn, "openalex_historical", "academic", keyword, None, str(e))

    db.set_state(conn, "last_historical_scan_at", datetime.now(timezone.utc).isoformat())
    return total


def _select_historical_highlights(conn, limit: int = 5) -> list[dict]:
    """Her koşuda gösterilecek "Geçmişten Öne Çıkanlar" listesi. Keşif
    (_maybe_collect_historical) haftada bir yeni aday bulur ama gösterim HER
    koşuda olur - havuzdaki ilgili/analiz edilmiş geçmiş makaleler arasından
    en son gösterilmeyenler (historical_shown_at NULLS FIRST) seçilir, aynı 5
    makale sürekli tekrar etmesin diye seçilenlerin historical_shown_at'ı
    hemen güncellenir (bir sonraki koşu farklılarını seçer, havuz yeterince
    büyüdükçe rotasyon anlamlı olur)."""
    rows = conn.execute(
        """
        SELECT * FROM papers
        WHERE is_historical = true AND relevance_status = 'relevant' AND analyzed_at IS NOT NULL
        ORDER BY historical_shown_at ASC NULLS FIRST, analyzed_at DESC
        LIMIT %s
        """,
        (limit,),
    ).fetchall()
    if rows:
        conn.execute(
            "UPDATE papers SET historical_shown_at = now() WHERE id = ANY(%s)",
            ([r["id"] for r in rows],),
        )
    return rows


def _resurface_stale_must_reads(conn, days: int = 21, limit: int = 2) -> list[dict]:
    """Kullanıcı isteği: "MUST_READ olup üç haftadır okumadığın makaleleri
    sistem tekrar gündeme getirebilir." unutulmuş MUST_READ'leri (hâlâ
    reading_status='unread', analyzed_at en az `days` gün önce) bulur.
    is_historical hariç - o zaten kendi rotasyonuna sahip."""
    return conn.execute(
        """
        SELECT * FROM papers
        WHERE is_historical = false
          AND reading_status = 'unread'
          AND (analysis->>'reading_priority') = 'MUST_READ'
          AND analyzed_at < now() - (%s || ' days')::interval
        ORDER BY analyzed_at ASC
        LIMIT %s
        """,
        (days, limit),
    ).fetchall()


_RECOMMEND_COOLDOWN_DAYS = 14

# PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md W1): eşikler -
# "yüksek personal relevance" ve "yüksek SCI/tez katkısı" için config'e
# taşınmadı (bilinçli - bunlar zaten var olan RELEVANCE_THRESHOLD_HIGH'tan
# FARKLI bir eksen, ayrı bir config eklemek W1'in kapsamını gereğinden
# büyütür), sabit ama isimlendirilmiş sabitler olarak tutuluyor.
_READ_NOW_HIGH_RELEVANCE_CONFIDENCE = 0.8
_READ_NOW_HIGH_PROFILE_SCORE = 7


def _read_now_reason(p: dict) -> str:
    """W1: önerilen tek makale için 1-2 cümlelik "neden şimdi" açıklaması -
    UYDURMA YOK, sadece zaten var olan alanlardan (why_read/why_relevant/
    thesis_relevance_reason/relevance confidence) seçilir."""
    a = p.get("analysis") or {}
    if a.get("reading_priority") == "MUST_READ" and a.get("why_read"):
        return a["why_read"]
    extraction = a.get("profile_extraction") or {}
    sci_score = extraction.get("sci_relevance_score") or 0
    if sci_score >= _READ_NOW_HIGH_PROFILE_SCORE and extraction.get("why_relevant"):
        return extraction["why_relevant"]
    thesis_score = extraction.get("thesis_relevance_score") or 0
    if thesis_score >= _READ_NOW_HIGH_PROFILE_SCORE and extraction.get("thesis_relevance_reason"):
        return extraction["thesis_relevance_reason"]
    conf = (p.get("relevance") or {}).get("confidence")
    if conf:
        return f"İlgi alanınla yüksek örtüşme gösteriyor (relevance: {conf:.0%})."
    return "Şu ana kadar okunmamış, değerlendirmesi güçlü bir makale."


def _select_read_now_recommendation(
    conn, exclude_ids: set[int] | None = None, cooldown_days: int = _RECOMMEND_COOLDOWN_DAYS
) -> dict | None:
    """W1 (PHASE 10, docs/FUNCTIONAL_GAP_ANALYSIS.md): digest sonunda TEK
    bir "📚 Oku Şimdi" önerisi - MUST_READ + personal relevance + SCI/tez
    katkısı + unread + not-recently-recommended sinyallerinin BİRLEŞİK
    skoruna göre TÜM korpustan (sadece bugünkü seçimlerden değil) tek bir
    aday seçer. `exclude_ids` - bugünkü digest'te zaten AYRI gösterilen
    makaleler (Current/Timeline/Historical/SCI/Thesis) - aynı makale aynı
    digest'te iki kez "oku" denmesin diye. Cooldown - papers.
    last_recommended_at, _send_feedback_followups'taki MUST_READ
    cooldown'uyla AYNI alan/mantık (genişletildi, yeni tablo YOK)."""
    row = conn.execute(
        """
        SELECT *,
          (CASE WHEN analysis->>'reading_priority' = 'MUST_READ' THEN 10 ELSE 0 END)
          + COALESCE((relevance->>'confidence')::numeric, 0) * 10
          + COALESCE((analysis#>>'{profile_extraction,sci_relevance_score}')::numeric, 0)
          + COALESCE((analysis#>>'{profile_extraction,thesis_relevance_score}')::numeric, 0)
          AS read_now_score
        FROM papers
        WHERE reading_status = 'unread'
          AND analyzed_at IS NOT NULL
          AND id != ALL(%(exclude)s)
          AND (last_recommended_at IS NULL OR last_recommended_at < now() - (%(cooldown)s || ' days')::interval)
          AND (
            analysis->>'reading_priority' = 'MUST_READ'
            OR COALESCE((relevance->>'confidence')::numeric, 0) >= %(rel_threshold)s
            OR COALESCE((analysis#>>'{profile_extraction,sci_relevance_score}')::numeric, 0) >= %(profile_threshold)s
            OR COALESCE((analysis#>>'{profile_extraction,thesis_relevance_score}')::numeric, 0) >= %(profile_threshold)s
          )
        ORDER BY read_now_score DESC
        LIMIT 1
        """,
        {
            "exclude": list(exclude_ids or set()) or [0],
            "cooldown": cooldown_days,
            "rel_threshold": _READ_NOW_HIGH_RELEVANCE_CONFIDENCE,
            "profile_threshold": _READ_NOW_HIGH_PROFILE_SCORE,
        },
    ).fetchone()
    if not row:
        return None
    row = dict(row)
    row["_read_now_reason"] = _read_now_reason(row)
    return row


def _send_feedback_followups(
    conn,
    current_papers: list[dict],
    historical_highlights: list[dict],
    analyzed_news: list[dict],
    learning_path_papers: list[dict] | None = None,
    profile_a_papers: list[dict] | None = None,
    profile_b_papers: list[dict] | None = None,
    read_now: dict | None = None,
) -> None:
    """Faz 5 geri bildirim döngüsü + 2026-09-11 genişletmesi (kullanıcı
    isteği: "kayıt butonları tam her makale altında olsun"): o koşuda
    gösterilen HER akademik makale kendi butonlarıyla ayrı bir mesaj olarak
    gönderilir (bkz. digest.PaperCard/build_all_paper_cards) - Telegram
    inline keyboard bir mesajın reply_markup'ına bağlı olduğu için bunun
    tek yolu budur. digest.generate_brief() bu yüzden artık HİÇBİR
    akademik makaleyi bulk metne TAM yazmıyor (sadece bölüm başlığı + kısa
    yönlendirme notu) - buradaki mesajlar o makalelerin TEK VE YEGANE
    sunumudur. "best" (Klasik) seçimi digest.py'dekiyle AYNI mantık (max
    historical_score) olduğu için iki taraf TUTARLI.

    Madde 10 (okuma durumu): "Aynı makaleyi sürekli 'Oku Şimdi' olarak
    önermesin" - SADECE MUST_READ kategorisi için: reading_status hâlâ
    'unread' olsa BİLE, papers.last_recommended_at ile bu makale
    _RECOMMEND_COOLDOWN_DAYS içinde ZATEN önerilmişse TEKRAR önerilmez.
    Diğer kategoriler (CURRENT/TIMELINE/CLASSIC/HISTORICAL/SCI/THESIS) bu
    ek cooldown'a TABİ DEĞİL - kendi seçim fonksiyonlarındaki rotasyon
    (recent_shown_at/learning_path_shown_at/sci_digest_shown_at/vb.)
    zaten aynı makalenin her gün tekrarlanmasını engelliyor."""
    paper_cards = {
        c.paper_id: c
        for c in digest.build_all_paper_cards(
            current_papers, learning_path_papers or [], historical_highlights,
            profile_a_papers or [], profile_b_papers or [], read_now=read_now,
        )
    }
    paper_targets: list[tuple[int, str]] = []  # (paper_id, TAM kart metni)
    if read_now:
        # W1: seçim SQL'i zaten unread + cooldown-geçmiş şartını uyguladı -
        # burada TEKRAR kontrol GEREKMEZ, sadece gönder + cooldown'u başlat
        # (AYNI last_recommended_at alanı - MUST_READ mekanizmasıyla PAYLAŞILIR,
        # bkz. _select_read_now_recommendation docstring'i).
        card = paper_cards.get(read_now["id"])
        if card:
            paper_targets.append((read_now["id"], card.text))
            conn.execute("UPDATE papers SET last_recommended_at = now() WHERE id = %s", (read_now["id"],))
    # MUST_READ makaleler AYRI bir cooldown mantığından geçiyor (aşağıda) -
    # bu setteki HİÇBİR id fallback döngüsünde TEKRAR işlenmemeli, cooldown
    # nedeniyle bu koşuda ATLANMIŞ olsa bile (aksi halde cooldown'u fallback
    # döngüsü ezerdi).
    must_read_ids = {p["id"] for p in current_papers if (p.get("analysis") or {}).get("reading_priority") == "MUST_READ"}

    for p in current_papers:
        if p["id"] not in must_read_ids:
            continue
        card = paper_cards.get(p["id"])
        if not card:
            continue
        row = conn.execute(
            "SELECT reading_status, last_recommended_at FROM papers WHERE id = %s", (p["id"],)
        ).fetchone()
        if row["reading_status"] != "unread":
            continue
        if row["last_recommended_at"]:
            cooldown = conn.execute(
                "SELECT now() - %s < (%s || ' days')::interval AS still_cooling",
                (row["last_recommended_at"], _RECOMMEND_COOLDOWN_DAYS),
            ).fetchone()
            if cooldown["still_cooling"]:
                continue
        paper_targets.append((p["id"], card.text))
        conn.execute("UPDATE papers SET last_recommended_at = now() WHERE id = %s", (p["id"],))

    # Geri kalan tüm kategoriler (CURRENT/TIMELINE/CLASSIC/HISTORICAL/SCI/
    # THESIS) - ek cooldown YOK (bkz. docstring), MUST_READ id'leri VE
    # read_now (yukarıda ZATEN gönderildi) HARİÇ - aksi halde read_now
    # burada İKİNCİ KEZ gönderilir (duplikasyon).
    read_now_id = read_now["id"] if read_now else None
    for paper_id, card in paper_cards.items():
        if paper_id in must_read_ids or paper_id == read_now_id:
            continue
        paper_targets.append((paper_id, card.text))

    news_targets: list[tuple[int, str]] = []  # (news_id, kısa etiket - bu düzeltmenin kapsamı DIŞINDA, değişmedi)
    for n in analyzed_news:
        if digest.news_tier(n) == "ACTION_REQUIRED":
            news_targets.append((n["id"], f"🚨 Aksiyon Gerekli: {n.get('title')}"))

    for item_id, text in paper_targets:
        message_id = notify.send_interactive(text, notify.feedback_buttons("p", item_id, notes=True))
        if message_id:
            db.record_telegram_message(conn, message_id, "paper", item_id)

    for item_id, text in news_targets:
        message_id = notify.send_interactive(text, notify.feedback_buttons("n", item_id, notes=False))
        if message_id:
            db.record_telegram_message(conn, message_id, "news", item_id)


# PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md G1): "5 Güncel
# Makale" eskiden SADECE novelty/academic_value ile sıralanıyordu - ikisi de
# konu-bağımsız genel LLM yargısı, bu yüzden "yeni ama SOC/threat-hunting
# ile ilgisiz" bir makale (ör. kriptografi) "yeni ve SOC'a doğrudan
# uygulanabilir" bir makaleyle eşit sıralanabiliyordu. domain_contribution_scores
# (paper_analyst.py'de ZATEN her makale için toplanıyor, YENİ bir LLM alanı
# DEĞİL) üzerinden bir konu-yakınlığı bonusu eklendi - okuyucu profiliyle
# (SOC/SIEM/threat-intel/malware/LLM security/DFIR/network security) en
# örtüşen makaleler öne çıkar.
_TOPIC_AFFINITY_DOMAINS = (
    "SOC_SIEM", "Threat_Intelligence", "Malware_Research", "LLM_Security",
    "Digital_Forensics", "Network_Security",
)


def _topic_affinity_boost(analysis: dict) -> float:
    domains = analysis.get("domain_contribution_scores") or {}
    return max((domains.get(d) or 0 for d in _TOPIC_AFFINITY_DOMAINS), default=0)


def _top_n_papers(papers: list[dict], n: int = 5) -> list[dict]:
    """"Yeni Akademik Makaleler" bölümünü de 5 ile sınırlamak için: bu koşuda
    analiz edilen makaleler arasından değer skoruna göre en iyi n tanesi.
    Skor = novelty + academic_value + konu-yakınlığı bonusu (bkz. yukarıdaki
    not) - üçü de 0-10 ölçeğinde, eşit ağırlıklı."""
    def score(p: dict) -> float:
        a = p.get("analysis") or {}
        return (a.get("novelty_score") or 0) + (a.get("academic_value_score") or 0) + _topic_affinity_boost(a)

    return sorted(papers, key=score, reverse=True)[:n]


def _select_current_papers(conn, this_run_papers: list[dict], limit: int = 5) -> list[dict]:
    """"5 Güncel Makale" - SABİT KOTA, reading_priority'den bağımsız (seçim
    önce olur, reading_priority sadece görüntüde etiket olarak kullanılır).

    Önce bu koşuda analiz edilen relevant makalelerden değer skoruna göre en
    iyisi (_top_n_papers). Yetmezse (bu koşu az sonuç getirdiyse) son 30
    günlük relevant havuzdan `recent_shown_at` rotasyonuyla tamamlanır - aynı
    yedek makaleler art arda gelmesin diye historical rotasyonuyla birebir
    aynı desen (ASC NULLS FIRST)."""
    top = _top_n_papers(this_run_papers, n=limit)
    for p in top:
        # PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md U1): bu
        # koşuda toplanmış mı, yoksa 30 günlük havuzdan mı tamamlandı -
        # bkz. _select_news_for_digest'teki AYNI ilke.
        p["_digest_source"] = "FRESH"
    selected = list(top)

    if len(selected) < limit:
        exclude_ids = [p["id"] for p in selected] or [0]
        backfill = conn.execute(
            """
            SELECT * FROM papers
            WHERE is_historical = false AND relevance_status = 'relevant' AND analyzed_at IS NOT NULL
              AND analyzed_at >= now() - interval '30 days'
              AND id != ALL(%s)
            ORDER BY recent_shown_at ASC NULLS FIRST, analyzed_at DESC
            LIMIT %s
            """,
            (exclude_ids, limit - len(selected)),
        ).fetchall()
        for p in backfill:
            p["_digest_source"] = "BACKFILL"
        selected.extend(backfill)

    if selected:
        conn.execute("UPDATE papers SET recent_shown_at = now() WHERE id = ANY(%s)", ([p["id"] for p in selected],))
    return selected


def _dominant_domain(papers: list[dict]) -> str | None:
    totals: dict[str, float] = {}
    for p in papers:
        for k, v in ((p.get("analysis") or {}).get("domain_contribution_scores") or {}).items():
            if v:
                totals[k] = totals.get(k, 0) + v
    return max(totals, key=totals.get) if totals else None


_LEARNING_PATH_SCORE_SQL = (
    "COALESCE((analysis->>'academic_value_score')::numeric, 0) "
    "+ COALESCE((analysis->>'foundational_value_score')::numeric, 0) "
    "+ COALESCE((relevance->>'confidence')::numeric, 0) * 10"
)


def _select_learning_path(conn, target_domain: str | None, exclude_ids: set[int], limit: int = 5) -> list[dict]:
    """"🧭 Temelden Güncele — Son 5 Yıl": son 5 yılın penceresinde, mümkünse
    günün baskın alanıyla (target_domain) aynı araştırma hattından, YAYIN
    TARİHİNE göre eskiden yeniye bir okuma yolu. novelty ana kriter DEĞİL.

    Kademeli gevşetme (kullanıcı isteği: "zorla sahte bağlantı kurma, aynı
    ana topic/domain içinden en iyi gerçek 5 relevant makaleyi seç"):
      1) target_domain'e güçlü katkısı olan (>=5)
      2) target_domain'e herhangi bir katkısı olan (>0)
      3) domain şartı olmadan, pencerede en iyi puanlılar
    Her aşama bir öncekinin eksiğini tamamlar, ASLA rastgele seçmez."""
    since = (date.today() - timedelta(days=5 * 365)).isoformat()
    until = date.today().isoformat()
    selected: list[dict] = []
    seen_ids = set(exclude_ids)

    # (SQL karşılaştırma operatörü, aşama açıklaması) - önce sıkı eşleşme
    # (>=5, "gerçekten bu konuda"), sonra gevşek (>0, "en azından bir miktar
    # ilgili") - kullanıcı isteği: zorla bağlantı kurma, ama tamamen rastgele
    # de seçme.
    domain_stages = [(">=", 5), (">", 0)] if target_domain else []
    for op, threshold in domain_stages:
        if len(selected) >= limit:
            break
        rows = conn.execute(
            f"""
            SELECT * FROM papers
            WHERE is_historical = false AND relevance_status = 'relevant' AND analyzed_at IS NOT NULL
              AND publication_date >= %(since)s AND publication_date <= %(until)s
              AND id != ALL(%(exclude)s)
              AND COALESCE((analysis->'domain_contribution_scores'->>%(domain)s)::numeric, 0) {op} %(threshold)s
            ORDER BY learning_path_shown_at ASC NULLS FIRST, ({_LEARNING_PATH_SCORE_SQL}) DESC
            LIMIT %(limit)s
            """,
            {
                "since": since, "until": until, "exclude": list(seen_ids) or [0],
                "domain": target_domain, "threshold": threshold,
                "limit": limit - len(selected),
            },
        ).fetchall()
        for r in rows:
            if r["id"] not in seen_ids:
                selected.append(r)
                seen_ids.add(r["id"])

    if len(selected) < limit:
        rows = conn.execute(
            f"""
            SELECT * FROM papers
            WHERE is_historical = false AND relevance_status = 'relevant' AND analyzed_at IS NOT NULL
              AND publication_date >= %(since)s AND publication_date <= %(until)s
              AND id != ALL(%(exclude)s)
            ORDER BY learning_path_shown_at ASC NULLS FIRST, ({_LEARNING_PATH_SCORE_SQL}) DESC
            LIMIT %(limit)s
            """,
            {"since": since, "until": until, "exclude": list(seen_ids) or [0], "limit": limit - len(selected)},
        ).fetchall()
        for r in rows:
            if r["id"] not in seen_ids:
                selected.append(r)
                seen_ids.add(r["id"])

    if selected:
        conn.execute(
            "UPDATE papers SET learning_path_shown_at = now() WHERE id = ANY(%s)",
            ([p["id"] for p in selected],),
        )
    selected.sort(key=lambda p: p["publication_date"] or date.min)
    return selected


def _digest_bridge_shown_at_column(profile_id: str) -> str:
    """GENERIC (public export, PHASE 11): hangi profil ID'sinin hangi
    rotasyon kolonunu kullandığı config.RESEARCH_PROFILE_A_ID/_B_ID'den
    (kullanıcı .env'i) gelir - hiçbir profil ID'si koda GÖMÜLÜ değildir.
    Şema iki sabit kolon taşır (research_profile_a/b_digest_shown_at) -
    "Research Profile A/B" iki-slotlu tasarım, N-profilli genel bir
    çözüm DEĞİL (bkz. docs/PUBLIC_EXPORT_PLAN.md kapsam notu)."""
    if profile_id == config.RESEARCH_PROFILE_A_ID:
        return "research_profile_a_digest_shown_at"
    if profile_id == config.RESEARCH_PROFILE_B_ID:
        return "research_profile_b_digest_shown_at"
    raise ValueError(
        f"'{profile_id}' RESEARCH_PROFILE_A_ID/_B_ID olarak yapılandırılmamış - "
        "digest köprüsü sadece bu iki slota atanmış profiller için çalışır."
    )


def _assess_digest_bridge_step(conn, profile: ResearchProfile, budget: NamedBudget) -> int:
    """"🔬 SCI Çalışmamız İçin" / "🎓 Tez Çalışmamız İçin" digest köprüsü:
    matched_profiles içinde bu profil olan, henüz analiz edilmemiş
    (analyzed_at IS NULL) makaleler için AYNI paper_analyst.analyze_paper()
    çağrısını kullanır - profile.extraction_schema İÇİNDEKİ "digest_bridge"
    alanı üzerinden (bkz. profiles/examples/*.yaml)
    YENİ bir LLM çağrısı/agent AÇILMIYOR, mevcut mekanizma yeniden
    kullanılıyor (proje ilkesi: "gereksiz yere tekrar tekrar LLM çağrısı
    yapma").

    relevance_status'a BAKMAZ (2026-09-10 mimari düzeltmesiyle AYNI ilke -
    bkz. src/research/workflow.py screening_step docstring'i: araştırma
    profili makalelerinin çoğu hâlâ 'pending', bu onları digest
    köprüsünden ALIKOYMAMALI). Sonuç AYNI papers.analysis/analyzed_at
    kolonlarına yazılır - bu makale daha sonra _analyze_relevant_papers
    (veya research workflow'un extraction_step'i) tarafından TEKRAR analiz
    EDİLMEZ (analyzed_at zaten dolu) - iki pipeline'ın derin analizleri
    tek, birleşik bir sonuçta buluşur, veri tekrarlanmaz."""
    if not profile.extraction_schema:
        return 0
    rows = conn.execute(
        "SELECT id, title, doi, arxiv_id, abstract, issn, eissn FROM papers "
        "WHERE %s = ANY(matched_profiles) AND analyzed_at IS NULL",
        (profile.id,),
    ).fetchall()
    n = 0
    for r in rows:
        if not budget.has_capacity():
            break
        if r["issn"] or r["eissn"]:
            journal_lookup.verify_and_apply(conn, r["id"], r["issn"], r["eissn"])
        budget.consume()
        try:
            analysis = paper_analyst.analyze_paper(
                r["title"], r["abstract"], None, "ABSTRACT_ONLY", extraction_schema=profile.extraction_schema
            )
        except Exception as e:  # noqa: BLE001 - tek makale hatası koşuyu durdurmasın
            db.log_collector_run(conn, "analysis_llm", "academic", (r["title"] or "")[:200], None, str(e))
            continue
        conn.execute(
            "UPDATE papers SET analysis = %s::jsonb, analyzed_at = now(), analysis_type = 'ABSTRACT_ONLY' WHERE id = %s",
            (db.to_jsonb(analysis), r["id"]),
        )
        n += 1
    return n


def _select_profile_papers_for_digest(conn, profile_id: str, limit: int) -> list[dict]:
    """"🔬 SCI Çalışmamız İçin" / "🎓 Tez Çalışmamız İçin" - TAM `limit` kadar
    GERÇEK aday makale gösterir (kullanıcı isteği: "TAM 5" - sırf sayıyı
    doldurmak için uydurma/alakasız makale EKLENMEZ, sadece gerçekten
    profile-matched adaylar arasından seçilir). Önce digest_bridge'i
    GEÇERLİ olarak analiz edilmiş makaleler (en zengin içerik), yetmezse
    henüz analiz edilmemiş ama gerçek profile-matched diğer adaylarla
    TAMAMLANIR - bu durumda digest o makalenin rubriğini dürüstçe "henüz
    analiz edilmedi" gösterir (bkz. digest._digest_bridge_lines), UYDURMA
    YAPILMAZ. Rotasyon papers.recent_shown_at ile AYNI desen, profile'a
    özel kolon (sci_digest_shown_at/thesis_digest_shown_at) - bir makale
    her iki profille de eşleşse bile rotasyonları birbirini EZMEZ."""
    shown_col = _digest_bridge_shown_at_column(profile_id)
    rows = conn.execute(
        f"""
        SELECT *, (analysis->>'profile_extraction_status' = 'valid') AS has_valid_extraction
        FROM papers
        WHERE %s = ANY(matched_profiles)
        ORDER BY has_valid_extraction DESC NULLS LAST, {shown_col} ASC NULLS FIRST, id DESC
        LIMIT %s
        """,
        (profile_id, limit),
    ).fetchall()
    if rows:
        conn.execute(
            f"UPDATE papers SET {shown_col} = now() WHERE id = ANY(%s)",
            ([r["id"] for r in rows],),
        )
    return rows


_RELATIONSHIP_ENRICH_MAX_PAPERS = 20


def _enrich_relationships(conn, papers: list[dict]) -> None:
    """Phase 2, madde 6: BUILDS_ON/FOUNDATION_FOR (bkz. src/research/
    citation_relationships.py). SADECE digest'te GÖSTERİLECEK makaleler
    için çalışır (current/timeline/classic/historical/SCI/tez - proje
    ilkesi: "detaylı zenginleştirme sadece yüksek-değerli makalelerde"),
    TÜM 763+ makale için DEĞİL - hem OpenCitations'a gereksiz yük
    binmesin hem de "sadece yüzeysel not tutmuyoruz, gerçek referans
    ilişkisi kuruyoruz" ilkesi ekonomik kalsın. builds_on_checked_at
    dolu olan makaleler ATLANIR (idempotent - aynı makale için dış API'ye
    tekrar tekrar sorulmaz, sonuç 0 kenar olsa bile).

    Sonucu papers üzerinde YERİNDE (in-place) `_builds_on`/
    `_foundation_for` anahtarları olarak işaretler - digest.py bunları
    okur, DB'ye tekrar gitmez."""
    candidates = [p for p in papers if p.get("id") and not p.get("builds_on_checked_at")][:_RELATIONSHIP_ENRICH_MAX_PAPERS]
    for p in candidates:
        citation_relationships.compute_builds_on(conn, p["id"], p.get("doi"))
        conn.execute("UPDATE papers SET builds_on_checked_at = now() WHERE id = %s", (p["id"],))

    for p in papers:
        if not p.get("id"):
            continue
        p["_builds_on"] = citation_relationships.get_relationships(conn, p["id"], citation_relationships.BUILDS_ON)
        p["_foundation_for"] = citation_relationships.get_relationships(conn, p["id"], citation_relationships.FOUNDATION_FOR)


_NEWS_DISPLAY_TIERS = ("ACTION_REQUIRED", "HUNT_OPPORTUNITY", "LEARN", "AWARENESS")
_NEWS_BACKFILL_WINDOW_DAYS = 30


_DEFAULT_TIER_TARGETS: dict[str, int] = {
    "ACTION_REQUIRED": 5, "HUNT_OPPORTUNITY": 5, "LEARN": 5, "AWARENESS": 5,
}


def _select_news_for_digest(
    conn,
    analyzed_news: list[dict],
    target_per_tier: int | dict[str, int] = 5,
    window_days: int = _NEWS_BACKFILL_WINDOW_DAYS,
) -> list[dict]:
    """`target_per_tier`: PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md
    A2/Y1) öncesi TEK bir int'ti (4 kategoriye eşit uygulanırdı) - artık
    per-tier bir dict de kabul eder (bkz. config.OPERATIONAL_ACTION_TARGET
    vb. - HER kategori bağımsız ayarlanabilir). Geriye dönük uyumluluk için
    int hâlâ kabul edilir (tüm tier'lara eşit uygulanır, eski davranış
    BİREBİR korunur).

    2026-09-10 kök neden analizinin asıl düzeltmesi: makalelerin aksine
    (bkz. _select_current_papers/_select_historical_highlights) haberlerin
    HİÇBİR backfill/rotasyon mekanizması yoktu - digest sadece BU KOŞUDA
    yeni analiz edilen (analyzed_news) haberleri görüyordu. Günlük LLM
    bütçesi dar olduğunda (araştırma profilleri makale hacmini büyüttüğünde
    bile - artık AYRI havuzlar var ama haber tarafının kendi payı da bazı
    koşularda 0 pending/0 bütçeye denk gelebilir) bu, TÜM 🚨/🕵️/📚/👀
    kategorilerinin "bu dönemde ... yok" yazmasına yol açıyordu - makaleler
    ise backfill sayesinde hep doluydu (asimetrik davranış, canlı log
    kanıtı: 2026-09-10 19:31 koşusu, bkz. proje notları).

    Bu fonksiyon makalelerle AYNI ilkeyi uygular: bu koşuda yeterli yeni
    haber yoksa, DAHA ÖNCE GERÇEKTEN analiz edilmiş ama henüz brifingde
    gösterilmemiş haberlerle (digest_shown_at ASC NULLS FIRST rotasyonu,
    papers.recent_shown_at ile birebir aynı desen) tamamlanır - HİÇBİR
    içerik uydurulmaz, sadece gerçek geçmiş analizin gösterimi ertelenmiş
    olur. ARCHIVE tier'ı (düşük öncelik) backfill'e dahil EDİLMEZ - kotayı
    doldurmak için oraya kaymak kategori anlamını bozar (kullanıcı isteği:
    "kategori anlamını bozma").

    2026-09-14 kök neden düzeltmesi ("sabah-akşam aynı haber neden tekrar
    gösteriliyor?"): bu sorgu digest_shown_at'i SIRALAMA için kullanıyordu
    ama ASLA bir HARİÇ TUTMA koşulu yoktu - LEARN/AWARENESS gibi dar
    havuzlu tier'larda (30 günde tek bir analiz edilmiş haber varsa) aynı
    kayıt, sabah gösterilip digest_shown_at güncellendikten SAATLER SONRA
    akşam koşusunda tekrar "en uygun aday" oluyordu (havuzda başka rakip
    yoktu). Artık: bugün (Europe/Istanbul takvim günü) zaten gösterilmiş
    bir kayıt, o gün içinde ANLAMLI bir değişiklik olmadıkça (bkz.
    material_update_at - SADECE dedup.is_material_news_update() TRUE
    dönerse ileri alınır: yeni CVE, KEV'e sonradan eklenme - bkz.
    _recheck_kev_status_for_material_updates -, active_exploitation/
    exploit_status yükselişi, yeni IOC/hunt artifact, sürüm/mitigation
    bilgisi eklenmesi, severity/operasyonel önem yükselişi. Başka bir
    kaynağın aynı haberi tekrar yazması ya da last_updated_at'in tek
    başına ilerlemesi ASLA material SAYILMAZ - bkz. o fonksiyonun
    docstring'i, madde 2) aday havuzuna HİÇ girmez."""
    targets: dict[str, int] = (
        {t: target_per_tier for t in _NEWS_DISPLAY_TIERS}
        if isinstance(target_per_tier, int)
        else {**_DEFAULT_TIER_TARGETS, **target_per_tier}
    )
    by_tier: dict[str, list[dict]] = {t: [] for t in _NEWS_DISPLAY_TIERS}
    seen_ids: set[int] = set()
    for n in analyzed_news:
        tier = digest.news_tier(n)
        seen_ids.add(n["id"])
        if tier in by_tier and len(by_tier[tier]) < targets[tier]:
            # PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md U1):
            # bu koşuda YENİ analiz edilen mi, yoksa daha önce analiz
            # edilmiş bir DAHA ÖNCEKİ koşudan mı geliyor - digest.py bunu
            # render edebilsin diye seçim anında damgalanıyor.
            n["_digest_source"] = "FRESH"
            by_tier[tier].append(n)

    if any(len(v) < targets[t] for t, v in by_tier.items()):
        candidates = conn.execute(
            """
            SELECT * FROM news_events
            WHERE analyzed_at IS NOT NULL
              AND analyzed_at >= now() - (%s || ' days')::interval
              AND id != ALL(%s)
              AND (
                    digest_shown_at IS NULL
                    OR (digest_shown_at AT TIME ZONE 'Europe/Istanbul')::date
                       < (now() AT TIME ZONE 'Europe/Istanbul')::date
                    OR (material_update_at IS NOT NULL AND material_update_at > digest_shown_at)
                  )
            ORDER BY digest_shown_at ASC NULLS FIRST, analyzed_at DESC
            """,
            (window_days, list(seen_ids) or [0]),
        ).fetchall()
        for cand in candidates:
            if all(len(v) >= targets[t] for t, v in by_tier.items()):
                break
            tier = digest.news_tier(cand)
            if tier not in by_tier or len(by_tier[tier]) >= targets[tier] or cand["id"] in seen_ids:
                continue
            cand["_digest_source"] = "BACKFILL"
            by_tier[tier].append(cand)
            seen_ids.add(cand["id"])

    combined = [n for tier in _NEWS_DISPLAY_TIERS for n in by_tier[tier]]
    if combined:
        conn.execute(
            "UPDATE news_events SET digest_shown_at = now() WHERE id = ANY(%s)",
            ([n["id"] for n in combined],),
        )
    return combined


# ---------------------------------------------------------------------------
# Haber: aynı olayı birleştir ya da yeni event aç
# ---------------------------------------------------------------------------
_RAW_TEXT_MERGE_CAP = 20000  # analyze_news zaten raw_text[:20000] kırpıyor - aynı sınır


def _merge_raw_text(old_text: str | None, new_text: str | None) -> str | None:
    """2026-09-15 (madde 5 - koşullu re-analiz için haberin ham metnini
    büyütür ki bir sonraki analiz YENİ içeriği GERÇEKTEN görsün): source
    repeat (aynı makalenin tekrar fetch edilmesi) new_text'i old_text'in
    İÇİNDE bulur ve HİÇBİR ŞEY eklemez - raw_text'i şişirmez, gereksiz bir
    re-analiz tetiklemez (has_new_deterministic_ioc_evidence zaten bu
    durumda boş küme farkı verir, ama raw_text büyümesin diye burada da
    ayrıca kontrol ediliyor)."""
    old_text = old_text or ""
    new_text = new_text or ""
    if not old_text:
        return new_text
    if not new_text or new_text.strip() in old_text:
        return old_text
    combined = old_text + "\n\n---\n\n" + new_text
    return combined[-_RAW_TEXT_MERGE_CAP:]


def _find_or_merge_news_event(conn, item: dict) -> None:
    window_start = datetime.now(timezone.utc) - timedelta(days=14)
    candidates = conn.execute(
        "SELECT id, title, cves, sources, cisa_kev, priority_label, analysis, "
        "raw_text, analyzed_at FROM news_events WHERE first_seen_at >= %s",
        (window_start,),
    ).fetchall()

    for cand in candidates:
        existing_urls = [s.get("url", "") for s in (cand["sources"] or [])]
        if is_same_event(item["title"], item["cves"], item["url"], cand["title"], cand["cves"] or [], existing_urls):
            sources = cand["sources"] or []
            if item["url"] and not any(s.get("url") == item["url"] for s in sources):
                sources.append({"name": item["source"], "url": item["url"]})
            old_cves = set(cand["cves"] or [])
            merged_cves = sorted(old_cves | set(item["cves"]))
            has_new_cve = bool(set(item["cves"]) - old_cves)
            # 2026-09-14/15 (bkz. _select_news_for_digest docstring'i +
            # dedup.is_material_news_update): material_update_at SADECE
            # TAMAMEN DETERMİNİSTİK bir değişiklik varsa (burada: yeni CVE)
            # merge ANINDA ileri alınır - madde 8: henüz üretilmemiş bir LLM
            # sonucu varmış gibi material timestamp ÜRETİLMEZ, bu yüzden
            # aşağıdaki regex-IOC tetiklemesi BURADA material_update_at'i
            # DEĞİL, sadece re-analiz ihtiyacını işaretler (gerçek material
            # kararı re-analiz tamamlandığında _analyze_relevant_news'te
            # verilir).
            old_snapshot = {
                "cves": cand["cves"] or [], "cisa_kev": cand["cisa_kev"],
                "priority_label": cand["priority_label"], "analysis": cand["analysis"],
            }
            new_snapshot = {**old_snapshot, "cves": merged_cves}
            material = is_material_news_update(old_snapshot, new_snapshot)

            # 2026-09-15 (madde 5/7/11 - "conditional re-analysis" +
            # "deterministic öncelik"): zaten analiz edilmiş bir olaya YENİ
            # deterministik kanıt (yeni CVE YA DA regex ile bulunabilen yeni
            # IP/hash/e-posta) geldiyse, koşullu re-analiz adayı yapılır -
            # analyzed_at=NULL'a çekilir ve mevcut, bütçe-gated
            # _analyze_relevant_news akışından TEKRAR geçer (madde 6: ayrı/
            # sınırsız bir LLM çağrı yolu YOK). Salt source-repeat/title/
            # last_seen/URL varyasyonu ne CVE ne de ham metnin regex-IOC
            # setini değiştirdiği için bunu TETİKLEMEZ.
            merged_raw_text = _merge_raw_text(cand["raw_text"], item["raw_text"])
            has_new_ioc_evidence = has_new_deterministic_ioc_evidence(cand["raw_text"] or "", item["raw_text"] or "")
            needs_reanalysis = cand["analyzed_at"] is not None and (has_new_cve or has_new_ioc_evidence)
            reanalysis_reason = None
            if needs_reanalysis:
                reasons = [r for r, flag in (("new_cve", has_new_cve), ("new_ioc_evidence", has_new_ioc_evidence)) if flag]
                reanalysis_reason = "+".join(reasons)

            conn.execute(
                """
                UPDATE news_events
                SET sources = %s::jsonb, cves = %s, last_updated_at = now(), raw_text = %s,
                    material_update_at = CASE WHEN %s THEN now() ELSE material_update_at END,
                    analyzed_at = CASE WHEN %s THEN NULL ELSE analyzed_at END,
                    pending_reanalysis_reason = CASE WHEN %s THEN %s ELSE pending_reanalysis_reason END
                WHERE id = %s
                """,
                (
                    db.to_jsonb(sources), merged_cves, merged_raw_text, material,
                    needs_reanalysis, needs_reanalysis, reanalysis_reason, cand["id"],
                ),
            )
            return

    conn.execute(
        """
        INSERT INTO news_events (title, dedup_key, summary, sources, published_at, raw_text, cves)
        VALUES (%(title)s, %(dedup_key)s, %(summary)s, %(sources)s::jsonb, %(published_at)s,
                %(raw_text)s, %(cves)s)
        """,
        {
            "title": item["title"][:1000],
            "dedup_key": normalize_title(item["title"]),
            "summary": item["summary"],
            "sources": db.to_jsonb([{"name": item["source"], "url": item["url"]}]),
            "published_at": item.get("published_at"),
            "raw_text": item["raw_text"],
            "cves": item["cves"],
        },
    )


# ---------------------------------------------------------------------------
# Relevance filtresi
# ---------------------------------------------------------------------------
def _classify_pending_papers(conn, budget: NamedBudget) -> None:
    rows = conn.execute("SELECT id, title, abstract FROM papers WHERE relevance_status = 'pending'").fetchall()
    for r in rows:
        if not budget.has_capacity():
            break
        budget.consume()
        try:
            result, status = relevance.classify_paper(r["title"], r["abstract"])
        except Exception as e:  # noqa: BLE001 - tek makale hatası koşuyu durdurmasın
            print(f"  [relevance/paper] {(r['title'] or '')[:80]!r} -> HATA: {e}")
            db.log_collector_run(conn, "relevance_llm", "academic", (r["title"] or "")[:200], None, str(e))
            continue
        print(f"  [relevance/paper] {(r['title'] or '')[:80]!r} -> {status} (bütçe kalan: {budget.remaining})")
        conn.execute(
            "UPDATE papers SET relevance = %s::jsonb, relevance_status = %s WHERE id = %s",
            (db.to_jsonb(result), status, r["id"]),
        )
        if status == "uncertain":
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason, confidence) VALUES ('paper', %s, %s, %s)",
                (r["id"], "relevance_uncertain", result.get("confidence")),
            )


def _classify_pending_news(conn, budget: NamedBudget) -> None:
    rows = conn.execute("SELECT id, title, summary FROM news_events WHERE relevance_status = 'pending'").fetchall()
    for r in rows:
        if not budget.has_capacity():
            break
        budget.consume()
        try:
            result, status = relevance.classify_news(r["title"], r["summary"])
        except Exception as e:  # noqa: BLE001
            print(f"  [relevance/news] {(r['title'] or '')[:80]!r} -> HATA: {e}")
            db.log_collector_run(conn, "relevance_llm", "news", (r["title"] or "")[:200], None, str(e))
            continue
        print(f"  [relevance/news] {(r['title'] or '')[:80]!r} -> {status} (bütçe kalan: {budget.remaining})")
        conn.execute(
            "UPDATE news_events SET relevance = %s::jsonb, relevance_status = %s WHERE id = %s",
            (db.to_jsonb(result), status, r["id"]),
        )
        if status == "uncertain":
            conn.execute(
                "INSERT INTO review_queue (item_type, item_id, reason, confidence) VALUES ('news', %s, %s, %s)",
                (r["id"], "relevance_uncertain", result.get("confidence")),
            )


# ---------------------------------------------------------------------------
# Derin analiz
# ---------------------------------------------------------------------------
def _analyze_relevant_papers(conn, budget: NamedBudget, active_profiles: list[ResearchProfile]) -> list[dict]:
    rows = conn.execute(
        "SELECT id, title, doi, arxiv_id, abstract, matched_profiles, issn, eissn, doaj_indexed FROM papers "
        "WHERE relevance_status = 'relevant' AND analyzed_at IS NULL"
    ).fetchall()

    analyzed: list[dict] = []
    for r in rows:
        if not budget.has_capacity():
            break
        # DOAJ doğrulaması (bkz. src/collectors/doaj.py) - LLM'e/bütçeye
        # dokunmuyor, sadece HTTP. NULL kontrolü: false ile "henüz
        # kontrol edilmedi" karışmasın.
        if r["doaj_indexed"] is None and (r["issn"] or r["eissn"]):
            try:
                match = doaj.check_journal(r["issn"], r["eissn"])
                conn.execute("UPDATE papers SET doaj_indexed = %s WHERE id = %s", (match is not None, r["id"]))
            except Exception:  # noqa: BLE001 - DOAJ erişilemezse sessizce NULL kalır
                pass
        try:
            pdf_url, pdf_source = academic.resolve_pdf(r["doi"], r["arxiv_id"])
        except Exception as e:  # noqa: BLE001 - PDF çözümleme hatası tek makaleyi
            # ABSTRACT_ONLY'e düşürsün, tüm koşuyu düşürmesin.
            db.log_collector_run(conn, "resolve_pdf", "academic", (r["title"] or "")[:200], None, str(e))
            pdf_url, pdf_source = None, None
        full_text, pdf_local, analysis_type = None, None, "ABSTRACT_ONLY"
        if pdf_url:
            key = (r["doi"] or r["arxiv_id"] or str(r["id"])).replace("/", "_")
            try:
                pdf_local, full_text = academic.download_and_extract_pdf(pdf_url, key)
            except Exception:
                pdf_local, full_text = None, None
            if full_text:
                analysis_type = "FULL_TEXT"

        ext_profile = research_profiles.pick_extraction_profile(r["matched_profiles"] or [], active_profiles)
        budget.consume()
        try:
            analysis = paper_analyst.analyze_paper(
                r["title"], r["abstract"], full_text, analysis_type,
                extraction_schema=ext_profile.extraction_schema if ext_profile else None,
            )
        except Exception as e:  # noqa: BLE001
            print(f"  [analiz/makale] {(r['title'] or '')[:80]!r} -> HATA: {e}")
            db.log_collector_run(conn, "analysis_llm", "academic", (r["title"] or "")[:200], None, str(e))
            continue
        print(
            f"  [analiz/makale] {(r['title'] or '')[:80]!r} -> {analysis_type} "
            f"(bütçe kalan: {budget.remaining})"
        )

        conn.execute(
            """
            UPDATE papers
            SET analysis = %s::jsonb, analyzed_at = now(), analysis_type = %s,
                pdf_url = COALESCE(%s, pdf_url), pdf_local_path = %s, pdf_source = %s
            WHERE id = %s
            """,
            (db.to_jsonb(analysis), analysis_type, pdf_url, pdf_local, pdf_source, r["id"]),
        )
        full_row = conn.execute("SELECT * FROM papers WHERE id = %s", (r["id"],)).fetchone()
        analyzed.append(full_row)
    return analyzed


def _recheck_kev_status_for_material_updates(conn, kev_set: set[str]) -> None:
    """2026-09-14 (bkz. main()'deki çağrı noktasının yorumu): zaten analiz
    edilmiş 'relevant' haberlerin cves listesini HER koşuda güncel kev_set'e
    karşı yeniden kontrol eder - LLM'e HİÇ gitmez. Sadece false->true
    geçişini `is_material_news_update` ÜZERİNDEN (ad-hoc bir if DEĞİL, aynı
    paylaşılan deterministik karşılaştırıcı) material_update_at'e yansıtır -
    tutarlılık için, bu geçiş zaten fonksiyonun 2. maddesiyle (KEV false->
    true) HER ZAMAN True döner, ama tek bir karar noktası olsun diye ayrı
    bir if yerine buradan geçiyor."""
    rows = conn.execute(
        "SELECT id, cves, cisa_kev, priority_label, analysis FROM news_events "
        "WHERE relevance_status = 'relevant' AND analyzed_at IS NOT NULL AND cisa_kev = false"
    ).fetchall()
    for r in rows:
        newly_kev = bool(set(r["cves"] or []) & kev_set)
        if not newly_kev:
            continue
        old_snapshot = {
            "cves": r["cves"] or [], "cisa_kev": False,
            "priority_label": r["priority_label"], "analysis": r["analysis"],
        }
        new_snapshot = {**old_snapshot, "cisa_kev": True}
        if is_material_news_update(old_snapshot, new_snapshot):
            conn.execute(
                "UPDATE news_events SET cisa_kev = true, material_update_at = now() WHERE id = %s",
                (r["id"],),
            )
        else:  # pragma: no cover - yapısal olarak ulaşılamaz, bkz. docstring
            conn.execute("UPDATE news_events SET cisa_kev = true WHERE id = %s", (r["id"],))


def _analyze_relevant_news(conn, kev_set: set[str], budget: NamedBudget) -> list[dict]:
    """2026-09-15 (madde 5/6 - "conditional re-analysis"): bu sorgu artık İKİ
    tür satırı BİRLİKTE işler - `analyzed_at IS NULL` hem "hiç analiz
    edilmemiş yeni haber" (analysis/cisa_kev/priority_label hepsi NULL/
    varsayılan) HEM DE "_find_or_merge_news_event'te GERÇEK yeni deterministik
    kanıt (yeni CVE/regex-IOC) bulunduğu için koşullu re-analiz ADAYI
    yapılmış, ESKİ analysis'i hâlâ dolu" satırları demek (bkz. o fonksiyonun
    docstring'i - pending_reanalysis_reason bu ikisini ayırt etmek için
    okunabilir, ama SORGU/BÜTÇE mantığı ikisi için de AYNI: mevcut
    NamedBudget'tan başka HİÇBİR yeni/sınırsız çağrı yolu YOK (madde 6),
    bütçe biterse döngü zaten `break` ile durur ve kalan satırlar
    analyzed_at=NULL olarak bir SONRAKİ koşuya ERTELENİR - pipeline
    ÇÖKMEZ, sadece o satır(lar) "pending" kalır."""
    rows = conn.execute(
        "SELECT id, title, raw_text, cves, cisa_kev, priority_label, analysis, pending_reanalysis_reason "
        "FROM news_events WHERE relevance_status = 'relevant' AND analyzed_at IS NULL"
    ).fetchall()

    analyzed: list[dict] = []
    for r in rows:
        if not budget.has_capacity():
            break
        budget.consume()
        old_analysis = r["analysis"] or {}
        try:
            fresh_analysis = news_analyst.analyze_news(r["title"], r["raw_text"] or "")
        except Exception as e:  # noqa: BLE001
            print(f"  [analiz/haber] {(r['title'] or '')[:80]!r} -> HATA: {e}")
            db.log_collector_run(conn, "analysis_llm", "news", (r["title"] or "")[:200], None, str(e))
            continue

        # 2026-09-15: eski + yeni LLM çıktısı KAYIPSIZ birleştirilir (madde 4
        # - "mevcut analysis JSON'u tamamen ezme") - brand-new bir haberde
        # old_analysis={} olduğu için bu, eski davranışla BİREBİR aynı sonucu
        # üretir (union-with-empty = sadece yeni).
        analysis = merge_news_analysis(old_analysis, fresh_analysis)
        merged_cves = sorted(set((r["cves"] or []) + (analysis.get("cves") or [])))
        is_kev = bool(set(merged_cves) & kev_set)
        score, label = news_analyst.compute_priority(analysis, is_kev)
        was_reanalysis = r["pending_reanalysis_reason"] is not None
        print(
            f"  [analiz/{'re-' if was_reanalysis else ''}haber] {(r['title'] or '')[:80]!r} -> "
            f"öncelik {label} (bütçe kalan: {budget.remaining})"
        )

        # 2026-09-15 (madde 8 - "material update timestamp"): sadece brand-
        # new bir haberde DEĞİL, koşullu re-analiz tamamlandığında da
        # is_material_news_update ÜZERİNDEN karar verilir - ör. severity/
        # relevance/active_exploitation yükselişi burada YAKALANIR. Brand-
        # new haberde old_snapshot zaten "boş" olduğu için (cisa_kev=False,
        # priority_label=None, analysis={}) neredeyse HER ZAMAN True döner -
        # bu ZARARSIZ: material_update_at'in ilk kez set edilmesi, aynı gün
        # içinde henüz digest_shown_at hiç olmadığından (NULL) same-day
        # suppression'ı ZATEN etkilemez (bkz. _select_news_for_digest: NULLS
        # FIRST + digest_shown_at IS NULL koşulu her ikisi de "göster" der).
        old_snapshot = {
            "cves": r["cves"] or [], "cisa_kev": r["cisa_kev"],
            "priority_label": r["priority_label"], "analysis": old_analysis,
        }
        new_snapshot = {"cves": merged_cves, "cisa_kev": is_kev, "priority_label": label, "analysis": analysis}
        material = is_material_news_update(old_snapshot, new_snapshot)

        conn.execute(
            """
            UPDATE news_events
            SET analysis = %s::jsonb, analyzed_at = now(), cves = %s,
                vendors = %s, products = %s, cisa_kev = %s,
                priority_score = %s, priority_label = %s,
                pending_reanalysis_reason = NULL,
                material_update_at = CASE WHEN %s THEN now() ELSE material_update_at END
            WHERE id = %s
            """,
            (
                db.to_jsonb(analysis), merged_cves,
                analysis.get("vendors") or [], analysis.get("products") or [],
                is_kev, score, label, material, r["id"],
            ),
        )
        full_row = conn.execute("SELECT * FROM news_events WHERE id = %s", (r["id"],)).fetchone()
        analyzed.append(full_row)
    return analyzed


# ---------------------------------------------------------------------------
# NotebookLM export
# ---------------------------------------------------------------------------
def _record_notebooklm_export_log(conn, topic: str, period: str, file_path: str, paper_id: int) -> None:
    """notebooklm_export_log: hangi makalenin hangi konu/periyot dosyasına
    yazıldığının kalıcı denetim izi. papers.notebooklm_topic zaten "bu
    makale export edildi mi" sorusunu cevaplıyor - bu tablo ayrıca "hangi
    dosyada, hangi diğer makalelerle birlikte" sorusunu SQL ile sorgulanabilir
    kılıyor (ör. bir periyottaki tüm makaleleri tek sorguyla listelemek)."""
    existing = conn.execute(
        "SELECT paper_ids FROM notebooklm_export_log WHERE topic = %s AND period = %s",
        (topic, period),
    ).fetchone()
    if existing:
        paper_ids = sorted(set(existing["paper_ids"] or []) | {paper_id})
        conn.execute(
            """
            UPDATE notebooklm_export_log
            SET file_path = %s, paper_ids = %s, updated_at = now()
            WHERE topic = %s AND period = %s
            """,
            (file_path, paper_ids, topic, period),
        )
    else:
        conn.execute(
            """
            INSERT INTO notebooklm_export_log (topic, period, file_path, paper_ids)
            VALUES (%s, %s, %s, %s)
            """,
            (topic, period, file_path, [paper_id]),
        )


def _export_to_notebooklm(conn, analyzed_papers: list[dict]) -> dict[str, list[str]]:
    period = notebooklm_export.current_period()
    updated: dict[str, list[str]] = {}
    for p in analyzed_papers:
        if p.get("notebooklm_topic"):
            continue
        result = notebooklm_export.export_paper(p)
        if not result:
            continue
        topic, file_path = result
        conn.execute("UPDATE papers SET notebooklm_topic = %s WHERE id = %s", (topic, p["id"]))
        _record_notebooklm_export_log(conn, topic, period, file_path, p["id"])
        updated.setdefault(topic, [])
        if file_path not in updated[topic]:
            updated[topic].append(file_path)
    return updated


# ---------------------------------------------------------------------------
# Coverage audit: bu koşu bir öncekine göre çok mu az sonuç getirdi?
# ---------------------------------------------------------------------------
def _run_gap_hours(run_started_at: datetime, last_run_str: str | None) -> float | None:
    """2026-09-11: bu koşu ile GERÇEK bir önceki koşu (pipeline_state.
    last_run_at) arasında kaç saat geçti - None ise gerçek bir önceki koşu
    hiç YOK (ilk koşu vb.), bu durumda anomaly kontrolü normal çalışır
    (karşılaştıracak GERÇEK bir "çok yakın" koşu yok). Bkz. proje notları:
    "muhtemelen bozuldu" YANLIŞ pozitifini önlemek için ana çağıran taraf
    (main()) bu değeri config.ANOMALY_MIN_RUN_GAP_HOURS ile karşılaştırır."""
    if not last_run_str:
        return None
    previous = datetime.fromisoformat(last_run_str)
    return (run_started_at - previous).total_seconds() / 3600


def _coverage_warning(conn, this_run_total: int) -> str | None:
    # 2026-09-13: run_type='incremental' filtresi - recovery_backfill
    # koşuları (bkz. src/recovery/) bu karşılaştırmaya HİÇ KARIŞMAZ (spec
    # Z: "Recovery/backfill run_type=recovery_backfill olduğu için
    # baseline'a girmemeli").
    row = conn.execute(
        """
        SELECT COALESCE(SUM(result_count), 0) AS prev_total
        FROM collector_runs
        WHERE finished_at >= now() - interval '36 hours'
          AND finished_at < now() - interval '10 hours'
          AND run_type = 'incremental'
        """
    ).fetchone()
    prev_total = row["prev_total"] if row else 0
    if prev_total and this_run_total < prev_total * 0.3:
        return (
            f"⚠️ Bu koşuda toplam {this_run_total} sonuç geldi, önceki koşuda {prev_total} idi. "
            f"Bir kaynak/feed bozulmuş olabilir - collector_runs tablosunu kontrol edin."
        )
    return None


def _log_collector_errors_to_file(rows: list[dict]) -> None:
    """2026-09-11 (kullanıcı isteği: "error loglarına yazsın"): collector_
    runs.error DOLU olan (gerçek bir istisna/HTTP hatası fırlatmış) her
    satırı ayrı, grep'lenebilir bir dosyaya yazar - config.
    COLLECTOR_ERROR_LOG_ENABLED ile açılıp kapatılabilir. collector_runs
    zaten kalıcı bir audit trail ama bu, "sadece gerçek hataları hızlıca
    görmek" için ayrı, gürültüsüz bir dosya."""
    if not config.COLLECTOR_ERROR_LOG_ENABLED or not rows:
        return
    os.makedirs(os.path.dirname(config.COLLECTOR_ERROR_LOG_FILE), exist_ok=True)
    with open(config.COLLECTOR_ERROR_LOG_FILE, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(f"{datetime.now(timezone.utc).isoformat()} source={r['source']} kind={r['kind']} error={r['error']}\n")


_INTENTIONAL_SKIP_MARKERS = ("disabled_degraded_optional", "disabled_missing_credentials")

# 2026-09-14 (kullanıcı isteği - "Collector hata mesajları neden Telegram'ı
# dolduruyor?"): sıra ÖNEMLİ - "429"/"rate limit" spesifik bir "timeout"
# ya da genel bir 5xx'ten ÖNCE kontrol edilmeli (bazı istisna metinleri
# ikisini de içerebilir, ör. "read operation timed out" 5xx İÇERMEZ ama
# emin olmak için sıralama sabit tutuluyor).
_ERROR_CLASS_PATTERNS = (
    ("rate-limit (429)", re.compile(r"\b429\b")),
    ("timeout", re.compile(r"timed out|timeout", re.IGNORECASE)),
    ("server error (5xx)", re.compile(r"\b5\d\d\b")),
    # PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md S3): önceden
    # JSON/XML parse hataları "diğer" içine düşüyordu - bir kaynağın format
    # değiştirmesi (rate-limit'ten AYRI bir arıza sınıfı) collector health'te
    # ayırt edilemiyordu.
    ("parse failure", re.compile(r"JSONDecodeError|XMLSyntaxError|ParseError|not valid JSON|invalid JSON|SyntaxError", re.IGNORECASE)),
)


def _classify_collector_error(error_text: str) -> str:
    for label, pattern in _ERROR_CLASS_PATTERNS:
        if pattern.search(error_text or ""):
            return label
    return "diğer"


def _aggregate_collector_errors(real_errors: list[dict]) -> list[str]:
    """Ham hata metinlerini Telegram'a TEK TEK basmak yerine (aynı kaynağın
    aynı koşuda birden fazla kelime/sorgu için art arda 429/timeout alması
    3-4 neredeyse birebir aynı satır üretiyordu - canlıda görüldü, bkz.
    2026-09-14 teşhis raporu) kaynak+hata sınıfı bazında TEK satıra
    toplar. Ham/tam exception metni KAYBOLMAZ - collector_runs.error
    kolonunda (her zaman) ve COLLECTOR_ERROR_LOG_ENABLED açıksa ayrı log
    dosyasında (bkz. _log_collector_errors_to_file, bu fonksiyondan ÖNCE
    zaten çağrılıyor) tam olarak duruyor; Telegram'a giden sadece SAYIM."""
    by_source: dict[str, Counter] = defaultdict(Counter)
    for r in real_errors:
        by_source[r["source"]][_classify_collector_error(r["error"])] += 1
    lines = []
    for source in sorted(by_source):
        counter = by_source[source]
        total = sum(counter.values())
        breakdown = ", ".join(f"{cls}: {n}" for cls, n in counter.most_common())
        lines.append(f"🔴 {source}: {total} hata ({breakdown})")
    return lines


def _real_collector_errors(conn, run_started_at: datetime) -> list[dict]:
    """Bu koşuda GERÇEKTEN istisna/HTTP hatası fırlatmış (collector_runs.
    error DOLU) kaynakları döner - "az sonuç ama başarılı yanıt" (error
    NULL) İLE KARIŞTIRILMAZ, bkz. _source_anomaly_warnings docstring'i.
    _INTENTIONAL_SKIP_MARKERS (ör. DBLP'nin bilinçli 'disabled_degraded_
    optional' işareti - bkz. ACCEPTANCE-02, ya da API key'i olmayan
    opsiyonel kaynakların 'disabled_missing_credentials'ı) GERÇEK HATA
    SAYILMAZ - bunlar zaten BİLİNÇLİ, beklenen bir durumu işaretliyor,
    "kaynak bozuldu" anlamına GELMİYOR."""
    rows = conn.execute(
        "SELECT source, kind, error FROM collector_runs "
        "WHERE finished_at >= %s AND error IS NOT NULL AND run_type = 'incremental'",
        (run_started_at,),
    ).fetchall()
    return [r for r in rows if r["error"] not in _INTENTIONAL_SKIP_MARKERS]


def _consecutive_zero_run_streak(conn, source: str, kind: str, before: datetime, max_lookback: int = 10) -> int:
    """PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md S2): bu kaynağın
    (error'suz, run_type='incremental') EN SON `max_lookback` koşusunu
    finished_at DESC sırayla tarar, `before` ANINDAN ÖNCEKİ en yeni koşudan
    başlayarak (bu koşunun kendisi HARİÇ) art arda kaç tanesinin
    result_count=0 olduğunu sayar - ilk sonuç>0 olan koşuda durur. Tek
    başına "0 sonuç, hata yok" (bkz. _source_anomaly_warnings) geçici bir
    zararsız durum olabilir; art arda birden çok koşuda tekrarı daha ciddi
    bir sinyaldir."""
    rows = conn.execute(
        "SELECT COALESCE(result_count, 0) AS c FROM collector_runs "
        "WHERE source = %s AND kind = %s AND error IS NULL AND run_type = 'incremental' "
        "AND finished_at < %s ORDER BY finished_at DESC LIMIT %s",
        (source, kind, before, max_lookback),
    ).fetchall()
    streak = 0
    for r in rows:
        if r["c"] != 0:
            break
        streak += 1
    return streak


def _source_anomaly_warnings(
    conn, run_started_at: datetime, threshold: float = 0.4
) -> list[str]:
    """Madde 8: SADECE toplam düşüşü (_coverage_warning, yukarıda) YETERSİZ
    - bir kaynak tamamen bozulup diğerleri onu telafi edebilir, toplamda
    fark hiç görünmeyebilir. Bu, HER kaynağı önceki başarılı koşuyla AYRI
    AYRI karşılaştırır (bkz. proje notları: "source X previous=320
    current=0 gibi anomalileri toplam sayıdan daha erken tespit edelim").
    `threshold` config-driven (config.SOURCE_ANOMALY_DROP_THRESHOLD).

    2026-09-11 düzeltmesi (canlı teşhis edildi - kullanıcı isteği:
    "gerçekten problem varsa bunu bulsun"): eskiden HER düşüş "muhtemelen
    bozuldu" diyordu - ama collector_runs.error NULL'sa (gerçek bir hata
    YOKSA) bu sadece "az/sıfır ama BAŞARILI yanıt" demektir (ör. aynı günü
    art arda taramak, dar since_date penceresi - arxiv canlı doğrulandı:
    dar pencerede 0, geniş pencerede 25 gerçek makale döndürdü, API'nin
    kendisi sağlıklıydı). Artık İKİ SEVİYE: bu koşuda GERÇEKTEN error'lu
    olan kaynaklar "⚠️ Collector Health: DEGRADED" + kaynak/hata-sınıfı
    bazında TEK SATIRLIK toplam (bkz. _aggregate_collector_errors - 2026-
    09-14 düzeltmesi: eskiden her BAŞARISIZ deneme kendi ham exception
    metniyle ayrı satır basıyordu, aynı kaynağın aynı koşuda 2-3 kelimede
    art arda 429/timeout alması Telegram'ı 3-4 neredeyse birebir aynı
    satırla dolduruyordu) ile özetlenir; ham metin KAYBOLMAZ, her zaman
    collector_runs.error'da ve (COLLECTOR_ERROR_LOG_ENABLED açıksa)
    _log_collector_errors_to_file'ın log dosyasında durur. error'suz ama
    sayısı düşen kaynaklar artık "bozuldu" DENMEZ, daha temkinli "sonuç
    azaldı, hata yok, kesin arıza sinyali DEĞİL" ifadesiyle raporlanır."""
    real_errors = _real_collector_errors(conn, run_started_at)
    _log_collector_errors_to_file(real_errors)
    error_sources = {(r["source"], r["kind"]) for r in real_errors}

    current_rows = conn.execute(
        "SELECT source, kind, COALESCE(SUM(result_count),0) AS c FROM collector_runs "
        "WHERE finished_at >= %s AND error IS NULL AND run_type = 'incremental' GROUP BY source, kind",
        (run_started_at,),
    ).fetchall()
    previous_rows = conn.execute(
        "SELECT source, kind, COALESCE(SUM(result_count),0) AS c FROM collector_runs "
        "WHERE finished_at >= %s - interval '36 hours' AND finished_at < %s AND error IS NULL "
        "AND run_type = 'incremental' "
        "GROUP BY source, kind",
        (run_started_at, run_started_at),
    ).fetchall()
    prev_map = {(r["source"], r["kind"]): r["c"] for r in previous_rows}

    warnings: list[str] = []
    aggregated_errors = _aggregate_collector_errors(real_errors)
    if aggregated_errors:
        warnings.append("⚠️ Collector Health: DEGRADED")
        warnings.extend(aggregated_errors)

    for r in current_rows:
        key = (r["source"], r["kind"])
        if key in error_sources:
            continue  # bu kaynak zaten yukarıda "GERÇEK HATA" olarak raporlandı
        prev = prev_map.get(key, 0)
        cur = r["c"]
        if cur == 0:
            # PHASE 10 (docs/FUNCTIONAL_GAP_ANALYSIS.md S2): bu kontrol
            # BİLEREK `prev` şartından BAĞIMSIZ - bir kaynak 36 saatlik
            # pencereden DAHA UZUN süredir 0 veriyorsa prev de 0 olur ve
            # aşağıdaki "karşılaştırma anlamsız" atlaması bu durumu HİÇ
            # yakalayamaz; art arda sıfır sinyali tam olarak bu senaryo
            # için var.
            prior_streak = _consecutive_zero_run_streak(conn, r["source"], r["kind"], run_started_at)
            total_streak = prior_streak + 1
            if total_streak >= config.SOURCE_CONSECUTIVE_ZERO_ALERT_COUNT:
                warnings.append(
                    f"⚠️ Kaynak '{r['source']}' ({r['kind']}): art arda {total_streak} koşudur 0 sonuç "
                    f"(hata yok, başarılı ama boş yanıt) - tek koşuluk bir düşüş değil, incelenmeli."
                )
            elif prev:
                warnings.append(
                    f"ℹ️ Kaynak '{r['source']}' ({r['kind']}): önceki koşuda {prev} sonuç, bu koşuda 0 - "
                    f"ANCAK hata YOK (başarılı yanıt). Kesin arıza sinyali değil, izlenmeli."
                )
            continue
        if not prev:
            continue  # önceki koşuda zaten 0'dı - karşılaştırma anlamsız
        if cur < prev * (1 - threshold):
            drop_pct = round((1 - cur / prev) * 100)
            warnings.append(
                f"ℹ️ Kaynak '{r['source']}' ({r['kind']}): {prev} → {cur} (%{drop_pct} düşüş) - "
                f"hata YOK, kesin arıza sinyali değil."
            )
    return warnings


def _build_collector_health(
    conn,
    run_started_at: datetime,
    display_news: list[dict],
    current_papers: list[dict],
    learning_path_papers: list[dict],
    historical_highlights: list[dict],
    profile_a_papers: list[dict],
    profile_b_papers: list[dict],
) -> str:
    """Madde 7: Her koşu için üretilir (Telegram'a DEĞİL - proje ilkesi
    "Telegram yalnızca presentation layer", ayrıntı log/stdout'ta kalır,
    bkz. main()'in sonundaki print). "Önceki run 855 -> bu run 216" gibi
    anomalilerin GÖRÜLEBİLMESİ için."""
    rows = conn.execute(
        "SELECT source, kind, result_count, error FROM collector_runs WHERE finished_at >= %s",
        (run_started_at,),
    ).fetchall()
    attempted = len(rows)
    successful = sum(1 for r in rows if r["error"] is None)
    failed = attempted - successful
    sources_configured = len({r["source"] for r in rows})
    news_collected = sum(r["result_count"] or 0 for r in rows if r["kind"] == "news" and r["error"] is None)
    papers_collected = sum(r["result_count"] or 0 for r in rows if r["kind"] == "academic" and r["error"] is None)

    dedup_row = conn.execute(
        "SELECT "
        "(SELECT count(*) FROM news_events WHERE created_at >= %s) AS news, "
        "(SELECT count(*) FROM papers WHERE created_at >= %s) AS papers",
        (run_started_at, run_started_at),
    ).fetchone()
    filtered_row = conn.execute(
        "SELECT "
        "(SELECT count(*) FROM news_events WHERE created_at >= %s AND relevance_status = 'relevant') AS news, "
        "(SELECT count(*) FROM papers WHERE created_at >= %s AND relevance_status = 'relevant') AS papers",
        (run_started_at, run_started_at),
    ).fetchone()

    tier_counts = {t: 0 for t in _NEWS_DISPLAY_TIERS}
    for n in display_news:
        tier = digest.news_tier(n)
        if tier in tier_counts:
            tier_counts[tier] += 1

    lines = [
        "# Collector Health",
        f"Sources configured: {sources_configured}",
        f"Sources attempted: {attempted}",
        f"Sources successful: {successful}",
        f"Sources failed: {failed}",
        f"News collected: {news_collected}",
        f"Papers collected: {papers_collected}",
        "After dedup:",
        f"  News: {dedup_row['news']}",
        f"  Papers: {dedup_row['papers']}",
        "After filtering (relevance='relevant', bu koşuda eklenenler arasında):",
        f"  News: {filtered_row['news']}",
        f"  Papers: {filtered_row['papers']}",
        "Categories:",
        f"  Action: {tier_counts['ACTION_REQUIRED']}/{config.OPERATIONAL_ACTION_TARGET}",
        f"  Hunt: {tier_counts['HUNT_OPPORTUNITY']}/{config.OPERATIONAL_HUNT_TARGET}",
        f"  Tutorial: {tier_counts['LEARN']}/{config.OPERATIONAL_TUTORIAL_TARGET}",
        f"  Awareness: {tier_counts['AWARENESS']}/{config.OPERATIONAL_AWARENESS_TARGET}",
        "Academic quota status:",
        f"  Current: {len(current_papers)}/{config.ACADEMIC_CURRENT_TARGET}",
        f"  Timeline: {len(learning_path_papers)}/{config.ACADEMIC_TIMELINE_TARGET}",
        f"  Classic: {min(1, len(historical_highlights))}/{config.ACADEMIC_CLASSIC_TARGET}",
        f"  Historical: {max(0, len(historical_highlights) - 1)}/{config.ACADEMIC_HISTORICAL_TARGET}",
        f"  Research Profile A: {len(profile_a_papers)}/{config.RESEARCH_PROFILE_A_TARGET}",
        f"  Research Profile B: {len(profile_b_papers)}/{config.RESEARCH_PROFILE_B_TARGET}",
    ]
    # 2026-09-14 (kullanıcı isteği: "Detaylı exception metinleri ...
    # COLLECTOR_HEALTH.md içinde kalsın"): Telegram'a artık sadece aggregate
    # sayım gidiyor (bkz. _aggregate_collector_errors) - ham exception
    # metni burada, dosyaya yazılan raporda tutuluyor (bkz. main()'deki
    # data/reports/COLLECTOR_HEALTH.md yazımı).
    error_rows = [r for r in rows if r["error"] and r["error"] not in _INTENTIONAL_SKIP_MARKERS]
    if error_rows:
        lines.append("")
        lines.append("## Errors (bu koşu, ham metin)")
        for r in error_rows:
            lines.append(f"- {r['source']} ({r['kind']}): {r['error']}")
    return "\n".join(lines)


def main() -> None:
    slot = "Sabah" if datetime.now().hour < 13 else "Akşam"
    run_result_total = 0
    # Collector health / source anomaly (madde 7-8) için bu koşunun
    # başlangıç zaman damgası - collector_runs'ı "bu koşu" ile "önceki
    # koşu" olarak ayırmak için kullanılıyor.
    run_started_at = datetime.now(timezone.utc)

    with db.get_conn() as conn:
        last_run_str = db.get_state(conn, "last_run_at")
        since_dt = (
            datetime.fromisoformat(last_run_str)
            if last_run_str
            else datetime.now(timezone.utc) - timedelta(hours=24)
        )
        since_date: date = since_dt.date()

        # 1) Akademik toplama - aktif research profile'lar (bkz.
        # src/research/profiles.py) üzerinden. daily_cyber TEK BAŞINA aktifken
        # (varsayılan) bu, eski "her KEYWORDS terimi her kaynağa" davranışının
        # BİREBİR aynısı - academic.COLLECTORS'ın düz-keyword fonksiyonlarını
        # değiştirmeden çağırıyor. SCI/tez profilleri query_builder ile
        # kurduğu boolean sorguları, her kaynağın GERÇEKTEN desteklediği söz
        # dizimiyle gönderir (bkz. query_builder.py docstring).
        active_profiles = research_profiles.load_active_profiles()
        if any(p.mode != "daily" for p in active_profiles):
            _log_disabled_optional_sources(conn)
        for profile in active_profiles:
            run_result_total += _collect_profile(conn, profile, since_date)

        # 1b) Geçmişten öne çıkanlar - haftada bir, KEYWORDS için en çok atıf
        # almış (güncel olmayan) makaleleri de toplar; aşağıdaki ilgililik
        # filtresi + derin analizden AYNI şekilde geçerler.
        _maybe_collect_historical(conn)

        # 2) Haber toplama
        for feed_url in config.NEWS_FEEDS:
            try:
                items = news_collector.fetch_rss_feed(feed_url, since_date)
                for item in items:
                    _find_or_merge_news_event(conn, item)
                db.log_collector_run(conn, feed_url, "news", None, len(items))
                run_result_total += len(items)
            except Exception as e:  # noqa: BLE001
                db.log_collector_run(conn, feed_url, "news", None, None, str(e))

        kev_set = news_collector.fetch_cisa_kev()
        # 2026-09-14 (kullanıcı isteği - madde 3/senaryo B: "07:30 KEV değil,
        # 19:30 KEV oldu"): cisa_kev eskiden SADECE _analyze_relevant_news'te
        # (analyzed_at IS NULL dalı, yani BİR KEZ) hesaplanıyordu - CISA
        # listesi her koşuda YENİDEN çekildiği halde zaten analiz edilmiş bir
        # habere SONRADAN eklenen KEV üyeliği hiçbir zaman yansımıyordu. Bu
        # adım TAMAMEN deterministik (LLM'e gitmez, is_kev ile AYNI mantık),
        # sadece false->true geçişini material_update_at'e yansıtır.
        _recheck_kev_status_for_material_updates(conn, kev_set)

        # 2b) Gemini günlük kota bütçesi - bkz. llm/budget.py. 2026-09-10 KÖK
        # NEDEN ANALİZİ: eskiden TEK bir paylaşılan LLMBudget hem haber hem
        # makale döngülerini besliyordu VE makaleler döngülerde HER ZAMAN
        # haberlerden ÖNCE işleniyordu - araştırma profilleri makale hacmini
        # büyüttükçe paylaşılan bütçe makalelerde tükenip haber işleme SIFIR
        # pay buluyordu (analyzed_news=[] -> 🚨/🕵️/📚/👀 dörtlüsü hep boş,
        # makaleler ise KENDİ backfill havuzundan doluydu - bkz. canlı log
        # kanıtı 2026-09-10 19:31 koşusu). Artık İKİ BAĞIMSIZ günlük havuz:
        # biri tükenmesi diğerini ETKİLEMEZ (proje notları: "iki pipeline
        # birbirinden bağımsız olsun").
        news_budget = NamedBudget(conn, "ops_news", config.NEWS_DAILY_LLM_BUDGET, runs_per_day=config.GEMINI_RUNS_PER_DAY)
        papers_budget = NamedBudget(conn, "ops_papers", config.PAPERS_DAILY_LLM_BUDGET, runs_per_day=config.GEMINI_RUNS_PER_DAY)

        # 3) İlgililik filtresi (Level 1 - ucuz model)
        _classify_pending_papers(conn, papers_budget)
        _classify_pending_news(conn, news_budget)

        # 3b) Citation snowballing (yalnızca snowball=true profiller, ör.
        # Research Profile A/B - bkz. cyber_radar/research/profiles.py) - bu profille
        # 'relevant' çıkan seed'lerden 1-hop references/citations/
        # recommendations toplar (bkz. src/collectors/citation_graph.py).
        # Snowball edilen yeni kayıtlar 'pending' olarak eklenir, bu yüzden
        # AYNI papers_budget ile bir kez daha ilgililik filtresinden geçirilir -
        # ayrı bir kod yolu değil, sadece yukarıdaki döngünün ikinci çağrısı
        # (zaten 'relevant'/'irrelevant' olanlara dokunmaz). Haberi ETKİLEMEZ.
        for profile in active_profiles:
            snowballed_count = _snowball_profile(conn, profile)
            run_result_total += snowballed_count
        _classify_pending_papers(conn, papers_budget)

        # 4) Derin analiz (Level 3-4 - güçlü model, sadece 'relevant' olanlar)
        # - artık makale ve haber TAMAMEN bağımsız bütçeyle, sıra ARTIK ÖNEMLİ
        # DEĞİL (hangisi önce çalışırsa çalışsın, diğerinin payını yemiyor).
        analyzed_papers = _analyze_relevant_papers(conn, papers_budget, active_profiles)
        analyzed_news = _analyze_relevant_news(conn, kev_set, news_budget)

        # 4b) Research Profile A/B digest köprüsü - GENERIC (public export,
        # PHASE 11): hangi profil ID'lerinin bu iki "kendi ayrı digest
        # bölümü olan" slotu doldurduğu config.RESEARCH_PROFILE_A_ID/
        # _B_ID'den (kullanıcı .env'i) gelir - hiçbir profil ID'si
        # koda GÖMÜLÜ değildir. SADECE bu profiller ACTIVE_RESEARCH_PROFILES
        # içindeyse çalışır (varsayılan boş = tamamen no-op, hiçbir
        # davranış değişmez). Kendi BAĞIMSIZ bütçe havuzları - ops_news/
        # ops_papers'ı YEMEZ ("bir kategorinin bütçesi diğerini etkilemesin").
        profile_a = next((p for p in active_profiles if p.id == config.RESEARCH_PROFILE_A_ID), None) if config.RESEARCH_PROFILE_A_ID else None
        profile_b = next((p for p in active_profiles if p.id == config.RESEARCH_PROFILE_B_ID), None) if config.RESEARCH_PROFILE_B_ID else None
        profile_a_papers: list[dict] = []
        profile_b_papers: list[dict] = []
        if profile_a:
            profile_a_budget = NamedBudget(conn, "research_profile_a_digest", config.RESEARCH_PROFILE_A_LLM_BUDGET, runs_per_day=config.GEMINI_RUNS_PER_DAY)
            _assess_digest_bridge_step(conn, profile_a, profile_a_budget)
            profile_a_papers = _select_profile_papers_for_digest(conn, profile_a.id, limit=config.RESEARCH_PROFILE_A_TARGET)
        if profile_b:
            profile_b_budget = NamedBudget(conn, "research_profile_b_digest", config.RESEARCH_PROFILE_B_LLM_BUDGET, runs_per_day=config.GEMINI_RUNS_PER_DAY)
            _assess_digest_bridge_step(conn, profile_b, profile_b_budget)
            profile_b_papers = _select_profile_papers_for_digest(conn, profile_b.id, limit=config.RESEARCH_PROFILE_B_TARGET)

        # 5) NotebookLM export
        nb_updates = _export_to_notebooklm(conn, analyzed_papers)

        # 5b) Brifing için config-driven KOTA seçimi (bkz. proje notları:
        # "hard-code etme, config'e taşı"): 🆕 Güncel + 🧭 Temelden Güncele +
        # (🏛️ Klasik + 📚 Geçmişten Öne Çıkanlar). reading_priority hiçbirinde
        # eleme kriteri DEĞİL - önce seçim yapılır, reading_priority sadece
        # görüntüde etiket olur (bkz. digest._paper_line). Kullanıcı isteği:
        # "selection != reading_priority".
        new_only = [p for p in analyzed_papers if not p.get("is_historical")]
        current_papers = _select_current_papers(conn, new_only, limit=config.ACADEMIC_CURRENT_TARGET)
        # _select_historical_highlights TEK havuzdan Klasik(1)+Geçmişten Öne
        # Çıkanlar(5) ikisini birden çeker (digest.py ranked[0]=Klasik,
        # ranked[1:]=geri kalanı ayırır) - bu yüzden limit ikisinin TOPLAMI.
        historical_highlights = _select_historical_highlights(
            conn, limit=config.ACADEMIC_CLASSIC_TARGET + config.ACADEMIC_HISTORICAL_TARGET
        )

        # 5c) Günün öğrenme teması: yalnızca bu koşudaki MUST_READ makaleler +
        # geçmiş havuzunun en iyisi üzerinden (bkz. digest.historical_score) -
        # hiçbiri yoksa curriculum.daily_theme() LLM'i hiç çağırmadan None döner.
        # Önceki döngüler (relevance + derin analiz) günlük bütçeyi tüketmiş
        # olabilir - bu tek çağrı da budget'a tabi ve ayrıca 429/ağ gibi API
        # hataları tüm pipeline'ı düşürmesin diye try/except ile sarmalı
        # (bkz. cyber-radar.service 2026-09-10 08:41 çökmesi: bu çağrı
        # budget'sız ve except'siz olduğu için tek başına pipeline'ı patlattı).
        theme_candidates = [p for p in current_papers if (p.get("analysis") or {}).get("reading_priority") == "MUST_READ"]
        if historical_highlights:
            theme_candidates.append(max(historical_highlights, key=digest.historical_score))
        daily_theme = None
        if theme_candidates and papers_budget.has_capacity():
            papers_budget.consume()
            try:
                daily_theme = curriculum.daily_theme([
                    {
                        "title": p.get("title"),
                        "why_read": (p.get("analysis") or {}).get("why_read"),
                        "domain_contribution_scores": (p.get("analysis") or {}).get("domain_contribution_scores"),
                    }
                    for p in theme_candidates
                ])
            except Exception as e:  # noqa: BLE001 - günün teması opsiyonel bir
                # zenginleştirme, hatası (kota/ağ/vb.) brifingin geri kalanını
                # durdurmasın
                print(f"daily_theme atlandı: {e}")

        # 5d) "🧭 Temelden Güncele — Son 5 Yıl": mümkünse günün temasıyla aynı
        # araştırma hattından (theme_candidates'ın baskın alanı), yoksa bugünkü
        # 5 güncel makalenin baskın alanından. current_papers'takiler HARİÇ
        # tutulur ki aynı makale iki bölümde birden görünmesin.
        target_domain = _dominant_domain(theme_candidates) or _dominant_domain(current_papers)
        learning_path_papers = _select_learning_path(
            conn, target_domain, exclude_ids={p["id"] for p in current_papers}, limit=config.ACADEMIC_TIMELINE_TARGET
        )

        stale_must_reads = _resurface_stale_must_reads(conn)

        # 5e) Haberler için de makalelerdeki gibi backfill/rotasyon (2026-09-10
        # kök neden analizinin asıl düzeltmesi - bkz. _select_news_for_digest):
        # bu koşuda YENİ analiz edilen haberler yetmezse (bütçe azdı/pending
        # yoktu), her tier daha önce analiz edilmiş ama henüz gösterilmemiş
        # gerçek haberlerle TAMAMLANIR - "sadece 5'e tamamlamak için düşük
        # kaliteli/uydurma haber EKLEME" (kullanıcı isteği) - hiçbir yeni
        # içerik uydurulmuyor, sadece DAHA ÖNCE gerçekten analiz edilmiş
        # havuzdan rotasyonla gösteriliyor.
        display_news = _select_news_for_digest(
            conn,
            analyzed_news,
            target_per_tier={
                "ACTION_REQUIRED": config.OPERATIONAL_ACTION_TARGET,
                "HUNT_OPPORTUNITY": config.OPERATIONAL_HUNT_TARGET,
                "LEARN": config.OPERATIONAL_TUTORIAL_TARGET,
                "AWARENESS": config.OPERATIONAL_AWARENESS_TARGET,
            },
        )

        # 5f) BUILDS_ON/FOUNDATION_FOR (madde 6) - SADECE digest'e girecek
        # makaleler için, gerçek reference/citation metadata'sıyla (bkz.
        # _enrich_relationships docstring'i).
        digest_paper_ids = {
            p["id"] for p in current_papers + historical_highlights + learning_path_papers + profile_a_papers + profile_b_papers
        }
        _enrich_relationships(
            conn, current_papers + historical_highlights + learning_path_papers + profile_a_papers + profile_b_papers
        )

        # 5g) W1 (PHASE 10, docs/FUNCTIONAL_GAP_ANALYSIS.md): digest sonunda
        # TEK bir "📚 Oku Şimdi" önerisi - bugün ZATEN AYRI gösterilen
        # makaleler HARİÇ tutulur (aynı makale iki kez "oku" denmesin).
        read_now = _select_read_now_recommendation(conn, exclude_ids=digest_paper_ids)

        # 6) Brifing üret + gönder
        brief = digest.generate_brief(
            display_news, current_papers, historical_highlights, nb_updates, slot,
            daily_theme=daily_theme, stale_must_reads=stale_must_reads, learning_path_papers=learning_path_papers,
            profile_a_papers=profile_a_papers, profile_b_papers=profile_b_papers, read_now=read_now,
        )
        # Madde 8: toplam düşüş (_coverage_warning) + kaynak bazlı anomali
        # (_source_anomaly_warnings) - Telegram brifingine SADECE anomali
        # VARSA prepend edilir, rutin bir koşuda brifing kirlenmez.
        #
        # 2026-09-11 düzeltmesi: bu koşu, önceki koşudan (since_dt - günün
        # başındaki gerçek last_run_at) ANOMALY_MIN_RUN_GAP_HOURS'tan (normal
        # kadans ~12 saat) daha KISA süre sonra çalıştıysa, kaynak/toplam
        # karşılaştırması YANILTICI olur (rate-limiting/dar since_date
        # penceresi normal bir sonuç, "kaynak bozuldu" DEĞİL - canlıda
        # gözlendi: iki koşu 40 dakika arayla çalıştırılınca openalex/
        # crossref/RSS feed'leri "%90 düşüş"/"0 sonuç, muhtemelen bozuldu"
        # diye YANLIŞ pozitif ürettiler). Bu durumda anomaly kontrolü
        # ATLANIR, TEK bir bilgilendirme notu basılır - gürültü YOK.
        run_gap_hours = _run_gap_hours(run_started_at, last_run_str)
        run_too_soon = run_gap_hours is not None and run_gap_hours < config.ANOMALY_MIN_RUN_GAP_HOURS
        if run_too_soon:
            warning_prefix = (
                f"ℹ️ Bu koşu önceki koşudan sadece ~{round(run_gap_hours * 60)} dakika sonra çalıştı - "
                f"kaynak/toplam karşılaştırması bu kadar kısa aralıkta güvenilir değil (muhtemelen "
                f"rate-limiting/dar arama penceresi, gerçek bir bozulma OLMAYABİLİR) - anomaly kontrolü "
                f"bu koşu için atlandı."
            )
        else:
            warning = _coverage_warning(conn, run_result_total)
            source_warnings = _source_anomaly_warnings(conn, run_started_at, threshold=config.SOURCE_ANOMALY_DROP_THRESHOLD)
            warning_prefix = "\n\n".join([w for w in [warning, *source_warnings] if w])
        if warning_prefix:
            brief = f"{warning_prefix}\n\n{brief}"
        digest.save_brief(brief, slot)
        sent = notify.send_telegram(brief)
        _send_feedback_followups(
            conn, current_papers, historical_highlights, analyzed_news,
            learning_path_papers=learning_path_papers, profile_a_papers=profile_a_papers, profile_b_papers=profile_b_papers,
            read_now=read_now,
        )

        # Madde 7: Collector Health - Telegram'a DEĞİL, log/stdout'a (bkz.
        # proje ilkesi "Telegram yalnızca presentation layer, detay
        # loglansın") - "önceki run 855 -> bu run 216" gibi anomaliler bu
        # rapordan görülebilir.
        health_report = _build_collector_health(
            conn, run_started_at, display_news, current_papers, learning_path_papers,
            historical_highlights, profile_a_papers, profile_b_papers,
        )

        db.set_state(conn, "last_run_at", datetime.now(timezone.utc).isoformat())

    # 2026-09-14: health_report artık sadece stdout/journal'da değil, ayrı
    # bir dosyada da (her koşuda ÜZERİNE YAZILIR - "şu anki durum" snapshot'ı,
    # geçmiş koşuların health_report'ları zaten collector_runs'ta kalıcı) -
    # kullanıcı isteği: "raw hata ayrıntıları ... COLLECTOR_HEALTH.md içinde
    # kalsın", journalctl'e erişmeden de okunabilsin diye.
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    with open(os.path.join(config.REPORTS_DIR, "COLLECTOR_HEALTH.md"), "w", encoding="utf-8") as f:
        f.write(health_report + "\n")

    # 7) Google Drive senkron + yerel disk temizliği (disk alanı sınırlı -
    #    başarıyla Drive'a yüklenmiş dosyalar config.LOCAL_RETENTION_DAYS
    #    gün sonra sunucudan silinir). GDRIVE_ENABLED=false ise no-op.
    retention_logs = retention.sync_and_cleanup()

    print(brief)
    print()
    print(health_report)
    if not sent:
        print("\n[UYARI] Telegram bildirimi gönderilemedi - .env içindeki TELEGRAM_* değerlerini kontrol edin.")
    for line in retention_logs:
        print(line)


if __name__ == "__main__":
    main()
