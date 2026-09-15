"""GDRIVE_SYNC_MODE='queued' entegrasyonu (bkz. src/retention.py
_queued_sync_and_cleanup, src/drive_queue.py). Gerçek Drive ağ çağrısı
kesinlikle YAPILMAMALI bu modda - bu tam da amacı (gerçek upload ayrı,
src/drive_worker.py'de). Gerçek db_backup.create_backup() de mock'lanır -
gerçek pg_dump çalıştırmak testin amacı değil."""
from __future__ import annotations

import os
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from cyber_radar import config, drive_queue, retention


@pytest.fixture
def queued_env(tmp_path):
    data_root = tmp_path / "data"
    reports_dir = data_root / "reports"
    db_backups_dir = data_root / "db_backups"
    notebooklm_dir = data_root / "notebooklm"
    research_dir = data_root / "research"
    pdf_dir = data_root / "academic" / "pdf"
    for d in (reports_dir, db_backups_dir, notebooklm_dir, research_dir, pdf_dir):
        d.mkdir(parents=True)

    state_path = str(tmp_path / "state" / "gdrive_upload_state.json")
    allowed_roots = [str(reports_dir), str(notebooklm_dir), str(db_backups_dir), str(research_dir), str(pdf_dir)]
    blind_scan_roots = [str(reports_dir), str(db_backups_dir), str(research_dir), str(pdf_dir)]

    with (
        patch.object(config, "GDRIVE_ENABLED", True),
        patch.object(config, "GDRIVE_SYNC_MODE", "queued"),
        patch.object(config, "GDRIVE_ALLOWED_ROOTS_ABS", allowed_roots),
        patch.object(config, "GDRIVE_BLIND_SCAN_ROOTS_ABS", blind_scan_roots),
        patch.object(config, "GDRIVE_QUEUE_STATE_FILE_ABS", state_path),
        patch.object(config, "REPORTS_DIR", str(reports_dir)),
        patch.object(config, "NOTEBOOKLM_DIR", str(notebooklm_dir)),
        patch.object(config, "NOTEBOOKLM_INDEX_DIR", str(notebooklm_dir / "_index")),
        patch.object(config, "NOTEBOOKLM_MANIFEST_FILE", str(notebooklm_dir / "_index" / "collected_papers.json")),
        patch.object(config, "PDF_DIR", str(pdf_dir)),
        patch.object(config, "LOCAL_RETENTION_DAYS", 2),
        patch.object(config, "PDF_CACHE_RETENTION_DAYS", 0),
    ):
        yield {
            "reports": reports_dir,
            "db_backups": db_backups_dir,
            "notebooklm": notebooklm_dir,
            "research": research_dir,
            "pdf": pdf_dir,
            "state_path": state_path,
        }


def test_queued_mode_never_calls_real_drive_api(queued_env):
    """Bu modun BÜTÜN amacı bu - ağ çağrısı 0 olmalı."""
    (queued_env["reports"] / "brief.md").write_bytes(b"# brief")

    with (
        patch("cyber_radar.retention.db_backup.create_backup", return_value=str(queued_env["db_backups"] / "x.dump")),
        patch("cyber_radar.retention.gdrive.upload_or_update") as mock_upload,
        patch("cyber_radar.retention.gdrive.ensure_folder") as mock_ensure_folder,
    ):
        (queued_env["db_backups"] / "x.dump").write_bytes(b"dump-data")
        logs = retention.sync_and_cleanup()

    mock_upload.assert_not_called()
    mock_ensure_folder.assert_not_called()
    assert any("kuyruğuna eklendi" in log for log in logs)


def test_queued_mode_enqueues_reports_and_db_backup(queued_env):
    (queued_env["reports"] / "brief.md").write_bytes(b"# brief")

    with patch(
        "cyber_radar.retention.db_backup.create_backup",
        side_effect=lambda: _fake_dump(queued_env["db_backups"]),
    ):
        retention.sync_and_cleanup()

    state = drive_queue.load_state()
    paths = {item["local_path"] for item in state["items"]}
    assert str(queued_env["reports"] / "brief.md") in paths
    assert any("dump" in p for p in paths)


def _fake_dump(db_backups_dir):
    path = db_backups_dir / "backup_1.dump"
    path.write_bytes(b"dump-data")
    return str(path)


