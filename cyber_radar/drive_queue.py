"""Persistent Google Drive upload queue - state/scan/priority logic (bkz.
docs/GOOGLE_DRIVE.md "Drive Queue V1"). Gerçek upload/verify/retention
mantığı src/drive_worker.py'de - bu modül SADECE state yönetimi, ki
saf/testable kalsın.

Tasarım ilkeleri (proje notları):
- Atomic write (tmp -> flush -> fsync -> os.replace, + dizin fsync
  best-effort) - yarıda kesilen bir yazma state dosyasını ASLA bozmaz.
- Corrupt state -> STOP, sessizce boş kuyruk üretip ÜZERİNE YAZMAZ (bkz.
  StateCorruptionError - çağıran taraf bunu CRITICAL olarak ele almalı).
- Stable item identity: resolved local_path + size + mtime_ns - aynı
  dosya değişmeden tekrar scan edilirse idempotent; dosya değişirse
  (size/mtime farklı) yeni bir id/versiyon.
- Exfiltration guard: SADECE config.GDRIVE_ALLOWED_ROOTS_ABS altındaki,
  symlink OLMAYAN dosyalar enqueue edilebilir.
- Retention güvenliği: SADECE status=verified + retention süresi geçmiş
  dosyalar silinebilir (bkz. is_verified_and_retention_eligible).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date, datetime, timezone
from typing import Any

from . import config

STATE_VERSION = 1

STATUS_QUEUED = "queued"
STATUS_UPLOADING = "uploading"
STATUS_DEFERRED = "deferred"
STATUS_VERIFIED = "verified"
STATUS_FAILED = "failed"
STATUS_STALE_LOCAL_VERSION = "stale_local_version"

# Öncelik: düşük sayı = yüksek öncelik (bkz. proje notları).
PRIORITY_FINAL_RECOVERY_REPORTS = 10
PRIORITY_DB_BACKUPS = 20
PRIORITY_NOTEBOOKLM = 30
PRIORITY_RESEARCH_ARTIFACTS = 40
PRIORITY_NORMAL_REPORTS = 50
PRIORITY_ACADEMIC_PDF = 60
PRIORITY_DEFAULT = 70


class StateCorruptionError(Exception):
    """State dosyası VAR ama okunamadı/parse edilemedi/beklenen şemada
    değil - worker BURADA DURMALI (bkz. scripts/drive_queue.py: CRITICAL
    log + Telegram uyarısı), boş bir state ÜRETİP ÜZERİNE YAZMAZ (mevcut
    kuyruk kaybolur)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_str() -> str:
    return date.today().isoformat()


def empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "budget_date": _today_str(),
        "bytes_uploaded_today": 0,
        "files_completed_today": 0,
        "items": [],
    }


def load_state(path: str | None = None) -> dict[str, Any]:
    """Dosya yoksa (ilk çalıştırma) boş state döner - bu CORRUPTION
    değildir. Dosya VARSA ama parse edilemiyorsa/şeması bozuksa
    StateCorruptionError fırlatır."""
    path = path or config.GDRIVE_QUEUE_STATE_FILE_ABS
    if not os.path.exists(path):
        return empty_state()
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise StateCorruptionError(f"{path} okunamadı/parse edilemedi: {e}") from e
    if not isinstance(state, dict) or "items" not in state or "version" not in state:
        raise StateCorruptionError(f"{path} beklenen şemada değil (items/version eksik)")
    return _roll_budget_if_new_day(state)


def _roll_budget_if_new_day(state: dict[str, Any]) -> dict[str, Any]:
    """Gün değişince YALNIZ günlük sayaçları resetler - queue/items
    KORUNUR (bkz. proje notları madde 14 "Budget accounting")."""
    today = _today_str()
    if state.get("budget_date") != today:
        state["budget_date"] = today
        state["bytes_uploaded_today"] = 0
        state["files_completed_today"] = 0
    return state


def save_state(state: dict[str, Any], path: str | None = None) -> None:
    """Atomic write: tmp -> flush -> fsync -> os.replace (+ dizin fsync
    best-effort). Yarıda kesilen bir yazma state'i BOZMAZ."""
    path = path or config.GDRIVE_QUEUE_STATE_FILE_ABS
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".gdrive_upload_state.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass  # dizin fsync'i her dosya sisteminde/izin modelinde desteklenmeyebilir
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def compute_item_id(local_path: str, size: int, mtime_ns: int) -> str:
    """Stable identity - resolved path + size + mtime_ns. Aynı dosya
    değişmeden tekrar scan edilirse AYNI id (idempotent enqueue); dosya
    değişirse YENİ id (yeni versiyon kabul edilir)."""
    resolved = os.path.realpath(local_path)
    digest = hashlib.sha256(f"{resolved}|{size}|{mtime_ns}".encode("utf-8")).hexdigest()
    return digest[:24]


