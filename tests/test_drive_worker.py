"""Drive Queue V1 worker (bkz. src/drive_worker.py) - upload dispatch,
retry sınıflandırma, bütçe/runtime durdurma koşulları, doğrulama. Gerçek
Drive API çağrısı YOK - src.gdrive fonksiyonları monkeypatch'lenir."""
from __future__ import annotations

import os
import time
from unittest.mock import patch

import httpx
import pytest

from cyber_radar import config, drive_queue, drive_worker


def _http_error(status_code, url="https://www.googleapis.com/drive/v3/files", headers=None):
    request = httpx.Request("GET", url)
    response = httpx.Response(status_code=status_code, headers=headers or {}, request=request)
    return httpx.HTTPStatusError(f"{status_code} error", request=request, response=response)


def _invalid_grant_error():
    request = httpx.Request("POST", "https://oauth2.googleapis.com/token")
    response = httpx.Response(status_code=400, request=request)
    return httpx.HTTPStatusError("400 invalid_grant", request=request, response=response)


@pytest.fixture
def allowed_root(tmp_path):
    root = tmp_path / "data" / "reports"
    root.mkdir(parents=True)
    with (
        patch.object(config, "GDRIVE_ALLOWED_ROOTS_ABS", [str(root)]),
        patch.object(config, "GDRIVE_BLIND_SCAN_ROOTS_ABS", [str(root)]),
    ):
        yield root


@pytest.fixture
def state_path(tmp_path):
    path = str(tmp_path / "state" / "gdrive_upload_state.json")
    with patch.object(config, "GDRIVE_QUEUE_STATE_FILE_ABS", path):
        yield path


def _write_file(path, content=b"hello"):
    path.write_bytes(content)
    return str(path)


# ---------------------------------------------------------------------------
# _retry_with_backoff - retry sınıflandırma
# ---------------------------------------------------------------------------
def test_retry_succeeds_after_transient_5xx():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _http_error(503)
        return "ok"

    with patch("time.sleep", return_value=None):
        result = drive_worker._retry_with_backoff(flaky, max_attempts=3, base_backoff=0.01)
    assert result == "ok"
    assert calls["n"] == 2


def test_retry_429_honors_retry_after_header():
    calls = {"n": 0}
    sleeps = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _http_error(429, headers={"Retry-After": "7"})
        return "ok"

    with patch("time.sleep", side_effect=lambda s: sleeps.append(s)):
        drive_worker._retry_with_backoff(flaky, max_attempts=3)
    assert sleeps[0] == 7


def test_retry_caps_backoff_at_configured_maximum():
    def always_429():
        raise _http_error(429)

    with patch("time.sleep", return_value=None) as mock_sleep:
        with pytest.raises(httpx.HTTPStatusError):
            drive_worker._retry_with_backoff(always_429, max_attempts=4, base_backoff=1000.0, cap=5.0)
    for call in mock_sleep.call_args_list:
        assert call.args[0] <= 5.0


def test_retry_401_refreshes_once_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _http_error(401)
        return "ok"

    with patch("time.sleep", return_value=None):
        result = drive_worker._retry_with_backoff(flaky, max_attempts=3)
    assert result == "ok"


def test_retry_permanent_404_raises_immediately_no_sleep():
    def always_404():
        raise _http_error(404)

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(httpx.HTTPStatusError):
            drive_worker._retry_with_backoff(always_404, max_attempts=3)
    mock_sleep.assert_not_called()


def test_invalid_grant_raises_auth_failure_immediately_no_retry():
    calls = {"n": 0}

    def fails():
        calls["n"] += 1
        raise _invalid_grant_error()

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(drive_worker.AuthFailureError):
            drive_worker._retry_with_backoff(fails, max_attempts=5)
    assert calls["n"] == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# upload_one - küçük/büyük dosya dispatch + doğrulama
