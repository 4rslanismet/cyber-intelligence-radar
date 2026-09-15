"""Drive Queue V1 worker - kuyruğu okur, günlük bütçe dahilinde upload
eder, checkpoint'ler, çıkar (bkz. docs/GOOGLE_DRIVE.md, src/drive_queue.py
state/scan/priority mantığı için). `scripts/drive_queue.py run` bunu
çağırır; ayrıca `cyber-radar-drive-sync.timer` (03:30) tarafından
tetiklenir.

Retry sınıfları (proje notları madde 21):
  401           -> bir sonraki deneme headers'ı tazeler (gdrive._headers
                   zaten proaktif refresh yapıyor), hâlâ başarısızsa STOP.
  invalid_grant -> STOP + CRITICAL (worker durur, tek dosya değil TÜM
                   kuyruk bloke - bkz. AuthFailureError).
  429/403       -> Retry-After'a uyan, TAVANLI bounded backoff.
  5xx/network   -> bounded retry.
Tek bir kötü dosya (kalıcı hata, ör. 404) kuyruğun TAMAMINI bloke ETMEZ -
o item deferred/failed işaretlenir, worker sıradaki adaya geçer."""
from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from . import config, drive_queue, gdrive

STOP_QUEUE_EMPTY = "QUEUE_EMPTY"
STOP_DAILY_BUDGET_REACHED = "DAILY_BUDGET_REACHED"
STOP_DAILY_FILE_LIMIT_REACHED = "DAILY_FILE_LIMIT_REACHED"
STOP_MAX_RUNTIME_REACHED = "MAX_RUNTIME_REACHED"
STOP_AUTH_FAILURE = "AUTH_FAILURE"
STOP_STATE_CORRUPTION = "STATE_CORRUPTION"
STOP_NORMAL_COMPLETE = "NORMAL_COMPLETE"

_CHUNK_ALIGN_BYTES = 256 * 1024  # Google şartı: son parça HARİÇ 256 KiB katı


