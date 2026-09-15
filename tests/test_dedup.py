"""_upsert_paper (bkz. src/run_pipeline.py) dedup mantığı: aynı makale farklı
kaynaklardan gelse bile TEK canonical satır olmalı. Test DB kullanır (bkz.
conftest.py db_conn fixture) - production'a dokunmaz."""
from __future__ import annotations

from cyber_radar.run_pipeline import _upsert_paper


def _count_papers(conn) -> int:
    return conn.execute("SELECT count(*) AS c FROM papers").fetchone()["c"]


def test_paper_dedup_by_doi(db_conn, sample_paper_item):
    item_a = dict(sample_paper_item, source_api="openalex")
    item_b = dict(sample_paper_item, source_api="crossref", title="A Study Of Security Visibility (slightly different)")

    _upsert_paper(db_conn, item_a)
    _upsert_paper(db_conn, item_b)

    assert _count_papers(db_conn) == 1
    row = db_conn.execute("SELECT source_apis FROM papers WHERE doi = %s", (sample_paper_item["doi"],)).fetchone()
    assert set(row["source_apis"]) == {"openalex", "crossref"}


def test_paper_dedup_by_arxiv_id(db_conn, sample_paper_item):
    item_a = dict(sample_paper_item, doi=None, arxiv_id="2401.00001", source_api="arxiv")
    item_b = dict(sample_paper_item, doi=None, arxiv_id="2401.00001", source_api="openreview")

    _upsert_paper(db_conn, item_a)
    _upsert_paper(db_conn, item_b)

    assert _count_papers(db_conn) == 1
    row = db_conn.execute("SELECT source_apis FROM papers WHERE arxiv_id = %s", ("2401.00001",)).fetchone()
    assert set(row["source_apis"]) == {"arxiv", "openreview"}


def test_paper_dedup_by_normalized_title(db_conn, sample_paper_item):
    """Ne DOI ne arXiv ID paylaşılmıyor ama başlık normalize edildiğinde
    aynı - ör. OpenAIRE (DOI'siz) ile OpenAlex (DOI'li) aynı makaleyi
    farklı kaynaklardan bulduğunda gerçekleşen senaryo."""
    item_a = dict(sample_paper_item, doi="10.1000/x.001", source_api="openalex")
    item_b = dict(
        sample_paper_item,
        doi=None,
        arxiv_id=None,
        openalex_id=None,
        title="A Study of Security Visibility in SOC Environments",  # birebir aynı normalize başlık
        source_api="openaire",
    )

    _upsert_paper(db_conn, item_a)
    _upsert_paper(db_conn, item_b)

    assert _count_papers(db_conn) == 1


def test_different_papers_are_not_merged(db_conn, sample_paper_item):
    item_a = dict(sample_paper_item, doi="10.1000/a", title="Paper A About Detection Coverage")
    item_b = dict(sample_paper_item, doi="10.1000/b", title="Paper B About Threat Intelligence")

    _upsert_paper(db_conn, item_a)
    _upsert_paper(db_conn, item_b)

    assert _count_papers(db_conn) == 2


def test_matched_profiles_accumulate_across_upserts(db_conn, sample_paper_item):
    _upsert_paper(db_conn, dict(sample_paper_item, source_api="openalex"), matched_profile="soc_analyst")
    _upsert_paper(db_conn, dict(sample_paper_item, source_api="crossref"), matched_profile="security_researcher")

    row = db_conn.execute(
        "SELECT matched_profiles FROM papers WHERE doi = %s", (sample_paper_item["doi"],)
    ).fetchone()
    assert set(row["matched_profiles"]) == {"soc_analyst", "security_researcher"}
