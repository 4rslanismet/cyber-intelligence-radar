"""BUILDS_ON/FOUNDATION_FOR (bkz. src/research/citation_relationships.py,
Phase 2 madde 6) - paper<->paper ilişkiler SADECE OpenCitations'ın
verdiği GERÇEK referans DOI'leriyle, bizim KENDİ papers tablomuzdaki
eşleşmelerle kurulur. Gerçek ağ çağrısı YOK - opencitations.
get_reference_dois mock'lanır. Test DB kullanır."""
from __future__ import annotations

from unittest.mock import patch

from cyber_radar import digest as digest_mod
from cyber_radar.research import citation_relationships as cr
from cyber_radar.run_pipeline import _enrich_relationships


def _insert_paper(conn, doi: str | None, title: str) -> int:
    row = conn.execute(
        "INSERT INTO papers (title, normalized_title, doi, matched_profiles) "
        "VALUES (%s, %s, %s, '{}') RETURNING id",
        (title, title.lower(), doi),
    ).fetchone()
    return row["id"]


def test_compute_builds_on_creates_symmetric_edges_for_real_matches(db_conn):
    paper_a = _insert_paper(db_conn, "10.1/a", "Paper A (foundation)")
    paper_b = _insert_paper(db_conn, "10.1/b", "Paper B (builds on A)")

    with patch("cyber_radar.research.citation_relationships.opencitations.get_reference_dois", return_value=["10.1/a"]):
        n = cr.compute_builds_on(db_conn, paper_b, "10.1/b")

    assert n == 1
    builds_on = cr.get_relationships(db_conn, paper_b, cr.BUILDS_ON)
    assert len(builds_on) == 1
    assert builds_on[0]["id"] == paper_a

    foundation_for = cr.get_relationships(db_conn, paper_a, cr.FOUNDATION_FOR)
    assert len(foundation_for) == 1
    assert foundation_for[0]["id"] == paper_b


def test_compute_builds_on_ignores_references_not_in_our_corpus(db_conn):
    """OpenCitations gerçek bir referans DOI'si dönse bile, o DOI bizim
    KENDİ papers tablomuzda yoksa hiçbir kenar KURULMAZ - "LLM/dış veri
    serbestçe ilişki uydurmasın" ilkesinin mekanik karşılığı."""
    paper_b = _insert_paper(db_conn, "10.1/b", "Paper B")
    with patch("cyber_radar.research.citation_relationships.opencitations.get_reference_dois", return_value=["10.1/not-in-our-db"]):
        n = cr.compute_builds_on(db_conn, paper_b, "10.1/b")
    assert n == 0
    assert cr.get_relationships(db_conn, paper_b, cr.BUILDS_ON) == []


def test_compute_builds_on_is_idempotent(db_conn):
    paper_a = _insert_paper(db_conn, "10.1/a", "Paper A")
    paper_b = _insert_paper(db_conn, "10.1/b", "Paper B")
    with patch("cyber_radar.research.citation_relationships.opencitations.get_reference_dois", return_value=["10.1/a"]):
        n1 = cr.compute_builds_on(db_conn, paper_b, "10.1/b")
        n2 = cr.compute_builds_on(db_conn, paper_b, "10.1/b")
    assert n1 == 1
    assert n2 == 0  # ON CONFLICT DO NOTHING - ikinci kez YENİ kenar eklenmedi
    assert len(cr.get_relationships(db_conn, paper_b, cr.BUILDS_ON)) == 1


def test_compute_builds_on_returns_zero_without_crashing_on_network_error(db_conn):
    paper_b = _insert_paper(db_conn, "10.1/b", "Paper B")
    with patch("cyber_radar.research.citation_relationships.opencitations.get_reference_dois", side_effect=Exception("network down")):
        n = cr.compute_builds_on(db_conn, paper_b, "10.1/b")
    assert n == 0


def test_compute_builds_on_returns_zero_without_doi_and_makes_no_network_call(db_conn):
    paper_b = _insert_paper(db_conn, None, "Paper B (no DOI)")
    with patch("cyber_radar.research.citation_relationships.opencitations.get_reference_dois") as mock_fn:
        n = cr.compute_builds_on(db_conn, paper_b, None)
    assert n == 0
    mock_fn.assert_not_called()


def test_enrich_relationships_attaches_builds_on_and_marks_checked(db_conn):
    paper_a = _insert_paper(db_conn, "10.1/a", "Paper A")
    paper_b = _insert_paper(db_conn, "10.1/b", "Paper B")
    row_a = db_conn.execute("SELECT * FROM papers WHERE id = %s", (paper_a,)).fetchone()
    row_b = db_conn.execute("SELECT * FROM papers WHERE id = %s", (paper_b,)).fetchone()

    with patch("cyber_radar.research.citation_relationships.opencitations.get_reference_dois") as mock_fn:
        mock_fn.side_effect = lambda doi: ["10.1/a"] if doi == "10.1/b" else []
        _enrich_relationships(db_conn, [dict(row_a), dict(row_b)])

    checked = db_conn.execute("SELECT builds_on_checked_at FROM papers WHERE id = %s", (paper_b,)).fetchone()
    assert checked["builds_on_checked_at"] is not None


def test_enrich_relationships_skips_already_checked_papers(db_conn):
    """builds_on_checked_at zaten dolu bir makale için OpenCitations'a
    TEKRAR sorulmamalı (idempotent, dış API'ye gereksiz yük yok)."""
    paper_b = _insert_paper(db_conn, "10.1/b", "Paper B")
    db_conn.execute("UPDATE papers SET builds_on_checked_at = now() WHERE id = %s", (paper_b,))
    row_b = dict(db_conn.execute("SELECT * FROM papers WHERE id = %s", (paper_b,)).fetchone())

    with patch("cyber_radar.research.citation_relationships.opencitations.get_reference_dois") as mock_fn:
        _enrich_relationships(db_conn, [row_b])
    mock_fn.assert_not_called()


def test_paper_line_renders_verified_builds_on_and_foundation_for():
    p = {
        "title": "Paper B", "analysis": {"reading_priority": "MUST_READ"},
        "_builds_on": [{"id": 1, "title": "Paper A", "doi": "10.1/a"}],
        "_foundation_for": [{"id": 3, "title": "Paper C", "doi": "10.1/c"}],
    }
    lines = "\n".join(digest_mod._paper_line(p, detailed=True))
    assert "BUILDS_ON" in lines and "Paper A" in lines
    assert "FOUNDATION_FOR" in lines and "Paper C" in lines


def test_paper_line_omits_relationship_lines_when_none_verified():
    p = {"title": "Paper X", "analysis": {"reading_priority": "MUST_READ"}}
    lines = "\n".join(digest_mod._paper_line(p, detailed=True))
    assert "BUILDS_ON" not in lines
    assert "FOUNDATION_FOR" not in lines
