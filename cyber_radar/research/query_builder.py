"""Boolean query builder: bir ResearchProfile'ın `concept_groups` + `queries`
tanımını, her akademik kaynağın GERÇEKTEN desteklediği sorgu söz dizimine
çevirir.

Kaynak API'lerin boolean desteği birbirinden ÇOK farklı - bunu canlı test
ederek doğruladık (bkz. proje notları), varsayım YAPMADIK:

  - OpenAlex `search` parametresi:  nested AND/OR/parantez'i DOĞRUDAN
    destekliyor (`"a" OR "b") AND ("c" OR "d")`) - canlı doğrulandı
    (oql çıktısı bunu gerçek bir "and"/"or" ağacına çeviriyor).
  - arXiv `search_query` parametresi: alan öneki + AND/OR/parantez
    destekliyor (`(abs:"a" OR abs:"b") AND cat:cs.CR`) - canlı doğrulandı.
  - Crossref `query`: GERÇEK boolean YOK, düz kelime torbası + relevance
    sıralaması - canlı doğrulandı (tırnak/AND yok sayılıyor, sonuç sayısı
    değişmiyor). Bu yüzden Crossref için sadece terimleri birleştirip
    veriyoruz, precision'ı relevance filtresine (Level 1 LLM) bırakıyoruz.
  - Semantic Scholar: normal /paper/search düz metin; boolean SADECE
    /paper/search/bulk uç noktasında (`+`=AND, `|`=OR, `"..."`=phrase)
    dokümante edilmiş. Bu sandbox'tan rate-limit nedeniyle CANLI test
    edilemedi - üretimde ilk çalıştırmada doğrulanmalı (bkz. academic.py
    _retry_get zaten 429'da retry+backoff yapıyor, yanlış çıkarsa collector
    sessizce az/0 sonuç döner, pipeline'ı düşürmez).
"""
from __future__ import annotations

from dataclasses import dataclass

from .profiles import ResearchProfile


@dataclass
class BuiltQuery:
    label: str  # log/collector_runs için okunur ad, ör. "soc_visibility+telemetry"
    groups: list[str]
    openalex: str
    arxiv: str
    crossref: str
    semantic_scholar_bulk: str


def _terms(profile: ResearchProfile, group: str) -> list[str]:
    terms = profile.concept_terms(group)
    if not terms:
        # Grup adı concept_groups'ta yoksa, grubun kendisini tek terim say -
        # daily_cyber.yaml'da her "grup" zaten tek bir düz KEYWORDS terimi
        # (bkz. profiles.py docstring: KEYWORDS davranışını birebir korumak).
        return [group]
    return terms


def _or_expr(terms: list[str], quote: str = '"') -> str:
    parts = [f'{quote}{t}{quote}' for t in terms]
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"


def _or_expr_arxiv(terms: list[str], field: str = "abs") -> str:
    parts = [f'{field}:"{t}"' if " " in t else f"{field}:{t}" for t in terms]
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"


def _or_expr_s2(terms: list[str]) -> str:
    parts = [f'"{t}"' if " " in t else t for t in terms]
    if len(parts) == 1:
        return parts[0]
    return "(" + " | ".join(parts) + ")"


def build_openalex(profile: ResearchProfile, groups: list[str]) -> str:
    return " AND ".join(_or_expr(_terms(profile, g)) for g in groups)


def build_arxiv(profile: ResearchProfile, groups: list[str]) -> str:
    body = " AND ".join(_or_expr_arxiv(_terms(profile, g)) for g in groups)
    # Mevcut search_arxiv() ile aynı ilke: cs.CR (Cryptography and Security)
    # dışına taşmasın.
    return f"({body}) AND cat:cs.CR"


def build_crossref(profile: ResearchProfile, groups: list[str]) -> str:
    """Gerçek boolean yok - tüm grupların TÜM terimlerini tek kelime
    torbasında birleştirir (dedup edilmiş). Precision Level 1 relevance
    filtresine bırakılır."""
    seen: list[str] = []
    for g in groups:
        for t in _terms(profile, g):
            if t not in seen:
                seen.append(t)
    return " ".join(seen)


def build_semantic_scholar_bulk(profile: ResearchProfile, groups: list[str]) -> str:
    return " + ".join(_or_expr_s2(_terms(profile, g)) for g in groups)


def build_all(profile: ResearchProfile) -> list[BuiltQuery]:
    """profile.queries listesindeki her AND-grubu kombinasyonu için 4
    kaynağa uygun sorgu string'i üretir. daily_cyber.yaml gibi tek-terimli
    "gruplar"da bu, mevcut KEYWORDS davranışıyla birebir aynı sonucu verir
    (tek terim = quote'lanmış tek kelime arama, AND/OR devreye girmez)."""
    built: list[BuiltQuery] = []
    for groups in profile.queries:
        built.append(
            BuiltQuery(
                label="+".join(groups),
                groups=groups,
                openalex=build_openalex(profile, groups),
                arxiv=build_arxiv(profile, groups),
                crossref=build_crossref(profile, groups),
                semantic_scholar_bulk=build_semantic_scholar_bulk(profile, groups),
            )
        )
    return built
