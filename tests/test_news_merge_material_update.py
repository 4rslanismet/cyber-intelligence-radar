"""_find_or_merge_news_event material_update_at davranışı (bkz.
src/run_pipeline.py, 2026-09-14 kök neden düzeltmesi). Test DB kullanır,
gerçek ağ çağrısı YOK."""
from __future__ import annotations

from cyber_radar.run_pipeline import _find_or_merge_news_event


def _item(title, cves, url, source="Test Feed"):
    return {
        "title": title,
        "cves": cves,
        "url": url,
        "source": source,
        "summary": "özet",
        "published_at": None,
        "raw_text": "ham metin",
    }


def test_merge_with_genuinely_new_cve_sets_material_update_at(db_conn):
    """Kullanıcı isteği: 'new CVE' gerçek bir material update sayılmalı."""
    title = "Aynı olay, yeni CVE ile"
    _find_or_merge_news_event(db_conn, _item(title, ["CVE-2026-1111"], "https://a.example/1"))
    row = db_conn.execute(
        "SELECT id, material_update_at FROM news_events WHERE title = %s", (title,)
    ).fetchone()
    assert row["material_update_at"] is None  # ilk kayıt - henüz güncelleme yok

    _find_or_merge_news_event(db_conn, _item(title, ["CVE-2026-2222"], "https://b.example/2"))
    updated = db_conn.execute(
        "SELECT material_update_at, cves FROM news_events WHERE id = %s", (row["id"],)
    ).fetchone()
    assert updated["material_update_at"] is not None
    assert set(updated["cves"]) == {"CVE-2026-1111", "CVE-2026-2222"}


def test_merge_without_new_cve_does_not_set_material_update_at(db_conn):
    """Kullanıcı isteği: 'sadece başka bir RSS kaynağı aynı olayı yazdı diye
    tekrar gösterme' - CVE seti büyümüyorsa material_update_at İLERLEMEMELİ,
    last_updated_at ilerlese bile."""
    title = "Aynı olay, tekrar aynı bilgiyle"
    _find_or_merge_news_event(db_conn, _item(title, ["CVE-2026-3333"], "https://a.example/1"))
    row = db_conn.execute("SELECT id FROM news_events WHERE title = %s", (title,)).fetchone()

    _find_or_merge_news_event(db_conn, _item(title, ["CVE-2026-3333"], "https://c.example/3"))
    updated = db_conn.execute(
        "SELECT material_update_at, last_updated_at FROM news_events WHERE id = %s", (row["id"],)
    ).fetchone()
    assert updated["material_update_at"] is None
    assert updated["last_updated_at"] is not None  # last_updated_at HER merge'de ilerler (mevcut davranış)


def test_merge_without_any_cve_at_all_does_not_set_material_update_at(db_conn):
    """Ne ilk kayıtta ne de mergede hiç CVE yoksa (ör. genel bir haber) -
    material_update_at asla set edilmemeli."""
    title = "CVE'siz genel haber"
    _find_or_merge_news_event(db_conn, _item(title, [], "https://a.example/1"))
    row = db_conn.execute("SELECT id FROM news_events WHERE title = %s", (title,)).fetchone()

    _find_or_merge_news_event(db_conn, _item(title, [], "https://d.example/4"))
    updated = db_conn.execute(
        "SELECT material_update_at FROM news_events WHERE id = %s", (row["id"],)
    ).fetchone()
    assert updated["material_update_at"] is None
