"""RSS/PDF fetch noktalarında SSRF guard + PDF boyut tavanı entegrasyonu
(bkz. 2026-09-15 güvenlik incelemesi). httpx gerçek ağa gitmez -
block_real_network fixture zaten bunu garanti eder (bkz. conftest.py);
buradaki testler guard'ın ağa GİTMEDEN ÖNCE devreye girdiğini doğruluyor."""
from __future__ import annotations

from datetime import date

import httpx
import pytest

from cyber_radar.collectors import academic, news


def test_fetch_rss_feed_rejects_local_url_without_touching_network():
    with pytest.raises(ValueError, match="reddedildi"):
        news.fetch_rss_feed("http://169.254.169.254/latest/meta-data/", date(2026, 1, 1))


def test_fetch_rss_feed_rejects_file_scheme():
    with pytest.raises(ValueError):
        news.fetch_rss_feed("file:///etc/passwd", date(2026, 1, 1))


def test_download_and_extract_pdf_rejects_unsafe_url_without_touching_network():
    local_path, text = academic.download_and_extract_pdf("http://127.0.0.1:8000/x.pdf", "some-key")
    assert (local_path, text) == (None, None)


def test_download_and_extract_pdf_rejects_oversized_response(monkeypatch):
    big_chunk = b"%PDF-1.4" + b"0" * (1024 * 1024)  # 1 MiB per çağrı

    class _FakeStreamResponse:
        status_code = 200
        headers = {"content-type": "application/pdf"}

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            for _ in range(200):  # 200 MiB toplam >> _MAX_PDF_BYTES (50 MiB)
                yield big_chunk

    class _FakeStreamCtx:
        def __enter__(self):
            return _FakeStreamResponse()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(httpx, "stream", lambda method, url, **kw: _FakeStreamCtx())

    local_path, text = academic.download_and_extract_pdf("https://example.org/huge.pdf", "some-key")
    assert (local_path, text) == (None, None)


def test_download_and_extract_pdf_respects_content_length_header(monkeypatch):
    class _FakeStreamResponse:
        status_code = 200
        headers = {"content-type": "application/pdf", "content-length": str(200 * 1024 * 1024)}

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield b"should never be consumed"

    class _FakeStreamCtx:
        def __enter__(self):
            return _FakeStreamResponse()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(httpx, "stream", lambda method, url, **kw: _FakeStreamCtx())

    local_path, text = academic.download_and_extract_pdf("https://example.org/huge.pdf", "some-key")
    assert (local_path, text) == (None, None)
