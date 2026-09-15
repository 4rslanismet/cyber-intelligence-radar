"""Credential gerektiren 9 opsiyonel kaynak (bkz. config.OPTIONAL_ACADEMIC_SOURCES):
key'siz iken pipeline hiçbir şekilde çökmemeli, sadece
'disabled_missing_credentials' loglamalı."""
from __future__ import annotations

from cyber_radar import config
from cyber_radar.run_pipeline import _log_disabled_optional_sources


def test_optional_sources_missing_credentials(db_conn, monkeypatch):
    for env_var in config.OPTIONAL_ACADEMIC_SOURCES.values():
        monkeypatch.delenv(env_var, raising=False)

    _log_disabled_optional_sources(db_conn)

    rows = db_conn.execute(
        "SELECT source FROM collector_runs WHERE error = 'disabled_missing_credentials'"
    ).fetchall()
    logged_sources = {r["source"] for r in rows}
    assert logged_sources == set(config.OPTIONAL_ACADEMIC_SOURCES.keys())


def test_optional_source_with_key_set_is_not_logged_disabled(db_conn, monkeypatch):
    """Bir key set edilirse o kaynak artık 'disabled' loglanmamalı - config
    sözlüğü/env eşlemesi doğru çalışıyor mu diye kontrol."""
    for env_var in config.OPTIONAL_ACADEMIC_SOURCES.values():
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv("IEEE_XPLORE_API_KEY", "dummy-test-key-not-real")

    _log_disabled_optional_sources(db_conn)

    rows = db_conn.execute(
        "SELECT source FROM collector_runs WHERE error = 'disabled_missing_credentials'"
    ).fetchall()
    logged_sources = {r["source"] for r in rows}
    assert "ieee_xplore" not in logged_sources
    assert len(logged_sources) == len(config.OPTIONAL_ACADEMIC_SOURCES) - 1


def test_no_collector_module_imports_fail_without_keys():
    """9 opsiyonel kaynağın HİÇBİRİ için gerçek bir collector modülü
    YAZILMADI (bkz. proje notları) - src/run_pipeline.py'nin import
    edilebilmesi, key'lerin hiçbiri set edilmemişken bile pipeline
    başlatmanın (initialization) başarılı olduğunu doğrular."""
    import importlib

    import cyber_radar.run_pipeline

    importlib.reload(cyber_radar.run_pipeline)  # ImportError fırlatmadan tekrar yüklenebilmeli
