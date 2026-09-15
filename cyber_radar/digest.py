"""Brifing üretici - orijinal mimari dokümanındaki (bölüm 26) şablonun
sadeleştirilmiş, gerçek veriden üretilen hali.

Haberler: news_tier'a göre 4 katman (Aksiyon Gerekli/Hunt Fırsatı/Öğretici/
Farkındalık) - "SO WHAT" bloğuyla (impact/check/detection/action/hunt).

Akademik: SABİT KOTA - her koşuda (veri varsa) 5+5+5:
  - 🆕 5 Güncel Makale (bu koşu + gerekirse son 30 gün havuzundan tamamlanır)
  - 🧭 Temelden Güncele — Son 5 Yıl (günün baskın alanından, kronolojik)
  - 🏛️ Bugünün Klasiği + 📚 Geçmişten Öne Çıkanlar (is_historical havuzu, 1+4)
Seçim run_pipeline.py'da yapılır (bkz. _select_current_papers/
_select_learning_path/_select_historical_highlights); "reading_priority"
SEÇİMİ belirlemez, yalnızca _paper_line içinde bir etiket olarak görünür -
"selection != reading_priority" (kullanıcı isteği). reading_priority/
my_relevance gibi alanlar ayrıca novelty_score'dan BAĞIMSIZ - bkz.
llm/paper_analyst.py ve llm/news_analyst.py'daki prompt notları.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import config

_CITATION_BUCKETS = [(1000, 10), (500, 8), (200, 6), (50, 4), (10, 2)]


def _citation_importance(cited_by_count: int | None) -> float:
    if not cited_by_count:
        return 0
    for threshold, score in _CITATION_BUCKETS:
        if cited_by_count >= threshold:
            return score
    return 1


def historical_score(p: dict[str, Any]) -> float:
    """citation_importance + foundational_value + educational_value + relevance,
    eşit ağırlıklı ortalama (0-10). Bilinçli olarak novelty_score'u HİÇ
    kullanmıyor - eski/klasik bir makale burada düşük çıkmasın diye (novelty
    zaten "Yeni Akademik Makaleler" tarafında kullanılıyor, bkz. run_pipeline._top_n_papers)."""
    a = p.get("analysis") or {}
    citation = _citation_importance(p.get("cited_by_count"))
    foundational = a.get("foundational_value_score") or 0
    educational = a.get("educational_value_score") or 0
    relevance_conf = ((p.get("relevance") or {}).get("confidence") or 0) * 10
    return round((citation + foundational + educational + relevance_conf) / 4, 1)


# PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md H1): "🧭 Temelden
# Güncele" eskiden sadece kronolojik sıralanıyordu ama bir öğrenme
# zincirindeki AŞAMAYI (temel -> gelişim -> modern yöntem -> son teknoloji
# -> güncel) hiç ETİKETLEMİYORDU. run_pipeline._select_learning_path zaten
# sonucu publication_date'e göre eskiden yeniye SIRALIYOR (bkz. o
# fonksiyonun son satırı) - burada YENİ bir LLM alanı istemeden, o sıraya
# göre DETERMİNİSTİK bir aşama etiketi üretiliyor (pozisyonel dilimleme).
_LEARNING_PATH_STAGES = ("FOUNDATION", "DEVELOPMENT", "MODERN_METHOD", "STATE_OF_THE_ART", "CURRENT")


def _learning_path_stage_labels(papers: list[dict[str, Any]]) -> list[str]:
    """`papers` publication_date'e göre eskiden yeniye SIRALI olmalı (bkz.
    run_pipeline._select_learning_path). Her makaleye, listedeki göreli
    konumuna göre 5 aşamadan birini deterministik olarak atar - rastgele
    ya da LLM'e sorulmuş bir etiket DEĞİL, sadece zaten var olan kronolojik
    sıranın okunabilir bir yorumu."""
    n = len(papers)
    if n == 0:
        return []
    labels = []
    for i in range(n):
        bucket = min(len(_LEARNING_PATH_STAGES) - 1, (i * len(_LEARNING_PATH_STAGES)) // n)
        labels.append(_LEARNING_PATH_STAGES[bucket])
    return labels


def _reading_minutes_txt(a: dict[str, Any]) -> str:
    minutes = a.get("estimated_reading_minutes")
    if not minutes:
        return ""
    basis_note = " (yalnızca özet)" if a.get("reading_time_basis") == "abstract_only" else ""
    return f" — ~{minutes} dk{basis_note}"


def _reading_time_breakdown(a: dict[str, Any]) -> tuple[int, int] | None:
    """Bölüm rehberinden kaba bir "önerilen süre" tahmini: READ bölümler tam,
    SKIM bölümler ~%30 ağırlık alır (gerçek bölüm uzunlukları elimizde yok,
    bu yüzden bilinçli olarak kaba bir oran - yanıltmasın diye her zaman
    "tahmini" olarak sunulmalı, kesin süre gibi değil)."""
    total = a.get("estimated_reading_minutes")
    guide = a.get("reading_guide") or []
    if not total or not guide:
        return None
    read_n = sum(1 for g in guide if g.get("action") == "READ")
    skim_n = sum(1 for g in guide if g.get("action") == "SKIM")
    recommended = max(1, round(total * (read_n + 0.3 * skim_n) / len(guide)))
    quick_skim = max(1, round(total * 0.15))
    return recommended, quick_skim


_DEEP_VIEW_RELEVANCE_THRESHOLD = 0.9  # "çok yüksek relevance" - bkz. proje notları madde 9


def _relevance_score_txt(p: dict[str, Any]) -> str:
    conf = (p.get("relevance") or {}).get("confidence")
    return f" (relevance: {conf:.0%})" if conf is not None else ""


def _paper_line(p: dict[str, Any], show_year: bool = False, detailed: bool = False, number: int | None = None) -> list[str]:
    """İki görünüm (madde 9 - "Telegram yalnızca presentation layer, detay
    DB'de saklanır"):
      BRIEF (detailed=False): karar(priority_tag) + role(role_tag) + başlık
        + süre + neden + kısa özet + relevance score.
      DEEP (detailed=True, veya MUST_READ/SCI/tez/çok yüksek relevance
        otomatik yükseltilir): BRIEF'in tamamı + paper_role/foundation_for/
        BUILDS_ON/zorluk/ön bilgi/okuma rehberi/... (aşağıda)."""
    a = p.get("analysis") or {}
    year = f"({p['publication_date'].isoformat()[:4]}) " if show_year and p.get("publication_date") else ""
    ptype = f"[{a['paper_type']}] " if a.get("paper_type") else ""
    # reading_priority artık SEÇİMİ belirlemiyor (bkz. run_pipeline._select_current_papers
    # / _select_learning_path) - sadece burada, seçilmiş makalenin yanında bir
    # etiket olarak gösteriliyor. "selection != reading_priority".
    priority_tag = f"[{a['reading_priority']}] " if a.get("reading_priority") else ""
    role_tag = f"[{'/'.join(a['paper_role'])}] " if a.get("paper_role") else ""
    bullet = f"{number}." if number is not None else "-"
    out = [
        f"{bullet} {priority_tag}{role_tag}{year}{ptype}**{p.get('title')}**"
        f"{_reading_minutes_txt(a)}{_relevance_score_txt(p)}"
    ]
    if a.get("why_read"):
        out.append(f"  Neden: {a['why_read']}")
    if a.get("turkish_summary"):
        out.append(f"  _{a['turkish_summary']}_")

    # DEEP view'a otomatik yükseltme: MUST_READ / çok yüksek relevance -
    # SCI/tez zaten kendi ayrı _digest_bridge_lines'ıyla her zaman detaylı
    # (bu fonksiyonun kapsamı dışında). Kalan her yerde çağıranın kararına
    # bakılır (bkz. proje notları: "26 makalenin tamamına devasa analiz
    # basmak Telegram'ı okunamaz hale getirir").
    high_relevance = ((p.get("relevance") or {}).get("confidence") or 0) >= _DEEP_VIEW_RELEVANCE_THRESHOLD
    detailed = detailed or a.get("reading_priority") == "MUST_READ" or high_relevance
    if not detailed:
        return out

    # NOT: paper_role artık üstteki başlık satırında role_tag olarak
    # gösteriliyor (BRIEF+DEEP ortak) - burada AYRICA tekrar basılmıyor.

    foundation_for = a.get("foundation_for") or []
    if foundation_for:
        out.append("  Temel oluşturduğu alanlar:")
        for f in foundation_for:
            out.append(f"    • {f}")

    # BUILDS_ON/FOUNDATION_FOR (paper<->paper, Phase 2 madde 6) - `foundation_for`
    # (yukarıda) ile KARIŞTIRILMASIN: bu LLM'in ürettiği KONU/alt-alan
    # etiketleri, buradaki `_builds_on`/`_foundation_for` ise run_pipeline.
    # _enrich_relationships tarafından SADECE gerçek reference/citation
    # metadata'sıyla (OpenCitations) doğrulanmış GERÇEK paper<->paper
    # kenarları - LLM bunları HİÇ üretmiyor, bkz. src/research/
    # citation_relationships.py.
    builds_on = p.get("_builds_on") or []
    if builds_on:
        out.append("  BUILDS_ON (doğrulanmış referans):")
        for rel in builds_on:
            out.append(f"    • {rel.get('title')}")
    foundation_for_papers = p.get("_foundation_for") or []
    if foundation_for_papers:
        out.append("  FOUNDATION_FOR (bu makaleye atıf yapan, korpusumuzdaki çalışmalar):")
        for rel in foundation_for_papers:
            out.append(f"    • {rel.get('title')}")

    if a.get("difficulty_label"):
        depth_bits = []
        if a.get("technical_depth_score") is not None:
            depth_bits.append(f"Teknik derinlik: {a['technical_depth_score']}/5")
        if a.get("math_intensity_score") is not None:
            depth_bits.append(f"Matematik yoğunluğu: {a['math_intensity_score']}/5")
        if a.get("implementation_value_score") is not None:
            depth_bits.append(f"Uygulanabilirlik: {a['implementation_value_score']}/5")
        depth_txt = f" ({', '.join(depth_bits)})" if depth_bits else ""
        out.append(f"  Zorluk: {a.get('difficulty_score', '?')}/5 - {a['difficulty_label']}{depth_txt}")

    prereqs = a.get("prerequisites") or []
    if prereqs:
        out.append("  Ön bilgi:")
        for pr in prereqs:
            mark = "✓" if pr.get("importance") == "essential" else "△"
            out.append(f"    {mark} {pr.get('topic')}")

    guide = a.get("reading_guide") or []
    if guide:
        out.append("  Okuma rehberi:")
        for g in guide:
            out.append(f"    {g.get('section')} → {g.get('action')}")
        breakdown = _reading_time_breakdown(a)
        if breakdown:
            recommended, quick_skim = breakdown
            out.append(
                f"  Süre: Tam metin ~{a.get('estimated_reading_minutes')} dk | "
                f"Önerilen bölümler ~{recommended} dk | Hızlı göz atma ~{quick_skim} dk"
            )

    must_see = a.get("must_see") or []
    if must_see:
        out.append(f"  Özellikle: {', '.join(must_see)}")

    domain_scores = a.get("domain_contribution_scores") or {}
    top_domains = sorted((d for d in domain_scores.items() if d[1]), key=lambda kv: kv[1], reverse=True)[:4]
    if top_domains:
        out.append("  Sana katkısı: " + ", ".join(f"{name} {score}/10" for name, score in top_domains))

    # Aktif öğrenme bloğu yalnızca gerçekten MUST_READ olanlarda (historical_score
    # ile seçilen "Bugünün Klasiği" MUST_READ olmayabilir - bu blok orada gösterilmez).
    if a.get("reading_priority") == "MUST_READ":
        questions = a.get("post_reading_questions") or []
        if questions:
            out.append("  Okuma sonrası sorular:")
            for i, q in enumerate(questions, 1):
                out.append(f"    {i}. {q}")
        if a.get("explain_to_analyst_prompt"):
            out.append(f"  Kendin açıkla: {a['explain_to_analyst_prompt']}")
        if a.get("practical_application"):
            out.append(f"  Pratik uygulama: {a['practical_application']}")

    return out


def _technical_block(n: dict[str, Any]) -> list[str]:
    """CVE/CVSS/CWE/KEV/vendor/product/affected-fixed sürüm - bkz. proje
    notları "Teknik bilgiler" formatı. Her alan opsiyonel, VERİ YOKSA
    satır hiç basılmaz (uydurma yok)."""
    a = n.get("analysis") or {}
    out: list[str] = []
    cves = n.get("cves") or []
    if cves:
        cvss = f" (CVSS: {a['cvss_score']})" if a.get("cvss_score") is not None else ""
        out.append(f"  CVE: {', '.join(cves)}{cvss}")
    cwe = a.get("cwe") or []
    if cwe:
        out.append(f"  CWE: {', '.join(cwe)}")
    if n.get("cisa_kev") or a.get("kev_related"):
        out.append("  KEV: Evet (CISA Known Exploited Vulnerabilities)")
    vendors, products = a.get("vendors") or [], a.get("products") or []
    if vendors or products:
        out.append(f"  Vendor/Product: {', '.join(vendors + products)}")
    affected, fixed = a.get("affected_versions") or [], a.get("fixed_versions") or []
    if affected:
        out.append(f"  Etkilenen sürümler: {', '.join(affected)}")
    if fixed:
        out.append(f"  Düzeltilen sürüm: {', '.join(fixed)}")
    return out


def _mitre_ioc_block(n: dict[str, Any]) -> list[str]:
    """MITRE ATT&CK + IOC + process/command/Event ID - bkz. proje notları.
    Hiçbiri metinde yoksa hiçbir satır basılmaz. 2026-09-15 (PHASE 10,
    docs/FUNCTIONAL_GAP_ANALYSIS.md B5/B6): ioc.emails ve registry/service/
    scheduled-task/mutex/user-agent artifact'leri - önceden çıkarılıyor ve
    material-update tespitinde kullanılıyordu ama digest'te HİÇ
    gösterilmiyordu, sadece DB'de kalıyordu."""
    a = n.get("analysis") or {}
    out: list[str] = []
    mitre = a.get("mitre_attack") or []
    if mitre:
        out.append(f"  MITRE ATT&CK: {', '.join(mitre)}")
    ioc = a.get("ioc") or {}
    ioc_parts = []
    for label, key in (("IP", "ips"), ("Domain", "domains"), ("Hash", "hashes"), ("URL", "urls"), ("E-posta", "emails")):
        vals = ioc.get(key) or []
        if vals:
            ioc_parts.append(f"{label}: {', '.join(vals)}")
    if ioc_parts:
        out.append(f"  IOC: {' | '.join(ioc_parts)}")
    processes = a.get("process_names") or []
    if processes:
        out.append(f"  Süreç: {', '.join(processes)}")
    cmds = a.get("command_lines") or []
    if cmds:
        out.append(f"  Komut: {' | '.join(f'`{c}`' for c in cmds)}")
    event_ids = a.get("event_ids") or []
    if event_ids:
        out.append(f"  Event ID: {', '.join(event_ids)}")
    registry_paths = a.get("registry_paths") or []
    if registry_paths:
        out.append(f"  Registry yolu: {', '.join(f'`{p}`' for p in registry_paths)}")
    registry_artifacts = a.get("registry_artifacts") or []
    if registry_artifacts:
        out.append(f"  Registry artifact: {', '.join(registry_artifacts)}")
    services = a.get("services") or []
    if services:
        out.append(f"  Servis: {', '.join(services)}")
    scheduled_tasks = a.get("scheduled_tasks") or []
    if scheduled_tasks:
        out.append(f"  Zamanlanmış görev: {', '.join(scheduled_tasks)}")
    mutexes = a.get("mutexes") or []
    if mutexes:
        out.append(f"  Mutex: {', '.join(mutexes)}")
    user_agents = a.get("user_agents") or []
    if user_agents:
        out.append(f"  User-Agent: {', '.join(f'`{u}`' for u in user_agents)}")
    return out


def _detection_tooling_block(n: dict[str, Any]) -> list[str]:
    a = n.get("analysis") or {}
    out: list[str] = []
    if a.get("splunk_applicability"):
        out.append(f"  Splunk: {a['splunk_applicability']}")
    if a.get("wazuh_applicability"):
        out.append(f"  Wazuh: {a['wazuh_applicability']}")
    if a.get("sigma_applicability"):
        out.append(f"  Sigma: {a['sigma_applicability']}")
    return out


def _so_what_block(n: dict[str, Any]) -> list[str]:
    a = n.get("analysis") or {}
    out = []
    if a.get("impact"):
        out.append(f"  Etki: {a['impact']}")
    if a.get("enterprise_impact"):
        out.append(f"  Kurumsal etki: {a['enterprise_impact']}")
    if a.get("exposure_check"):
        out.append(f"  Kontrol et: {a['exposure_check']}")
    out.extend(_technical_block(n))
    detection = a.get("detection") or []
    if detection:
        out.append(f"  Tespit: {'; '.join(detection)}")
    mitigation = a.get("mitigation") or []
    if mitigation:
        out.append(f"  Aksiyon: {'; '.join(mitigation)}")
    if a.get("hunt_query"):
        out.append(f"  Hunt: `{a['hunt_query']}`")
    out.extend(_mitre_ioc_block(n))
    out.extend(_detection_tooling_block(n))
    return out


def _hunt_block(n: dict[str, Any]) -> list[str]:
    a = n.get("analysis") or {}
    out = []
    if a.get("attack_vector"):
        out.append(f"  Teknik: {a['attack_vector']}")
    detection = a.get("detection") or []
    if detection:
        out.append(f"  Bakılacak loglar: {'; '.join(detection)}")
    out.extend(_mitre_ioc_block(n))
    if a.get("hunt_query"):
        out.append(f"  Hunt: `{a['hunt_query']}`")
    out.extend(_detection_tooling_block(n))
    if a.get("soc_value_score") is not None:
        out.append(f"  SOC değeri: {a['soc_value_score']}/10")
    return out


def _is_active_exploit(n: dict[str, Any]) -> bool:
    """2026-09-14: Hunt Fırsatı boş-durum mesajı için - bir haber "aktif
    istismar" sayılır mı? Üç bağımsız sinyal: news_events.cisa_kev
    (deterministik, run_pipeline.py'de gerçek KEV listesine karşı kontrol
    edilir - bkz. news_analyst.py'deki kev_related yorumu), ya da LLM
    analizindeki active_exploitation/exploit_status alanları (metnin kendi
    iddiası). Hiçbiri UYDURMA değil - hepsi ya deterministik ya da zaten
    var olan, grounded analiz alanları."""
    a = n.get("analysis") or {}
    return bool(n.get("cisa_kev") or a.get("active_exploitation") or a.get("exploit_status") == "active_exploitation")


def news_tier(n: dict[str, Any]) -> str:
    a = n.get("analysis") or {}
    tier = a.get("news_tier")
    if tier:
        return tier
    # news_tier bu değişiklikten ÖNCE analiz edilmiş haberlerde yok - eski
    # alanlardan (priority_label/my_relevance/hunt_query) kaba bir eşleme.
    if n.get("priority_label") in ("CRITICAL", "HIGH") or a.get("my_relevance") == "HIGH":
        return "ACTION_REQUIRED"
    if a.get("hunt_query"):
        return "HUNT_OPPORTUNITY"
    if a.get("my_relevance") == "MEDIUM":
        return "AWARENESS"
    return "ARCHIVE" if a else "AWARENESS"



def _humanize_field_name(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def _relevance_dimension_summary(dims: dict[str, Any] | None, threshold: int = 6) -> str | None:
    """Derives "which sub-topic does this contribute to" deterministically
    from an already-collected 0-10 dimension-score dict (whatever the
    active profile's extraction_schema calls its dimensions field) -
    no extra LLM field needed, no fabrication risk, and no hardcoded
    per-profile dimension-name labels (generic: humanizes the field name
    the profile author chose)."""
    if not dims:
        return None
    hits = [_humanize_field_name(k) for k, v in dims.items() if isinstance(v, (int, float)) and v >= threshold]
    return ", ".join(hits) if hits else None


def _generic_profile_bridge_lines(
    p: dict[str, Any],
    score_field: str,
    reason_field: str,
    dims_field: str,
    number: int | None = None,
) -> list[str]:
    """Generic "Research Profile A/B" digest section renderer (see
    docs/PROFILES.md) - works with ANY user-defined profile's
    `digest_bridge` extraction_schema, not a hardcoded field list. Field
    names are config-driven (RESEARCH_PROFILE_A/B_SCORE_FIELD etc., see
    cyber_radar/config.py) so a custom profile can use its own vocabulary.
    Everything under `profile_extraction.digest_bridge` is rendered as-is
    (humanized field name -> value), whatever fields the profile's own
    schema happens to define - no profile-specific Python code is needed
    to add a new research profile. Analysis-not-yet-done is shown
    honestly, never fabricated. `number=None` when embedded standalone in
    its own PaperCard (no ordinal needed, bullet is "-")."""
    a = p.get("analysis") or {}
    bullet = f"{number}." if number is not None else "-"
    out = [f"{bullet} **{p.get('title')}**"]
    extraction_status = a.get("profile_extraction_status")
    extraction = (a.get("profile_extraction") or {}) if extraction_status == "valid" else {}
    if extraction_status != "valid" or not extraction:
        out.append("  _Not yet analyzed - will be evaluated once LLM budget allows._")
        return out

    score = extraction.get(score_field)
    if score is not None:
        out.append(f"  Relevance score: {score}/10")

    reason = extraction.get(reason_field)
    if reason:
        out.append(f"  Why relevant: {reason}")

    dims_summary = _relevance_dimension_summary(extraction.get(dims_field))
    if dims_summary:
        out.append(f"  Strongest dimensions: {dims_summary}")

    bridge = extraction.get("digest_bridge") or {}
    for field, val in bridge.items():
        if isinstance(val, list):
            val = ", ".join(str(v) for v in val) if val else None
        if val:
            out.append(f"  {_humanize_field_name(field)}: {val}")
    return out


@dataclass
class PaperCard:
    """2026-09-11 Telegram anchor-mesaj DUPLİKASYON düzeltmesi (bkz. proje
    notları): eskiden interaktif bir makale (MUST_READ/Bugünün Klasiği)
    HEM toplu digest metninde tam olarak gösteriliyor HEM DE butonları
    taşımak için "📚 Oku Şimdi: <title>" gibi AYRI, kısa bir "anchor"
    mesajı gönderiliyordu - kullanıcı ekranında aynı makale iki kere,
    biri tam biri kırpık, art arda görünüyordu. Artık böyle bir makale
    toplu metinde HİÇ gösterilmiyor (bkz. generate_brief), TEK bir
    PaperCard'a dönüşüyor - kartın `text`'i o makalenin TAM (detaylı)
    sunumunu içerir, kategori başlığıyla birlikte. Keyboard BİLEREK bu
    objede DEĞİL - digest.py Telegram/notify katmanına bağımlı kalmasın
    diye (katman ayrımı), keyboard'u çağıran taraf (run_pipeline.
    _send_feedback_followups) notify.feedback_buttons ile ekleyip
    notify.send_interactive(card.text, keyboard) ile TEK mesajda gönderir
    - text ve keyboard ASLA ayrı mesajlara bölünmez (Telegram inline
    keyboard zaten tek bir mesajın reply_markup'ına bağlıdır)."""
    paper_id: int
    category: str  # "MUST_READ" | "CURRENT" | "TIMELINE" | "CLASSIC" | "HISTORICAL" | "SCI" | "THESIS"
    text: str


# Telegram'ın 4096 karakter sınırından pay bırakır (bkz. proje notları) -
# kart TEK mesaj olarak kalmalı (bölünemez, keyboard'u taşıyor), bu yüzden
# aşan içerik BÖLÜNMEZ, kelime sınırında GÜVENLE kısaltılır.
_CARD_TEXT_MAX_LEN = 3800


def _safe_truncate(text: str, size: int = _CARD_TEXT_MAX_LEN) -> str:
    if len(text) <= size:
        return text
    cut = text[:size]
    last_space = cut.rfind(" ")
    if last_space > 0:
        cut = cut[:last_space]
    return cut + "\n\n_(mesaj sınırı nedeniyle kısaltıldı - tam analiz veritabanında saklı)_"


def _card_from_lines(paper_id: int, category: str, header: str, body_lines: list[str]) -> PaperCard:
    text = f"{header}\n\n" + "\n".join(body_lines)
    return PaperCard(paper_id=paper_id, category=category, text=_safe_truncate(text))


# PHASE 10 (2026-09-15, docs/FUNCTIONAL_GAP_ANALYSIS.md U1): bir kaydın
# BU KOŞUDA mı toplandığı yoksa daha önceki bir koşudan mı (havuz/rotasyon)
# geldiği - run_pipeline.py seçim anında `_digest_source` ile damgalar.
# SADECE "BACKFILL" için kısa bir etiket basılır - FRESH zaten varsayılan/
# beklenen durum olduğu için her kayıtta tekrarlamak Telegram'ı gereksiz
# kalabalıklaştırır (kullanıcı isteği: "kısa göster").
def _source_tag(item: dict[str, Any]) -> str:
    return " _[BACKFILL]_" if item.get("_digest_source") == "BACKFILL" else ""


def _build_paper_card(p: dict[str, Any], category: str, header: str, extra_lines: list[str] | None = None) -> PaperCard:
    body = _paper_line(p, show_year=True, detailed=True, number=None)
    if extra_lines:
        body = body + extra_lines
    return _card_from_lines(p["id"], category, f"{header}{_source_tag(p)}", body)


def build_all_paper_cards(
    current_papers: list[dict[str, Any]],
    learning_path_papers: list[dict[str, Any]] | None = None,
    historical_papers: list[dict[str, Any]] | None = None,
    profile_a_papers: list[dict[str, Any]] | None = None,
    profile_b_papers: list[dict[str, Any]] | None = None,
    read_now: dict[str, Any] | None = None,
) -> list[PaperCard]:
    """2026-09-11 (kullanıcı isteği: "kayıt butonları tam her makale
    altında olsun"): geri bildirim butonları TEK BİR makaleye değil, o
    koşuda gösterilen HER makaleye ekleniyor - Telegram inline keyboard
    bir mesajın reply_markup'ına bağlı olduğu için (bkz. PaperCard
    docstring'i), bunun tek yolu HER makalenin kendi mesajı+keyboard'u
    olması. generate_brief() bu yüzden artık HİÇBİR akademik makaleyi
    toplu metne TAM olarak yazmıyor (sadece bölüm başlığı + "N makale
    ayrı mesaj olarak gönderildi" notu) - SADECE burada üretilen kartlar
    gösteriliyor. Aynı seçim mantığı (best = en yüksek historical_score)
    generate_brief ile TUTARLI olmalı."""
    cards: list[PaperCard] = []

    for p in current_papers:
        must_read = (p.get("analysis") or {}).get("reading_priority") == "MUST_READ"
        header = "📚 Oku Şimdi" if must_read else "🆕 Güncel Makale"
        category = "MUST_READ" if must_read else "CURRENT"
        cards.append(_build_paper_card(p, category, header))

    stage_labels = _learning_path_stage_labels(learning_path_papers or [])
    for p, stage in zip(learning_path_papers or [], stage_labels):
        cards.append(_build_paper_card(p, "TIMELINE", "🧭 Temelden Güncele", extra_lines=[f"  Öğrenme aşaması: {stage}"]))

    if historical_papers:
        ranked = sorted(historical_papers, key=historical_score, reverse=True)
        best, rest = ranked[0], ranked[1:]
        a = best.get("analysis") or {}
        extra = [
            f"  Historical score: {historical_score(best)}/10 "
            f"(atıf: {_citation_importance(best.get('cited_by_count'))}, "
            f"temel eser: {a.get('foundational_value_score', '?')}, "
            f"öğrenme değeri: {a.get('educational_value_score', '?')})"
        ]
        classic_domains = a.get("domain_contribution_scores") or {}
        if classic_domains:
            top_domain = max(classic_domains, key=classic_domains.get)
            next_reads = [
                p for p in current_papers
                if ((p.get("analysis") or {}).get("domain_contribution_scores") or {}).get(top_domain, 0) >= 5
            ]
            if next_reads:
                extra.append("  Bunu okuduktan sonra:")
                for nr in next_reads[:3]:
                    extra.append(f"    → {nr.get('title')}")
        cards.append(_build_paper_card(best, "CLASSIC", "🏛️ Bugünün Klasiği", extra_lines=extra))
        for p in rest:
            cards.append(_build_paper_card(p, "HISTORICAL", "📚 Geçmişten Öne Çıkanlar", extra_lines=[f"  Historical score: {historical_score(p)}/10"]))

    for p in profile_a_papers or []:
        body = _generic_profile_bridge_lines(
            p, config.RESEARCH_PROFILE_A_SCORE_FIELD, config.RESEARCH_PROFILE_A_REASON_FIELD,
            config.RESEARCH_PROFILE_A_DIMS_FIELD,
        )
        cards.append(_card_from_lines(p["id"], "RESEARCH_PROFILE_A", "🔬 Research Profile A", body))

    for p in profile_b_papers or []:
        body = _generic_profile_bridge_lines(
            p, config.RESEARCH_PROFILE_B_SCORE_FIELD, config.RESEARCH_PROFILE_B_REASON_FIELD,
            config.RESEARCH_PROFILE_B_DIMS_FIELD,
        )
        cards.append(_card_from_lines(p["id"], "RESEARCH_PROFILE_B", "🎓 Research Profile B", body))

    if read_now:
        # W1 (PHASE 10, docs/FUNCTIONAL_GAP_ANALYSIS.md): TÜM korpustan
        # algoritmik olarak seçilmiş TEK bir öneri - "neden şimdi" cümlesi
        # (_read_now_reason, run_pipeline.py) en üstte, altında TAM makale
        # kartı (diğer kategorilerle AYNI detaylı görünüm).
        reason = read_now.get("_read_now_reason")
        body = ([f"  _{reason}_", ""] if reason else []) + _paper_line(read_now, show_year=True, detailed=True, number=None)
        cards.append(_card_from_lines(read_now["id"], "READ_NOW", "📚 Oku Şimdi — Bugünün Önerisi", body))

    return cards


def generate_brief(
    news_events: list[dict[str, Any]],
    papers: list[dict[str, Any]],
    historical_papers: list[dict[str, Any]],
    notebooklm_updates: dict[str, list[str]],
    slot: str,
    daily_theme: dict[str, Any] | None = None,
    stale_must_reads: list[dict[str, Any]] | None = None,
    learning_path_papers: list[dict[str, Any]] | None = None,
    profile_a_papers: list[dict[str, Any]] | None = None,
    profile_b_papers: list[dict[str, Any]] | None = None,
    read_now: dict[str, Any] | None = None,
) -> str:
    """slot: 'Sabah' | 'Akşam' - yalnızca başlıkta görünür."""
    now = datetime.now()
    lines = [
        f"# Cyber Intelligence Radar — {slot} Brifingi",
        f"_{now.strftime('%Y-%m-%d %H:%M')}_",
        "",
    ]

    if stale_must_reads:
        lines.append("## ⏰ Unutma")
        lines.append("_MUST_READ işaretli ama hâlâ okumadığın makaleler (3+ hafta):_")
        for p in stale_must_reads:
            days_ago = (now.date() - p["analyzed_at"].date()).days if p.get("analyzed_at") else "?"
            lines.append(f"- **{p.get('title')}** ({days_ago} gün önce önerildi)")
        lines.append("")

    # ------------------------------------------------------------------
    # Haberler: 5 katman (news_tier, bkz. news_analyst.py). "Daha fazla haber"
    # yerine "hangi haber ne yapmanı gerektiriyor" sorusuna göre ayrılıyor -
    # ACTION_REQUIRED tam SO WHAT bloğu, HUNT_OPPORTUNITY teknik hunt bloğu,
    # LEARN/AWARENESS kısa özet, ARCHIVE sadece sayaç.
    # ------------------------------------------------------------------
    def _my_relevance(n: dict[str, Any]) -> str:
        return (n.get("analysis") or {}).get("my_relevance") or "MEDIUM"

    tiers: dict[str, list[dict[str, Any]]] = {k: [] for k in
        ("ACTION_REQUIRED", "HUNT_OPPORTUNITY", "LEARN", "AWARENESS", "ARCHIVE")}
    for n in news_events:
        tiers[news_tier(n)].append(n)

    lines.append("## 🚨 Aksiyon Gerekli")
    if tiers["ACTION_REQUIRED"]:
        for n in tiers["ACTION_REQUIRED"]:
            cves = ", ".join(n.get("cves") or []) or "-"
            severity = n.get("priority_label") or "?"
            relevance = _my_relevance(n)
            # 2026-09-14 (kullanıcı isteği - "Severity ile Actionability
            # birbirine karışıyor mu?"): tasarım zaten AYRI iki alan
            # (priority_label=Global Severity, analysis.my_relevance=
            # operasyonel önem) ve news_tier() bilinçli olarak İKİSİNDEN
            # BİRİ HIGH/CRITICAL ise ACTION_REQUIRED sayıyor - bu YANLIŞ
            # DEĞİL (severity düşük ama bize özel aksiyon gerektiren bir
            # haber olabilir). Ama köşeli parantezdeki etiket SADECE
            # severity'yi gösteriyordu (ör. "[LOW]") - okuyucu haberin AYNI
            # ZAMANDA yüksek operasyonel önemden dolayı burada olduğunu
            # göremiyordu. Ranking/seçim mantığı DEĞİŞMEDİ, sadece ikisi
            # farklıyken etiket de ikisini göstersin diye render değişti.
            tag = severity if severity == relevance else f"{severity} · ACTION:{relevance}"
            lines.append(
                f"- **[{tag}] {n.get('title')}**{_source_tag(n)} "
                f"(Global Severity: {severity}, My Relevance: {relevance}, CVE: {cves})"
            )
            summary = (n.get("analysis") or {}).get("summary")
            if summary:
                lines.append(f"  _{summary}_")
            lines.extend(_so_what_block(n))
            lines.append("----")
    else:
        lines.append("_Bu dönemde acil aksiyon gerektiren olay yok._")
    lines.append("")

    lines.append("## 🕵️ Hunt Fırsatı")
    if tiers["HUNT_OPPORTUNITY"]:
        for n in tiers["HUNT_OPPORTUNITY"]:
            lines.append(f"- **{n.get('title')}**{_source_tag(n)}")
            summary = (n.get("analysis") or {}).get("summary")
            if summary:
                lines.append(f"  _{summary}_")
            lines.extend(_hunt_block(n))
            lines.append("----")
    else:
        # 2026-09-14 (kullanıcı isteği - "Hunt Fırsatı neden sürekli boş?"):
        # eskiden HER durumda AYNI jenerik "somut hunt deseni yok" metni
        # basılıyordu - okuyucu bunun "bu dönem hiç exploit haberi yok"mu
        # yoksa "exploit haberi var ama doğrulanabilir artifact yok"mu
        # olduğunu ayıramıyordu. UYDURMA YAPMADAN (artifact YOKSA hunt_query
        # hâlâ null kalır, news_analyst.py zaten "uydurma" diyor) sadece
        # NEDENİ açıklayan bir mesaja ayırıyoruz.
        no_artifact_count = sum(
            1 for n in news_events
            if _is_active_exploit(n) and not (n.get("analysis") or {}).get("hunt_query")
        )
        if no_artifact_count:
            lines.append(
                f"_Bu koşuda {no_artifact_count} aktif exploit haberi bulundu, ancak kaynaklarda "
                f"doğrulanabilir IOC/process/command-line artifact olmadığından otomatik hunt "
                f"sorgusu üretilmedi._"
            )
        else:
            lines.append("_Bu dönemde somut bir hunt deseni çıkarılabilecek haber yok._")
    lines.append("")

    lines.append("## 📚 Öğretici")
    if tiers["LEARN"]:
        for n in tiers["LEARN"]:
            lines.append(f"- **{n.get('title')}**{_source_tag(n)}")
            summary = (n.get("analysis") or {}).get("summary")
            if summary:
                lines.append(f"  _{summary}_")
            lines.append("----")
    else:
        lines.append("_Bu dönemde öğretici işaretli başka haber yok._")
    lines.append("")

    lines.append("## 👀 Farkındalık")
    if tiers["AWARENESS"]:
        for n in tiers["AWARENESS"][:10]:
            lines.append(f"- **{n.get('title')}**{_source_tag(n)}")
            summary = (n.get("analysis") or {}).get("summary")
            if summary:
                lines.append(f"  _{summary}_")
            lines.append("----")
    else:
        lines.append("_Bu dönemde sadece farkındalık amaçlı başka haber yok._")
    lines.append("")

    if tiers["ARCHIVE"]:
        lines.append(f"## 🗄️ Arşivlendi (haber)\n_{len(tiers['ARCHIVE'])} haber düşük öncelikli - DB'de duruyor._\n")

    if daily_theme and daily_theme.get("theme"):
        lines.append("## 🎯 Bugünün Öğrenme Konusu")
        lines.append(f"**{daily_theme['theme']}**")
        for item in daily_theme.get("learn_today") or []:
            lines.append(f"- {item}")
        if daily_theme.get("reading_order_note"):
            lines.append(f"_{daily_theme['reading_order_note']}_")
        lines.append("")

    # ------------------------------------------------------------------
    # Akademik: SABİT KOTA, 5+5+5 (kullanıcı isteği - "selection != reading_priority").
    # Seçim run_pipeline.py'da yapıldı (_select_current_papers /
    # _select_learning_path / _select_historical_highlights); burada sadece
    # gösteriliyor. reading_priority _paper_line içinde bir ETİKET olarak
    # görünür, hangi makalenin brifinge gireceğini belirlemez.
    # ------------------------------------------------------------------
    # 2026-09-11 (kullanıcı isteği: "kayıt butonları tam her makale altında
    # olsun"): Telegram inline keyboard bir mesajın reply_markup'ına bağlı
    # olduğu için (bkz. PaperCard docstring'i), HER makalenin kendi
    # butonlarına sahip olabilmesinin TEK yolu her birinin kendi mesajı
    # olması - bu yüzden HİÇBİR akademik makale artık toplu metne TAM
    # yazılmıyor (bkz. build_all_paper_cards - AYNI seçim/sıralama mantığı,
    # iki yerde tutarlı). Bulk digest'te sadece bölüm başlığı + kısa bir
    # yönlendirme notu kalıyor - aynı makale hem toplu metinde hem
    # interaktif kartta GÖRÜNMEMELİ.
    def _sent_as_cards_note(n: int, label: str) -> str:
        return f"_{n} {label} — her biri kendi butonlarıyla ayrı mesaj olarak gönderildi._"

    lines.append("## 🆕 5 Güncel Makale")
    lines.append(_sent_as_cards_note(len(papers), "makale") if papers else "_Bu dönemde ilgili güncel makale bulunamadı._")
    lines.append("")

    lines.append("## 🧭 Temelden Güncele — Son 5 Yıl")
    lines.append(
        _sent_as_cards_note(len(learning_path_papers), "makale") if learning_path_papers
        else "_Bu dönemde son 5 yıldan anlamlı bir okuma yolu oluşturulamadı._"
    )
    lines.append("")

    # Geçmiş havuzu: rotasyon _select_historical_highlights'ta. En yüksek
    # historical_score'lu (novelty DEĞİL - bkz. yukarıdaki historical_score())
    # "Bugünün Klasiği", kalanı "Geçmişten Öne Çıkanlar" - AYNI "best" seçim
    # mantığı build_all_paper_cards'ta, iki yerde tutarlı.
    lines.append("## 🏛️ Bugünün Klasiği / 📚 Geçmişten Öne Çıkanlar")
    lines.append(
        _sent_as_cards_note(len(historical_papers), "makale") if historical_papers
        else "_Bu dönemde başka geçmiş/klasik makale yok._"
    )
    lines.append("")

    # ------------------------------------------------------------------
    # Research Profile A/B - GENERIC (public export). Only populated when
    # a profile is assigned to config.RESEARCH_PROFILE_A_ID/_B_ID AND
    # active in ACTIVE_RESEARCH_PROFILES (see run_pipeline.main 4b) - by
    # default both are unset, these sections never print, default briefing
    # format is unaffected.
    # ------------------------------------------------------------------
    if profile_a_papers:
        lines.append(f"## 🔬 Research Profile A ({len(profile_a_papers)})")
        lines.append(_sent_as_cards_note(len(profile_a_papers), "paper"))
        lines.append("")

    if profile_b_papers:
        lines.append(f"## 🎓 Research Profile B ({len(profile_b_papers)})")
        lines.append(_sent_as_cards_note(len(profile_b_papers), "paper"))
        lines.append("")

    # W1 (PHASE 10, docs/FUNCTIONAL_GAP_ANALYSIS.md): digest sonunda TEK
    # bir öneri - AYNI "bulk'ta sadece başlık, TAM içerik kendi kartında"
    # ilkesi (SCI/tez ile TUTARLI).
    if read_now:
        lines.append("## 📚 Oku Şimdi — Bugünün Önerisi")
        lines.append(_sent_as_cards_note(1, "makale"))
        lines.append("")

    if notebooklm_updates:
        lines.append("## NotebookLM İçin Güncellenen Dosyalar")
        lines.append("_Aşağıdaki dosyaları ilgili NotebookLM notebook'unuza manuel yükleyin:_")
        for topic, files in notebooklm_updates.items():
            for f in files:
                lines.append(f"- **{topic}**: `{f}`")
        lines.append("")

    review_count = sum(1 for n in news_events if n.get("relevance_status") == "uncertain") + sum(
        1 for p in papers if p.get("relevance_status") == "uncertain"
    )
    if review_count:
        lines.append(f"## Gözden Geçirme Kuyruğu\n{review_count} öğe belirsiz kategoride, review_queue tablosunda bekliyor.\n")

    return "\n".join(lines)


def save_brief(text: str, slot: str) -> str:
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y-%m-%d')}_{slot.lower()}.md"
    path = os.path.join(config.REPORTS_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path
