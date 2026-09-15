"""Research profile yükleyici.

Bir "research profile", radar'ın NE aradığını tanımlayan deklaratif bir YAML
dosyasıdır (bkz. profiles/*.yaml). Üç bilinçli amaç:

1. `config.KEYWORDS`'ün yerini alır ama onu ÇÖPE ATMAZ: `daily_cyber.yaml`
   mevcut KEYWORDS davranışını (her kelime kendi başına, ayrı sorgu) birebir
   yeniden üretir - profile sistemine geçiş davranış değişikliği YARATMAZ.
2. Research Profile A/B modları (bkz. profiles/examples/*.yaml) `concept_groups` +
   `queries` üzerinden gerçek boolean sorgular tanımlar (bkz. query_builder.py).
3. `snowball` bayrağı hangi profillerin citation snowballing (bkz.
   src/collectors/citation_graph.py) kullanacağını belirler - günlük radar
   KULLANMAZ (amaç güncellik/genişlik, atıf derinliği değil).

Bilinçli olarak KÜÇÜK tutuldu: extraction schema / evidence matrix / gap
analysis / claim checker gibi sonraki adımlar (bkz. proje notları) bu
modüle DOKUNMADAN üstüne eklenebilir - profile sadece "ne aransın" sorusunu
cevaplıyor, "ne çıkarılsın" sorusuna değil.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from .. import config


@dataclass
class ScreeningCriterion:
    """Bir inclusion/exclusion kriteri - makine tarafından işlenebilir bir
    `id` (ör. 'INC_SOC') + insanın okuyacağı `description`. Reason code'lar
    (bkz. src/research/screening.py) BUNLARIN id'leridir - serbest LLM
    metni DEĞİL."""

    id: str
    description: str


@dataclass
class ScreeningConfig:
    """Bir research profile'ın systematic screening (bkz.
    src/research/screening.py) kriterleri - discovery relevance'tan
    (src/llm/relevance.py) TAMAMEN AYRI bir kavram: "bu kayıt BU profilin
    literatür korpusuna dahil edilmeli mi?" sorusunu cevaplar."""

    date_from: int | None = None
    date_to: int | None = None
    allowed_document_types: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=lambda: ["en"])
    inclusion_criteria: list[ScreeningCriterion] = field(default_factory=list)
    exclusion_criteria: list[ScreeningCriterion] = field(default_factory=list)

    def criterion_ids(self) -> set[str]:
        return {c.id for c in self.inclusion_criteria} | {c.id for c in self.exclusion_criteria}


@dataclass
class GapAnalysisConfig:
    """Paket 5B - src/research/gap_analysis.py bu eşikleri kullanır.
    minimum_evidence_coverage altında kalan bir özellik için research gap
    İLAN EDİLMEZ - evidence_uncertainty üretilir (bkz. proje notları:
    "düşük kanıt kapsamı bir literatür boşluğu üretmemeli")."""

    minimum_evidence_coverage: float = 0.60
    rare_feature_threshold: float = 0.20


@dataclass
class ResearchProfile:
    id: str
    title: str
    # "daily" = mevcut KEYWORDS davranışı (rolling since_date penceresi,
    # snowballing yok). "sci" / "thesis" = boolean query_builder + (opsiyonel)
    # citation snowballing.
    mode: str
    concept_groups: dict[str, list[str]] = field(default_factory=dict)
    # Her eleman bir "AND grubu": ["soc_visibility", "telemetry"] ->
    # (soc_visibility'nin terimleri OR) AND (telemetry'nin terimleri OR).
    # bkz. query_builder.build_boolean_query().
    queries: list[list[str]] = field(default_factory=list)
    research_questions: list[str] = field(default_factory=list)
    date_from: int | None = None
    date_to: int | None = None
    languages: list[str] = field(default_factory=lambda: ["en"])
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    snowball: bool = False
    # Bir koşuda bu profil için snowball edilecek seed makale sayısı üst
    # sınırı (yalnızca relevance='relevant' çıkanlardan) - 2-hop YAPILMIYOR
    # (bkz. proje notları: "birkaç seed paper'dan binlerce makale üretir"),
    # 1-hop'ta bile seed sayısını sınırlamazsak references+citations+
    # recommendations üç ayrı istek × seed sayısı kadar büyür.
    snowball_seed_limit: int = 10
    per_query_max_results: int = 25
    # Profile-özel LLM extraction şeması: GERÇEK bir JSON Schema (bkz.
    # src/research/extraction_schema.py) - TEK KAYNAK, iki tüketici:
    # extraction_schema.to_prompt_text() Gemini prompt'una çevirir,
    # extraction_schema.validate() yanıtı runtime'da doğrular. Model
    # çıktısında AYRI bir "profile_extraction" anahtarı altında toplanır,
    # base şemayla (paper_analyst._SYSTEM) KARIŞMAZ.
    extraction_schema: dict[str, Any] | None = None
    # Systematic screening kriterleri (bkz. src/research/screening.py) -
    # None ise (ör. daily_cyber) screening engine bu profil için hiç
    # çalışmaz, günlük radar davranışı ETKİLENMEZ.
    screening: ScreeningConfig | None = None
    # Paket 5B eşikleri (bkz. src/research/gap_analysis.py) - None ise
    # varsayılan GapAnalysisConfig() (0.60/0.20) kullanılır.
    gap_analysis: GapAnalysisConfig | None = None

    def concept_terms(self, group_name: str) -> list[str]:
        return self.concept_groups.get(group_name, [])


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_screening_config(raw: dict[str, Any]) -> ScreeningConfig | None:
    s = raw.get("screening")
    if not s:
        return None
    dr = s.get("date_range") or {}
    return ScreeningConfig(
        date_from=dr.get("from"),
        date_to=dr.get("to"),
        allowed_document_types=s.get("allowed_document_types") or [],
        languages=s.get("languages") or ["en"],
        inclusion_criteria=[
            ScreeningCriterion(id=c["id"], description=c["description"]) for c in s.get("inclusion_criteria") or []
        ],
        exclusion_criteria=[
            ScreeningCriterion(id=c["id"], description=c["description"]) for c in s.get("exclusion_criteria") or []
        ],
    )


