"""Dedup mantığı.

Akademik tarafta gerçek anahtar DOI / arXiv ID / OpenAlex ID (DB'de UNIQUE
kolonlar bunu zaten garanti eder); normalized_title ise bu ID'ler eksikse
ikinci bir güvenlik ağı olarak kullanılır.

Haber tarafında ise "aynı olayın 20 kaynağı = 1 event, 20 source" prensibi
burada uygulanır: canonical URL, CVE kesişimi ve başlık benzerliğiyle mevcut
bir news_events satırına mı ekleniyoruz yoksa yeni satır mı açılıyor karar
verilir.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "fbclid", "gclid", "mc_cid", "mc_eid",
}

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """Başlığı karşılaştırılabilir hale getirir: küçük harf, noktalama yok,
    tekrarlayan boşluklar tek boşluğa indirilir."""
    if not title:
        return ""
    t = title.lower().strip()
    t = _PUNCT_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t)
    return t.strip()


def canonical_url(url: str) -> str:
    """Tracking parametrelerini temizler, host'u küçük harfe çevirir,
    sondaki / işaretini kaldırır."""
    if not url:
        return url
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in _TRACKING_PARAMS]
    path = parsed.path.rstrip("/") or "/"
    cleaned = parsed._replace(
        netloc=parsed.netloc.lower(),
        path=path,
        query=urlencode(query),
        fragment="",
    )
    return urlunparse(cleaned)


def title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def extract_cves(text: str) -> list[str]:
    if not text:
        return []
    return sorted(set(re.findall(r"CVE-\d{4}-\d{4,7}", text, flags=re.IGNORECASE)), key=str.upper)


def is_same_event(
    new_title: str,
    new_cves: list[str],
    new_url: str,
    existing_title: str,
    existing_cves: list[str],
    existing_urls: list[str],
    title_threshold: float = 0.72,
) -> bool:
    """Bir haberin mevcut bir news_events satırıyla aynı olay olup olmadığına
    karar verir. Sinyaller: aynı canonical URL, ortak CVE, veya yüksek başlık
    benzerliği. Orijinal mimari dokümanındaki dedup sinyallerinin (CVE, ürün,
    vendor, başlık benzerliği) basitleştirilmiş, tek-sunucuya uygun hali."""
    if new_url and canonical_url(new_url) in {canonical_url(u) for u in existing_urls}:
        return True
    if new_cves and existing_cves and set(new_cves) & set(existing_cves):
        return True
    if title_similarity(new_title, existing_title) >= title_threshold:
        return True
    return False


# ---------------------------------------------------------------------------
# 2026-09-14 (kullanıcı isteği - "material update modelini düzelt"): aynı
# olayın İKİ ANI (old_event = son gösterildiğindeki/önceki durum, new_event =
# şimdiki DB durumu) arasında okuyucu için GERÇEKTEN aksiyon değiştirebilecek
# bir fark var mı? TAMAMEN DETERMİNİSTİK - hiçbir alanda LLM'e "material mı?"
# diye SORULMAZ, sadece iki yapılandırılmış sözlük karşılaştırılır. is_same_
# event()'ten AYRI bir soru: o "aynı olay mı", bu "aynı olay ANLAMLI ŞEKİLDE
# DEĞİŞTİ mi" - ikisi karıştırılmamalı.
# ---------------------------------------------------------------------------
_SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
_RELEVANCE_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
# None/"none_reported" en düşük, "poc" orta, "active_exploitation" en yüksek -
# sadece YÜKSELİŞ material sayılır (bkz. is_material_news_update).
_EXPLOIT_STATUS_ORDER = {None: 0, "none_reported": 0, "poc": 1, "active_exploitation": 2}

# 2026-09-15 (madde 2 tamamlandı - news_analyst.py şeması genişletildi):
# email/registry artifact (IOC) ve file path/registry path/service/
# scheduled task/mutex/user-agent (hunt artifact) artık şemada VAR - bkz.
# src/llm/news_analyst.py 2026-09-15 değişikliği.
_IOC_LIST_FIELDS = ("ips", "domains", "hashes", "urls", "emails")
_HUNT_ARTIFACT_LIST_FIELDS = (
    "process_names", "command_lines", "event_ids", "file_paths",
    "registry_paths", "registry_artifacts", "services", "scheduled_tasks",
    "mutexes", "user_agents",
)


def _normalize_whitespace(value) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def _normalize_casefold(value) -> str:
    """Varsayılan normalizer: boşluk + case farkını yok sayar (madde 2/3 -
    "case-insensitive uygun alanlarda lowercase")."""
    return _normalize_whitespace(value).lower()


def _normalize_ip(value) -> str:
    """IPv4 için kanonik form (öndeki sıfırları at, ör. '192.168.001.001' ==
    '192.168.1.1'); IPv6/parse edilemeyen değerler için casefold'a düşer."""
    s = _normalize_whitespace(value)
    parts = s.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        try:
            return ".".join(str(int(p)) for p in parts)
        except ValueError:
            pass
    return s.lower()


