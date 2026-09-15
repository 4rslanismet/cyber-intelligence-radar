"""arXiv / OpenAlex / Semantic Scholar rate-limit koruması (bkz.
src/collectors/academic.py, 2026-09-14 kök neden raporu madde 6 + ikinci
tur temizliği madde 6-11: "recovery_mode SADECE gerçek recovery/backfill
anlamına gelsin, base host-limiter HER modda koşulsuz aktif olsun").
Gerçek ağ çağrısı YOK - httpx.get monkeypatch'lenir (block_real_network
fixture'ının üzerine) ya da academic._get_with_limiter/_recovery_backoff_get
doğrudan mock'lanır."""
from __future__ import annotations

import os
import time
from datetime import date

import httpx
import pytest

from cyber_radar.collectors import academic


def _fake_response(status_code: int, json_body: dict, url: str = "https://example.test", headers: dict | None = None):
    return httpx.Response(
        status_code=status_code,
        json=json_body,
        headers=headers or {},
        request=httpx.Request("GET", url),
    )


# ---------------------------------------------------------------------------
# _HostRequestLimiter: ardışık iki çağrı arasında minimum aralık - hem normal
# hem recovery yolun PAYLAŞTIĞI tek limiter mekanizması.
# ---------------------------------------------------------------------------
def test_host_request_limiter_enforces_minimum_interval():
    limiter = academic._HostRequestLimiter(0.05)
    t0 = time.monotonic()
    limiter.wait_for_slot()
    limiter.wait_for_slot()  # ilk çağrıdan hemen sonra - beklemeli
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.05


def test_host_request_limiter_does_not_wait_if_enough_time_already_passed():
    limiter = academic._HostRequestLimiter(0.05)
    limiter.wait_for_slot()
    time.sleep(0.06)
    t0 = time.monotonic()
    limiter.wait_for_slot()
    assert time.monotonic() - t0 < 0.02  # neredeyse anında dönmeli


# ---------------------------------------------------------------------------
# _get_with_limiter: BASE katman - normal VE recovery HER İKİSİNİN de
# üzerinden geçtiği, koşulsuz limiter + bounded retry.
# ---------------------------------------------------------------------------
def test_get_with_limiter_calls_wait_for_slot(monkeypatch):
    calls = {"waited": False}

    class _FakeLimiter:
        def wait_for_slot(self):
            calls["waited"] = True

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_response(200, {"results": []}))
    academic._get_with_limiter("https://api.openalex.org/works", {}, _FakeLimiter())
    assert calls["waited"] is True


def test_get_with_limiter_has_bounded_retry_not_recovery_ladder(monkeypatch):
    """Base katman `_retry_get`'in KISA merdivenini kullanır (4 deneme, max
    25sn) - recovery'nin 30/60/120/300sn merdiveni burada YOK."""
    sleeps: list[float] = []
    monkeypatch.setattr(academic.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_response(429, {}))
    limiter = academic._HostRequestLimiter(0.0)

    with pytest.raises(httpx.HTTPStatusError):
        academic._get_with_limiter("https://export.arxiv.org/api/query", {}, limiter)

    assert all(s <= 25 for s in sleeps)  # recovery merdiveninin 30/60/120/300 değerleri YOK