def priority_for_path(abs_path: str) -> int:
    normalized = abs_path.replace(os.sep, "/")
    if "/data/reports/recovery/" in normalized:
        return PRIORITY_FINAL_RECOVERY_REPORTS
    if "/data/db_backups/" in normalized:
        return PRIORITY_DB_BACKUPS
    if "/data/notebooklm/" in normalized:
        return PRIORITY_NOTEBOOKLM
    if "/data/research/" in normalized:
        return PRIORITY_RESEARCH_ARTIFACTS
    if "/data/reports/" in normalized:
        return PRIORITY_NORMAL_REPORTS
    if "/data/academic/pdf/" in normalized:
        return PRIORITY_ACADEMIC_PDF
    return PRIORITY_DEFAULT


def remote_folder_for_path(abs_path: str) -> str:
    """Drive'daki hedef alt klasör adı (bkz. docs/GOOGLE_DRIVE.md klasör
    yapısı)."""
    normalized = abs_path.replace(os.sep, "/")
    if "/data/reports/recovery/" in normalized:
        return "recovery"
    if "/data/db_backups/" in normalized:
        return "db_backups"
    if "/data/notebooklm/" in normalized:
        return "notebooklm"
    if "/data/research/" in normalized:
        return "research"
    if "/data/reports/" in normalized:
        return "reports"
    if "/data/academic/pdf/" in normalized:
        return "papers"
    return "misc"


def is_path_allowed(path: str) -> bool:
    """Exfiltration guard: SADECE config.GDRIVE_ALLOWED_ROOTS_ABS altındaki
    dosyalar, symlink'ler VARSAYILAN OLARAK reddedilir."""
    if os.path.islink(path):
        return False
    try:
        resolved = os.path.realpath(path)
    except OSError:
        return False
    for root in config.GDRIVE_ALLOWED_ROOTS_ABS:
        root_resolved = os.path.realpath(root)
        if resolved == root_resolved or resolved.startswith(root_resolved + os.sep):
            return True
    return False


