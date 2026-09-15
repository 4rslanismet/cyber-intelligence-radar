"""Collector Health raporu + kaynak bazlı anomaly detection (bkz.
src/run_pipeline._build_collector_health/_source_anomaly_warnings, Phase 2
madde 7-8). Test DB kullanır, gerçek ağ/Gemini çağrısı YOK."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from unittest.mock import patch

from cyber_radar import config
from cyber_radar.run_pipeline import (
    _aggregate_collector_errors,
    _build_collector_health,
    _classify_collector_error,
    _coverage_warning,
    _real_collector_errors,
    _run_gap_hours,
    _source_anomaly_warnings,
)


def _log(conn, source, kind, result_count, error=None, finished_at=None, run_type="incremental"):
    conn.execute(
        "INSERT INTO collector_runs (source, kind, finished_at, query, result_count, error, run_type) "
        "VALUES (%s, %s, COALESCE(%s, now()), %s, %s, %s, %s)",
        (source, kind, finished_at, "q", result_count, error, run_type),
    )


def test_source_anomaly_detects_total_drop_to_zero(db_conn):
    now = datetime.now(timezone.utc)
    prev_time = now - timedelta(hours=20)
    _log(db_conn, "openalex", "academic", 320, finished_at=prev_time)
    _log(db_conn, "openalex", "academic", 0)  # bu koşu - tamamen sıfır

    warnings = _source_anomaly_warnings(db_conn, now, threshold=0.4)
    assert len(warnings) == 1
    assert "openalex" in warnings[0]
    assert "320" in warnings[0]


def test_source_anomaly_detects_percentage_drop_above_threshold(db_conn):
    now = datetime.now(timezone.utc)
    prev_time = now - timedelta(hours=20)
    _log(db_conn, "crossref", "academic", 100, finished_at=prev_time)
    _log(db_conn, "crossref", "academic", 10)  # %90 düşüş, threshold %40'ı aşıyor

    warnings = _source_anomaly_warnings(db_conn, now, threshold=0.4)
    assert len(warnings) == 1
    assert "crossref" in warnings[0]


def test_source_anomaly_silent_when_drop_under_threshold(db_conn):
    now = datetime.now(timezone.utc)
    prev_time = now - timedelta(hours=20)
    _log(db_conn, "arxiv", "academic", 100, finished_at=prev_time)
    _log(db_conn, "arxiv", "academic", 80)  # %20 düşüş, threshold %40'ın altında

    assert _source_anomaly_warnings(db_conn, now, threshold=0.4) == []


def test_source_anomaly_silent_when_previous_was_already_zero(db_conn):
    """Önceki koşuda zaten 0 olan bir kaynak için karşılaştırma anlamsız -
    warning üretilmemeli (yeni eklenmiş/hiç sonuç vermeyen normal bir
    kaynak olabilir)."""
    now = datetime.now(timezone.utc)
    prev_time = now - timedelta(hours=20)
    _log(db_conn, "openreview", "academic", 0, finished_at=prev_time)
    _log(db_conn, "openreview", "academic", 0)
    assert _source_anomaly_warnings(db_conn, now, threshold=0.4) == []


def test_source_anomaly_escalates_on_consecutive_zero_streak(db_conn):
    """PHASE 10 (docs/FUNCTIONAL_GAP_ANALYSIS.md S2): tek bir '0 sonuç,
    hata yok' izlenmeli seviyesinde kalır, ama AYNI kaynak art arda
    SOURCE_CONSECUTIVE_ZERO_ALERT_COUNT (varsayılan 3) kadar koşuda 0
    veriyorsa uyarı ⚠️ seviyesine yükselir - BİLEREK `prev` (36 saatlik
    pencere) şartından bağımsız, çünkü uzun bir sıfır serisi o pencereyi
    aşabilir (bkz. fonksiyonun kod içi notu)."""
    now = datetime.now(timezone.utc)
    for hours_ago in (72, 48, 24):
        _log(db_conn, "openreview", "academic", 0, finished_at=now - timedelta(hours=hours_ago))
    _log(db_conn, "openreview", "academic", 0)  # bu koşu da 0 - toplam 4. art arda

    warnings = _source_anomaly_warnings(db_conn, now, threshold=0.4)
    assert len(warnings) == 1
    assert "⚠️" in warnings[0]
    assert "art arda 4 koşudur 0 sonuç" in warnings[0]


def test_source_anomaly_streak_resets_after_a_nonzero_run(db_conn):
    """t-30h'te GERÇEK bir sonuç var (36 saatlik pencere İÇİNDE, bu yüzden
    prev truthy) - bu, streak'i keser. Sadece t-6h ve şimdiki koşu 0
    (toplam 2 art arda) - eşiğin (3) ALTINDA, mild mesaj beklenir."""
    now = datetime.now(timezone.utc)
    _log(db_conn, "openreview", "academic", 50, finished_at=now - timedelta(hours=30))
    _log(db_conn, "openreview", "academic", 0, finished_at=now - timedelta(hours=6))
    _log(db_conn, "openreview", "academic", 0)

    warnings = _source_anomaly_warnings(db_conn, now, threshold=0.4)
    assert len(warnings) == 1
    assert "⚠️" not in warnings[0]
    assert "izlenmeli" in warnings[0]


def test_source_anomaly_ignores_errored_runs_in_comparison(db_conn):
    """error IS NOT NULL olan satırlar (zaten bir hata mesajıyla loglanmış)
    karşılaştırmaya DAHİL EDİLMEZ - onlar zaten ayrı şekilde görünür durumda."""
    now = datetime.now(timezone.utc)
    prev_time = now - timedelta(hours=20)
    _log(db_conn, "dblp", "academic", None, error="timeout", finished_at=prev_time)
    _log(db_conn, "dblp", "academic", None, error="disabled_degraded_optional")
    assert _source_anomaly_warnings(db_conn, now, threshold=0.4) == []


def test_build_collector_health_report_contains_expected_sections(db_conn):
    now = datetime.now(timezone.utc)
    _log(db_conn, "openalex", "academic", 50)
    _log(db_conn, "bleepingcomputer", "news", 20)
    _log(db_conn, "some_broken_feed", "news", None, error="timeout")

    report = _build_collector_health(
        db_conn, now, display_news=[], current_papers=[], learning_path_papers=[],
        historical_highlights=[], profile_a_papers=[], profile_b_papers=[],
    )
    assert "Sources attempted: 3" in report
    assert "Sources successful: 2" in report
    assert "Sources failed: 1" in report
    assert "News collected: 20" in report
    assert "Papers collected: 50" in report
    assert "Categories:" in report
    assert "Academic quota status:" in report
    # PHASE 10 (docs/FUNCTIONAL_GAP_ANALYSIS.md R1): tam bölüm listesi -
    # spec'teki örnek formatla birebir eşleşmeli.
    assert "# Collector Health" in report
    assert "Sources configured:" in report
    assert "After dedup:" in report
    assert "After filtering" in report
    assert "  Action:" in report
    assert "  Hunt:" in report
    assert "  Tutorial:" in report
    assert "  Awareness:" in report
    assert "  Current:" in report
    assert "  Timeline:" in report
    assert "  Classic:" in report
    assert "  Historical:" in report
    assert "  Research Profile A:" in report
    assert "  Research Profile B:" in report


def test_classify_collector_error_recognizes_parse_failures():
    """PHASE 10 (docs/FUNCTIONAL_GAP_ANALYSIS.md S3): JSON/XML parse
    hataları önceden 'diğer' sınıfına düşüyordu, rate-limit'ten ayırt
    edilemiyordu."""
    assert _classify_collector_error("json.decoder.JSONDecodeError: Expecting value") == "parse failure"
    assert _classify_collector_error("lxml.etree.XMLSyntaxError: Premature end of data") == "parse failure"
    assert _classify_collector_error("Response is not valid JSON") == "parse failure"
    assert _classify_collector_error("Client error '429 Unknown Error'") == "rate-limit (429)"


def test_aggregate_collector_errors_distinguishes_parse_failures_from_rate_limits(db_conn):
    errors = [
        {"source": "arxiv", "error": "Client error '429 Unknown Error'"},
        {"source": "arxiv", "error": "json.decoder.JSONDecodeError: Expecting value"},
    ]
    lines = _aggregate_collector_errors(errors)
    assert len(lines) == 1
    assert "rate-limit (429): 1" in lines[0]
    assert "parse failure: 1" in lines[0]


def test_build_collector_health_shows_academic_quota_fractions(db_conn):
    now = datetime.now(timezone.utc)
    report = _build_collector_health(
        db_conn, now, display_news=[],
        current_papers=[{"id": 1}, {"id": 2}],
        learning_path_papers=[{"id": 3}],
        historical_highlights=[{"id": 4}, {"id": 5}],
        profile_a_papers=[{"id": 6}] * 5,
        profile_b_papers=[],
    )
    assert "Current: 2/5" in report
    assert "Timeline: 1/5" in report
    assert "Research Profile A: 5/5" in report
    assert "Research Profile B: 0/5" in report


# ---------------------------------------------------------------------------
# 2026-09-11: iki koşu normal kadanstan (config.ANOMALY_MIN_RUN_GAP_HOURS,
# varsayılan 6 saat) çok daha yakın çalışırsa kaynak/toplam karşılaştırması
# YANILTICI olur (rate-limiting/dar since_date penceresi normal, "kaynak
# bozuldu" DEĞİL - canlıda gözlendi: 40 dakika arayla iki koşu openalex/
# crossref/RSS'te "%90 düşüş"/"muhtemelen bozuldu" YANLIŞ pozitifi
# üretti). _run_gap_hours bu süreyi hesaplar, main() bunu threshold'la
# karşılaştırıp anomaly kontrolünü atlar.
# ---------------------------------------------------------------------------
def test_run_gap_hours_returns_none_when_no_previous_run():
    now = datetime.now(timezone.utc)
    assert _run_gap_hours(now, None) is None


def test_run_gap_hours_computes_correct_gap():
    now = datetime.now(timezone.utc)
    previous = now - timedelta(minutes=40)
    gap = _run_gap_hours(now, previous.isoformat())
    assert abs(gap - (40 / 60)) < 0.01


def test_run_gap_of_40_minutes_is_below_default_anomaly_threshold():
    """Canlıda gözlenen tam senaryo: 40 dakikalık bir aralık, varsayılan
    ANOMALY_MIN_RUN_GAP_HOURS (6 saat) eşiğinin ALTINDA kalmalı - yani bu
    koşuda anomaly kontrolü ATLANMALI (main()'deki run_too_soon mantığı)."""
    now = datetime.now(timezone.utc)
    previous = now - timedelta(minutes=40)
    gap = _run_gap_hours(now, previous.isoformat())
    assert gap < config.ANOMALY_MIN_RUN_GAP_HOURS


def test_run_gap_of_12_hours_is_above_default_anomaly_threshold():
    """Normal kadans (12 saat) eşiğin ÜSTÜNDE kalmalı - bu durumda anomaly
    kontrolü NORMAL çalışmaya devam etmeli (gerçek bozulmalar hâlâ yakalanır)."""
    now = datetime.now(timezone.utc)
    previous = now - timedelta(hours=12)
    gap = _run_gap_hours(now, previous.isoformat())
    assert gap > config.ANOMALY_MIN_RUN_GAP_HOURS


# ---------------------------------------------------------------------------
# 2026-09-11 (kullanıcı isteği: "gerçekten problem varsa bunu bulsun, error
# loglarına yazsın") - canlı teşhis edildi: bir kaynağın sonuç sayısı
# düşmesi TEK BAŞINA "bozuldu" anlamına gelmiyor (ör. arxiv: dar pencerede
# 0, geniş pencerede 25 gerçek makale döndürdü - API sağlıklıydı). Artık
# SADECE collector_runs.error DOLU olan (gerçek istisna/HTTP hatası)
# kaynaklar "🔴" ile işaretleniyor VE ayrı bir log dosyasına yazılıyor;
# error'suz düşüşler "ℹ️" ile daha temkinli raporlanıyor.
#
# 2026-09-14 güncellemesi (kullanıcı isteği: "Collector hata mesajları
# neden Telegram'ı dolduruyor?"): ham exception metni ("ConnectionError:
# timeout") artık Telegram'a giden warnings listesinde YOK - aynı kaynağın
# aynı koşuda art arda 429/timeout alması eskiden 2-3 neredeyse birebir
# aynı ham satır üretiyordu. Şimdi kaynak+hata-sınıfı bazında TEK,
# AGGREGATE bir satıra ve bir "⚠️ Collector Health: DEGRADED" başlığına
# indirgeniyor; ham metin collector_runs.error'da/log dosyasında/
# COLLECTOR_HEALTH.md'de duruyor (bkz. _aggregate_collector_errors).
# ---------------------------------------------------------------------------
def test_real_error_is_flagged_as_gercek_hata_not_generic_broken_wording(db_conn):
    now = datetime.now(timezone.utc)
    _log(db_conn, "openalex", "academic", None, error="ConnectionError: timeout")
    warnings = _source_anomaly_warnings(db_conn, now)
    assert "⚠️ Collector Health: DEGRADED" in warnings
    assert any("🔴" in w and "openalex" in w and "timeout" in w for w in warnings)


def test_real_errors_from_same_source_are_aggregated_not_repeated(db_conn):
    """2026-09-14 kök neden: aynı kaynağın aynı koşuda 3 ayrı sorgusu
    (ör. 3 KEYWORDS kelimesi) başarısız olursa, eskiden 3 ayrı ham satır
    basılıyordu - Telegram'ı dolduran asıl buydu. Artık TEK satırda,
    hata sınıfı bazında sayılmalı."""
    now = datetime.now(timezone.utc)
    _log(db_conn, "arxiv", "academic", None, error="The read operation timed out")
    _log(db_conn, "arxiv", "academic", None, error="Client error '429 Unknown Error' for url ...")
    _log(db_conn, "arxiv", "academic", None, error="Client error '429 Unknown Error' for url ...")
    warnings = _source_anomaly_warnings(db_conn, now)
    arxiv_lines = [w for w in warnings if "🔴" in w and "arxiv" in w]
    assert len(arxiv_lines) == 1
    assert "3 hata" in arxiv_lines[0]
    assert "timeout: 1" in arxiv_lines[0]
    assert "429" in arxiv_lines[0] and "2" in arxiv_lines[0]


def test_benign_drop_without_error_is_not_called_broken(db_conn):
    """error YOK, sadece sayı düştü - artık "bozuldu"/"muhtemelen bozuldu"
    DENMEMELİ, daha temkinli bir ifade kullanılmalı."""
    now = datetime.now(timezone.utc)
    prev_time = now - timedelta(hours=20)
    _log(db_conn, "arxiv", "academic", 43, finished_at=prev_time)
    _log(db_conn, "arxiv", "academic", 0)
    warnings = _source_anomaly_warnings(db_conn, now)
    assert len(warnings) == 1
    assert "bozuldu" not in warnings[0].lower()
    assert "ℹ️" in warnings[0]
    assert "hata YOK" in warnings[0] or "hata yok" in warnings[0].lower()


def test_intentional_skip_markers_are_not_real_errors(db_conn):
    now = datetime.now(timezone.utc)
    _log(db_conn, "dblp", "academic", None, error="disabled_degraded_optional")
    _log(db_conn, "ieee_xplore", "academic", None, error="disabled_missing_credentials")
    assert _real_collector_errors(db_conn, now) == []


def test_real_errors_are_written_to_dedicated_log_file(db_conn, tmp_path):
    log_file = tmp_path / "collector_errors.log"
    now = datetime.now(timezone.utc)
    _log(db_conn, "crossref", "academic", None, error="HTTPStatusError: 500")
    with patch("cyber_radar.run_pipeline.config.COLLECTOR_ERROR_LOG_FILE", str(log_file)), \
         patch("cyber_radar.run_pipeline.config.COLLECTOR_ERROR_LOG_ENABLED", True):
        _source_anomaly_warnings(db_conn, now)
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "crossref" in content
    assert "HTTPStatusError: 500" in content


def test_error_log_writing_respects_disabled_config(db_conn, tmp_path):
    log_file = tmp_path / "should_not_exist.log"
    now = datetime.now(timezone.utc)
    _log(db_conn, "crossref", "academic", None, error="HTTPStatusError: 500")
    with patch("cyber_radar.run_pipeline.config.COLLECTOR_ERROR_LOG_FILE", str(log_file)), \
         patch("cyber_radar.run_pipeline.config.COLLECTOR_ERROR_LOG_ENABLED", False):
        _source_anomaly_warnings(db_conn, now)
    assert not log_file.exists()


# ---------------------------------------------------------------------------
# 2026-09-14 kök neden raporu (madde 3 - "Global 644 → 174 alarmı doğru mu?"):
# hem _coverage_warning hem _source_anomaly_warnings zaten run_type='incremental'
# filtreliyordu (kod incelemesiyle doğrulandı) ama bu ASLA test edilmemişti -
# recovery_backfill'in devasa toplam sayılarının baseline'ı kirletmediğini ve
# gerçek bir incremental anomalisinin hâlâ yakalandığını burada kanıtlıyoruz.
# ---------------------------------------------------------------------------
def test_recovery_backfill_totals_never_pollute_the_incremental_baseline(db_conn):
    """previous recovery_backfill=2000, current incremental=200 -> alarm YOK
    (recovery_backfill hiçbir zaman baseline'a girmemeli)."""
    now = datetime.now(timezone.utc)
    prev_time = now - timedelta(hours=20)
    _log(db_conn, "openalex", "academic", 2000, finished_at=prev_time, run_type="recovery_backfill")
    assert _coverage_warning(db_conn, this_run_total=200) is None


def test_incremental_only_baseline_still_catches_a_real_drop(db_conn):
    """previous incremental toplam yüksekken, bugünkü incremental toplam
    %70+ düşerse (recovery_backfill karışmasa bile) global uyarı hâlâ
    üretilmeli - filtre 'hiç alarm üretmeme'ye kaçmamalı."""
    now = datetime.now(timezone.utc)
    prev_time = now - timedelta(hours=20)
    _log(db_conn, "openalex", "academic", 800, finished_at=prev_time, run_type="incremental")
    warning = _coverage_warning(db_conn, this_run_total=100)
    assert warning is not None
    assert "800" in warning


def test_recovery_backfill_previous_run_does_not_trigger_source_level_anomaly(db_conn):
    """previous recovery_backfill=2000 (arxiv), current incremental=0 (ama
    hata YOK) -> kaynak bazlı karşılaştırma da recovery_backfill'i GÖRMEMELİ,
    yani 'önceki 2000 -> şimdi 0' gibi yanıltıcı bir uyarı ÜRETİLMEMELİ."""
    now = datetime.now(timezone.utc)
    prev_time = now - timedelta(hours=20)
    _log(db_conn, "arxiv", "academic", 2000, finished_at=prev_time, run_type="recovery_backfill")
    _log(db_conn, "arxiv", "academic", 0)  # bu koşu, incremental, hata YOK
    warnings = _source_anomaly_warnings(db_conn, now)
    assert warnings == []  # "önceki koşuda zaten 0'dı" dalına düşer - recovery_backfill hiç görülmedi


def test_previous_incremental_success_then_current_429_is_flagged(db_conn):
    """previous incremental arxiv=50 (başarılı), current incremental
    arxiv=0 + HTTP 429 (gerçek hata) -> alarm VAR, ve gerçek hata olarak
    (ℹ️ değil, DEGRADED+🔴) raporlanmalı."""
    now = datetime.now(timezone.utc)
    prev_time = now - timedelta(hours=20)
    _log(db_conn, "arxiv", "academic", 50, finished_at=prev_time, run_type="incremental")
    _log(db_conn, "arxiv", "academic", None, error="Client error '429 Unknown Error' for url ...")
    warnings = _source_anomaly_warnings(db_conn, now)
    assert "⚠️ Collector Health: DEGRADED" in warnings
    assert any("🔴" in w and "arxiv" in w and "429" in w for w in warnings)