def _normalize_registry_path(value) -> str:
    """Registry yolu/artifact'i: Windows registry case-insensitive'dir ve
    hem '/' hem '\\\\' ayırıcı olarak görülebilir - madde 3: "registry path
    slash/case farkları normalize"."""
    return _normalize_whitespace(value).lower().replace("/", "\\")


def _normalize_file_path(value) -> str:
    """Dosya yolu: SADECE whitespace normalize edilir, CASE KORUNUR (madde 3:
    "file path gereksiz whitespace farklarından etkilenmesin" - case için
    ayrı bir istek YOK, dosya sistemleri case-sensitive olabildiği için
    varsayılan casefold'a zorlanmadı)."""
    return _normalize_whitespace(value)


# Alan bazlı normalizer seçimi - belirtilmeyen her alan _normalize_casefold'a
# düşer (CVE/hash/domain/email/mitigation/version metni gibi "case önemsiz"
# çoğu alan için doğru varsayılan).
_FIELD_NORMALIZERS = {
    "ips": _normalize_ip,
    "registry_paths": _normalize_registry_path,
    "registry_artifacts": _normalize_registry_path,
    "file_paths": _normalize_file_path,
}


def _normalize_field_values(field: str, values) -> set[str]:
    normalizer = _FIELD_NORMALIZERS.get(field, _normalize_casefold)
    out: set[str] = set()
    for v in values or []:
        if v is None:
            continue
        norm = normalizer(v)
        if norm:
            out.add(norm)
    return out


def _new_field_items(field: str, old_values, new_values) -> set[str]:
    """new'de olup old'da OLMAYAN, alana uygun şekilde normalize edilmiş
    öğeler - sıralama/case/format farkı YOK SAYILIR (madde 2: "aynı CVE/IOC
    listesinin farklı sıralanması material değildir")."""
    return _normalize_field_values(field, new_values) - _normalize_field_values(field, old_values)