def test_queued_mode_notebooklm_open_period_not_enqueued(queued_env):
    topic_dir = queued_env["notebooklm"] / "cybersecurity"
    topic_dir.mkdir()
    today_period = date.today().strftime("%Y-%m-%d")
    (topic_dir / f"{today_period}.md").write_bytes(b"# open period, not closed yet")

    with patch("cyber_radar.retention.db_backup.create_backup", side_effect=Exception("no backup needed for this test")):
        retention.sync_and_cleanup()

    state = drive_queue.load_state()
    paths = {item["local_path"] for item in state["items"]}
    assert str(topic_dir / f"{today_period}.md") not in paths


def test_queued_mode_notebooklm_closed_period_enqueued(queued_env):
    topic_dir = queued_env["notebooklm"] / "cybersecurity"
    topic_dir.mkdir()
    old_period = "2020-01-01"
    (topic_dir / f"{old_period}.md").write_bytes(b"# long closed")

    with (
        patch("cyber_radar.retention.db_backup.create_backup", side_effect=Exception("skip")),
        patch("cyber_radar.retention.period_end_date", return_value=date(2020, 1, 3)),
    ):
        retention.sync_and_cleanup()

    state = drive_queue.load_state()
    paths = {item["local_path"] for item in state["items"]}
    assert str(topic_dir / f"{old_period}.md") in paths


def test_queued_mode_manifest_enqueued_but_never_purged(queued_env):
    index_dir = queued_env["notebooklm"] / "_index"
    index_dir.mkdir()
    manifest_path = index_dir / "collected_papers.json"
    manifest_path.write_bytes(b"{}")

    with patch("cyber_radar.retention.db_backup.create_backup", side_effect=Exception("skip")):
        retention.sync_and_cleanup()

    state = drive_queue.load_state()
    item = next(i for i in state["items"] if i["local_path"] == str(manifest_path))
    # Elle 'verified' + çok eski yap - normalde silinirdi, manifest İSTİSNA.
    item["status"] = drive_queue.STATUS_VERIFIED
    item["verified_at"] = (date.today() - timedelta(days=100)).isoformat() + "T00:00:00+00:00"
    drive_queue.save_state(state)

    with patch("cyber_radar.retention.db_backup.create_backup", side_effect=Exception("skip")):
        retention.sync_and_cleanup()

    assert manifest_path.exists()


def test_queued_mode_purges_only_verified_and_retained(queued_env):
    old_dump = queued_env["db_backups"] / "old.dump"
    old_dump.write_bytes(b"old-dump")

    with patch("cyber_radar.retention.db_backup.create_backup", side_effect=Exception("skip, only testing purge")):
        retention.sync_and_cleanup()

    state = drive_queue.load_state()
    item = next(i for i in state["items"] if i["local_path"] == str(old_dump))
    assert item["status"] == drive_queue.STATUS_QUEUED
    assert old_dump.exists()  # henüz verified değil - SİLİNMEMELİ

    item["status"] = drive_queue.STATUS_VERIFIED
    item["verified_at"] = (date.today() - timedelta(days=10)).isoformat() + "T00:00:00+00:00"
    drive_queue.save_state(state)

    with patch("cyber_radar.retention.db_backup.create_backup", side_effect=Exception("skip")):
        retention.sync_and_cleanup()

    assert not old_dump.exists()  # şimdi verified + retention geçti - silinmeli


def test_queued_mode_deferred_or_failed_never_purged(queued_env):
    stuck_file = queued_env["reports"] / "stuck.md"
    stuck_file.write_bytes(b"stuck")

    with patch("cyber_radar.retention.db_backup.create_backup", side_effect=Exception("skip")):
        retention.sync_and_cleanup()

    state = drive_queue.load_state()
    item = next(i for i in state["items"] if i["local_path"] == str(stuck_file))
    item["status"] = drive_queue.STATUS_FAILED
    item["verified_at"] = (date.today() - timedelta(days=100)).isoformat() + "T00:00:00+00:00"
    drive_queue.save_state(state)

    with patch("cyber_radar.retention.db_backup.create_backup", side_effect=Exception("skip")):
        retention.sync_and_cleanup()

    assert stuck_file.exists()


def test_direct_mode_unaffected_by_queued_mode_code_path(queued_env):
    """GDRIVE_SYNC_MODE='direct' (varsayılan) - queued kod yolu HİÇ tetiklenmemeli,
    src/retention.py'nin ORİJİNAL davranışı korunur (bkz. test_retention_drive_failure.py,
    burada SADECE dispatch'in doğru dala gittiğini doğruluyoruz)."""
    with (
        patch.object(config, "GDRIVE_SYNC_MODE", "direct"),
        patch("cyber_radar.retention._queued_sync_and_cleanup") as mock_queued,
        patch("cyber_radar.retention.gdrive.is_configured", return_value=False),
    ):
        retention.sync_and_cleanup()

    mock_queued.assert_not_called()