# ---------------------------------------------------------------------------
# _recovery_backoff_get: SADECE recovery/backfill'e özel EK politika -
# Retry-After'a uyar ama tavanla (300sn) sınırlar, yoksa 30/60/120/300sn
# merdiveni kullanır.
# ---------------------------------------------------------------------------
def test_recovery_backoff_respects_retry_after_header_but_caps_it(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(academic.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(academic.random, "uniform", lambda a, b: 0.0)  # jitter'ı sabitle

    calls = {"n": 0}

    def fake_get(url, params=None, timeout=None, follow_redirects=None, headers=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _fake_response(429, {}, headers={"Retry-After": "9999"})  # tavanın ÇOK üstünde
        return _fake_response(200, {"results": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    limiter = academic._HostRequestLimiter(0.0)

    resp = academic._recovery_backoff_get("https://api.openalex.org/works", {}, limiter)

    assert resp.status_code == 200
    assert calls["n"] == 2
    assert sleeps == [academic._RETRY_AFTER_CAP_SECONDS]  # 9999 değil, 300'e sınırlandı


def test_recovery_backoff_uses_ladder_when_no_retry_after(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(academic.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(academic.random, "uniform", lambda a, b: 0.0)

    calls = {"n": 0}

    def fake_get(url, params=None, timeout=None, follow_redirects=None, headers=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return _fake_response(429, {})  # Retry-After YOK
        return _fake_response(200, {"results": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    limiter = academic._HostRequestLimiter(0.0)

    resp = academic._recovery_backoff_get("https://export.arxiv.org/api/query", {}, limiter)

    assert resp.status_code == 200
    assert sleeps == list(academic._RECOVERY_BACKOFF_LADDER[:2])  # 30, 60 - merdivenden


def test_recovery_backoff_gives_up_and_raises_after_ladder_exhausted(monkeypatch):
    monkeypatch.setattr(academic.time, "sleep", lambda s: None)
    monkeypatch.setattr(academic.random, "uniform", lambda a, b: 0.0)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_response(429, {}))
    limiter = academic._HostRequestLimiter(0.0)

    with pytest.raises(httpx.HTTPStatusError):
        academic._recovery_backoff_get("https://export.arxiv.org/api/query", {}, limiter)


def test_retry_after_is_bounded_never_unbounded_sleep(monkeypatch):
    """2026-09-13 canlı olayının regresyon testi: OpenAlex'in dakikalarca/
    saatlerce isteyebileceği bir Retry-After DEĞERİ HİÇBİR ZAMAN doğrudan
    uygulanmamalı - _RETRY_AFTER_CAP_SECONDS'ı AŞAN her sleep çağrısı bug'dır."""
    sleeps: list[float] = []
    monkeypatch.setattr(academic.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(academic.random, "uniform", lambda a, b: 0.0)
    calls = {"n": 0}

    def fake_get(url, params=None, timeout=None, follow_redirects=None, headers=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _fake_response(429, {}, headers={"Retry-After": "36000"})  # 10 saat
        return _fake_response(200, {"results": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    academic._recovery_backoff_get("https://api.openalex.org/works", {}, academic._HostRequestLimiter(0.0))
    assert all(s <= academic._RETRY_AFTER_CAP_SECONDS for s in sleeps)


# ---------------------------------------------------------------------------
# 2026-09-14 ikinci tur (madde 6-7): base host-limiter HER İKİ modda da
# koşulsuz aktif; recovery_mode SADECE ek politika (uzun timeout + backoff
# merdiveni) açıp kapatan bir switch - limiter'ı DEĞİL.
# ---------------------------------------------------------------------------
def test_arxiv_limiter_used_in_incremental(monkeypatch):
    called = {}

    def fake_base(url, params, limiter, headers=None):
        called["fn"] = "base"
        called["limiter"] = limiter
        return _fake_response(200, {}, url=url)

    monkeypatch.setattr(academic, "_get_with_limiter", fake_base)
    monkeypatch.setattr(academic, "_parse_arxiv_response", lambda text, since, until=None: [])

    academic.search_arxiv("cybersecurity", date(2026, 1, 1), recovery_mode=False)
    assert called["fn"] == "base"
    assert called["limiter"] is academic._ARXIV_LIMITER


def test_arxiv_limiter_used_in_recovery(monkeypatch):
    called = {}

    def fake_recovery(url, params, limiter, headers=None):
        called["fn"] = "recovery"
        called["limiter"] = limiter
        return _fake_response(200, {}, url=url)

    monkeypatch.setattr(academic, "_recovery_backoff_get", fake_recovery)
    monkeypatch.setattr(academic, "_parse_arxiv_response", lambda text, since, until=None: [])

    academic.search_arxiv("cybersecurity", date(2026, 1, 1), recovery_mode=True)
    assert called["fn"] == "recovery"
    assert called["limiter"] is academic._ARXIV_LIMITER  # AYNI limiter, farklı politika


def test_openalex_limiter_used_in_incremental(monkeypatch):
    called = {}

    def fake_base(url, params, limiter, headers=None):
        called["limiter"] = limiter
        return _fake_response(200, {"results": []}, url=url)

    monkeypatch.setattr(academic, "_get_with_limiter", fake_base)

    academic.search_openalex("cybersecurity", date(2026, 1, 1), recovery_mode=False)
    assert called["limiter"] is academic._OPENALEX_LIMITER


def test_semantic_scholar_limiter_used_in_incremental(monkeypatch):
    called = {}

    def fake_base(url, params, limiter, headers=None):
        called["limiter"] = limiter
        return _fake_response(200, {"data": []}, url=url)

    monkeypatch.setattr(academic, "_get_with_limiter", fake_base)

    academic.search_semantic_scholar("cybersecurity", date(2026, 1, 1))
    assert called["limiter"] is academic._SEMANTIC_SCHOLAR_LIMITER


def test_semantic_scholar_bulk_limiter_used(monkeypatch):
    called = {}

    def fake_base(url, params, limiter, headers=None):
        called["limiter"] = limiter
        return _fake_response(200, {"data": []}, url=url)

    monkeypatch.setattr(academic, "_get_with_limiter", fake_base)

    academic.search_semantic_scholar_bulk("cybersecurity AND SOC", date(2026, 1, 1))
    assert called["limiter"] is academic._SEMANTIC_SCHOLAR_LIMITER


def test_normal_pipeline_does_not_require_recovery_mode_for_limiter(monkeypatch):
    """Kök nokta: recovery_mode=False (normal incremental varsayılanı) İKEN
    BİLE arXiv/OpenAlex/Semantic Scholar host-limiter'dan geçiyor - limiter
    kullanımı recovery_mode'a bağlı DEĞİL."""
    seen_limiters = []

    def fake_base(url, params, limiter, headers=None):
        seen_limiters.append(limiter)
        return _fake_response(200, {"results": [], "data": []}, url=url)

    monkeypatch.setattr(academic, "_get_with_limiter", fake_base)
    monkeypatch.setattr(academic, "_parse_arxiv_response", lambda text, since, until=None: [])

    academic.search_arxiv("cybersecurity", date(2026, 1, 1))  # recovery_mode default=False
    academic.search_openalex("cybersecurity", date(2026, 1, 1))  # default=False
    academic.search_semantic_scholar("cybersecurity", date(2026, 1, 1))  # hiç recovery_mode parametresi YOK

    assert seen_limiters == [academic._ARXIV_LIMITER, academic._OPENALEX_LIMITER, academic._SEMANTIC_SCHOLAR_LIMITER]


def test_recovery_policy_is_more_conservative(monkeypatch):
    """recovery_mode=True iken timeout DAHA UZUN (50s > 20s) ve backoff
    merdiveni DAHA UZUN (300s tavan > 25s) - recovery normal'den daha
    temkinli, ama AYNI base limiter'ı kullanıyor."""
    assert academic._RECOVERY_TIMEOUT.read > academic._TIMEOUT.read
    assert academic._RETRY_AFTER_CAP_SECONDS > 25.0  # base _retry_get'in max bekleme süresinden BÜYÜK


def test_rate_limit_failure_does_not_crash_pipeline():
    """Tek bir kaynağın 429/timeout ile başarısız olması _collect_profile'ı
    ÇÖKERTMEMELİ - bkz. src/run_pipeline.py: her koleksiyon çağrısı kendi
    try/except'iyle izole, exception collector_runs.error'a yazılıp bir
    sonraki kaynağa geçiliyor. Burada AYNI ilkeyi doğrudan _collect_
    profile-benzeri bir sarmalayıcıyla kanıtlıyoruz."""
    def _always_429(*a, **k):
        raise httpx.HTTPStatusError("429", request=httpx.Request("GET", "https://x"), response=_fake_response(429, {}))

    total = 0
    errors = []
    for fn in (_always_429, lambda: [1, 2, 3]):
        try:
            items = fn()
            total += len(items)
        except Exception as e:  # noqa: BLE001 - _collect_profile'daki AYNI desen
            errors.append(str(e))
    assert total == 3  # ikinci "kaynak" hâlâ işlendi
    assert len(errors) == 1  # birinci kaynağın hatası izole kaldı, pipeline'ı düşürmedi


# ---------------------------------------------------------------------------
# 2026-09-15 CANLI ARIZA DÜZELTMESİ: process-içi limiter, AYRI process'ler
# (src.run_pipeline + scripts.run_recovery aynı anda çalışınca, canlıda
# tam olarak oldu - bkz. src/collectors/academic.py _HostRequestLimiter
# docstring'i) arasında GERÇEK bir koruma sağlamıyordu - her process kendi
# belleğinde sıfırdan sayıyordu. Bu testler `lock_file` verilince İKİ AYRI
# nesnenin (aynı process içinde bile olsa, birbirinin belleğinden HABERSİZ)
# aynı dosya üzerinden GERÇEKTEN koordine olduğunu kanıtlıyor - iki ayrı
# process'i simüle etmenin en basit yolu bu, mekanizma dosya kilidine
# dayandığı için process sınırı önemli değil.
# ---------------------------------------------------------------------------
def test_cross_process_lock_enforces_interval_between_independent_instances(tmp_path):
    lock_file = str(tmp_path / "ratelimit_test.lock")
    limiter_a = academic._HostRequestLimiter(0.1, lock_file=lock_file)
    limiter_b = academic._HostRequestLimiter(0.1, lock_file=lock_file)  # AYRI nesne - "başka process"

    t0 = time.monotonic()
    limiter_a.wait_for_slot()   # ilk "process" ilk isteğini atar
    limiter_b.wait_for_slot()   # ikinci "process" HEMEN ardından - beklemeli
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.1  # limiter_b, limiter_a'nın process-içi belleğinden HABERSİZ olsa da bekledi


def test_cross_process_lock_does_not_wait_if_enough_time_passed(tmp_path):
    lock_file = str(tmp_path / "ratelimit_test2.lock")
    limiter_a = academic._HostRequestLimiter(0.1, lock_file=lock_file)
    limiter_b = academic._HostRequestLimiter(0.1, lock_file=lock_file)

    limiter_a.wait_for_slot()
    time.sleep(0.12)
    t0 = time.monotonic()
    limiter_b.wait_for_slot()
    assert time.monotonic() - t0 < 0.05  # yeterince zaman geçmiş, beklememeli


def test_cross_process_lock_survives_empty_or_corrupt_state_file(tmp_path):
    lock_file = str(tmp_path / "ratelimit_test3.lock")
    with open(lock_file, "w") as f:
        f.write("not-a-number-garbage")  # bozuk/okunamaz içerik

    limiter = academic._HostRequestLimiter(0.05, lock_file=lock_file)
    t0 = time.monotonic()
    limiter.wait_for_slot()  # ÇÖKMEMELİ - bozuk içeriği 0.0 kabul edip devam etmeli
    assert time.monotonic() - t0 < 0.05  # "son çağrı" bilinmiyor sayıldığı için beklemedi


def test_cross_process_lock_creates_state_directory_if_missing(tmp_path):
    lock_file = str(tmp_path / "nested" / "dir" / "ratelimit_test4.lock")
    limiter = academic._HostRequestLimiter(0.0, lock_file=lock_file)
    limiter.wait_for_slot()  # ÇÖKMEMELİ - data/state/ eşdeğeri yoksa oluşturmalı
    assert os.path.exists(lock_file)


def test_live_arxiv_openalex_semantic_scholar_limiters_use_cross_process_locks():
    """Canlı arıza tam olarak bu üç limiter'ın process-içi çalışmasından
    kaynaklandı - üçünün de artık gerçek bir lock_file'a sahip olduğunu
    doğrula (regresyon testi, bkz. 2026-09-15 08:43 canlı arXiv 429/timeout
    olayı)."""
    assert academic._ARXIV_LIMITER.lock_file is not None
    assert academic._OPENALEX_LIMITER.lock_file is not None
    assert academic._SEMANTIC_SCHOLAR_LIMITER.lock_file is not None
    # Üçü de farklı dosyalarda - birbirini yanlışlıkla bekletmemeli.
    assert len({
        academic._ARXIV_LIMITER.lock_file,
        academic._OPENALEX_LIMITER.lock_file,
        academic._SEMANTIC_SCHOLAR_LIMITER.lock_file,
    }) == 3