def _load_gap_analysis_config(raw: dict[str, Any]) -> GapAnalysisConfig | None:
    g = raw.get("gap_analysis")
    if not g:
        return None
    return GapAnalysisConfig(
        minimum_evidence_coverage=float(g.get("minimum_evidence_coverage", 0.60)),
        rare_feature_threshold=float(g.get("rare_feature_threshold", 0.20)),
    )


def load_profile(path: str) -> ResearchProfile:
    raw = _load_yaml(path)
    date_range = raw.get("date_range") or {}
    return ResearchProfile(
        id=raw["id"],
        title=raw.get("title", raw["id"]),
        mode=raw.get("mode", "sci"),
        concept_groups=raw.get("concept_groups") or {},
        queries=[list(q) for q in raw.get("queries") or []],
        research_questions=raw.get("research_questions") or [],
        date_from=date_range.get("from"),
        date_to=date_range.get("to"),
        languages=raw.get("languages") or ["en"],
        include=raw.get("include") or [],
        exclude=raw.get("exclude") or [],
        snowball=bool(raw.get("snowball", False)),
        snowball_seed_limit=int(raw.get("snowball_seed_limit", 10)),
        per_query_max_results=int(raw.get("per_query_max_results", 25)),
        extraction_schema=raw.get("extraction_schema"),
        screening=_load_screening_config(raw),
        gap_analysis=_load_gap_analysis_config(raw),
    )


def pick_extraction_profile(
    matched_profile_ids: list[str], active_profiles: list[ResearchProfile]
) -> ResearchProfile | None:
    """A paper may match more than one profile (matched_profiles). Only
    ONE profile's extraction schema is used per paper - if a paper
    matches both of the configured Research Profile A/B slots (see
    config.RESEARCH_PROFILE_A_ID/_B_ID, docs/PROFILES.md), Profile B is
    preferred as a tie-break (deliberately simple: one extraction schema
    per paper, never merged - if this matters for your profiles, keep
    their concept_groups non-overlapping instead of relying on the
    tie-break). Profiles without an extraction_schema (e.g. a plain
    daily-news profile) are never considered. No match -> None -
    paper_analyst runs its normal (profile-less) analysis."""
    by_id = {p.id: p for p in active_profiles}
    for preferred in (config.RESEARCH_PROFILE_B_ID, config.RESEARCH_PROFILE_A_ID):
        if preferred and preferred in matched_profile_ids:
            p = by_id.get(preferred)
            if p and p.extraction_schema:
                return p
    # Beyond the two configured slots (a user's own additional profiles),
    # try the first matching profile that has an extraction schema.
    for pid in matched_profile_ids:
        p = by_id.get(pid)
        if p and p.extraction_schema:
            return p
    return None


def load_active_profiles() -> list[ResearchProfile]:
    """config.ACTIVE_RESEARCH_PROFILES (virgülle ayrılmış id listesi,
    varsayılan "daily_cyber" - mevcut davranışı korur) sırasına göre
    profiles/<id>.yaml dosyalarını yükler. Bilinmeyen bir id
    sessizce atlanır (log'a yazılır) - tek bozuk/eksik profil tüm koşuyu
    düşürmesin."""
    profiles: list[ResearchProfile] = []
    for profile_id in config.ACTIVE_RESEARCH_PROFILES:
        path = os.path.join(config.RESEARCH_PROFILES_DIR, f"{profile_id}.yaml")
        if not os.path.exists(path):
            print(f"[UYARI] research profile bulunamadı, atlanıyor: {path}")
            continue
        try:
            p = load_profile(path)
        except Exception as e:  # noqa: BLE001 - bozuk bir profil tüm koşuyu düşürmesin
            print(f"[UYARI] research profile yüklenemedi ({path}): {e}")
            continue
        if p.mode == "daily":
            # daily_cyber.yaml BİLİNÇLİ OLARAK queries/concept_groups
            # TANIMLAMAZ - config.KEYWORDS (.env, kullanıcı tarafından
            # değiştirilebilir) HER koşuda canlı okunur ve buradan üretilir.
            # Böylece profile sistemine geçiş KEYWORDS davranışını/esnekliğini
            # kaybettirmez: her keyword kendi başına, tek terimli bir "AND
            # grubu" olarak aranır - mevcut search_* fonksiyonlarının
            # `for keyword in config.KEYWORDS` döngüsüyle birebir aynı sonuç.
            p.concept_groups = {kw: [kw] for kw in config.KEYWORDS}
            p.queries = [[kw] for kw in config.KEYWORDS]
        profiles.append(p)
    return profiles