# ---------------------------------------------------------------------------
def test_small_file_uses_direct_upload_and_verifies(allowed_root):
    state = drive_queue.empty_state()
    f = _write_file(allowed_root / "small.txt", b"x" * 100)
    item = drive_queue.enqueue(state, f)

    with (
        patch.object(config, "GDRIVE_RESUMABLE_THRESHOLD_MB", 5.0),
        patch("cyber_radar.drive_worker.gdrive.ensure_folder", return_value="folder123"),
        patch("cyber_radar.drive_worker.gdrive.upload_or_update", return_value="file-abc") as mock_upload,
        patch("cyber_radar.drive_worker.gdrive.get_file_metadata", return_value={"size": "100", "trashed": False}),
        patch("cyber_radar.drive_worker.gdrive.start_resumable_upload") as mock_resumable,
    ):
        result = drive_worker.upload_one(state, item, "root-id")

    mock_upload.assert_called_once()
    mock_resumable.assert_not_called()
    assert result == {"verified": True, "bytes_confirmed": 100}
    assert item["status"] == drive_queue.STATUS_VERIFIED
    assert item["verified_at"] is not None


def test_remote_size_mismatch_marks_deferred_not_verified(allowed_root):
    state = drive_queue.empty_state()
    f = _write_file(allowed_root / "small.txt", b"x" * 100)
    item = drive_queue.enqueue(state, f)

    with (
        patch.object(config, "GDRIVE_RESUMABLE_THRESHOLD_MB", 5.0),
        patch("cyber_radar.drive_worker.gdrive.ensure_folder", return_value="folder123"),
        patch("cyber_radar.drive_worker.gdrive.upload_or_update", return_value="file-abc"),
        patch("cyber_radar.drive_worker.gdrive.get_file_metadata", return_value={"size": "1", "trashed": False}),
    ):
        result = drive_worker.upload_one(state, item, "root-id")

    assert result["verified"] is False
    assert item["status"] == drive_queue.STATUS_DEFERRED


def test_bad_single_file_does_not_raise_out_of_upload_one(allowed_root):
    """upload_one tek bir dosya için exception fırlatabilir - kuyruğu
    bloke etmemek run_worker'ın sorumluluğu (bkz. test_bad_file_does_not_block_queue)."""
    state = drive_queue.empty_state()
    f = _write_file(allowed_root / "small.txt")
    item = drive_queue.enqueue(state, f)

    with (
        patch("cyber_radar.drive_worker.gdrive.ensure_folder", return_value="folder123"),
        patch("cyber_radar.drive_worker.gdrive.upload_or_update", side_effect=_http_error(404)),
    ):
        with pytest.raises(httpx.HTTPStatusError):
            drive_worker.upload_one(state, item, "root-id")


def test_large_file_dispatches_to_resumable_upload(allowed_root):
    state = drive_queue.empty_state()
    size = 10 * 1024 * 1024
    f = _write_file(allowed_root / "big.bin", b"a" * size)
    item = drive_queue.enqueue(state, f)

    with (
        patch.object(config, "GDRIVE_RESUMABLE_THRESHOLD_MB", 5.0),
        patch.object(config, "GDRIVE_UPLOAD_CHUNK_MB", 4.0),
        patch("cyber_radar.drive_worker.gdrive.ensure_folder", return_value="folder123"),
        patch("cyber_radar.drive_worker.gdrive.start_resumable_upload", return_value="session-uri-1") as mock_start,
        patch(
            "cyber_radar.drive_worker.gdrive.upload_chunk",
            side_effect=[
                {"complete": False, "confirmed_offset": 4 * 1024 * 1024},
                {"complete": False, "confirmed_offset": 8 * 1024 * 1024},
                {"complete": True, "file": {"id": "big-file-id"}},
            ],
        ) as mock_chunk,
        patch(
            "cyber_radar.drive_worker.gdrive.get_file_metadata",
            return_value={"size": str(size), "trashed": False},
        ),
        patch("cyber_radar.drive_worker.drive_queue.save_state"),
    ):
        result = drive_worker.upload_one(state, item, "root-id")

    mock_start.assert_called_once()
    assert mock_chunk.call_count == 3
    assert result == {"verified": True, "bytes_confirmed": size}
    assert item["status"] == drive_queue.STATUS_VERIFIED


