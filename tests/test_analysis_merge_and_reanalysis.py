"""merge_news_analysis (kayıpsız merge) + _analyze_relevant_news koşullu
re-analiz + _find_or_merge_news_event'in re-analiz TETİKLEME kararı (bkz.
2026-09-15 ikinci tur - "material update lifecycle'ı tamamla, madde 4/5/6").
Test DB kullanır, gerçek Gemini/ağ çağrısı YOK - news_analyst.analyze_news
monkeypatch'lenir."""
from __future__ import annotations

from unittest.mock import patch

from cyber_radar.dedup import merge_news_analysis
from cyber_radar.llm.budget import NamedBudget
from cyber_radar.run_pipeline import _analyze_relevant_news, _find_or_merge_news_event


# ---------------------------------------------------------------------------
# merge_news_analysis: kayıpsız birleştirme (madde 4)
# ---------------------------------------------------------------------------
def test_analysis_artifacts_merge_without_loss():
    old = {
        "process_names": ["powershell.exe"],
        "ioc": {"ips": ["1.2.3.4"], "domains": [], "hashes": [], "urls": [], "emails": []},
        "hunt_query": "powershell.exe -> whoami",
        "active_exploitation": True,
        "exploit_status": "active_exploitation",
    }
    new = {
        "process_names": ["rundll32.exe"],  # eski powershell.exe'yi İÇERMİYOR
        "ioc": {"ips": [], "domains": ["evil.com"], "hashes": [], "urls": [], "emails": []},
        "hunt_query": None,  # yeni analiz boş döndü
        "active_exploitation": False,  # yeni analiz "false" dedi
        "exploit_status": None,
    }
    merged = merge_news_analysis(old, new)
    assert set(merged["process_names"]) == {"powershell.exe", "rundll32.exe"}
    assert set(merged["ioc"]["ips"]) == {"1.2.3.4"}
    assert set(merged["ioc"]["domains"]) == {"evil.com"}
    assert merged["hunt_query"] == "powershell.exe -> whoami"  # eski korunur, yeni boş
    assert merged["active_exploitation"] is True  # sadece yükselebilir, geri düşmez
    assert merged["exploit_status"] == "active_exploitation"


def test_analysis_merge_prefers_new_scalar_when_present():
    old = {"summary": "eski özet", "hunt_query": "eski hunt"}
    new = {"summary": "yeni, daha detaylı özet", "hunt_query": "yeni hunt"}
    merged = merge_news_analysis(old, new)
    assert merged["summary"] == "yeni, daha detaylı özet"
    assert merged["hunt_query"] == "yeni hunt"


def test_analysis_merge_with_no_old_analysis_is_pure_new():
    """Brand-new bir haberde old_analysis={} - union-with-empty = sadece
    yeni, eski davranışla BİREBİR aynı sonuç."""
    new = {"process_names": ["cmd.exe"], "ioc": {"ips": ["9.9.9.9"]}, "summary": "test"}
    merged = merge_news_analysis(None, new)
    assert merged["process_names"] == ["cmd.exe"]
    assert merged["ioc"]["ips"] == ["9.9.9.9"]
    assert merged["summary"] == "test"


# ---------------------------------------------------------------------------
# Conditional re-analysis: merge zamanında tetikleme kararı (madde 5)
# ---------------------------------------------------------------------------
def _fresh_item(title, cves, url, raw_text, source="Feed"):
    return {
        "title": title, "cves": cves, "url": url, "source": source,
        "summary": "özet", "published_at": None, "raw_text": raw_text,
    }


def _mark_analyzed(conn, row_id):
    conn.execute(
        "UPDATE news_events SET analysis = '{}'::jsonb, analyzed_at = now(), relevance_status = 'relevant' "
        "WHERE id = %s",
        (row_id,),
    )


def test_source_repeat_does_not_trigger_reanalysis(db_conn):
    title = "Aynı olay, tekrar fetch"
    _find_or_merge_news_event(db_conn, _fresh_item(title, ["CVE-2026-4444"], "https://a.example/1", "ham metin, IOC yok"))
    row = db_conn.execute("SELECT id FROM news_events WHERE title = %s", (title,)).fetchone()
    _mark_analyzed(db_conn, row["id"])

    _find_or_merge_news_event(db_conn, _fresh_item(title, ["CVE-2026-4444"], "https://a.example/1", "ham metin, IOC yok"))
    updated = db_conn.execute(
        "SELECT analyzed_at, pending_reanalysis_reason FROM news_events WHERE id = %s", (row["id"],)
    ).fetchone()
    assert updated["analyzed_at"] is not None  # re-analiz TETİKLENMEDİ
    assert updated["pending_reanalysis_reason"] is None


