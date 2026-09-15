"""PostgreSQL yedekleme.

pg_dump ile custom-format (-Fc, sıkıştırılmış + selektif restore destekler)
bir dump alır. retention.py bunu her koşuda çağırıp Drive'a yükler ve
diğer her şeyle aynı kuralla (LOCAL_RETENTION_DAYS gün sonra) sunucudan
siler - Drive'daki kopyalar kalıcı kalır (disk sınırlı, Drive değil).

Neden ayrı bir yedek mekanizması gerekiyordu: retention.py'ın kapsamındaki
her şey (raporlar, NotebookLM export'ları, PDF önbelleği) dosya sistemi
üzerinde üretilen TÜREV çıktılar - asıl ham/analiz edilmiş veri (papers,
news_events, tüm Gemini analiz sonuçları) sadece Postgres'te duruyordu ve
hiç yedeklenmiyordu. Sunucu disk arızası olsaydı Drive'daki markdown
özetleri kalır ama tablo verisi tamamen kaybolurdu.

Geri yükleme için: python3 -m src.db_restore
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone

from . import config

DB_BACKUP_DIR = os.path.join(config.DATA_DIR, "db_backups")


def create_backup() -> str:
    """Yeni bir pg_dump alır, yerel dosya yolunu döner. Hata olursa
    subprocess.CalledProcessError fırlatır (çağıran taraf yakalar)."""
    os.makedirs(DB_BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    dest = os.path.join(DB_BACKUP_DIR, f"cyber_radar_{timestamp}.dump")
    # pg_dump, libpq bağlantı URI'sini doğrudan pozisyonel argüman olarak
    # kabul eder - host/port/user/password'ü elle ayrıştırmaya gerek yok.
    subprocess.run(
        ["pg_dump", config.DATABASE_URL, "-Fc", "-f", dest],
        check=True,
        timeout=300,
        capture_output=True,
        text=True,
    )
    return dest
