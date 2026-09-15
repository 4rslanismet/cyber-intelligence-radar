"""NotebookLM export katmanı.

Tasarım kararı: NotebookLM'in genel kullanıcıya açık bir API'si yok (sadece
Enterprise/preview düzeyinde). Bu yüzden pipeline NotebookLM'e otomatik
YÜKLEME yapmaz - bunun yerine NotebookLM'e MANUEL sürükle-bırakla
yükleyeceğiniz, düzenli, konu bazlı dosyalar üretir.

Neden "1 makale = 1 dosya" değil de "1 konu + 1 ay = 1 dosya"?
NotebookLM'in ücretsiz planında notebook başına ~50 kaynak sınırı var (bkz.
README). Her makaleyi ayrı dosya yaparsanız bu limiti haftalar içinde
doldurursunuz. Bunun yerine her konu kendi NotebookLM notebook'unuz olur, her
ay o konudaki tüm makaleler TEK bir markdown dosyasında birikir - yılda 12
kaynak/konu, limitin çok altında kalırsınız.

Değeri yüksek makalelerin (novelty_score + academic_value_score toplamı
eşik üstü) PDF'i varsa, aynı periyot/konu klasörüne ayrıca kopyalanır -
isterseniz onu da ayrı bir kaynak olarak notebook'a eklersiniz (tam metin
grounding için), gerekmiyorsa sadece markdown özeti yeterli olur.

Periyotlama: disk alanı sınırlı olduğu için dosyalar AY değil,
config.NOTEBOOKLM_PERIOD_DAYS (varsayılan 2) günlük sabit pencerelerle
gruplanır - örn. "2026-09-05_2026-09-06". Bir pencere kapandığında
(retention.py bunu algılar) dosya Google Drive'a yüklenip sunucudan silinir;
kapanmış bir pencereye bir daha asla yazılmaz, bu yüzden "sil sonra tekrar
yaz" çakışması hiç oluşmaz.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import date, timedelta
from typing import Any

from . import config

# Periyot sınırlarının zamanla kaymaması için sabit bir çapa tarihi kullanılıyor.
_PERIOD_EPOCH = date(2026, 1, 1)


def classify_topic(primary_domain: str | None, secondary_domains: list[str] | None = None) -> str:
    """Relevance/analiz agent'ının döndürdüğü primary_domain metnini
    config.NOTEBOOKLM_TOPICS içindeki konulardan birine eşler. Eşleşme yoksa
    'General_Cybersecurity' konusuna düşer - hiçbir makale export dışı kalmaz."""
    haystack = " ".join(filter(None, [primary_domain] + (secondary_domains or []))).lower()
    for topic, keywords in config.NOTEBOOKLM_TOPICS.items():
        if any(kw in haystack for kw in keywords):
            return topic
    return "General_Cybersecurity"


def current_period() -> str:
    """Bugünün ait olduğu periyot etiketini döner (ör. '2026-09-06_2026-09-07').
    run_pipeline.py'ın notebooklm_export_log tablosuna yazarken kullanması
    için - _period_str()'ün altını çizmeye gerek kalmasın diye public."""
    return _period_str()


def _period_bounds(d: date | None = None) -> tuple[date, date]:
    d = d or date.today()
    span = max(1, config.NOTEBOOKLM_PERIOD_DAYS)
    bucket_index = (d - _PERIOD_EPOCH).days // span
    start = _PERIOD_EPOCH + timedelta(days=bucket_index * span)
    end = start + timedelta(days=span - 1)
    return start, end


def _period_str(d: date | None = None) -> str:
    start, end = _period_bounds(d)
    return f"{start.isoformat()}_{end.isoformat()}"


def period_end_date(period: str) -> date | None:
    """'2026-09-05_2026-09-06' -> date(2026, 9, 6). Tanınmayan formatta None
    döner (retention.py bu durumda dosyaya dokunmaz - güvenli taraf)."""
    try:
        _, end_str = period.split("_", 1)
        return date.fromisoformat(end_str)
    except (ValueError, AttributeError):
        return None


def _topic_dir(topic: str) -> str:
    path = os.path.join(config.NOTEBOOKLM_DIR, topic)
    os.makedirs(path, exist_ok=True)
    return path


def _batch_md_path(topic: str, period: str) -> str:
    return os.path.join(_topic_dir(topic), f"{period}.md")


def _paper_already_in_file(file_path: str, doi: str | None, arxiv_id: str | None, title: str) -> bool:
    if not os.path.exists(file_path):
        return False
    marker = doi or arxiv_id or title
    if not marker:
        return False
    with open(file_path, "r", encoding="utf-8") as f:
        return marker in f.read()


