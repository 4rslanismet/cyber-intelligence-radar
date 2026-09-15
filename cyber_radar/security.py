"""SSRF/dış-URL güvenlik kontrolleri - tek yerden, PAYLAŞILAN.

Neden ayrı bir modül: proje şu an .env'deki sabit NEWS_FEEDS/KEYWORDS'ü
kullanıyor (operatör kendi güvendiği kaynaklarını giriyor) ama public ürün
planında (bkz. proje notları - master plan) kullanıcılar profil YAML'ından
kendi RSS/kaynak URL'lerini ekleyebilecek - bu, dış dünyadan gelen bir URL
listesini sunucunun HTTP istemcisine veriyor demek. Aynı risk PDF/Unpaywall
çözümlemesinde de var (üçüncü parti API metadata'sından gelen bir URL).
Bilinçli olarak TEK, PAYLAŞILAN bir kontrol noktası - her fetch call site'ı
kendi ad-hoc kontrolünü icat etmesin diye.

Kapsam/sınır: bu SADECE "açıkça özel/yerel bir hedefe mi gidiyor" kontrolü -
DNS rebinding (hostname isteği anında güvenli bir IP'ye çözülüp connect
sırasında farklı bir IP'ye yönlendirilmesi) veya TOCTOU'ya karşı TAM koruma
DEĞİL (bu, httpx'e özel bir transport/DNS resolver hook'u gerektirir - bkz.
KNOWN_LIMITATIONS). Yine de literal IP olarak yazılmış yerel/private/link-
local hedefleri (ör. biri NEWS_FEEDS'e "http://169.254.169.254/..." ya da
"http://127.0.0.1:5432/..." yazarsa) ve http(s) DIŞINDAKİ şemaları
(file://, ftp://, gopher://) GÜVENİLİR ŞEKİLDE reddeder - SSRF payload'larının
büyük çoğunluğu bunlardan biri."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def is_safe_external_url(url: str) -> bool:
    """True: http(s) şeması + (hostname İSE, DNS çözümü kontrol edilmeden
    öylece kabul edilir - aşağıdaki not) ya da (literal IP İSE, private/
    loopback/link-local/reserved/multicast/unspecified DEĞİLSE) kabul.
    False: boş/parse edilemeyen URL, http(s) dışı şema, bilinen yerel
    hostname (localhost, cloud metadata hostname'i), ya da private/özel bir
    literal IP adresi."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False
    host = parsed.hostname
    if not host:
        return False
    if host.lower() in _BLOCKED_HOSTNAMES:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Hostname (DNS ile çözülecek) - burada DNS'e gitmiyoruz (network
        # I/O + rebinding riski) - şema/literal-IP kontrolü SSRF payload'larının
        # ezici çoğunluğunu (config'e yazılmış çıplak internal IP/localhost)
        # zaten yakalıyor. Tam koruma DNS-sonrası IP doğrulaması ister.
        return True
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )
