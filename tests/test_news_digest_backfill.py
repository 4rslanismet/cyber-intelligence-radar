"""_select_news_for_digest (bkz. src/run_pipeline.py, 2026-09-10 kök neden
analizi: haberlerin makaleler gibi bir backfill/rotasyon mekanizması
olmadığı için LLM bütçesi darken TÜM haber kategorileri boş görünüyordu).
Test DB kullanır, gerçek ağ/Gemini çağrısı YOK."""
from __future__ import annotations

import json

from cyber_radar.run_pipeline import _select_news_for_digest

# 2026-09-15: "now() - interval 'N hours'" gece yarısına yakın çalışan test
# koşularında (ör. 00:15'te "9 saat önce" = DÜN) yanlışlıkla farklı takvim
# gününe düşüp same-day testlerini FLAKY yapıyordu (canlıda gözlendi - bkz.
# proje notları). Bunun yerine HER ZAMAN bugünün (Europe/Istanbul) başlangıcına
# göre, saat diliminden bağımsız sabit bir ifade kullanılıyor.
_TODAY_START_IST = "(date_trunc('day', now() AT TIME ZONE 'Europe/Istanbul') AT TIME ZONE 'Europe/Istanbul')"


def _insert_news(conn, tier: str, title: str) -> int:
    row = conn.execute(
        """
        INSERT INTO news_events (title, dedup_key, analysis, analyzed_at, relevance_status)
        VALUES (%(title)s, %(dedup_key)s, %(analysis)s::jsonb, now(), 'relevant')
        RETURNING id
        """,
        {
            "title": title,
            "dedup_key": title.lower(),
            "analysis": json.dumps({"news_tier": tier, "summary": "test"}),
        },
    ).fetchone()
    return row["id"]


def test_backfills_empty_tier_from_previously_analyzed_pool(db_conn):
    """Bu koşuda hiç yeni analiz edilen haber YOK (analyzed_news=[]) ama
    DB'de daha önce analiz edilmiş, henüz gösterilmemiş ACTION_REQUIRED bir
    haber var - backfill onu göstermeli. Bu, tam olarak canlıda görülen
    'tüm kategoriler boş' bug'ının düzeltmesi."""
    _insert_news(db_conn, "ACTION_REQUIRED", "Eski ama gösterilmemiş kritik haber")

    result = _select_news_for_digest(db_conn, analyzed_news=[], target_per_tier=5)

    assert len(result) == 1
    assert result[0]["title"] == "Eski ama gösterilmemiş kritik haber"


def test_prefers_this_run_analyzed_news_over_backfill(db_conn):
    _insert_news(db_conn, "HUNT_OPPORTUNITY", "Eski hunt haberi")
    fresh_id = _insert_news(db_conn, "HUNT_OPPORTUNITY", "Taze hunt haberi")
    fresh_row = db_conn.execute("SELECT * FROM news_events WHERE id = %s", (fresh_id,)).fetchone()

    result = _select_news_for_digest(db_conn, analyzed_news=[dict(fresh_row)], target_per_tier=1)

    assert len(result) == 1
    assert result[0]["title"] == "Taze hunt haberi"  # bu koşunun taze haberi ÖNCELİKLİ


def test_archive_tier_news_never_appears_in_digest_selection(db_conn):
    """ARCHIVE tier'ı kategori kotasını doldurmak için KULLANILMAZ - kategori
    anlamını bozmamalı (kullanıcı isteği): news_tier() ARCHIVE döndüren
    haberler _NEWS_DISPLAY_TIERS'da yer almadığından hiçbir zaman seçilmez."""
    row_id = _insert_news(db_conn, "ARCHIVE", "Düşük öncelikli arşiv haberi")
    row = db_conn.execute("SELECT * FROM news_events WHERE id = %s", (row_id,)).fetchone()
    result = _select_news_for_digest(db_conn, analyzed_news=[dict(row)], target_per_tier=5)
    assert result == []


def test_rotation_marks_digest_shown_at_so_same_item_is_not_repeated_forever(db_conn):
    _insert_news(db_conn, "LEARN", "Rotasyon testi haberi")
    first = _select_news_for_digest(db_conn, analyzed_news=[], target_per_tier=1)
    assert len(first) == 1
    row = db_conn.execute("SELECT digest_shown_at FROM news_events WHERE id = %s", (first[0]["id"],)).fetchone()
    assert row["digest_shown_at"] is not None


def test_respects_target_per_tier_even_with_many_candidates(db_conn):
    for i in range(10):
        _insert_news(db_conn, "AWARENESS", f"Farkındalık haberi {i}")
    result = _select_news_for_digest(db_conn, analyzed_news=[], target_per_tier=3)
    assert len(result) == 3