def test_resume_uses_remote_confirmed_offset_not_local_guess(allowed_root):
    state = drive_queue.empty_state()
    size = 10 * 1024 * 1024
    f = _write_file(allowed_root / "big.bin", b"a" * size)
    item = drive_queue.enqueue(state, f)
    item["upload_session_uri"] = "existing-session"
    item["confirmed_offset"] = 1  # yerel (bayat) değer - REMOTE'a güvenilmeli, buna değil

    with (
        patch.object(config, "GDRIVE_RESUMABLE_THRESHOLD_MB", 5.0),
        patch.object(config, "GDRIVE_UPLOAD_CHUNK_MB", 4.0),
        patch("cyber_radar.drive_worker.gdrive.ensure_folder", return_value="folder123"),
        patch(
            "cyber_radar.drive_worker.gdrive.query_resumable_status",
            return_value={"complete": False, "confirmed_offset": 8 * 1024 * 1024},
        ) as mock_status,
        patch("cyber_radar.drive_worker.gdrive.start_resumable_upload") as mock_start,
        patch(
            "cyber_radar.drive_worker.gdrive.upload_chunk",
            return_value={"complete": True, "file": {"id": "big-file-id"}},
        ) as mock_chunk,
        patch("cyber_radar.drive_worker.gdrive.get_file_metadata", return_value={"size": str(size), "trashed": False}),
        patch("cyber_radar.drive_worker.drive_queue.save_state"),
    ):
        drive_worker.upload_one(state, item, "root-id")

    mock_status.assert_called_once_with("existing-session", size)
    mock_start.assert_not_called()
    called_offset = mock_chunk.call_args.args[2]
    assert called_offset == 8 * 1024 * 1024


def test_expired_session_starts_new_one(allowed_root):
    state = drive_queue.empty_state()
    size = 10 * 1024 * 1024
    f = _write_file(allowed_root / "big.bin", b"a" * size)
    item = drive_queue.enqueue(state, f)
    item["upload_session_uri"] = "dead-session"

    with (
        patch.object(config, "GDRIVE_RESUMABLE_THRESHOLD_MB", 5.0),
        patch.object(config, "GDRIVE_UPLOAD_CHUNK_MB", 4.0),
        patch("cyber_radar.drive_worker.gdrive.ensure_folder", return_value="folder123"),
        patch(
            "cyber_radar.drive_worker.gdrive.query_resumable_status",
            side_effect=gdrive_session_expired(),
        ),
        patch("cyber_radar.drive_worker.gdrive.start_resumable_upload", return_value="new-session") as mock_start,
        patch(
            "cyber_radar.drive_worker.gdrive.upload_chunk",
            return_value={"complete": True, "file": {"id": "big-file-id"}},
        ),
        patch("cyber_radar.drive_worker.gdrive.get_file_metadata", return_value={"size": str(size), "trashed": False}),
        patch("cyber_radar.drive_worker.drive_queue.save_state"),
    ):
        result = drive_worker.upload_one(state, item, "root-id")

    mock_start.assert_called_once()
    assert result["verified"] is True


def gdrive_session_expired():
    from cyber_radar.gdrive import SessionExpiredError

    return SessionExpiredError("410 Gone")


def test_large_file_upload_stops_when_budget_exhausted_mid_upload(allowed_root):
    state = drive_queue.empty_state()
    size = 10 * 1024 * 1024
    f = _write_file(allowed_root / "big.bin", b"a" * size)
    item = drive_queue.enqueue(state, f)
    # bütçe tam olarak sıfır - hiç chunk yüklenmeden dur
    with patch.object(config, "GDRIVE_DAILY_UPLOAD_BUDGET_GB", 0.0):
        with (
            patch.object(config, "GDRIVE_RESUMABLE_THRESHOLD_MB", 5.0),
            patch("cyber_radar.drive_worker.gdrive.ensure_folder", return_value="folder123"),
            patch("cyber_radar.drive_worker.gdrive.start_resumable_upload", return_value="session-1"),
            patch("cyber_radar.drive_worker.gdrive.upload_chunk") as mock_chunk,
            patch("cyber_radar.drive_worker.drive_queue.save_state"),
        ):
            result = drive_worker.upload_one(state, item, "root-id")

    mock_chunk.assert_not_called()
    assert result == {"verified": False, "bytes_confirmed": 0}
    assert item["status"] == drive_queue.STATUS_DEFERRED