def test_title_change_does_not_trigger_reanalysis(db_conn):
    """is_same_event zaten yüksek başlık benzerliğiyle eşleştiriyor - küçük
    bir wording farkı ne CVE ne de regex-IOC setini değiştirir."""
    title = "Vendor X kritik güvenlik açığı duyurusu"
    _find_or_merge_news_event(db_conn, _fresh_item(title, ["CVE-2026-5555"], "https://a.example/2", "ham metin, IOC yok"))
    row = db_conn.execute("SELECT id FROM news_events WHERE title = %s", (title,)).fetchone()
    _mark_analyzed(db_conn, row["id"])

    _find_or_merge_news_event(db_conn, _fresh_item(
        "Vendor X kritik güvenlik açığı duyurusu!", ["CVE-2026-5555"], "https://a.example/2", "ham metin, IOC yok",
    ))
    updated = db_conn.execute(
        "SELECT analyzed_at, pending_reanalysis_reason FROM news_events WHERE id = %s", (row["id"],)
    ).fetchone()
    assert updated["analyzed_at"] is not None
    assert updated["pending_reanalysis_reason"] is None


def test_new_authoritative_evidence_can_trigger_reanalysis(db_conn):
    """Yeni bir CVE gelmesi zaten analiz edilmiş bir olayı koşullu re-analiz
    adayı yapmalı - ham metin de büyümeli ki LLM yeni içeriği GÖREBİLSİN."""
    title = "Vendor Y aktif istismar bülteni"
    _find_or_merge_news_event(db_conn, _fresh_item(title, ["CVE-2026-6666"], "https://a.example/3", "ilk ham metin"))
    row = db_conn.execute("SELECT id FROM news_events WHERE title = %s", (title,)).fetchone()
    _mark_analyzed(db_conn, row["id"])

    _find_or_merge_news_event(db_conn, _fresh_item(title, ["CVE-2026-7777"], "https://b.example/4", "ikinci ham metin"))
    updated = db_conn.execute(
        "SELECT analyzed_at, pending_reanalysis_reason, raw_text FROM news_events WHERE id = %s", (row["id"],)
    ).fetchone()
    assert updated["analyzed_at"] is None  # re-analiz ADAYI yapıldı
    assert updated["pending_reanalysis_reason"] == "new_cve"
    assert "ikinci ham metin" in updated["raw_text"]


def test_new_ip_ioc_evidence_triggers_reanalysis(db_conn):
    title = "Botnet altyapısı raporu"
    _find_or_merge_news_event(db_conn, _fresh_item(title, [], "https://a.example/5", "genel bir açıklama, IOC yok"))
    row = db_conn.execute("SELECT id FROM news_events WHERE title = %s", (title,)).fetchone()
    _mark_analyzed(db_conn, row["id"])

    _find_or_merge_news_event(db_conn, _fresh_item(
        title, [], "https://b.example/6", "C2 sunucusu 203.0.113.55 olarak tespit edildi",
    ))
    updated = db_conn.execute(
        "SELECT analyzed_at, pending_reanalysis_reason FROM news_events WHERE id = %s", (row["id"],)
    ).fetchone()
    assert updated["analyzed_at"] is None
    assert updated["pending_reanalysis_reason"] == "new_ioc_evidence"


def test_pending_news_never_analyzed_is_unaffected_by_reanalysis_logic(db_conn):
    """Hiç analiz edilmemiş (analyzed_at IS NULL baştan) bir olaya yeni bir
    kaynak merge olduğunda pending_reanalysis_reason set EDİLMEMELİ - bu
    zaten normal ilk-analiz akışına gidecek, 'yeniden' analiz değil."""
    title = "Hiç analiz edilmemiş haber"
    _find_or_merge_news_event(db_conn, _fresh_item(title, ["CVE-2026-8181"], "https://a.example/7", "ilk metin"))
    _find_or_merge_news_event(db_conn, _fresh_item(title, ["CVE-2026-9191"], "https://b.example/8", "ikinci metin"))
    row = db_conn.execute(
        "SELECT analyzed_at, pending_reanalysis_reason FROM news_events WHERE title = %s", (title,)
    ).fetchone()
    assert row["analyzed_at"] is None
    assert row["pending_reanalysis_reason"] is None


