"""2026-09-10 kök neden analizi: haber ve makale işleme artık İKİ BAĞIMSIZ
günlük LLM bütçesi kullanıyor (bkz. src/run_pipeline.main, config.
NEWS_DAILY_LLM_BUDGET/PAPERS_DAILY_LLM_BUDGET) - biri tükenmesi diğerini
ETKİLEMEZ. Gerçek Gemini çağrısı YOK, sadece NamedBudget sayaç izolasyonu
test ediliyor."""
from __future__ import annotations

from cyber_radar.llm.budget import NamedBudget


def test_news_and_papers_pools_are_independent(db_conn):
    news_budget = NamedBudget(db_conn, "ops_news", 9)
    papers_budget = NamedBudget(db_conn, "ops_papers", 9)

    # Makale tarafı TÜM payını tüketsin.
    papers_budget.consume(9)
    assert papers_budget.remaining == 0
    # Haber tarafı hiç ETKİLENMEMELİ - eskiden ikisi AYNI sayacı paylaşıyordu,
    # bu yüzden bu tam olarak canlıda gözlenen "makale çoğaldıkça haber
    # kotası sıfırlanıyor" bug'ının regresyon testidir.
    assert news_budget.remaining == 9
    assert news_budget.has_capacity()


def test_ops_pools_do_not_share_counter_with_daily_cyber_llmbudget_key(db_conn):
    """ops_news/ops_papers, run_pipeline.py'nin ESKİ paylaşılan
    'llm_calls_<gün>' anahtarına (LLMBudget) HİÇ dokunmamalı - farklı bir
    pipeline_state anahtarı kullanıyor (llm_calls_ops_news_<gün> /
    llm_calls_ops_papers_<gün>)."""
    from datetime import date

    from cyber_radar import db as db_mod

    daily_key = f"llm_calls_{date.today().isoformat()}"
    before = db_mod.get_state(db_conn, daily_key)

    NamedBudget(db_conn, "ops_news", 9).consume(3)
    NamedBudget(db_conn, "ops_papers", 9).consume(3)

    after = db_mod.get_state(db_conn, daily_key)
    assert before == after  # eski günlük radar sayacı hiç değişmedi


def test_per_run_cap_with_real_db(db_conn):
    """runs_per_day verildiğinde LLMBudget'la AYNI ilke: TEK BİR koşu günün
    yarısından fazlasını tüketemez (sabah koşusu akşam koşusunu aç
    bırakmasın), ama iki koşu BİRLİKTE günlük toplam limiti aşmadığı sürece
    ikisi de kendi payını kullanabilir (9+9=18, tam günlük limit)."""
    b = NamedBudget(db_conn, "ops_news_cap_test", daily_limit=18, runs_per_day=2)
    assert b.remaining == 9  # 18 // 2, sabah koşusu günün yarısını aşamaz

    b.consume(9)
    # Aynı gün İKİNCİ bir NamedBudget nesnesi (ör. akşam koşusu) - toplamda
    # henüz 18'e ulaşılmadığı (9 kullanıldı) için akşam koşusu KENDİ 9'luk
    # payını hâlâ alabilmeli - per-run cap "her koşu en fazla yarısı"
    # anlamına gelir, "ikinci koşu asla çalışamaz" DEĞİL.
    b2 = NamedBudget(db_conn, "ops_news_cap_test", daily_limit=18, runs_per_day=2)
    assert b2.remaining == 9

    b2.consume(9)
    # Artık günün TAMAMI (18/18) tüketildi - üçüncü bir çağrı (ör. aynı günde
    # tekrar tetiklenen bir koşu) sıfır bulmalı.
    b3 = NamedBudget(db_conn, "ops_news_cap_test", daily_limit=18, runs_per_day=2)
    assert b3.remaining == 0