# ---------------------------------------------------------------------------
# run_worker - bütçe/runtime durdurma koşulları, tek kötü dosya izolasyonu
# ---------------------------------------------------------------------------
def test_run_worker_stops_on_queue_empty(state_path, allowed_root):
    with patch("cyber_radar.drive_worker.gdrive.is_configured", return_value=True):
        result = drive_worker.run_worker()
    assert result["stop_reason"] == drive_worker.STOP_QUEUE_EMPTY
    assert result["files_verified"] == 0


def test_run_worker_stops_when_not_configured(state_path, allowed_root):
    with patch("cyber_radar.drive_worker.gdrive.is_configured", return_value=False):
        result = drive_worker.run_worker()
    assert result["stop_reason"] == drive_worker.STOP_AUTH_FAILURE


def test_run_worker_respects_daily_file_limit(state_path, allowed_root):
    for i in range(3):
        _write_file(allowed_root / f"f{i}.txt", b"x" * 10)

    with (
        patch.object(config, "GDRIVE_DAILY_FILE_LIMIT", 2),
        patch.object(config, "GDRIVE_RESUMABLE_THRESHOLD_MB", 5.0),
        patch("cyber_radar.drive_worker.gdrive.is_configured", return_value=True),
        patch("cyber_radar.drive_worker.gdrive.ensure_folder", return_value="folder123"),
        patch("cyber_radar.drive_worker.gdrive.upload_or_update", return_value="file-id"),
        patch("cyber_radar.drive_worker.gdrive.get_file_metadata", return_value={"size": "10", "trashed": False}),
    ):
        result = drive_worker.run_worker()

    assert result["stop_reason"] == drive_worker.STOP_DAILY_FILE_LIMIT_REACHED
    assert result["files_verified"] == 2


def test_run_worker_respects_daily_byte_budget(state_path, allowed_root):
    for i in range(3):
        _write_file(allowed_root / f"f{i}.txt", b"x" * 1000)

    with (
        patch.object(config, "GDRIVE_DAILY_UPLOAD_BUDGET_GB", 2000 / (1024 * 1024 * 1024)),
        patch.object(config, "GDRIVE_RESUMABLE_THRESHOLD_MB", 5.0),
        patch("cyber_radar.drive_worker.gdrive.is_configured", return_value=True),
        patch("cyber_radar.drive_worker.gdrive.ensure_folder", return_value="folder123"),
        patch("cyber_radar.drive_worker.gdrive.upload_or_update", return_value="file-id"),
        patch("cyber_radar.drive_worker.gdrive.get_file_metadata", return_value={"size": "1000", "trashed": False}),
    ):
        result = drive_worker.run_worker()

    assert result["stop_reason"] == drive_worker.STOP_DAILY_BUDGET_REACHED
    assert result["files_verified"] == 2


def test_run_worker_max_runtime_stops_loop(state_path, allowed_root):
    for i in range(5):
        _write_file(allowed_root / f"f{i}.txt", b"x" * 10)

    call_count = {"n": 0}
    start = time.monotonic()

    def fake_monotonic():
        call_count["n"] += 1
        return start + (call_count["n"] * 100)  # her kontrolde büyük sıçrama - hemen limit aşılır

    with (
        patch.object(config, "GDRIVE_RESUMABLE_THRESHOLD_MB", 5.0),
        patch("cyber_radar.drive_worker.gdrive.is_configured", return_value=True),
        patch("cyber_radar.drive_worker.time.monotonic", side_effect=fake_monotonic),
    ):
        result = drive_worker.run_worker(max_runtime_minutes=1)

    assert result["stop_reason"] == drive_worker.STOP_MAX_RUNTIME_REACHED
    assert result["files_verified"] == 0