# ---------------------------------------------------------------------------
# _analyze_relevant_news: bütçe disiplini + çökmeme (madde 6)
# ---------------------------------------------------------------------------
def _insert_pending_news(conn, title, raw_text="ham metin", cves=None):
    row = conn.execute(
        "INSERT INTO news_events (title, dedup_key, raw_text, cves, relevance_status) "
        "VALUES (%(title)s, %(dedup_key)s, %(raw_text)s, %(cves)s, 'relevant') RETURNING id",
        {"title": title, "dedup_key": title.lower(), "raw_text": raw_text, "cves": cves or []},
    ).fetchone()
    return row["id"]


def test_reanalysis_respects_llm_budget(db_conn):
    _insert_pending_news(db_conn, "Haber 1")
    _insert_pending_news(db_conn, "Haber 2")
    budget = NamedBudget(db_conn, "test_pool_respects_budget", daily_limit=1)

    with patch("cyber_radar.run_pipeline.news_analyst.analyze_news", return_value={"summary": "test", "news_tier": "AWARENESS"}):
        analyzed = _analyze_relevant_news(db_conn, kev_set=set(), budget=budget)

    assert len(analyzed) == 1  # SADECE bütçe kadarı işlendi
    remaining_pending = db_conn.execute(
        "SELECT count(*) AS c FROM news_events WHERE relevance_status = 'relevant' AND analyzed_at IS NULL"
    ).fetchone()
    assert remaining_pending["c"] == 1  # diğeri PENDING kaldı, kaybolmadı


def test_reanalysis_budget_exhaustion_does_not_crash_pipeline(db_conn):
    _insert_pending_news(db_conn, "Haber A")
    _insert_pending_news(db_conn, "Haber B")
    _insert_pending_news(db_conn, "Haber C")
    budget = NamedBudget(db_conn, "test_pool_exhaustion", daily_limit=0)  # baştan boş

    with patch("cyber_radar.run_pipeline.news_analyst.analyze_news", return_value={"summary": "test", "news_tier": "AWARENESS"}):
        analyzed = _analyze_relevant_news(db_conn, kev_set=set(), budget=budget)  # ÇÖKMEMELİ

    assert analyzed == []


def test_no_material_update_when_reanalysis_has_no_meaningful_change(db_conn):
    """Re-analiz tamamlanır ama sonuç ÖNCEKİYLE (severity/relevance/IOC vb.)
    aynıysa material_update_at İLERLEMEMELİ."""
    news_id = _insert_pending_news(db_conn, "Sabit haber", cves=["CVE-2026-1010"])
    fixed_analysis = {"summary": "test", "news_tier": "AWARENESS", "my_relevance": "LOW"}

    with patch("cyber_radar.run_pipeline.news_analyst.analyze_news", return_value=dict(fixed_analysis)):
        _analyze_relevant_news(db_conn, kev_set=set(), budget=NamedBudget(db_conn, "test_pool_no_material_1", daily_limit=10))

    # İlk (brand-new) analiz doğal olarak material sayılabilir - bunu
    # sıfırlayıp "değişmeyen bir re-analiz" senaryosunu izole ediyoruz.
    db_conn.execute("UPDATE news_events SET analyzed_at = NULL, material_update_at = NULL WHERE id = %s", (news_id,))

    with patch("cyber_radar.run_pipeline.news_analyst.analyze_news", return_value=dict(fixed_analysis)):
        _analyze_relevant_news(db_conn, kev_set=set(), budget=NamedBudget(db_conn, "test_pool_no_material_2", daily_limit=10))

    second = db_conn.execute("SELECT material_update_at FROM news_events WHERE id = %s", (news_id,)).fetchone()
    assert second["material_update_at"] is None


def test_reanalysis_llm_error_does_not_crash_and_leaves_row_pending(db_conn):
    """analyze_news exception fırlatırsa (429/timeout/vb.) satır pending
    kalmalı, pipeline çökmemeli - mevcut try/except deseniyle AYNI."""
    _insert_pending_news(db_conn, "Hatalı analiz haberi")
    budget = NamedBudget(db_conn, "test_pool_llm_error", daily_limit=10)

    with patch("cyber_radar.run_pipeline.news_analyst.analyze_news", side_effect=RuntimeError("429 rate limit")):
        analyzed = _analyze_relevant_news(db_conn, kev_set=set(), budget=budget)  # ÇÖKMEMELİ

    assert analyzed == []
    row = db_conn.execute(
        "SELECT analyzed_at FROM news_events WHERE title = %s", ("Hatalı analiz haberi",)
    ).fetchone()
    assert row["analyzed_at"] is None