def is_material_news_update(old_event: dict, new_event: dict) -> bool:
    """old_event/new_event: news_events satırıyla aynı şekle sahip sözlükler
    - en az `cves` (list[str]), `cisa_kev` (bool), `priority_label` (str|None),
    `analysis` (dict|None) alanlarını taşımalı. `analysis` içinde bakılan
    alt-alanlar: my_relevance, active_exploitation, exploit_status,
    ioc{ips,domains,hashes,urls}, process_names, command_lines, event_ids,
    hunt_query, affected_versions, fixed_versions, mitigation.

    BİLİNÇLİ OLARAK HİÇ bakılmayan alanlar (madde 2 - "material sayılmaması
    gerekenler"): title, url, sources, last_updated_at, first_seen_at,
    published_at, source sayısı - bu fonksiyon bunları okumadığı için
    yapısal olarak bunlardaki bir değişiklik asla material sayılmaz."""
    old_analysis = old_event.get("analysis") or {}
    new_analysis = new_event.get("analysis") or {}

    # 1) Yeni CVE eklendi.
    if _new_field_items("cves", old_event.get("cves"), new_event.get("cves")):
        return True

    # 2) CISA KEV false -> true (KEV'e EKLENME özellikle önemli).
    if bool(new_event.get("cisa_kev")) and not bool(old_event.get("cisa_kev")):
        return True

    # 3) active_exploitation/exploit_status YÜKSELİŞİ - düşüş (ör. true'dan
    #    false'a) bilinçli olarak material SAYILMAZ (kullanıcı isteği: "true
    #    -> false gibi anlamsız ters güncellemede otomatik material kabul
    #    etme" - mevcut veri modelinde zaten bir haberin analysis'i ilk
    #    analizden sonra asla otomatik "geri düşmüyor", bu kontrol sadece
    #    ileride bir re-analiz akışı eklenirse GÜVENLİ davransın diye var).
    if bool(new_analysis.get("active_exploitation")) and not bool(old_analysis.get("active_exploitation")):
        return True
    old_exploit_rank = _EXPLOIT_STATUS_ORDER.get(old_analysis.get("exploit_status"), 0)
    new_exploit_rank = _EXPLOIT_STATUS_ORDER.get(new_analysis.get("exploit_status"), 0)
    if new_exploit_rank > old_exploit_rank:
        return True

    # 4) Yeni doğrulanabilir IOC (alana uygun normalize edilmiş - case/sıra/
    #    format farkı material SAYILMAZ; IP'ler kanonik forma, registry/
    #    domain/hash/email/url casefold'a indirgenir).
    old_ioc = old_analysis.get("ioc") or {}
    new_ioc = new_analysis.get("ioc") or {}
    for field in _IOC_LIST_FIELDS:
        if _new_field_items(field, old_ioc.get(field), new_ioc.get(field)):
            return True

    # 5) Yeni hunt/forensic artifact (process/command-line/event id/file
    #    path/registry path-artifact/service/scheduled task/mutex/user-
    #    agent) ya da ilk kez gerçek bir hunt_query oluşması.
    for field in _HUNT_ARTIFACT_LIST_FIELDS:
        if _new_field_items(field, old_analysis.get(field), new_analysis.get(field)):
            return True
    if new_analysis.get("hunt_query") and not old_analysis.get("hunt_query"):
        return True

    # 6) Etkilenen sürüm bilgisi anlamlı şekilde değişti (normalize edilmiş
    #    set farkı - saf metin/noktalama farkı normalize sonrası zaten
    #    eşitlenir).
    if _new_field_items("affected_versions", old_analysis.get("affected_versions"), new_analysis.get("affected_versions")):
        return True

    # 7) Fixed/patched version eklendi ya da değişti.
    if _new_field_items("fixed_versions", old_analysis.get("fixed_versions"), new_analysis.get("fixed_versions")):
        return True

    # 8) Mitigation/remediation GERÇEKTEN yeni bir öneri içeriyor - saf
    #    wording/paraphrase farkı normalize sonrası aynı sete düşer,
    #    tetiklemez.
    if _new_field_items("mitigation", old_analysis.get("mitigation"), new_analysis.get("mitigation")):
        return True

    # 9) Severity ANLAMLI YÜKSELİŞİ (LOW->HIGH, MEDIUM->CRITICAL vb.) -
    #    düşüş bilinçli olarak material SAYILMAZ (kullanıcı isteği).
    old_severity = _SEVERITY_ORDER.get(old_event.get("priority_label"), -1)
    new_severity = _SEVERITY_ORDER.get(new_event.get("priority_label"), -1)
    if new_severity > old_severity:
        return True

    # 10) Operasyonel relevance (my_relevance) YÜKSELİŞİ - kategorik bir alan
    #     (LOW/MEDIUM/HIGH), sayısal bir "skor" değil, bu yüzden "aynı LLM
    #     analizinin biraz farklı skor üretmesi" burada YAPISAL OLARAK
    #     mümkün değil (kullanıcı isteği: volatile LLM output'u tek başına
    #     tetikleyici yapma - kategorik karşılaştırma zaten bunu sağlıyor).
    old_relevance = _RELEVANCE_ORDER.get(old_analysis.get("my_relevance"), -1)
    new_relevance = _RELEVANCE_ORDER.get(new_analysis.get("my_relevance"), -1)
    if new_relevance > old_relevance:
        return True

    return False


