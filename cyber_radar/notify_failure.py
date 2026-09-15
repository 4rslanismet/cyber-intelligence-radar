"""Pipeline koşusu BAŞARISIZ olduğunda Telegram'a uyarı gönderir.

systemd cyber-radar.service'in [Unit] bölümündeki OnFailure= tarafından
tetiklenir (bkz. systemd/cyber-radar-failure-notify.service). Ana pipeline
kodundan (run_pipeline.py) ayrı tutulmasının nedeni: pipeline zaten
çökmüşse, çöken sürecin İÇİNDEN bir "çöktüm" bildirimi göndermeye
güvenmek istemiyoruz - systemd'nin ayrı, bağımsız bir unit tetiklemesi
çok daha güvenilir.

Kullanım: python3 -m src.notify_failure
"""
from __future__ import annotations

import socket
import subprocess

from . import notify


def main() -> None:
    host = socket.gethostname()
    log_hint = "journalctl -u cyber-radar.service -n 50 --no-pager"
    tail = ""
    try:
        result = subprocess.run(
            ["journalctl", "-u", "cyber-radar.service", "-n", "15", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        tail = result.stdout.strip()[-1500:]
    except Exception:  # noqa: BLE001 - log alınamazsa bildirim yine de gitsin
        pass

    text = (
        f"⚠️ Cyber Intelligence Radar pipeline BAŞARISIZ OLDU\n"
        f"Sunucu: {host}\n"
        f"Log için: {log_hint}\n"
    )
    if tail:
        text += f"\nSon loglar:\n{tail}"

    ok = notify.send_telegram(text)
    if not ok:
        print("[UYARI] Hata bildirimi de gönderilemedi - Telegram ayarlarını kontrol edin.")


if __name__ == "__main__":
    main()