def enqueue(state: dict[str, Any], local_path: str) -> dict[str, Any] | None:
    """Bir dosyayı kuyruğa ekler - idempotent (aynı path+size+mtime_ns
    zaten kuyruktaysa mevcut item AYNEN döner, yeni satır eklenmez).
    Allowed-roots dışında, symlink, ya da mevcut olmayan bir dosya için
    None döner (sessizce reddedilir - çağıran taraf isterse loglar)."""
    if not is_path_allowed(local_path) or not os.path.isfile(local_path):
        return None
    stat = os.stat(local_path)
    item_id = compute_item_id(local_path, stat.st_size, stat.st_mtime_ns)

    existing = find_item(state, item_id)
    if existing:
        return existing

    abs_path = os.path.realpath(local_path)
    now = _now_iso()
    item = {
        "id": item_id,
        "local_path": local_path,
        "remote_folder": remote_folder_for_path(abs_path),
        "drive_name": os.path.basename(local_path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "priority": priority_for_path(abs_path),
        "status": STATUS_QUEUED,
        "remote_file_id": None,
        "upload_session_uri": None,
        "session_created_at": None,
        "confirmed_offset": 0,
        "attempts": 0,
        "last_error": None,
        "created_at": now,
        "updated_at": now,
        "verified_at": None,
    }
    state["items"].append(item)
    return item


def scan_roots(state: dict[str, Any], roots: list[str]) -> int:
    """Verilen kök dizinleri (ALLOWED_ROOTS'un tamamı ya da bir alt kümesi)
    tarayıp yeni dosyaları enqueue eder. Döner: yeni eklenen item sayısı -
    zaten kuyrukta olan (aynı id) dosyalar tekrar eklenmez. Bir alt küme
    verilmesinin sebebi: bazı kökler (ör. notebooklm) "sadece kapanmış
    periyot" gibi ek iş kuralına tabi ve blind bir dizin taramasıyla
    ENQUEUE EDİLMEMELİ - bkz. src/retention.py _enqueue_notebooklm."""
    added = 0
    existing_ids = {item["id"] for item in state["items"]}
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
            for name in filenames:
                full_path = os.path.join(dirpath, name)
                if os.path.islink(full_path):
                    continue
                item = enqueue(state, full_path)
                if item and item["id"] not in existing_ids:
                    added += 1
                    existing_ids.add(item["id"])
    return added


def scan_allowed_roots(state: dict[str, Any]) -> int:
    """GDRIVE_BLIND_SCAN_ROOTS_ABS'ı (notebooklm HARİÇ tüm allowed-roots)
    tarar - src/drive_worker.py worker başlangıcında "defensive scan"
    olarak çağırır. notebooklm kasıtlı olarak DIŞARIDA: "sadece kapanmış
    periyot" iş kuralı var, blind bir dizin taraması bunu ihlal eder -
    notebooklm dosyaları kuyruğa YALNIZCA src/retention.py'nin kapalı-
    periyot kapısından geçen açık enqueue() çağrısıyla girer (bkz.
    _enqueue_notebooklm). notebooklm yine de config.GDRIVE_ALLOWED_ROOTS_ABS'ta
    kalır ki is_path_allowed() exfiltration guard'ı o dosyalar için de
    çalışsın."""
    return scan_roots(state, config.GDRIVE_BLIND_SCAN_ROOTS_ABS)


def find_item(state: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for item in state["items"]:
        if item["id"] == item_id:
            return item
    return None


def revalidate_local_file(item: dict[str, Any]) -> bool:
    """Upload başlamadan/resumable devam etmeden ÖNCE dosyanın hâlâ aynı
    olduğunu doğrular ("local file mutation" güvenliği). Değişmişse/
    silinmişse item'ı stale_local_version yapar ve False döner - eski
    upload session'dan DEVAM EDİLMEZ, yeni bir versiyon queue'ya
    eklenebilir (scan_allowed_roots ile, farklı id üretir)."""
    path = item["local_path"]
    if not os.path.isfile(path):
        item["status"] = STATUS_STALE_LOCAL_VERSION
        item["last_error"] = "local file no longer exists"
        item["updated_at"] = _now_iso()
        return False
    stat = os.stat(path)
    if stat.st_size != item["size"] or stat.st_mtime_ns != item["mtime_ns"]:
        item["status"] = STATUS_STALE_LOCAL_VERSION
        item["last_error"] = "local file changed since queued (size/mtime mismatch)"
        item["updated_at"] = _now_iso()
        return False
    return True


def next_upload_candidates(state: dict[str, Any], limit: int | None = None) -> list[dict[str, Any]]:
    """queued/deferred item'ları öncelik (küçük sayı = yüksek), sonra
    created_at (adil sıralama - starvation'ı azaltır) ile sıralar."""
    candidates = [i for i in state["items"] if i["status"] in (STATUS_QUEUED, STATUS_DEFERRED)]
    candidates.sort(key=lambda i: (i["priority"], i["created_at"]))
    return candidates[:limit] if limit else candidates


def pending_summary(state: dict[str, Any]) -> dict[str, Any]:
    pending = [i for i in state["items"] if i["status"] in (STATUS_QUEUED, STATUS_DEFERRED)]
    return {
        "pending_files": len(pending),
        "pending_bytes": sum(i["size"] for i in pending),
        "verified": sum(1 for i in state["items"] if i["status"] == STATUS_VERIFIED),
        "deferred": sum(1 for i in state["items"] if i["status"] == STATUS_DEFERRED),
        "failed": sum(1 for i in state["items"] if i["status"] == STATUS_FAILED),
        "stale": sum(1 for i in state["items"] if i["status"] == STATUS_STALE_LOCAL_VERSION),
    }


def is_verified_and_retention_eligible(item: dict[str, Any], retention_days: int) -> bool:
    """Retention güvenliği: SADECE status=verified VE retention süresi
    geçmiş dosyalar silinebilir. queued/uploading/deferred/failed/
    stale_local_version HİÇBİR ZAMAN silinmez (bkz. docs/DECISIONS.md
    "Drive sync failure never triggers local cleanup" - AYNI ilke,
    queue'ya taşınmış hali)."""
    if item["status"] != STATUS_VERIFIED or not item.get("verified_at"):
        return False
    verified_at = datetime.fromisoformat(item["verified_at"])
    age_days = (datetime.now(timezone.utc) - verified_at).days
    return age_days >= retention_days


def purge_retained_files(
    state: dict[str, Any],
    retention_days_by_folder: dict[str, int],
    default_days: int,
    never_delete_paths: set[str] | None = None,
) -> list[str]:
    """Retention güvenliği ile YEREL dosya siler: SADECE
    is_verified_and_retention_eligible() True olan item'lar (bkz. o
    fonksiyonun docstring'i - queued/uploading/deferred/failed/
    stale_local_version HİÇBİR ZAMAN silinmez). `retention_days_by_folder`
    remote_folder adına göre (ör. "db_backups", "papers") farklı bekleme
    süresi uygulamak için - eşleşmeyen kategoriler `default_days` kullanır
    (bkz. docs/GOOGLE_DRIVE.md kategori bazlı retention tablosu).
    `never_delete_paths` - ör. NotebookLM manifest'i gibi "her zaman senkron
    ama ASLA silinmez" dosyalar için (resolved path ile karşılaştırılır)."""
    never_delete_resolved = {os.path.realpath(p) for p in (never_delete_paths or set())}
    logs: list[str] = []
    for item in state["items"]:
        if os.path.realpath(item["local_path"]) in never_delete_resolved:
            continue
        days = retention_days_by_folder.get(item["remote_folder"], default_days)
        if not is_verified_and_retention_eligible(item, days):
            continue
        path = item["local_path"]
        if os.path.isfile(path):
            try:
                os.remove(path)
                logs.append(f"🗑️ {path} sunucudan silindi (Drive'da doğrulanmış kopyası var).")
            except OSError as e:
                logs.append(f"⚠️ {path} silinemedi: {e}")
    return logs


def remaining_byte_budget(state: dict[str, Any]) -> int:
    budget_bytes = int(config.GDRIVE_DAILY_UPLOAD_BUDGET_GB * 1024 * 1024 * 1024)
    return max(0, budget_bytes - state.get("bytes_uploaded_today", 0))


def remaining_file_budget(state: dict[str, Any]) -> int:
    return max(0, config.GDRIVE_DAILY_FILE_LIMIT - state.get("files_completed_today", 0))
