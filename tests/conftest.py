"""Ortak pytest fixture'ları.

İKİ TEMEL GARANTİ (proje notları):

1. Hiçbir gerçek ağ çağrısı: `block_real_network` (autouse) her testte
   httpx.get/post'u varsayılan olarak BLOKE eder - bir test gerçekten
   Gemini/Telegram/OpenAlex/Crossref/Semantic Scholar/OpenAIRE/OpenReview/
   DBLP/OpenCitations'a gitmeye çalışırsa (mock'lamayı unutmuşsa) RuntimeError
   fırlatır, sessizce gerçek bir isteğe kaymaz.

2. Hiçbir production veri değişikliği: `db_conn` production `cyber_radar`
   DB'sine DEĞİL, ayrı `cyber_radar_test` DB'sine bağlanır (db/schema.sql ile
   kurulu) ve her testin sonunda ROLLBACK yapar - hiçbir satır kalıcı olmaz,
   602 gerçek papers satırına asla dokunulmaz. Test DB erişilemezse (ör.
   başka bir makinede/CI'da hiç kurulmamışsa) DB gerektiren testler
   `pytest.skip` ile atlanır, suit'in geri kalanı yine de çalışır.
"""
from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.rows import dict_row

from cyber_radar import config

# Production DATABASE_URL'den (.env, secret İÇERİR - hardcode EDİLMEZ) sadece
# DB adını değiştirerek türetilir. TEST_DATABASE_URL env var'ıyla override
# edilebilir (ör. başka bir makinede farklı bir test DB'ye işaret etmek için).
_DEFAULT_TEST_DB_URL = config.DATABASE_URL.rsplit("/", 1)[0] + "/cyber_radar_test"
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", _DEFAULT_TEST_DB_URL)


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise RuntimeError(
            "Testlerde gerçek HTTP çağrısına izin verilmiyor - bu çağrı mock'lanmalıydı "
            "(bkz. tests/conftest.py: block_real_network). "
            f"args={args!r} kwargs={kwargs!r}"
        )

    monkeypatch.setattr("httpx.get", _blocked)
    monkeypatch.setattr("httpx.post", _blocked)


@pytest.fixture(autouse=True)
def _fast_inter_call_delay(monkeypatch):
    """2026-09-14: RECOVERY_INTER_CALL_DELAY_SECONDS artık run_type='incremental'
    dahil HER _collect_profile koşusunda uygulanıyor (bkz. run_pipeline.py -
    normal günlük koşu da arXiv/OpenAlex/Semantic Scholar'da 429 almaya
    başladığı için gate kaldırıldı). Testler gerçek zamanda beklemesin diye
    burada 0'a sabitleniyor - gecikmenin KENDİSİNİ doğrulayan bir test bu
    fixture'ı kendi içinde ayrıca monkeypatch'leyerek override edebilir."""
    monkeypatch.setattr(config, "RECOVERY_INTER_CALL_DELAY_SECONDS", 0.0)


@pytest.fixture(autouse=True)
def _pin_gdrive_sync_mode(monkeypatch):
    """2026-09-15: GDRIVE_SYNC_MODE canlı .env'e göre değişebilir (bkz.
    docs/GOOGLE_DRIVE.md - production 'queued', kod seviyesi varsayılan
    'direct'). Testler HANGİ modu test ettiklerini KENDİLERİ açıkça
    patch.object ile belirtmeli - .env'in o anki değerine göre sessizce
    farklı davranmamalı. Kod seviyesi varsayılanı ('direct') sabitliyoruz;
    bunu test eden dosyalar zaten kendi içinde override eder."""
    monkeypatch.setattr(config, "GDRIVE_SYNC_MODE", "direct")


@pytest.fixture()
def db_conn():
    """Test DB'ye bağlanır, testin sonunda HER ZAMAN rollback yapar (başarılı
    da olsa başarısız da olsa) - satırlar hiçbir zaman kalıcı olmaz."""
    try:
        conn = psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row, autocommit=False)
    except psycopg.OperationalError as e:
        pytest.skip(f"test DB'ye bağlanılamadı ({TEST_DATABASE_URL.rsplit('@', 1)[-1]}): {e}")
        return
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture()
def sample_paper_item():
    """academic.py'nin normalize sözlük şekli - collector'ların hepsi bunu
    döner, _upsert_paper bunu bekler."""
    return {
        "title": "A Study of Security Visibility in SOC Environments",
        "authors": ["A. Researcher"],
        "doi": "10.1000/test.doi.001",
        "arxiv_id": None,
        "openalex_id": None,
        "venue": "Test Journal",
        "publication_date": "2024-01-01",
        "abstract": "Test abstract about SOC visibility.",
        "pdf_url": None,
        "source_api": "test_source",
    }
