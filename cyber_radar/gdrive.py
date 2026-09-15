"""Google Drive entegrasyonu - OAuth 2.0 Device Authorization Grant.

Sunucuda tarayıcı olmadığı için standart OAuth "local server" akışı yerine
Google'ın CİHAZ (device) akışı kullanılıyor: script bir kod üretir, siz bu
kodu telefonunuzdan/bilgisayarınızdan https://www.google.com/device adresinde
girip yetkilendirirsiniz; script arka planda token'ı alıp diske kaydeder.
Bir daha asla tarayıcı/insan etkileşimi gerekmez (refresh_token süresiz
geçerlidir, OAuth consent screen "In production" durumuna alındığı sürece).

Sadece `drive.file` scope'u istenir - yani bu uygulama SADECE kendi
oluşturduğu/yüklediği dosyalara erişebilir, Drive'ınızdaki başka hiçbir
dosyayı göremez veya değiştiremez.

İlk kurulum: python3 -m src.gdrive_auth

Bilinçli tasarım: google-api-python-client / google-auth-oauthlib gibi ağır
bağımlılıklar eklemek yerine, zaten requirements.txt'te olan httpx ile
doğrudan Drive REST API v3'e konuşuyoruz - disk/bağımlılık ayak izini
büyütmemek için.
"""
from __future__ import annotations

import json
import mimetypes
import os
import time
from typing import Any

import httpx

from . import config

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
SCOPE = "https://www.googleapis.com/auth/drive.file"

_TOKEN_EXPIRY_SAFETY_MARGIN_SEC = 60


