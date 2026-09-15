"""src/research/query_builder.py - concept groups'tan her kaynağın GERÇEKTEN
desteklediği sorgu söz dizimine çeviri. Bu dosyada test edilen davranış
(OpenAlex/arXiv nested boolean desteği, Crossref bag-of-words) daha önce
CANLI API'lere karşı doğrulanmıştı (bkz. proje notları) - burada YALNIZCA
string üretim mantığı test ediliyor, ağ çağrısı yok."""
from __future__ import annotations

from cyber_radar.research.profiles import ResearchProfile
from cyber_radar.research.query_builder import build_all, build_arxiv, build_crossref, build_openalex


def _profile(**overrides) -> ResearchProfile:
    base = dict(
        id="test_profile",
        title="Test",
        mode="sci",
        concept_groups={
            "a": ["security visibility", "security observability"],
            "b": ["SOC", "security operations center"],
        },
        queries=[["a", "b"]],
    )
    base.update(overrides)
    return ResearchProfile(**base)


def test_boolean_query_builder_openalex_nested_and_or():
    p = _profile()
    q = build_openalex(p, ["a", "b"])
    assert q == '("security visibility" OR "security observability") AND ("SOC" OR "security operations center")'


def test_boolean_query_builder_arxiv_field_prefixed():
    p = _profile()
    q = build_arxiv(p, ["a", "b"])
    assert 'abs:"security visibility"' in q
    assert " OR " in q
    assert q.endswith("AND cat:cs.CR")


def test_boolean_query_builder_crossref_bag_of_words_no_operators():
    """Crossref GERÇEK boolean desteklemiyor (canlı doğrulandı) - bu yüzden
    AND/OR/parantez İÇERMEMELİ, düz kelime torbası olmalı."""
    p = _profile()
    q = build_crossref(p, ["a", "b"])
    assert "AND" not in q
    assert "OR" not in q
    assert "(" not in q
    for term in ("security visibility", "security observability", "SOC", "security operations center"):
        assert term in q


def test_single_term_group_is_not_wrapped_in_parens():
    """Tek terimli bir grup (ör. daily_cyber.yaml'daki keyword'ler) OR
    parantezine SARILMAMALI - eski KEYWORDS davranışıyla birebir aynı kalsın."""
    p = _profile(concept_groups={"cybersecurity": ["cybersecurity"]}, queries=[["cybersecurity"]])
    q = build_openalex(p, ["cybersecurity"])
    assert q == '"cybersecurity"'


def test_query_builder_handles_unknown_group_name_gracefully():
    """concept_groups'ta OLMAYAN bir grup adı (bozuk/eksik profile) pipeline'ı
    ÇÖKERTMEMELİ - grup adının kendisi tek terim sayılır (bkz.
    query_builder._terms fallback)."""
    p = _profile(concept_groups={}, queries=[["some_undefined_group"]])
    q = build_openalex(p, ["some_undefined_group"])
    assert q == '"some_undefined_group"'


def test_build_all_produces_one_entry_per_query():
    p = _profile(queries=[["a", "b"], ["a"]])
    built = build_all(p)
    assert len(built) == 2
    assert built[0].label == "a+b"
    assert built[1].label == "a"
    # Her BuiltQuery 4 kaynak için de bir string üretmeli.
    for b in built:
        assert b.openalex and b.crossref and b.arxiv and b.semantic_scholar_bulk


def test_build_all_empty_queries_returns_empty_list():
    """queries=[] olan (bozuk) bir profile boş liste döner, hata FIRLATMAZ."""
    p = _profile(queries=[])
    assert build_all(p) == []