def test_empty_when_nothing_analyzed_anywhere(db_conn):
    """Gerçekten hiçbir analiz edilmiş haber yoksa (ilk kurulum vb.) boş
    liste döner - uydurma içerik ÜRETİLMEZ."""
    assert _select_news_for_digest(db_conn, analyzed_news=[], target_per_tier=5) == []


# ---------------------------------------------------------------------------
# 2026-09-14 kök neden düzeltmesi ("sabah-akşam aynı haber neden tekrar
# gösteriliyor?" - canlı örnek: BengalSEO/Grindr haberleri 14 Eylül'de hem
# sabah hem akşam brifinginde birebir aynı metinle çıktı). Kök neden: bu
# fonksiyon digest_shown_at'i SIRALAMA için kullanıyordu ama HİÇBİR HARİÇ
# TUTMA koşulu yoktu - dar havuzlu tier'larda (LEARN/AWARENESS gibi) aynı
# kayıt saatler sonra "en uygun aday" olarak tekrar seçiliyordu.
# ---------------------------------------------------------------------------
def test_same_day_unchanged_item_is_not_shown_twice(db_conn):
    """morning shown -> unchanged event -> evening selector -> NOT SELECTED."""
    news_id = _insert_news(db_conn, "AWARENESS", "Sabah gösterilen değişmemiş haber")
    db_conn.execute(
        f"UPDATE news_events SET digest_shown_at = {_TODAY_START_IST} + interval '1 minute' WHERE id = %s",
        (news_id,),
    )
    result = _select_news_for_digest(db_conn, analyzed_news=[], target_per_tier=1)
    assert result == []


def test_same_day_item_with_material_update_may_be_shown_again(db_conn):
    """morning shown -> material_update=true -> evening selector -> MAY SELECT."""
    news_id = _insert_news(db_conn, "AWARENESS", "Sabah gösterilen, sonra güncellenen haber")
    db_conn.execute(
        f"""
        UPDATE news_events
        SET digest_shown_at = {_TODAY_START_IST} + interval '1 minute',
            material_update_at = {_TODAY_START_IST} + interval '2 minutes'
        WHERE id = %s
        """,
        (news_id,),
    )
    result = _select_news_for_digest(db_conn, analyzed_news=[], target_per_tier=1)
    assert len(result) == 1
    assert result[0]["id"] == news_id


def test_same_day_item_updated_before_it_was_shown_is_not_a_material_update(db_conn):
    """material_update_at, digest_shown_at'ten ÖNCEyse (güncelleme zaten
    gösterilen içeriğe yansımıştı) bu bir istisna SAYILMAZ - sadece
    material_update_at > digest_shown_at olan durumlarda tekrar gösterilir."""
    news_id = _insert_news(db_conn, "AWARENESS", "Güncelleme gösterimden önceydi")
    db_conn.execute(
        f"""
        UPDATE news_events
        SET material_update_at = {_TODAY_START_IST} + interval '1 minute',
            digest_shown_at = {_TODAY_START_IST} + interval '2 minutes'
        WHERE id = %s
        """,
        (news_id,),
    )
    result = _select_news_for_digest(db_conn, analyzed_news=[], target_per_tier=1)
    assert result == []


def test_different_day_unchanged_item_is_still_eligible_for_rotation(db_conn):
    """Fix'in etkisi SADECE aynı takvim günüyle sınırlı - dünkü bir gösterim
    normal rotasyonu (mevcut backfill davranışını) BOZMAMALI."""
    news_id = _insert_news(db_conn, "AWARENESS", "Dün gösterilmiş haber")
    db_conn.execute(
        "UPDATE news_events SET digest_shown_at = now() - interval '30 hours' WHERE id = %s",
        (news_id,),
    )
    result = _select_news_for_digest(db_conn, analyzed_news=[], target_per_tier=1)
    assert len(result) == 1
    assert result[0]["id"] == news_id


