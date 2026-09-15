"""Gemini günlük istek kotası bütçeleyici (load balancing).

cyber-radar.timer günde GEMINI_RUNS_PER_DAY kez çalışır (varsayılan 2:
07:30/19:30). Bir koşuda toplanan 'pending' haber/makale sayısı tavan
değildir (ör. 30 günlük historical scan sonrası) - relevance + derin analiz
döngüleri sınırsız art arda LLM çağırırsa bu, ücretsiz tier'ın hem dakikalık
hem günlük limitini tek koşuda aşabilir.

Bu modül pipeline_state (bkz. db.get_state/set_state) üzerinde günlük bir
sayaç tutar ve her koşuya, günlük hakkın koşu sayısına bölünmüş kadarını -
her durumda o gün kalan gerçek hakkı geçmeyecek şekilde - bütçe olarak verir.
Bütçe biterken döngü sessizce durur: işlenmeyen satırlar 'pending' /
analyzed_at IS NULL kalır, bir sonraki koşuda (gerekirse ertesi gün) otomatik
devam eder - veri kaybı yok, sadece zamana yayılıyor.
"""
from __future__ import annotations

import datetime as dt

from .. import config, db


def _state_key(day: dt.date) -> str:
    return f"llm_calls_{day.isoformat()}"


class LLMBudget:
    """Bir pipeline koşusu boyunca paylaşılan, tüketildikçe azalan çağrı hakkı.

    Kullanım: koşu başında bir kez oluşturulur, ilgililik + analiz
    döngülerine parametre olarak geçirilir; her öğeden önce has_capacity()
    kontrol edilir, çağrı denenecekse consume() ile hak düşülür."""

    def __init__(self, conn) -> None:
        self._conn = conn
        self._day = dt.date.today()
        used_today = int(db.get_state(conn, _state_key(self._day), "0") or "0")
        self._used_today = used_today
        remaining_today = max(0, config.GEMINI_DAILY_REQUEST_LIMIT - used_today)
        per_run_cap = config.GEMINI_DAILY_REQUEST_LIMIT // max(1, config.GEMINI_RUNS_PER_DAY)
        self.remaining = min(remaining_today, per_run_cap)

    def has_capacity(self) -> bool:
        return self.remaining > 0

    def consume(self, n: int = 1) -> None:
        """LLM çağrısı denenmeden hemen önce çağrılır (rezervasyon). Günlük
        sayaç anında Postgres'e yazılır ki koşu yarıda kesilse bile doğru
        kalsın."""
        self.remaining = max(0, self.remaining - n)
        self._used_today += n
        db.set_state(self._conn, _state_key(self._day), str(self._used_today))


class NamedBudget:
    """LLMBudget'tan (yukarıda) BİLİNÇLİ OLARAK AYRI bir günlük bütçe
    havuzu - proje notları: "Daily Cyber kotası ile tez/SCI kotasını
    birbirine yedirme". Kendi `llm_calls_<pool>_<gün>` pipeline_state
    anahtarını kullanır - run_pipeline.py'nin (daily_cyber) LLMBudget'ıyla
    SAYAÇ PAYLAŞMAZ, günlük radar'ın kotasını asla yemez.

    scripts/run_research_workflow.py bunu screening (DAILY_SCREENING_BUDGET)
    ve research extraction (RESEARCH_ANALYSIS_BUDGET) için AYRI AYRI
    örnekler - ikisi birbirinin de kotasını yemez. Bütçe biterse research
    workflow ÇÖKMEZ, 'pending' bırakır ve bir sonraki --resume koşusunda
    devam eder (LLMBudget ile AYNI "veri kaybı yok, zamana yayılır" ilkesi).

    run_pipeline.py (günlük radar) da 2026-09-10 kök neden analizinden
    sonra bunu haber ve makale işleme için İKİ AYRI havuz olarak kullanıyor
    (pool="ops_news"/"ops_papers") - `runs_per_day` verilirse LLMBudget'la
    AYNI "günlük hakkı koşu sayısına böl" davranışını uygular (sabah koşusu
    günün tüm payını tüketip akşam koşusunu aç bırakmasın diye)."""

    def __init__(self, conn, pool_name: str, daily_limit: int, runs_per_day: int | None = None) -> None:
        self._conn = conn
        self._pool_name = pool_name
        self._day = dt.date.today()
        used_today = int(db.get_state(conn, self._state_key(), "0") or "0")
        self._used_today = used_today
        remaining_today = max(0, daily_limit - used_today)
        if runs_per_day:
            per_run_cap = daily_limit // max(1, runs_per_day)
            self.remaining = min(remaining_today, per_run_cap)
        else:
            self.remaining = remaining_today

    def _state_key(self) -> str:
        return f"llm_calls_{self._pool_name}_{self._day.isoformat()}"

    def has_capacity(self) -> bool:
        return self.remaining > 0

    def consume(self, n: int = 1) -> None:
        self.remaining = max(0, self.remaining - n)
        self._used_today += n
        db.set_state(self._conn, self._state_key(), str(self._used_today))
