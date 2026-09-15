"""Postgres bağlantı yardımcıları. psycopg3 kullanır, connection pool yok -
tek sunucuda günde 2 koşu için gereksiz karmaşıklık; her koşu kendi bağlantısını
açıp kapatır."""
from __future__ import annotations

import contextlib
import json
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from . import config


@contextlib.contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(config.DATABASE_URL, row_factory=dict_row, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


def get_state(conn: psycopg.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM pipeline_state WHERE key = %s", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn: psycopg.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO pipeline_state (key, value, updated_at)
        VALUES (%s, %s, now())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """,
        (key, value),
    )


def log_collector_run(
    conn: psycopg.Connection,
    source: str,
    kind: str,
    query: str | None,
    result_count: int | None,
    error: str | None = None,
    run_type: str = "incremental",
    recovery_run_id: int | None = None,
) -> None:
    """`run_type`/`recovery_run_id`: 2026-09-13 recovery backfill için
    eklendi (bkz. src/recovery/) - normal pipeline çağrıları HİÇBİR ZAMAN
    bunları geçirmez, `run_type` her zaman varsayılan 'incremental' kalır.
    Bu ayrım sayesinde coverage/source anomaly kontrolleri (bkz.
    run_pipeline._coverage_warning/_source_anomaly_warnings) recovery
    koşularını normal baseline'a HİÇ KARIŞTIRMAZ."""
    conn.execute(
        """
        INSERT INTO collector_runs (source, kind, finished_at, query, result_count, error, run_type, recovery_run_id)
        VALUES (%s, %s, now(), %s, %s, %s, %s, %s)
        """,
        (source, kind, query, result_count, error, run_type, recovery_run_id),
    )


def record_telegram_message(conn: psycopg.Connection, message_id: int, item_type: str, item_id: int) -> None:
    """Faz 5 geri bildirim döngüsü: bir interaktif mesajın (bkz. notify.send_interactive)
    hangi makale/habere ait olduğunu kaydeder - telegram_listener.py bir yanıt
    (reply) geldiğinde bunu sorgulayarak hangi satırı güncelleyeceğini bulur."""
    conn.execute(
        "INSERT INTO telegram_message_map (message_id, item_type, item_id) VALUES (%s, %s, %s) "
        "ON CONFLICT (message_id) DO NOTHING",
        (message_id, item_type, item_id),
    )


def to_jsonb(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