# ---------------------------------------------------------------------------
# 2026-09-14 (ikinci tur - "material update modelini düzelt", Senaryo A/B):
# uçtan uca entegrasyon - _recheck_kev_status_for_material_updates +
# _select_news_for_digest birlikte, gerçek KEV-flip senaryosuyla.
# ---------------------------------------------------------------------------
def test_same_day_non_material_update_suppressed(db_conn):
    """SENARYO A: sabah gösterildi, akşam aynı kaynak tekrar aynı bilgiyle
    geldi (source repeat) - material_update_at hiç ilerlemedi -> SUPPRESSED."""
    from cyber_radar.run_pipeline import _find_or_merge_news_event

    _find_or_merge_news_event(db_conn, {
        "title": "CVE-2026-9999 duyurusu", "cves": ["CVE-2026-9999"], "url": "https://a.example/1",
        "source": "Feed A", "summary": "özet", "published_at": None, "raw_text": "ham metin",
    })
    row = db_conn.execute("SELECT id FROM news_events WHERE title = %s", ("CVE-2026-9999 duyurusu",)).fetchone()
    db_conn.execute(
        f"UPDATE news_events SET analysis = %s::jsonb, analyzed_at = now(), relevance_status = 'relevant', "
        f"digest_shown_at = {_TODAY_START_IST} + interval '1 minute' WHERE id = %s",
        ('{"news_tier": "AWARENESS", "summary": "test"}', row["id"]),
    )
    # Akşam: aynı kaynak AYNI CVE ile tekrar geliyor (source repeat, yeni bilgi YOK).
    _find_or_merge_news_event(db_conn, {
        "title": "CVE-2026-9999 duyurusu", "cves": ["CVE-2026-9999"], "url": "https://a.example/1",
        "source": "Feed A", "summary": "özet", "published_at": None, "raw_text": "ham metin",
    })
    result = _select_news_for_digest(db_conn, analyzed_news=[], target_per_tier=1)
    assert result == []


def test_same_day_material_update_allows_redisplay(db_conn):
    """SENARYO B: sabah KEV değil, akşam CISA KEV listesine eklendi ->
    material_update_at ilerler, event akşam digest'inde tekrar aday
    olabilir (gerçek _recheck_kev_status_for_material_updates yolu)."""
    from cyber_radar.run_pipeline import _find_or_merge_news_event, _recheck_kev_status_for_material_updates

    _find_or_merge_news_event(db_conn, {
        "title": "CVE-2026-8888 duyurusu", "cves": ["CVE-2026-8888"], "url": "https://a.example/2",
        "source": "Feed A", "summary": "özet", "published_at": None, "raw_text": "ham metin",
    })
    row = db_conn.execute("SELECT id FROM news_events WHERE title = %s", ("CVE-2026-8888 duyurusu",)).fetchone()
    db_conn.execute(
        f"UPDATE news_events SET analysis = %s::jsonb, analyzed_at = now(), relevance_status = 'relevant', "
        f"cisa_kev = false, digest_shown_at = {_TODAY_START_IST} + interval '1 minute' WHERE id = %s",
        ('{"news_tier": "AWARENESS", "summary": "test"}', row["id"]),
    )
    # Akşam: CISA bu CVE'yi artık KEV listesine eklemiş.
    _recheck_kev_status_for_material_updates(db_conn, kev_set={"CVE-2026-8888"})

    updated = db_conn.execute(
        "SELECT cisa_kev, material_update_at, digest_shown_at FROM news_events WHERE id = %s", (row["id"],)
    ).fetchone()
    assert updated["cisa_kev"] is True
    assert updated["material_update_at"] is not None
    assert updated["material_update_at"] > updated["digest_shown_at"]

    result = _select_news_for_digest(db_conn, analyzed_news=[], target_per_tier=1)
    assert len(result) == 1
    assert result[0]["id"] == row["id"]


def test_per_tier_targets_are_independent(db_conn):
    """PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md A2/Y1):
    target_per_tier artık bir dict de kabul eder - her kategori BAĞIMSIZ
    bir hedefe sahip olabilir (ör. Hunt=1, Action=3), biri diğerini
    ETKİLEMEZ."""
    for i in range(3):
        _insert_news(db_conn, "ACTION_REQUIRED", f"Action haberi {i}")
    for i in range(3):
        _insert_news(db_conn, "HUNT_OPPORTUNITY", f"Hunt haberi {i}")

    result = _select_news_for_digest(
        db_conn, analyzed_news=[], target_per_tier={"ACTION_REQUIRED": 3, "HUNT_OPPORTUNITY": 1}
    )
    tiers = [json.loads(json.dumps(n["analysis"]))["news_tier"] if isinstance(n["analysis"], dict) else None for n in result]
    action_count = sum(1 for t in tiers if t == "ACTION_REQUIRED")
    hunt_count = sum(1 for t in tiers if t == "HUNT_OPPORTUNITY")
    assert action_count == 3
    assert hunt_count == 1


def test_int_target_per_tier_still_applies_uniformly(db_conn):
    """Geriye dönük uyumluluk: eski (tek int) davranış BİREBİR korunur."""
    for i in range(2):
        _insert_news(db_conn, "AWARENESS", f"Farkındalık haberi {i}")
    result = _select_news_for_digest(db_conn, analyzed_news=[], target_per_tier=2)
    assert len(result) == 2