def test_run_worker_bad_file_does_not_block_rest_of_queue(state_path, allowed_root):
    _write_file(allowed_root / "bad.txt", b"x" * 10)
    _write_file(allowed_root / "good.txt", b"y" * 10)

    def upload_side_effect(local_path, parent_id, drive_name=None):
        if os.path.basename(local_path) == "bad.txt":
            raise _http_error(404)
        return "good-file-id"

    with (
        patch.object(config, "GDRIVE_MAX_RETRIES_PER_FILE", 1),
        patch.object(config, "GDRIVE_RESUMABLE_THRESHOLD_MB", 5.0),
        patch("cyber_radar.drive_worker.gdrive.is_configured", return_value=True),
        patch("cyber_radar.drive_worker.gdrive.ensure_folder", return_value="folder123"),
        patch("cyber_radar.drive_worker.gdrive.upload_or_update", side_effect=upload_side_effect),
        patch("cyber_radar.drive_worker.gdrive.get_file_metadata", return_value={"size": "10", "trashed": False}),
    ):
        result = drive_worker.run_worker()

    assert result["stop_reason"] == drive_worker.STOP_QUEUE_EMPTY
    assert result["files_verified"] == 1
    assert result["files_failed"] == 1


def test_run_worker_auth_failure_stops_worker_entirely(state_path, allowed_root):
    _write_file(allowed_root / "a.txt", b"x" * 10)
    _write_file(allowed_root / "b.txt", b"x" * 10)

    with (
        patch.object(config, "GDRIVE_RESUMABLE_THRESHOLD_MB", 5.0),
        patch("cyber_radar.drive_worker.gdrive.is_configured", return_value=True),
        patch("cyber_radar.drive_worker.gdrive.ensure_folder", return_value="folder123"),
        patch("cyber_radar.drive_worker.gdrive.upload_or_update", side_effect=_invalid_grant_error()),
    ):
        result = drive_worker.run_worker()

    assert result["stop_reason"] == drive_worker.STOP_AUTH_FAILURE
    assert result["files_verified"] == 0


def test_run_worker_state_corruption_stops_immediately(state_path, allowed_root):
    import os

    os.makedirs(os.path.dirname(config.GDRIVE_QUEUE_STATE_FILE_ABS), exist_ok=True)
    with open(config.GDRIVE_QUEUE_STATE_FILE_ABS, "w") as f:
        f.write("not json")

    result = drive_worker.run_worker()
    assert result["stop_reason"] == drive_worker.STOP_STATE_CORRUPTION


def test_run_worker_persists_state_so_restart_resumes(state_path, allowed_root):
    _write_file(allowed_root / "a.txt", b"x" * 10)

    with (
        patch.object(config, "GDRIVE_RESUMABLE_THRESHOLD_MB", 5.0),
        patch("cyber_radar.drive_worker.gdrive.is_configured", return_value=True),
        patch("cyber_radar.drive_worker.gdrive.ensure_folder", return_value="folder123"),
        patch("cyber_radar.drive_worker.gdrive.upload_or_update", return_value="file-id"),
        patch("cyber_radar.drive_worker.gdrive.get_file_metadata", return_value={"size": "10", "trashed": False}),
    ):
        drive_worker.run_worker()

    reloaded = drive_queue.load_state()
    assert reloaded["items"][0]["status"] == drive_queue.STATUS_VERIFIED
    assert reloaded["files_completed_today"] == 1

    # ikinci çalıştırma - aynı dosya TEKRAR yüklenmemeli
    with (
        patch("cyber_radar.drive_worker.gdrive.is_configured", return_value=True),
        patch("cyber_radar.drive_worker.gdrive.upload_or_update") as mock_upload_again,
    ):
        result2 = drive_worker.run_worker()

    mock_upload_again.assert_not_called()
    assert result2["stop_reason"] == drive_worker.STOP_QUEUE_EMPTY
