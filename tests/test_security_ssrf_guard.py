"""cyber_radar.security.is_safe_external_url - SSRF guard testleri (bkz. 2026-09-15
"public üründeki güvenlik sorunları" incelemesi). Saf fonksiyon testleri,
ağ çağrısı YOK."""
from __future__ import annotations

import pytest

from cyber_radar.security import is_safe_external_url


@pytest.mark.parametrize("url", [
    "https://example.org/feed.xml",
    "http://example.org/feed.xml",
    "https://export.arxiv.org/api/query",
    "https://8.8.8.8/feed.xml",  # public bir literal IP - reddedilmemeli
])
def test_public_http_urls_are_safe(url):
    assert is_safe_external_url(url) is True


@pytest.mark.parametrize("url", [
    "",
    None,
    "file:///etc/passwd",
    "ftp://example.org/x",
    "gopher://example.org/x",
    "http://localhost/admin",
    "http://LOCALHOST:8080/",
    "http://127.0.0.1/",
    "http://127.0.0.1:5432/",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
    "http://10.0.0.5/internal",
    "http://172.16.0.1/",
    "http://192.168.1.1/",
    "http://[::1]/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "not a url at all",
])
def test_unsafe_or_local_urls_are_rejected(url):
    assert is_safe_external_url(url) is False


def test_hostname_based_url_is_not_dns_resolved_but_scheme_checked():
    """Bilinçli sınır: hostname'ler DNS'e gitmeden kabul edilir (bkz. modül
    docstring'i) - ama http(s) dışı bir şema hostname olsa bile reddedilir."""
    assert is_safe_external_url("https://some-random-feed.example.com/rss") is True
    assert is_safe_external_url("javascript://some-random-feed.example.com/") is False