class AuthFailureError(Exception):
    """invalid_grant ya da kalıcı 401 - worker STOP etmeli (bkz. modül
    docstring'i)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_invalid_grant_error(exc: Exception) -> bool:
    """Token endpoint'inin KENDİSİNDEN gelen bir hata (bkz. canlıda görülen
    'oauth2.googleapis.com/token' 400/invalid_grant deseni) - bir dosyanın
    kendi hatası DEĞİL, sistem çapında bir auth sorunu, tek dosya retry'ı
    ile ÇÖZÜLEMEZ."""
    if isinstance(exc, httpx.HTTPStatusError):
        return "oauth2.googleapis.com/token" in str(exc.request.url)
    return False


def _retry_with_backoff(
    fn: Callable[[], Any], max_attempts: int = 3, base_backoff: float = 30.0, cap: float = 300.0
) -> Any:
    """429/403/5xx/network için sınırlı, Retry-After'a uyan backoff -
    UNBOUNDED sleep YOK (bkz. academic.py'deki AYNI ilke -
    _RETRY_AFTER_CAP_SECONDS). 401'de bir sonraki deneme headers'ı tazeler
    (gdrive._headers proaktif refresh yapar). invalid_grant'ta HEMEN
    AuthFailureError fırlatır - retry FAYDASIZ, bu dosyanın değil sistemin
    sorunu. Kalıcı bir 4xx (404 gibi, 401/403/429 DIŞINDA) HEMEN fırlatılır
    - retry etmek sonucu değiştirmez."""
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except httpx.HTTPStatusError as e:
            last_exc = e
            if _is_invalid_grant_error(e):
                raise AuthFailureError(str(e)) from e
            status = e.response.status_code
            if status == 401 and attempt < max_attempts - 1:
                continue
            if status not in (401, 429, 403) and status < 500:
                raise
            if attempt >= max_attempts - 1:
                raise
            retry_after = e.response.headers.get("Retry-After")
            try:
                wait_s = min(float(retry_after), cap) if retry_after else min(base_backoff * (attempt + 1), cap)
            except ValueError:
                wait_s = min(base_backoff * (attempt + 1), cap)
            time.sleep(wait_s)
        except httpx.HTTPError as e:
            last_exc = e
            if attempt >= max_attempts - 1:
                raise
            time.sleep(min(base_backoff * (attempt + 1), cap))
    raise last_exc or RuntimeError("_retry_with_backoff: beklenmeyen durum")  # pragma: no cover


def _local_md5_if_affordable(local_path: str, size: int) -> str | None:
    """GDRIVE_VERIFY_MD5_MAX_MB altındaki dosyalar için yerel MD5 hesaplar;
    üzerindeyse None döner (tüm dosyayı okumanın maliyeti config ile
    sınırlanır - bkz. src/config.py GDRIVE_VERIFY_MD5_MAX_MB yorumu).
    Boyut+trashed karşılaştırması zaten yapılıyor; bu SADECE ek bir katman."""
    if size > config.GDRIVE_VERIFY_MD5_MAX_MB * 1024 * 1024:
        return None
    h = hashlib.md5()  # noqa: S324 - bütünlük kontrolü, kriptografik amaç değil (Drive API'nin kendi alanı)
    with open(local_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _ensure_root_folder() -> str:
    if config.GDRIVE_ROOT_FOLDER_ID:
        return config.GDRIVE_ROOT_FOLDER_ID
    return gdrive.ensure_folder(config.GDRIVE_ROOT_FOLDER_NAME)


def _upload_small_file(item: dict[str, Any], folder_id: str) -> str:
    return _retry_with_backoff(
        lambda: gdrive.upload_or_update(item["local_path"], folder_id, item["drive_name"])
    )


def _align_chunk_size(desired: int, remaining_total: int) -> int:
    """Son parça HARİÇ 256 KiB'nin katı olmalı (Google şartı, bkz.
    gdrive.upload_chunk docstring'i)."""
    if desired >= remaining_total:
        return remaining_total  # son parça - hizalama gerekmez
    aligned = (desired // _CHUNK_ALIGN_BYTES) * _CHUNK_ALIGN_BYTES
    return aligned or _CHUNK_ALIGN_BYTES


def _upload_large_file(state: dict[str, Any], item: dict[str, Any], folder_id: str) -> str | None:
    """Resumable, chunked upload - günlük bayt bütçesi bitince YARIDA
    KESİLİR (None döner, item deferred kalır) - ertesi worker çalıştırması
    query_resumable_status ile KALDIĞI YERDEN (remote'un dediği yerden,
    local confirmed_offset'e kör güvenmeden) devam eder."""
    total_size = item["size"]
    chunk_size = int(config.GDRIVE_UPLOAD_CHUNK_MB * 1024 * 1024)
    session_uri = item.get("upload_session_uri")
    confirmed_offset = 0

    if session_uri:
        try:
            status = _retry_with_backoff(lambda: gdrive.query_resumable_status(session_uri, total_size))
        except gdrive.SessionExpiredError:
            session_uri = None
        else:
            if status["complete"]:
                return status["file"]["id"]
            confirmed_offset = status["confirmed_offset"]

    if not session_uri:
        session_uri = _retry_with_backoff(
            lambda: gdrive.start_resumable_upload(
                item["local_path"], folder_id, item["drive_name"], existing_file_id=item.get("remote_file_id")
            )
        )
        item["upload_session_uri"] = session_uri
        item["session_created_at"] = _now_iso()
        confirmed_offset = 0

    with open(item["local_path"], "rb") as f:
        f.seek(confirmed_offset)
        while confirmed_offset < total_size:
            if drive_queue.remaining_byte_budget(state) <= 0:
                item["confirmed_offset"] = confirmed_offset
                item["updated_at"] = _now_iso()
                return None  # DAILY_BUDGET_REACHED - normal bir durum, hata DEĞİL

            this_chunk_size = _align_chunk_size(
                min(chunk_size, total_size - confirmed_offset), total_size - confirmed_offset
            )
            data = f.read(this_chunk_size)
            offset_at_start = confirmed_offset

            try:
                result = _retry_with_backoff(
                    lambda: gdrive.upload_chunk(session_uri, data, offset_at_start, total_size)
                )
            except gdrive.SessionExpiredError:
                session_uri = _retry_with_backoff(
                    lambda: gdrive.start_resumable_upload(
                        item["local_path"], folder_id, item["drive_name"],
                        existing_file_id=item.get("remote_file_id"),
                    )
                )
                item["upload_session_uri"] = session_uri
                item["session_created_at"] = _now_iso()
                status = _retry_with_backoff(lambda: gdrive.query_resumable_status(session_uri, total_size))
                confirmed_offset = 0 if status["complete"] else status["confirmed_offset"]
                f.seek(confirmed_offset)
                continue

            state["bytes_uploaded_today"] = state.get("bytes_uploaded_today", 0) + len(data)
            if result["complete"]:
                return result["file"]["id"]
            confirmed_offset = result["confirmed_offset"]
            item["confirmed_offset"] = confirmed_offset
            item["updated_at"] = _now_iso()
            drive_queue.save_state(state)  # her chunk sonrası atomic checkpoint - restart güvenli

    return None  # pragma: no cover - döngü normalde return ile çıkar


def upload_one(state: dict[str, Any], item: dict[str, Any], root_id: str) -> dict[str, Any]:
    """Tek bir item'ı işler: küçük/büyük dispatch -> upload -> Drive'dan
    TAZE metadata ile doğrulama (upload response'una GÜVENİLMEZ - bkz.
    proje notları "Verification"). Döner: {"verified": bool,
    "bytes_confirmed": int}."""
    threshold_bytes = int(config.GDRIVE_RESUMABLE_THRESHOLD_MB * 1024 * 1024)
    item["status"] = drive_queue.STATUS_UPLOADING
    item["updated_at"] = _now_iso()

    if item["size"] <= threshold_bytes and item["size"] > drive_queue.remaining_byte_budget(state):
        item["status"] = drive_queue.STATUS_DEFERRED
        item["updated_at"] = _now_iso()
        return {"verified": False, "bytes_confirmed": 0}

    folder_id = _retry_with_backoff(lambda: gdrive.ensure_folder(item["remote_folder"], root_id))

    if item["size"] <= threshold_bytes:
        file_id = _upload_small_file(item, folder_id)
        state["bytes_uploaded_today"] = state.get("bytes_uploaded_today", 0) + item["size"]
    else:
        file_id = _upload_large_file(state, item, folder_id)
        if file_id is None:
            item["status"] = drive_queue.STATUS_DEFERRED
            item["updated_at"] = _now_iso()
            return {"verified": False, "bytes_confirmed": 0}

    item["remote_file_id"] = file_id
    remote = _retry_with_backoff(lambda: gdrive.get_file_metadata(file_id))
    verified = (
        remote.get("size") is not None
        and int(remote["size"]) == item["size"]
        and not remote.get("trashed", False)
    )
    if verified and remote.get("md5Checksum"):
        local_md5 = _local_md5_if_affordable(item["local_path"], item["size"])
        if local_md5 is not None:
            verified = remote["md5Checksum"] == local_md5

    if not verified:
        item["status"] = drive_queue.STATUS_DEFERRED
        item["last_error"] = f"remote verification failed: {remote}"
        item["updated_at"] = _now_iso()
        return {"verified": False, "bytes_confirmed": 0}

    item["status"] = drive_queue.STATUS_VERIFIED
    item["verified_at"] = _now_iso()
    item["updated_at"] = item["verified_at"]
    item["attempts"] = 0
    item["last_error"] = None
    return {"verified": True, "bytes_confirmed": item["size"]}


def run_worker(max_runtime_minutes: float | None = None) -> dict[str, Any]:
    """Ana worker döngüsü - bir seferlik çalışıp çıkar (bkz.
    cyber-radar-drive-sync.timer, sürekli değil). Döner: structured log
    dict (bkz. proje notları madde 29)."""
    start_time = time.monotonic()
    if max_runtime_minutes is None:
        max_runtime_minutes = config.GDRIVE_WORKER_MAX_RUNTIME_MINUTES

    bytes_confirmed = 0
    files_verified = 0
    files_deferred = 0
    files_failed = 0
    stop_reason = STOP_NORMAL_COMPLETE

    try:
        state = drive_queue.load_state()
    except drive_queue.StateCorruptionError:
        return _result(STOP_STATE_CORRUPTION, 0, 0, 0, 0, time.monotonic() - start_time, 0, 0)

    drive_queue.scan_allowed_roots(state)

    if not gdrive.is_configured():
        drive_queue.save_state(state)
        return _result(
            STOP_AUTH_FAILURE, 0, 0, 0, 0, time.monotonic() - start_time,
            drive_queue.remaining_byte_budget(state), drive_queue.remaining_file_budget(state),
        )

    root_id: str | None = None
    try:
        while True:
            if (time.monotonic() - start_time) / 60 >= max_runtime_minutes:
                stop_reason = STOP_MAX_RUNTIME_REACHED
                break
            if drive_queue.remaining_byte_budget(state) <= 0:
                stop_reason = STOP_DAILY_BUDGET_REACHED
                break
            if drive_queue.remaining_file_budget(state) <= 0:
                stop_reason = STOP_DAILY_FILE_LIMIT_REACHED
                break

            candidates = drive_queue.next_upload_candidates(state, limit=1)
            if not candidates:
                stop_reason = STOP_QUEUE_EMPTY
                break
            item = candidates[0]

            if not drive_queue.revalidate_local_file(item):
                drive_queue.save_state(state)
                continue

            if root_id is None:
                try:
                    root_id = _retry_with_backoff(_ensure_root_folder)
                except AuthFailureError:
                    stop_reason = STOP_AUTH_FAILURE
                    break

            try:
                result = upload_one(state, item, root_id)
            except AuthFailureError:
                stop_reason = STOP_AUTH_FAILURE
                drive_queue.save_state(state)
                break
            except Exception as e:  # noqa: BLE001 - TEK dosya kuyruğun tamamını bloke ETMEMELİ
                item["attempts"] = item.get("attempts", 0) + 1
                item["last_error"] = str(e)
                item["updated_at"] = _now_iso()
                if item["attempts"] >= config.GDRIVE_MAX_RETRIES_PER_FILE:
                    item["status"] = drive_queue.STATUS_FAILED
                    files_failed += 1
                else:
                    item["status"] = drive_queue.STATUS_DEFERRED
                    files_deferred += 1
                drive_queue.save_state(state)
                continue

            if result["verified"]:
                bytes_confirmed += result["bytes_confirmed"]
                files_verified += 1
                state["files_completed_today"] = state.get("files_completed_today", 0) + 1
            else:
                files_deferred += 1
            drive_queue.save_state(state)
    finally:
        drive_queue.save_state(state)

    return _result(
        stop_reason, bytes_confirmed, files_verified, files_deferred, files_failed,
        time.monotonic() - start_time,
        drive_queue.remaining_byte_budget(state), drive_queue.remaining_file_budget(state),
    )


def _result(stop_reason, bytes_confirmed, files_verified, files_deferred, files_failed,
            runtime_seconds, budget_remaining_bytes, budget_remaining_files) -> dict[str, Any]:
    return {
        "stop_reason": stop_reason,
        "bytes_confirmed": bytes_confirmed,
        "files_verified": files_verified,
        "files_deferred": files_deferred,
        "files_failed": files_failed,
        "runtime_seconds": runtime_seconds,
        "budget_remaining_bytes": budget_remaining_bytes,
        "budget_remaining_files": budget_remaining_files,
    }
