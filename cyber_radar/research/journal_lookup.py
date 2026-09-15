"""Journal registry doğrulaması (SCIE/WoS/Scopus).

BİLİNÇLİ OLARAK KÜÇÜK ve PASİF: bu modül hiçbir dış API'ye gitmez, hiçbir
şeyi TAHMİN etmez. Tek yaptığı, bir makalenin ISSN/eISSN'ini
`journal_registry` tablosuna karşı sorgulamak - tablo BOŞ başlar, veri
`scripts/import_journal_registry.py` ile bir WoS Master Journal List /
Scopus Source List export'undan (CSV) elle içeri alınır.

"SCIE kontrolünü bibliyografik metadata'dan tahmin etmeyelim" ilkesi (bkz.
proje notları) burada somutlaşıyor: journal_registry'de eşleşme YOKSA
`journal_verified` false kalır, wos_index/journal_quartile NULL kalır -
"bilmiyoruz" ile "SCIE değil" birbirine KARIŞTIRILMAZ.
"""
from __future__ import annotations


def lookup(conn, issn: str | None, eissn: str | None) -> dict | None:
    """journal_registry'de issn VEYA eissn üzerinden eşleşme arar (kayıtlar
    genelde tek bir ISSN varyantıyla girilir, hangisinin print/electronic
    olduğu kaynağa göre değişebildiği için ikisini de deniyoruz)."""
    if not issn and not eissn:
        return None
    return conn.execute(
        """
        SELECT wos_index, scie, jcr_quartile, jcr_year, scopus_indexed, scopus_quartile, journal_name
        FROM journal_registry
        WHERE (issn IS NOT NULL AND (issn = %(issn)s OR issn = %(eissn)s))
           OR (eissn IS NOT NULL AND (eissn = %(issn)s OR eissn = %(eissn)s))
        LIMIT 1
        """,
        {"issn": issn, "eissn": eissn},
    ).fetchone()


def verify_and_apply(conn, paper_id: int, issn: str | None, eissn: str | None) -> None:
    """lookup() eşleşme bulursa papers.journal_verified/wos_index/
    journal_quartile'ı doldurur. Eşleşme yoksa HİÇBİR ŞEY YAPMAZ (var olan
    false/null durumu korunur) - registry sonradan genişletilirse
    (scripts/import_journal_registry.py) bir SONRAKİ koşuda bu satır
    otomatik doğrulanır, geriye dönük script gerekmez."""
    match = lookup(conn, issn, eissn)
    if not match:
        return
    quartile = match.get("jcr_quartile") or match.get("scopus_quartile")
    conn.execute(
        "UPDATE papers SET journal_verified = true, wos_index = %s, journal_quartile = %s WHERE id = %s",
        (match.get("wos_index"), quartile, paper_id),
    )