def _format_paper_entry(paper: dict[str, Any]) -> str:
    analysis = paper.get("analysis") or {}
    authors = ", ".join(paper.get("authors") or []) or "—"
    lines = [
        f"## {paper.get('title', '(başlıksız)')}",
        "",
        f"- **Yazarlar:** {authors}",
        f"- **Yayın/Venue:** {paper.get('venue') or '—'}",
        f"- **Tarih:** {paper.get('publication_date') or '—'}",
        f"- **DOI:** {paper.get('doi') or '—'}",
        f"- **arXiv:** {paper.get('arxiv_id') or '—'}",
        f"- **Analiz türü:** {paper.get('analysis_type', 'ABSTRACT_ONLY')}",
        f"- **PDF:** {paper.get('pdf_url') or '—'}",
        "",
        f"**Özet:** {paper.get('abstract') or '—'}",
        "",
    ]
    if analysis:
        if analysis.get("research_problem"):
            lines.append(f"**Araştırma problemi:** {analysis['research_problem']}")
        if analysis.get("methodology"):
            lines.append(f"**Yöntem:** {analysis['methodology']}")
        if analysis.get("datasets"):
            lines.append(f"**Dataset'ler:** {', '.join(analysis['datasets'])}")
        if analysis.get("key_results"):
            lines.append("**Sonuçlar:**")
            lines.extend(f"- {r}" for r in analysis["key_results"])
        if analysis.get("limitations"):
            lines.append("**Limitasyonlar:**")
            lines.extend(f"- {l}" for l in analysis["limitations"])
        if analysis.get("research_gap"):
            lines.append("**Research gap:**")
            lines.extend(f"- {g}" for g in analysis["research_gap"])
        if analysis.get("potential_research_ideas"):
            lines.append("**Potansiyel araştırma fikirleri:**")
            lines.extend(f"- {i}" for i in analysis["potential_research_ideas"])
        if analysis.get("code_repository"):
            lines.append(f"**Kod:** {analysis['code_repository']}")
        scores = []
        if analysis.get("novelty_score") is not None:
            scores.append(f"novelty={analysis['novelty_score']}")
        if analysis.get("academic_value_score") is not None:
            scores.append(f"academic_value={analysis['academic_value_score']}")
        if scores:
            lines.append(f"**Skorlar:** {', '.join(scores)}")
    lines.append("\n---\n")
    return "\n".join(lines)


def _record_manifest(paper: dict[str, Any], topic: str, period: str) -> None:
    """Export edilen her makaleyi kalıcı, hiç silinmeyen bir 'toplananlar
    listesi'ne (data/notebooklm/_index/collected_papers.json) ekler. PDF
    içeriği YOK - sadece başlık/DOI/arXiv/abstract/konu/periyot. Bu dosya
    her koşuda Drive'a senkron edilir (retention.py) ve aynı makalenin
    tekrar tekrar toplanıp analiz edilmediğini görünür kılan bir denetim
    izi olarak kalır (asıl dedup her zaman DB'de: papers.doi/arxiv_id/
    normalized_title UNIQUE kısıtları ve analyzed_at IS NULL filtresi)."""
    os.makedirs(config.NOTEBOOKLM_INDEX_DIR, exist_ok=True)
    entries: list[dict[str, Any]] = []
    if os.path.exists(config.NOTEBOOKLM_MANIFEST_FILE):
        try:
            with open(config.NOTEBOOKLM_MANIFEST_FILE, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except (json.JSONDecodeError, OSError):
            entries = []

    entries.append(
        {
            "title": paper.get("title"),
            "doi": paper.get("doi"),
            "arxiv_id": paper.get("arxiv_id"),
            "abstract": paper.get("abstract"),
            "topic": topic,
            "period": period,
            "exported_at": date.today().isoformat(),
        }
    )
    with open(config.NOTEBOOKLM_MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def export_paper(paper: dict[str, Any]) -> tuple[str, str] | None:
    """Tek bir analiz edilmiş makaleyi ilgili konu/periyot dosyasına ekler.
    Zaten eklenmişse (DOI/arXiv ID/başlık dosyada varsa) tekrar eklemez.
    Döner: (topic, file_path) ya da zaten varsa/uygun değilse None."""
    analysis = paper.get("analysis") or {}
    topic = classify_topic(
        (paper.get("relevance") or {}).get("primary_domain"),
        (paper.get("relevance") or {}).get("secondary_domains"),
    )
    period = _period_str()
    file_path = _batch_md_path(topic, period)

    if _paper_already_in_file(file_path, paper.get("doi"), paper.get("arxiv_id"), paper.get("title", "")):
        return None

    is_new_file = not os.path.exists(file_path)
    with open(file_path, "a", encoding="utf-8") as f:
        if is_new_file:
            f.write(f"# {topic.replace('_', ' ')} — {period}\n\n")
            f.write(
                "Bu dosya Cyber Intelligence Radar tarafından otomatik üretildi. "
                "NotebookLM'de bu konuya ait notebook'a kaynak olarak yükleyin.\n\n---\n\n"
            )
        f.write(_format_paper_entry(paper))

    value_score = (analysis.get("novelty_score") or 0) + (analysis.get("academic_value_score") or 0)
    pdf_local = paper.get("pdf_local_path")
    if pdf_local and os.path.exists(pdf_local) and value_score >= config.NOTEBOOKLM_PDF_VALUE_THRESHOLD:
        pdf_dir = os.path.join(_topic_dir(topic), f"{period}_pdfs")
        os.makedirs(pdf_dir, exist_ok=True)
        dest = os.path.join(pdf_dir, os.path.basename(pdf_local))
        if not os.path.exists(dest):
            shutil.copy2(pdf_local, dest)

    _record_manifest(paper, topic, period)
    return topic, file_path


def export_papers(papers: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Birden fazla makaleyi export eder. Döner: {topic: [file_path, ...]}
    (run_pipeline.py bunu notebooklm_export_log'a yazmak ve digest'te
    'şu dosyaları güncelledik' demek için kullanır)."""
    updated: dict[str, list[str]] = {}
    for paper in papers:
        result = export_paper(paper)
        if result:
            topic, file_path = result
            updated.setdefault(topic, [])
            if file_path not in updated[topic]:
                updated[topic].append(file_path)
    return updated