# ---------------------------------------------------------------------------
# 2026-09-15 (madde 7 - "deterministic öncelik"): LLM'e GİTMEDEN, saf regex
# ile metinden çıkarılabilecek YÜKSEK-KESİNLİKLİ indicator türleri - IP
# (IPv4), hash (MD5/SHA1/SHA256 uzunlukları), e-posta. Domain/URL gibi daha
# DÜŞÜK kesinlikli/geniş regex'ler BİLİNÇLİ OLARAK dışarıda bırakıldı
# (yanlış pozitif riski yüksek - ör. bir versiyon numarasını "domain"
# sanma - bkz. proje notları/final rapor "Known limitations"). Bu, NİHAİ
# güvenilir IOC listesini ÜRETMEZ (o hâlâ LLM + _ground_against_source'un
# işi) - SADECE "bu metinde daha önce görülmemiş, potansiyel yeni bir
# indicator var mı" sorusuna, koşullu re-analizi TETİKLEMEK için ucuz/
# deterministik bir sinyal verir (bkz. run_pipeline._find_or_merge_news_
# event).
# ---------------------------------------------------------------------------
_DETERMINISTIC_IP_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
_DETERMINISTIC_HASH_RE = re.compile(r"\b[a-fA-F0-9]{64}\b|\b[a-fA-F0-9]{40}\b|\b[a-fA-F0-9]{32}\b")
_DETERMINISTIC_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def extract_deterministic_iocs(text: str) -> dict[str, set[str]]:
    """Bkz. yukarıdaki modül notu - IP/hash/e-posta, regex ile, LLM YOK."""
    text = text or ""
    return {
        "ips": {_normalize_ip(m) for m in _DETERMINISTIC_IP_RE.findall(text)},
        "hashes": {_normalize_casefold(m) for m in _DETERMINISTIC_HASH_RE.findall(text)},
        "emails": {_normalize_casefold(m) for m in _DETERMINISTIC_EMAIL_RE.findall(text)},
    }


def has_new_deterministic_ioc_evidence(old_raw_text: str, new_raw_text: str) -> bool:
    """İki ham metin arasında (eski satırın raw_text'i vs yeni gelen item'ın
    raw_text'i) regex ile çıkarılabilen YENİ bir IP/hash/e-posta var mı?
    Madde 5/11'in "conditional re-analysis" tetikleyicilerinden biri -
    source repeat/title değişimi/aynı makalenin tekrar fetch edilmesi AYNI
    ham metni üretir, bu yüzden BOŞ küme farkı verir (tetiklemez)."""
    old_iocs = extract_deterministic_iocs(old_raw_text)
    new_iocs = extract_deterministic_iocs(new_raw_text)
    return any(new_iocs[k] - old_iocs[k] for k in new_iocs)


# ---------------------------------------------------------------------------
# 2026-09-15 (madde 4 - "analysis merge davranışını kontrol et"): bir haber
# koşullu olarak yeniden analiz edildiğinde (bkz. run_pipeline._analyze_
# relevant_news), YENİ LLM çıktısı ESKİ analysis'in ÜZERİNE tamamen
# YAZILMAZ.
# ---------------------------------------------------------------------------
_ANALYSIS_LIST_MERGE_FIELDS = (
    "process_names", "command_lines", "event_ids", "file_paths",
    "registry_paths", "registry_artifacts", "services", "scheduled_tasks",
    "mutexes", "user_agents", "affected_versions", "fixed_versions", "mitigation",
    "vendors", "products",
)
_ANALYSIS_IOC_MERGE_FIELDS = ("ips", "domains", "hashes", "urls", "emails")
_ANALYSIS_SCALAR_KEEP_IF_NEW_EMPTY_FIELDS = (
    "hunt_query", "splunk_applicability", "wazuh_applicability", "attack_vector",
    "impact", "exposure_check", "evidence_note",
)


