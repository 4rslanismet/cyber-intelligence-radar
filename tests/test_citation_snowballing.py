"""Citation snowballing (bkz. src/collectors/citation_graph.py,
src/collectors/opencitations.py, src/run_pipeline._snowball_profile).
Kritik davranış: Semantic Scholar VE OpenCitations aynı makaleyi (aynı DOI)
BAĞIMSIZ olarak bulursa, tek bir canonical papers satırı oluşmalı - iki ayrı
kayıt YOK."""
from __future__ import annotations

from cyber_radar.run_pipeline import _snowball_profile
from cyber_radar.research.profiles import ResearchProfile


def _snowball_profile_obj() -> ResearchProfile:
    return ResearchProfile(
        id="test_snowball",
        title="Test",
        mode="sci",
        snowball=True,
        snowball_seed_limit=5,
    )


def test_no_snowball_when_profile_disabled(db_conn):
    p = ResearchProfile(id="no_snowball", title="Test", mode="sci", snowball=False)
    assert _snowball_profile(db_conn, p) == 0


def test_no_snowball_when_no_relevant_seeds(db_conn):
    """Bu profille eşleşmiş 'relevant' bir makale yoksa snowball hiç
    denenmemeli (0 seed -> 0 yeni kayıt, hiç dış çağrı yapılmaz - autouse
    block_real_network zaten bunu garanti eder)."""
    assert _snowball_profile(db_conn, _snowball_profile_obj()) == 0


def test_opencitations_dedup(db_conn, monkeypatch):
    """Semantic Scholar snowball'u DOI=X'i bulsun, OpenCitations da AYNI
    DOI=X'i (references/citations üzerinden) bulsun - sonuçta papers
    tablosunda bu DOI için TEK satır olmalı."""
    seed_doi = "10.1000/seed.paper"
    db_conn.execute(
        """
        INSERT INTO papers (doi, title, normalized_title, relevance, relevance_status, matched_profiles)
        VALUES (%s, %s, %s, %s::jsonb, 'relevant', %s)
        """,
        (seed_doi, "Seed Paper", "seed paper", '{"confidence": 0.9}', ["test_snowball"]),
    )

    duplicate_doi = "10.1000/found.by.both"
    shared_candidate = {
        "title": "Found By Both S2 And OpenCitations",
        "authors": [],
        "doi": duplicate_doi,
        "arxiv_id": None,
        "openalex_id": None,
        "venue": None,
        "publication_date": None,
        "abstract": None,
        "pdf_url": None,
        "source_api": "semantic_scholar_snowball_ref",
    }
    opencitations_version = dict(shared_candidate, source_api="opencitations_snowball")

    monkeypatch.setattr(
        "cyber_radar.collectors.citation_graph.snowball_from_seeds", lambda seeds, limit: [dict(shared_candidate)]
    )
    monkeypatch.setattr("cyber_radar.collectors.opencitations.get_reference_dois", lambda doi: [duplicate_doi])
    monkeypatch.setattr("cyber_radar.collectors.opencitations.get_citation_dois", lambda doi: [])
    monkeypatch.setattr(
        "cyber_radar.collectors.opencitations.resolve_dois", lambda dois: [dict(opencitations_version) for _ in dois]
    )

    added = _snowball_profile(db_conn, _snowball_profile_obj())
    assert added == 2  # her iki kaynak da "1 sonuç" raporladı (ham sayım)

    rows = db_conn.execute("SELECT source_apis FROM papers WHERE doi = %s", (duplicate_doi,)).fetchall()
    assert len(rows) == 1  # ama TEK canonical satır
    assert set(rows[0]["source_apis"]) == {"semantic_scholar_snowball_ref", "opencitations_snowball"}


def test_snowball_seed_query_orders_by_confidence(db_conn):
    """En yüksek confidence'lı seed'ler önce gelmeli (bkz.
    _snowball_profile'daki ORDER BY (relevance->>'confidence')::numeric DESC)."""
    for i, conf in enumerate([0.5, 0.95, 0.7]):
        db_conn.execute(
            """
            INSERT INTO papers (doi, title, normalized_title, relevance, relevance_status, matched_profiles)
            VALUES (%s, %s, %s, %s::jsonb, 'relevant', %s)
            """,
            (f"10.1000/seed.{i}", f"Seed {i}", f"seed {i}", f'{{"confidence": {conf}}}', ["test_snowball"]),
        )
    seeds = db_conn.execute(
        """
        SELECT doi, (relevance->>'confidence')::numeric AS conf FROM papers
        WHERE relevance_status = 'relevant' AND %s = ANY(matched_profiles)
        ORDER BY (relevance->>'confidence')::numeric DESC NULLS LAST
        """,
        ("test_snowball",),
    ).fetchall()
    assert [float(s["conf"]) for s in seeds] == [0.95, 0.7, 0.5]
