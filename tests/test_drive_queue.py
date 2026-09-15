"""Drive Queue V1 - persistent state/scan/priority mantığı (bkz.
src/drive_queue.py, docs/GOOGLE_DRIVE.md "Drive Queue V1"). Gerçek Drive API
çağrısı YOK - bu modül saf state yönetimi, ağ bağımsız. Tüm testler
tmp_path altında izole bir state dosyası/allowed-root kullanır, gerçek
data/ dizinine dokunmaz."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from cyber_radar import config, drive_queue


@pytest.fixture
def allowed_root(tmp_path):
    root = tmp_path / "reports"
    root.mkdir()
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


def _write_file(path, content=b"hello world"):
    path.write_bytes(content)
    return str(path)


# ---------------------------------------------------------------------------
# enqueue / stable identity
# ---------------------------------------------------------------------------
def test_enqueue_idempotent(allowed_root):
    state = drive_queue.empty_state()
    f = _write_file(allowed_root / "a.txt")
    item1 = drive_queue.enqueue(state, f)
    item2 = drive_queue.enqueue(state, f)
    assert item1["id"] == item2["id"]
    assert len(state["items"]) == 1


def test_changed_file_gets_new_version_id(allowed_root):
    state = drive_queue.empty_state()
    f = allowed_root / "a.txt"
    path = _write_file(f, b"v1")
    item1 = drive_queue.enqueue(state, path)
    time.sleep(0.01)
    _write_file(f, b"v2-longer-content")
    item2 = drive_queue.enqueue(state, path)
    assert item1["id"] != item2["id"]
    assert len(state["items"]) == 2


def test_enqueue_rejects_path_outside_allowed_roots(allowed_root, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"nope")
    state = drive_queue.empty_state()
    assert drive_queue.enqueue(state, str(outside)) is None
    assert state["items"] == []


def test_enqueue_rejects_symlink(allowed_root):
    real = allowed_root / "real.txt"
    real.write_bytes(b"data")
    link = allowed_root / "link.txt"
    os.symlink(real, link)
    state = drive_queue.empty_state()
    assert drive_queue.enqueue(state, str(link)) is None


def test_enqueue_rejects_nonexistent_file(allowed_root):
    state = drive_queue.empty_state()
    assert drive_queue.enqueue(state, str(allowed_root / "missing.txt")) is None


def test_scan_allowed_roots_adds_each_file_once(allowed_root):
    _write_file(allowed_root / "a.txt")
    _write_file(allowed_root / "b.txt")
    state = drive_queue.empty_state()
    added_first = drive_queue.scan_allowed_roots(state)
    added_second = drive_queue.scan_allowed_roots(state)
    assert added_first == 2
    assert added_second == 0
    assert len(state["items"]) == 2


def test_scan_allowed_roots_skips_symlinked_files_and_dirs(allowed_root):
    real_dir = allowed_root / "realdir"
    real_dir.mkdir()
    _write_file(real_dir / "x.txt")
    os.symlink(real_dir, allowed_root / "linkdir")
    real_file = allowed_root / "real.txt"
    real_file.write_bytes(b"data")
    os.symlink(real_file, allowed_root / "link.txt")

    state = drive_queue.empty_state()
    drive_queue.scan_allowed_roots(state)
    paths = {item["local_path"] for item in state["items"]}
    assert str(real_dir / "x.txt") in paths
    assert str(real_file) in paths
    assert str(allowed_root / "link.txt") not in paths


# ---------------------------------------------------------------------------
# atomic save / corrupt-state fail-safe
# ---------------------------------------------------------------------------
def test_atomic_state_save_and_load_roundtrip(state_path, allowed_root):
    state = drive_queue.empty_state()
    f = _write_file(allowed_root / "a.txt")
    drive_queue.enqueue(state, f)
    drive_queue.save_state(state)

    assert os.path.exists(state_path)
    reloaded = drive_queue.load_state()
    assert len(reloaded["items"]) == 1
    assert reloaded["items"][0]["local_path"] == f


def test_save_state_leaves_no_tmp_file_behind(state_path):
    state = drive_queue.empty_state()
    drive_queue.save_state(state)
    directory = os.path.dirname(state_path)
    leftovers = [n for n in os.listdir(directory) if n.startswith(".gdrive_upload_state.")]
    assert leftovers == []


def test_missing_state_file_is_not_corruption(state_path):
    assert not os.path.exists(state_path)
    state = drive_queue.load_state()
    assert state["items"] == []


def test_corrupt_state_file_raises_and_does_not_overwrite(state_path):
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w") as f:
        f.write("{not valid json")

    with pytest.raises(drive_queue.StateCorruptionError):
        drive_queue.load_state()

    with open(state_path) as f:
        assert f.read() == "{not valid json"


def test_state_missing_required_keys_raises_corruption(state_path):
    import json

    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w") as f:
        json.dump({"foo": "bar"}, f)

    with pytest.raises(drive_queue.StateCorruptionError):
        drive_queue.load_state()


# ---------------------------------------------------------------------------
# daily budget (bayt/dosya) - gün değişince YALNIZ sayaçlar sıfırlanır
# ---------------------------------------------------------------------------
def test_daily_budget_resets_on_new_day_but_keeps_items(state_path, allowed_root):
    state = drive_queue.empty_state()
    f = _write_file(allowed_root / "a.txt")
    drive_queue.enqueue(state, f)
    state["bytes_uploaded_today"] = 1234
    state["files_completed_today"] = 3
    state["budget_date"] = "2000-01-01"
    drive_queue.save_state(state)

    reloaded = drive_queue.load_state()
    assert reloaded["bytes_uploaded_today"] == 0
    assert reloaded["files_completed_today"] == 0
    assert len(reloaded["items"]) == 1


def test_daily_budget_not_reset_within_same_day(state_path):
    state = drive_queue.empty_state()
    state["bytes_uploaded_today"] = 500
    drive_queue.save_state(state)
    reloaded = drive_queue.load_state()
    assert reloaded["bytes_uploaded_today"] == 500


def test_remaining_byte_budget_hard_cap():
    state = drive_queue.empty_state()
    with patch.object(config, "GDRIVE_DAILY_UPLOAD_BUDGET_GB", 1.0 / (1024 * 1024)):  # 1 MiB
        state["bytes_uploaded_today"] = 1024 * 1024
        assert drive_queue.remaining_byte_budget(state) == 0
        state["bytes_uploaded_today"] = 2 * 1024 * 1024  # aşım - negatif OLMAMALI
        assert drive_queue.remaining_byte_budget(state) == 0


def test_remaining_file_budget_hard_cap():
    state = drive_queue.empty_state()
    with patch.object(config, "GDRIVE_DAILY_FILE_LIMIT", 5):
        state["files_completed_today"] = 5
        assert drive_queue.remaining_file_budget(state) == 0
        state["files_completed_today"] = 9
        assert drive_queue.remaining_file_budget(state) == 0


# ---------------------------------------------------------------------------
# priority ordering / fair scheduling
# ---------------------------------------------------------------------------
def test_priority_order_low_number_first(tmp_path):
    data_root = tmp_path / "data"
    reports_dir = data_root / "reports"
    recovery_dir = reports_dir / "recovery"
    recovery_dir.mkdir(parents=True)

    with (
        patch.object(config, "GDRIVE_ALLOWED_ROOTS_ABS", [str(reports_dir)]),
        patch.object(config, "GDRIVE_BLIND_SCAN_ROOTS_ABS", [str(reports_dir)]),
    ):
        _test_priority_order_low_number_first(reports_dir, recovery_dir)


def _test_priority_order_low_number_first(reports_dir, recovery_dir):
    state = drive_queue.empty_state()

    normal_report = _write_file(reports_dir / "normal.txt")
    recovery_report = _write_file(recovery_dir / "recovery.txt")

    drive_queue.enqueue(state, normal_report)
    drive_queue.enqueue(state, recovery_report)

    candidates = drive_queue.next_upload_candidates(state)
    assert candidates[0]["local_path"] == recovery_report
    assert candidates[1]["local_path"] == normal_report


def test_next_upload_candidates_excludes_verified_and_failed(allowed_root):
    state = drive_queue.empty_state()
    f1 = _write_file(allowed_root / "a.txt")
    f2 = _write_file(allowed_root / "b.txt")
    item1 = drive_queue.enqueue(state, f1)
    item2 = drive_queue.enqueue(state, f2)
    item1["status"] = drive_queue.STATUS_VERIFIED
    item2["status"] = drive_queue.STATUS_FAILED

    assert drive_queue.next_upload_candidates(state) == []


def test_completed_file_not_reuploaded_after_rescan(allowed_root):
    state = drive_queue.empty_state()
    f = _write_file(allowed_root / "a.txt")
    item = drive_queue.enqueue(state, f)
    item["status"] = drive_queue.STATUS_VERIFIED

    drive_queue.scan_allowed_roots(state)  # dosya değişmedi -> aynı id, tekrar queued yapılmamalı
    assert len(state["items"]) == 1
    assert state["items"][0]["status"] == drive_queue.STATUS_VERIFIED


def test_fair_ordering_by_created_at_within_same_priority(allowed_root):
    state = drive_queue.empty_state()
    f1 = _write_file(allowed_root / "a.txt")
    f2 = _write_file(allowed_root / "b.txt")
    item1 = drive_queue.enqueue(state, f1)
    item1["created_at"] = "2020-01-01T00:00:00+00:00"
    item2 = drive_queue.enqueue(state, f2)
    item2["created_at"] = "2020-01-02T00:00:00+00:00"

    candidates = drive_queue.next_upload_candidates(state)
    assert candidates[0]["id"] == item1["id"]
    assert candidates[1]["id"] == item2["id"]


# ---------------------------------------------------------------------------
# revalidate_local_file - upload/resume öncesi mutation koruması
# ---------------------------------------------------------------------------
def test_revalidate_local_file_detects_mutation(allowed_root):
    state = drive_queue.empty_state()
    f = allowed_root / "a.txt"
    path = _write_file(f, b"v1")
    item = drive_queue.enqueue(state, path)

    time.sleep(0.01)
    _write_file(f, b"v2-different-size")
    assert drive_queue.revalidate_local_file(item) is False
    assert item["status"] == drive_queue.STATUS_STALE_LOCAL_VERSION


def test_revalidate_local_file_detects_deletion(allowed_root):
    state = drive_queue.empty_state()
    f = allowed_root / "a.txt"
    path = _write_file(f)
    item = drive_queue.enqueue(state, path)
    os.remove(path)
    assert drive_queue.revalidate_local_file(item) is False
    assert item["status"] == drive_queue.STATUS_STALE_LOCAL_VERSION


def test_revalidate_local_file_passes_when_unchanged(allowed_root):
    state = drive_queue.empty_state()
    f = _write_file(allowed_root / "a.txt")
    item = drive_queue.enqueue(state, f)
    assert drive_queue.revalidate_local_file(item) is True
    assert item["status"] == drive_queue.STATUS_QUEUED


# ---------------------------------------------------------------------------
# retention eligibility - SADECE verified + süre geçmiş
# ---------------------------------------------------------------------------
def test_retention_requires_verified_status():
    item = {"status": drive_queue.STATUS_QUEUED, "verified_at": None}
    assert drive_queue.is_verified_and_retention_eligible(item, retention_days=7) is False


def test_retention_requires_age_past_threshold():
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    item = {"status": drive_queue.STATUS_VERIFIED, "verified_at": recent}
    assert drive_queue.is_verified_and_retention_eligible(item, retention_days=7) is False

    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    item_old = {"status": drive_queue.STATUS_VERIFIED, "verified_at": old}
    assert drive_queue.is_verified_and_retention_eligible(item_old, retention_days=7) is True


def test_retention_never_eligible_for_deferred_or_failed():
    for status in (drive_queue.STATUS_DEFERRED, drive_queue.STATUS_FAILED, drive_queue.STATUS_STALE_LOCAL_VERSION):
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        item = {"status": status, "verified_at": old}
        assert drive_queue.is_verified_and_retention_eligible(item, retention_days=7) is False


# ---------------------------------------------------------------------------
# pending_summary
# ---------------------------------------------------------------------------
def test_pending_summary_counts(allowed_root):
    state = drive_queue.empty_state()
    f1 = _write_file(allowed_root / "a.txt", b"12345")
    f2 = _write_file(allowed_root / "b.txt", b"1234567890")
    item1 = drive_queue.enqueue(state, f1)
    item2 = drive_queue.enqueue(state, f2)
    item2["status"] = drive_queue.STATUS_VERIFIED

    summary = drive_queue.pending_summary(state)
    assert summary["pending_files"] == 1
    assert summary["pending_bytes"] == 5
    assert summary["verified"] == 1
    assert item1["status"] == drive_queue.STATUS_QUEUED