def _dedup_preserve_originals(field: str, *value_lists: list) -> list:
    """Birden fazla listeyi, alana uygun normalize edilmiş anahtarla dedup
    ederek birleştirir - ama listeye SAKLANAN değer orijinal (normalize
    EDİLMEMİŞ) string'dir, sadece dedup KARARI normalize edilmiş temsille
    verilir (kullanıcıya gösterilecek metin bozulmasın diye)."""
    normalizer = _FIELD_NORMALIZERS.get(field, _normalize_casefold)
    seen: set[str] = set()
    combined: list = []
    for values in value_lists:
        for v in values or []:
            if not v:
                continue
            key = normalizer(v)
            if key and key not in seen:
                seen.add(key)
                combined.append(v)
    return combined


def merge_news_analysis(old_analysis: dict | None, new_analysis: dict) -> dict:
    """Bir haber koşullu re-analize edildiğinde ESKİ + YENİ `analysis`
    sözlüklerini KAYIPSIZ birleştirir:

    - Liste tipi, gruned edilmiş alanlar (IOC alt-alanları + hunt/forensic
      artifact'ler + affected/fixed version + mitigation): OLD ∪ NEW
      (alana uygun normalize edilmiş dedup ile) - yeni LLM çağrısı eski bir
      bulguyu atlarsa (non-determinism) bu SESSİZCE KAYBOLMAZ.
    - Skaler serbest-metin alanları (hunt_query, splunk/wazuh_applicability,
      attack_vector, impact, exposure_check, evidence_note): YENİ tercih
      edilir, ama YENİ boş/null dönerse ESKİSİ KORUNUR.
    - active_exploitation/exploit_status: SADECE YÜKSELEBİLİR (bkz.
      _EXPLOIT_STATUS_ORDER) - bir re-analiz daha önce doğrulanmış "aktif
      istismar var" bulgusunu asla geri ALAMAZ, LLM'e bir "downgrade"
      UYDURTULMAZ.
    - Diğer tüm skaler alanlar (summary, event_type, my_relevance, news_
      tier, soc_value_score vb.): YENİ analiz, DAHA FAZLA/güncel kanıtla
      üretildiği için tercih edilir (bkz. çağıran taraf - bu alanlar zaten
      `dict(new_analysis)` ile başlangıç değeri olarak YENİ'den gelir)."""
    old_analysis = old_analysis or {}
    merged = dict(new_analysis)

    for field in _ANALYSIS_LIST_MERGE_FIELDS:
        merged[field] = _dedup_preserve_originals(field, old_analysis.get(field), new_analysis.get(field))

    old_ioc = old_analysis.get("ioc") or {}
    new_ioc = new_analysis.get("ioc") or {}
    merged["ioc"] = {
        field: _dedup_preserve_originals(field, old_ioc.get(field), new_ioc.get(field))
        for field in _ANALYSIS_IOC_MERGE_FIELDS
    }

    for field in _ANALYSIS_SCALAR_KEEP_IF_NEW_EMPTY_FIELDS:
        if not merged.get(field) and old_analysis.get(field):
            merged[field] = old_analysis[field]

    merged["active_exploitation"] = bool(new_analysis.get("active_exploitation")) or bool(
        old_analysis.get("active_exploitation")
    )
    old_exploit_rank = _EXPLOIT_STATUS_ORDER.get(old_analysis.get("exploit_status"), 0)
    new_exploit_rank = _EXPLOIT_STATUS_ORDER.get(new_analysis.get("exploit_status"), 0)
    merged["exploit_status"] = (
        old_analysis.get("exploit_status") if old_exploit_rank > new_exploit_rank else new_analysis.get("exploit_status")
    )

    return merged
