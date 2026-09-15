"""2026-09-14 kök neden raporu (madde 7 - Drive OAuth 400): retention.py'nin
"bir dosya ASLA önce silinip sonra yüklenmiş olsun varsayılmaz" katı kuralını
gerçekten koruduğunu doğrular. Gerçek ağ/Drive çağrısı YOK - `gdrive.
ensure_folder` (Drive API'ye giden İLK çağrı, token refresh'in patladığı
tam nokta - canlıda görülen 400 Bad Request) exception fırlatacak şekilde
mock'lanır."""
from __future__ import annotations

from unittest.mock import patch

from cyber_radar import config, retention


def test_drive_failure_skips_cleanup_and_deletes_nothing():
    """`_ensure_root_folder()` (ki içinde `gdrive.ensure_folder` var) patladığında
    try bloğundaki SONRAKİ hiçbir _sync_and_purge_*/_backup_and_purge_* adımı
    ÇAĞRILMAMALI - bu fonksiyonlar dosya SİLEN fonksiyonlar, "Drive'a
    yüklenemedi ama yine de sildik" senaryosu asla oluşmamalı."""
    with (
        patch.object(config, "GDRIVE_ENABLED", True),
        patch.object(config, "GDRIVE_SYNC_MODE", "direct"),
        patch("cyber_radar.retention.gdrive.is_configured", return_value=True),
        patch(
            "cyber_radar.retention.gdrive.ensure_folder",
            side_effect=RuntimeError("Client error '400 Bad Request' for url 'https://oauth2.googleapis.com/token'"),
        ),
        patch("cyber_radar.retention._backup_and_purge_database") as purge_db,
        patch("cyber_radar.retention._sync_and_purge_notebooklm") as purge_nb,
        patch("cyber_radar.retention._sync_and_purge_reports") as purge_reports,
        patch("cyber_radar.retention._sync_and_purge_pdf_cache") as purge_pdf,
    ):
        logs = retention.sync_and_cleanup()

    purge_db.assert_not_called()
    purge_nb.assert_not_called()
    purge_reports.assert_not_called()
    purge_pdf.assert_not_called()
    assert len(logs) == 1
    assert "temizlik atlandı" in logs[0]
    assert "400 Bad Request" in logs[0]


def test_drive_disabled_is_a_silent_noop():
    """GDRIVE_ENABLED=false - hiçbir Drive çağrısı, hiçbir log, hiçbir silme."""
    with patch.object(config, "GDRIVE_ENABLED", False):
        assert retention.sync_and_cleanup() == []


def test_drive_missing_token_warns_but_deletes_nothing():
    with (
        patch.object(config, "GDRIVE_ENABLED", True),
        patch.object(config, "GDRIVE_SYNC_MODE", "direct"),
        patch("cyber_radar.retention.gdrive.is_configured", return_value=False),
    ):
        logs = retention.sync_and_cleanup()
    assert len(logs) == 1
    assert "hiçbir dosya silinmedi" in logs[0]
