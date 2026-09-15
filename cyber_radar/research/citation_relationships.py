"""BUILDS_ON / FOUNDATION_FOR (Phase 2, madde 6) - paper-to-paper
ilişkiler SADECE gerçek reference/citation metadata'sıyla kurulur, LLM
serbest biçimde citation graph UYDURAMAZ (proje notları: "İlişkileri
yalnızca gerçekten akademik/metodolojik ilişki varsa kur... LLM'in serbest
biçimde citation graph uydurmasına izin verme").

Mekanizma: src/collectors/opencitations.py (zaten snowballing'de kullanılan,
CANLI doğrulanmış bir kaynak) bir makalenin GERÇEK referans DOI listesini
verir. Bu liste bizim KENDİ `papers` tablomuzdaki DOI'lerle eşleştirilir -
eşleşen her DOI, "bu makale O makaleye BUILDS_ON" anlamına gelen, dış bir
API'den DOĞRULANMIŞ bir kenar olur. Hiçbir LLM çağrısı YOK, hiçbir tahmin
YOK - ya gerçek bir referans metadata eşleşmesi var, ya hiç edge kurulmaz.

Mevcut "foundation_for" (papers.analysis->foundation_for, LLM-üretilmiş
KONU/alt-alan string listesi) İLE KARIŞTIRILMAMALI - o, "bu çalışma hangi
GÜNCEL alt-konulara temel oluşturuyor" sorusuna LLM'in verdiği serbest
yorum, BU MODÜL ise gerçek paper<->paper kenarları kurar. İkisi FARKLI
kavramlar, ikisi de korunuyor (biri bozulmadı, diğeri eklendi)."""
from __future__ import annotations

from typing import Any

from ..collectors import opencitations

BUILDS_ON = "builds_on"
FOUNDATION_FOR = "foundation_for"


def compute_builds_on(conn, paper_id: int, doi: str | None) -> int:
    """`paper_id`'nin GERÇEKTEN referans verdiği, bizim KENDİ papers
    tablomuzda da bulunan makaleleri bulur, doğrulanmış (paper_id ->
    related_paper_id, 'builds_on') ve tersi (related_paper_id -> paper_id,
    'foundation_for') iki kenar ekler. Idempotent - ON CONFLICT DO NOTHING
    (aynı çift ikinci kez eklenmez). Döner: eklenen YENİ kenar sayısı
    (builds_on tarafı, foundation_for otomatik simetriktir)."""
    if not doi:
        return 0
    try:
        reference_dois = opencitations.get_reference_dois(doi)
    except Exception:  # noqa: BLE001 - ağ hatası bu makaleyi ATLASIN, koşuyu düşürmesin
        return 0
    if not reference_dois:
        return 0

    matches = conn.execute(
        "SELECT id, doi FROM papers WHERE doi = ANY(%s) AND id != %s",
        (reference_dois, paper_id),
    ).fetchall()
    n = 0
    for m in matches:
        r1 = conn.execute(
            """
            INSERT INTO paper_relationships (paper_id, related_paper_id, relationship_type, verified_via)
            VALUES (%s, %s, %s, 'opencitations_reference_doi')
            ON CONFLICT (paper_id, related_paper_id, relationship_type) DO NOTHING
            RETURNING id
            """,
            (paper_id, m["id"], BUILDS_ON),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO paper_relationships (paper_id, related_paper_id, relationship_type, verified_via)
            VALUES (%s, %s, %s, 'opencitations_reference_doi')
            ON CONFLICT (paper_id, related_paper_id, relationship_type) DO NOTHING
            """,
            (m["id"], paper_id, FOUNDATION_FOR),
        )
        if r1:
            n += 1
    return n


def get_relationships(conn, paper_id: int, relationship_type: str) -> list[dict[str, Any]]:
    """Bu makalenin (paper_id) verilen türdeki (builds_on/foundation_for)
    DOĞRULANMIŞ ilişkili makalelerini döner - [{"id", "title", "doi"}]."""
    rows = conn.execute(
        """
        SELECT p.id, p.title, p.doi
        FROM paper_relationships pr
        JOIN papers p ON p.id = pr.related_paper_id
        WHERE pr.paper_id = %s AND pr.relationship_type = %s
        ORDER BY pr.created_at ASC
        """,
        (paper_id, relationship_type),
    ).fetchall()
    return [dict(r) for r in rows]