# ---------------------------------------------------------------------------
# Token depolama + yenileme
# ---------------------------------------------------------------------------
def _load_token() -> dict[str, Any] | None:
    if not os.path.exists(config.GDRIVE_TOKEN_FILE):
        return None
    with open(config.GDRIVE_TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_token(token: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(config.GDRIVE_TOKEN_FILE), exist_ok=True)
    with open(config.GDRIVE_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token, f)
    try:
        os.chmod(config.GDRIVE_TOKEN_FILE, 0o600)
    except PermissionError:
        # Dosyanın SAHİBİ olmayan bir kullanıcı (ör. dosya daha önce farklı
        # bir OS kullanıcısıyla oluşturulduysa) chmod yapamaz - içerik zaten
        # yazıldı (write iznimiz varsa buraya kadar gelinir), sadece izin
        # sıkılaştırmasını atlıyoruz. Drive senkronunu tamamen durdurmaya
        # değmez (canlıda başımıza geldi - kullanıcı değişikliği sonrası).
        pass


def is_configured() -> bool:
    """Drive senkronu fiilen çalışabilir mi? (env dolu + token alınmış)"""
    return bool(
        config.GDRIVE_OAUTH_CLIENT_ID
        and config.GDRIVE_OAUTH_CLIENT_SECRET
        and _load_token()
    )


# ---------------------------------------------------------------------------
# İlk kurulum: device flow (src/gdrive_auth.py bunu çağırır)
# ---------------------------------------------------------------------------
def start_device_auth() -> dict[str, Any]:
    """Döner: {verification_url, user_code, device_code, interval, expires_in}"""
    r = httpx.post(
        DEVICE_CODE_URL,
        data={"client_id": config.GDRIVE_OAUTH_CLIENT_ID, "scope": SCOPE},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def poll_device_token(device_code: str, interval: int, expires_in: int) -> dict[str, Any]:
    """Kullanıcı tarayıcıda onaylayana kadar bekler; onaylanınca token'ı kaydeder."""
    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)
        r = httpx.post(
            TOKEN_URL,
            data={
                "client_id": config.GDRIVE_OAUTH_CLIENT_ID,
                "client_secret": config.GDRIVE_OAUTH_CLIENT_SECRET,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=30,
        )
        data = r.json()
        if r.status_code == 200:
            data["obtained_at"] = time.time()
            _save_token(data)
            return data
        error = data.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        raise RuntimeError(f"Google OAuth hatası: {data}")
    raise TimeoutError("Yetkilendirme süresi doldu, `python3 -m src.gdrive_auth` ile tekrar deneyin.")


def _refresh_access_token(token: dict[str, Any]) -> dict[str, Any]:
    r = httpx.post(
        TOKEN_URL,
        data={
            "client_id": config.GDRIVE_OAUTH_CLIENT_ID,
            "client_secret": config.GDRIVE_OAUTH_CLIENT_SECRET,
            "refresh_token": token["refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    r.raise_for_status()
    fresh = r.json()
    token["access_token"] = fresh["access_token"]
    token["expires_in"] = fresh.get("expires_in", 3600)
    token["obtained_at"] = time.time()
    _save_token(token)
    return token


def _access_token() -> str:
    token = _load_token()
    if not token:
        raise RuntimeError(
            "Google Drive token'ı yok. Önce `python3 -m src.gdrive_auth` çalıştırın."
        )
    age = time.time() - token.get("obtained_at", 0)
    if age >= token.get("expires_in", 3600) - _TOKEN_EXPIRY_SAFETY_MARGIN_SEC:
        token = _refresh_access_token(token)
    return token["access_token"]


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {_access_token()}"}
    if extra:
        headers.update(extra)
    return headers


# ---------------------------------------------------------------------------
# Klasör/dosya işlemleri
# ---------------------------------------------------------------------------
_folder_cache: dict[tuple[str, str | None], str] = {}


def _escape_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def ensure_folder(name: str, parent_id: str | None = None) -> str:
    """Verilen isimde bir klasör varsa ID'sini döner, yoksa oluşturur.
    Aynı run içinde tekrar tekrar aynı klasörü aramamak için process-local
    cache kullanılır."""
    cache_key = (name, parent_id)
    if cache_key in _folder_cache:
        return _folder_cache[cache_key]

    safe_name = _escape_query_value(name)
    query = f"name = '{safe_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    r = httpx.get(
        f"{DRIVE_API}/files",
        headers=_headers(),
        params={"q": query, "fields": "files(id,name)", "spaces": "drive"},
        timeout=30,
    )
    r.raise_for_status()
    files = r.json().get("files", [])

    if files:
        folder_id = files[0]["id"]
    else:
        metadata: dict[str, Any] = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            metadata["parents"] = [parent_id]
        r = httpx.post(
            f"{DRIVE_API}/files",
            headers=_headers({"Content-Type": "application/json"}),
            json=metadata,
            timeout=30,
        )
        r.raise_for_status()
        folder_id = r.json()["id"]

    _folder_cache[cache_key] = folder_id
    return folder_id


def _find_file(name: str, parent_id: str) -> str | None:
    safe_name = _escape_query_value(name)
    query = f"name = '{safe_name}' and trashed = false and '{parent_id}' in parents"
    r = httpx.get(
        f"{DRIVE_API}/files",
        headers=_headers(),
        params={"q": query, "fields": "files(id,name)", "spaces": "drive"},
        timeout=30,
    )
    r.raise_for_status()
    files = r.json().get("files", [])
    return files[0]["id"] if files else None


def _guess_mime(local_path: str) -> str:
    if local_path.endswith(".md"):
        return "text/markdown"
    guessed, _ = mimetypes.guess_type(local_path)
    return guessed or "application/octet-stream"


def upload_or_update(local_path: str, parent_id: str, drive_name: str | None = None) -> str:
    """Dosyayı verilen Drive klasörüne yükler; aynı isimde dosya zaten varsa
    içeriğini günceller (üzerine yazar), yoksa yeni dosya oluşturur.
    Döner: Drive file ID.

    Uygulama detayı: önce metadata-only bir dosya oluşturulur (yoksa), sonra
    içerik ayrı bir PATCH ile (uploadType=media) yazılır - bu, Drive'ın
    multipart/related gövde formatını elle inşa etmeye gerek bırakmıyor ve
    hem "yeni oluştur" hem "güncelle" için aynı kod yolunu kullanmamızı
    sağlıyor."""
    name = drive_name or os.path.basename(local_path)
    file_id = _find_file(name, parent_id)
    if not file_id:
        metadata = {"name": name, "parents": [parent_id]}
        r = httpx.post(
            f"{DRIVE_API}/files",
            headers=_headers({"Content-Type": "application/json"}),
            json=metadata,
            timeout=30,
        )
        r.raise_for_status()
        file_id = r.json()["id"]

    with open(local_path, "rb") as f:
        content = f.read()
    r = httpx.patch(
        f"{DRIVE_UPLOAD_API}/files/{file_id}",
        headers=_headers({"Content-Type": _guess_mime(local_path)}),
        params={"uploadType": "media"},
        content=content,
        timeout=180,
    )
    r.raise_for_status()
    return file_id


# ---------------------------------------------------------------------------
# Resumable upload (2026-09-15, Drive Queue V1 - bkz. docs/GOOGLE_DRIVE.md).
# `upload_or_update` (yukarıda) küçük dosyalar için hâlâ kullanılıyor -
# BOZULMADI. Bu üç fonksiyon SADECE büyük dosyalar (>
# GDRIVE_RESUMABLE_THRESHOLD_MB) için src/drive_queue.py'nin worker'ı
# tarafından çağrılır. Google'ın resumable upload protokolü:
# https://developers.google.com/drive/api/guides/manage-uploads#resumable
# ---------------------------------------------------------------------------
def start_resumable_upload(
    local_path: str, parent_id: str, drive_name: str | None = None, existing_file_id: str | None = None
) -> str:
    """Yeni bir resumable upload session açar, session URI'sini
    (Location header) döner. `existing_file_id` verilirse (dosya zaten
    Drive'da varsa) içeriği GÜNCELLER (PATCH), yoksa YENİ dosya oluşturur
    (POST) - `upload_or_update`'in metadata-sonra-içerik deseniyle AYNI
    mantık, ama içerik parçalı (chunked) gönderilir."""
    name = drive_name or os.path.basename(local_path)
    size = os.path.getsize(local_path)
    metadata: dict[str, Any] = {"name": name}
    if not existing_file_id:
        metadata["parents"] = [parent_id]

    if existing_file_id:
        url = f"{DRIVE_UPLOAD_API}/files/{existing_file_id}"
        method = "PATCH"
    else:
        url = f"{DRIVE_UPLOAD_API}/files"
        method = "POST"

    r = httpx.request(
        method,
        url,
        headers=_headers({
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": _guess_mime(local_path),
            "X-Upload-Content-Length": str(size),
        }),
        params={"uploadType": "resumable"},
        json=metadata,
        timeout=30,
    )
    r.raise_for_status()
    location = r.headers.get("Location")
    if not location:
        raise RuntimeError("Drive resumable upload session URI (Location header) alınamadı.")
    return location


def query_resumable_status(session_uri: str, total_size: int) -> dict[str, Any]:
    """Var olan bir resumable session'ın Drive tarafındaki GERÇEK durumunu
    sorgular - restart sonrası yerel confirmed_offset'e KÖR GÜVENİLMEZ
    (bkz. proje notları madde "Resume": remote confirmed offset source of
    truth olsun). Döner: {"complete": True, "file": {...}} (upload zaten
    bitmiş) ya da {"complete": False, "confirmed_offset": N}.
    Session süresi dolmuş/geçersizse (404/410) SessionExpiredError
    fırlatır - çağıran taraf yeni bir session açmalı."""
    r = httpx.put(
        session_uri,
        headers=_headers({"Content-Range": f"bytes */{total_size}"}),
        timeout=30,
    )
    if r.status_code in (404, 410):
        raise SessionExpiredError(f"Resumable session geçersiz/süresi dolmuş (HTTP {r.status_code})")
    if r.status_code in (200, 201):
        return {"complete": True, "file": r.json()}
    if r.status_code == 308:
        range_header = r.headers.get("Range")  # ör. "bytes=0-8388607"
        confirmed = int(range_header.split("-")[1]) + 1 if range_header else 0
        return {"complete": False, "confirmed_offset": confirmed}
    r.raise_for_status()
    raise RuntimeError(f"Beklenmeyen resumable status yanıtı: HTTP {r.status_code}")


def upload_chunk(session_uri: str, chunk: bytes, start_offset: int, total_size: int) -> dict[str, Any]:
    """[start_offset, start_offset+len(chunk)) aralığını yükler. Chunk
    boyutu SON parça HARİÇ 256 KiB'nin katı olmalı (Google şartı) -
    src/drive_queue.py çağıranı bunu GDRIVE_UPLOAD_CHUNK_MB'den (varsayılan
    8MB = tam 32x256KiB) garanti eder. Döner: {"complete": True,
    "file": {...}} ya da {"complete": False, "confirmed_offset": N}."""
    end_offset = start_offset + len(chunk) - 1
    r = httpx.put(
        session_uri,
        headers=_headers({
            "Content-Range": f"bytes {start_offset}-{end_offset}/{total_size}",
            "Content-Length": str(len(chunk)),
        }),
        content=chunk,
        timeout=120,
    )
    if r.status_code in (404, 410):
        raise SessionExpiredError(f"Resumable session geçersiz/süresi dolmuş (HTTP {r.status_code})")
    if r.status_code in (200, 201):
        return {"complete": True, "file": r.json()}
    if r.status_code == 308:
        range_header = r.headers.get("Range")
        confirmed = int(range_header.split("-")[1]) + 1 if range_header else end_offset + 1
        return {"complete": False, "confirmed_offset": confirmed}
    r.raise_for_status()
    raise RuntimeError(f"Beklenmeyen chunk upload yanıtı: HTTP {r.status_code}")


class SessionExpiredError(Exception):
    """Resumable upload session 404/410 döndü - yeni bir session açılmalı
    (bkz. proje notları madde "Session expiry"), ama bounded retry'a tabi
    (GDRIVE_MAX_RETRIES_PER_FILE) - sonsuz restart YOK."""


def get_file_metadata(file_id: str, fields: str = "id,name,size,md5Checksum,trashed") -> dict[str, Any]:
    """Upload TAMAMLANDI response'una güvenmek yerine, verification adımı
    için Drive'dan TAZE metadata çeker (bkz. proje notları madde
    "Verification": "upload response geldi diye VERIFIED deme")."""
    r = httpx.get(f"{DRIVE_API}/files/{file_id}", headers=_headers(), params={"fields": fields}, timeout=30)
    r.raise_for_status()
    return r.json()
