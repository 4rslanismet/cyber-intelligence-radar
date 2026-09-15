"""Telegram bot bildirimi. E-posta yerine Telegram tercih edildi çünkü tek
HTTP isteğiyle çalışır, ekstra SMTP/kimlik doğrulama derdi yok."""
from __future__ import annotations

import json
import re
import time

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from . import config

_TELEGRAM_MAX_LEN = 4096
# Telegram Bot API tek bir chat'e karşı ~1 mesaj/sn önerir; uzun brifingler
# _chunk() ile birden fazla mesaja bölündüğünde aralarında bekleme olmadan
# art arda göndermek 429 (Too Many Requests) riski taşır - bkz. aşağıdaki
# send_telegram: chunk'lar arasına bu kadar bekleme konuyor.
_CHUNK_INTERVAL_SECONDS = 1.1
# Her chunk'ın başına eklenen "{başlık} [i/N]" sayfa etiketi için ayrılan pay
# (2026-09-10 kök neden analizi: bu etiket EKLENDİKTEN SONRA _TELEGRAM_MAX_LEN'i
# aşmasın diye _chunk() bu payı düşülmüş bir boyutla çağrılır).
_PAGE_LABEL_RESERVE = 40

# Semantic chunking sınır önceliği (2026-09-10 kök neden analizi: eski
# _chunk() karakter sayısına göre KÖRÜNE `text[i:i+size]` kesiyordu - bir
# kaydın/bölümün ortasında kesme örneği canlıda görüldü: "📚 Oku Şimdi:
# TagZilla: ... Threat Re..."). Öncelik: kategori başlığı -> makale/haber
# ayracı (digest.py'nin zaten kullandığı '----') -> paragraf. Hiçbiri
# sığdırmıyorsa (tek bir blok tek başına size'dan büyük - çok nadir) son
# çare olarak KELİME sınırında bölünür, kelimenin ortasında ASLA kesilmez.
_CHUNK_BOUNDARIES = ["\n## ", "\n----", "\n\n"]


def _group_by_boundary(text: str, size: int, sep: str) -> list[str]:
    """sep'e göre ayırır, ardışık parçaları size sınırını aşmayacak şekilde
    gruplar (küçük bölümler aynı chunk'ta birleşir - gereksiz yere N kat
    fazla mesaj gitmesin diye). Tek bir parça sep'siz bile size'dan büyükse
    olduğu gibi bırakılır - çağıran taraf bir sonraki, daha ince sınırla
    tekrar dener."""
    pieces = text.split(sep)
    groups: list[str] = []
    current = pieces[0]
    for p in pieces[1:]:
        # ÖNEMLİ: p, orijinal metinde HER ZAMAN sep'ten SONRA geliyordu - yeni
        # bir grup olarak başlarsa (merge edilmezse) sep'i KENDİSİNE geri
        # eklemek gerekir, yoksa "\n## " gibi ayraçlar sessizce KAYBOLUR
        # (bir önceki hatalı sürümde tam olarak bu oluyordu - "## Kategori B"
        # başlığının "## " kısmı gövdeye hiç eklenmiyordu).
        piece_with_sep = sep + p
        candidate = current + piece_with_sep
        if len(candidate) <= size:
            current = candidate
        else:
            groups.append(current)
            current = piece_with_sep
    groups.append(current)
    return groups


def _word_wrap(text: str, size: int) -> list[str]:
    """Son çare: hiçbir '## '/'----'/'\\n\\n' sınırı içermeyen TEK bir blok
    hâlâ size'dan büyükse (nadiren - çok uzun bir tek paragraf), kelime
    sınırında böler. Kelimenin ortasında ASLA kesmez (tek bir kelimenin
    KENDİSİ size'dan uzunsa - ör. çok uzun bir URL - bundan kaçış yok, sert
    kesilir)."""
    words = text.split(" ")
    chunks: list[str] = []
    current = ""
    for w in words:
        candidate = f"{current} {w}" if current else w
        if len(candidate) <= size:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = w
        while len(current) > size:
            chunks.append(current[:size])
            current = current[size:]
    if current:
        chunks.append(current)
    return chunks


def _is_retryable(exc: BaseException) -> bool:
    """academic.py'daki aynı prensip: 429/5xx geçici, retry+backoff'a değer;
    diğer 4xx'ler (ör. yanlış chat_id) kalıcı, tekrar denemek sonucu
    değiştirmez."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return isinstance(exc, httpx.HTTPError)


def _chunk(text: str, size: int = _TELEGRAM_MAX_LEN) -> list[str]:
    """Semantic chunking (bkz. proje notları, 2026-09-10 kök neden analizi):
    hiçbir kayıt/bölüm kelimenin veya bölümün ortasında kesilmemeli. Sırayla
    _CHUNK_BOUNDARIES'teki sınırlarda böler, sığan komşu bloklar birleşir;
    hâlâ size'ı aşan bir blok kalırsa bir sonraki (daha ince) sınırla tekrar
    denenir, en sonunda hiçbiri yetmezse kelime sınırında böler."""
    if not text:
        return [text]
    pending = [text]
    for sep in _CHUNK_BOUNDARIES:
        next_pending: list[str] = []
        for block in pending:
            if len(block) <= size:
                next_pending.append(block)
            else:
                next_pending.extend(_group_by_boundary(block, size, sep))
        pending = next_pending

    final: list[str] = []
    for block in pending:
        final.extend([block] if len(block) <= size else _word_wrap(block, size))
    return final or [text]


def _plain_text(md: str) -> str:
    """digest.py'ın ürettiği markdown'ı Telegram'a parse_mode OLMADAN
    gönderilecek okunur düz metne çevirir. parse_mode=Markdown bilinçli
    olarak KULLANILMIYOR: Telegram'ın eski Markdown'ı serbest metindeki
    kaçışsız '_', '(', ')' gibi karakterlerde "can't parse entities" (400)
    hatasıyla mesajı tamamen reddediyor - gerçek bir koşuda başımıza geldi.
    MarkdownV2 doğru kaçışlama ister ki bu da digest çıktısı gibi serbest
    metin için kırılgan; en sağlam çözüm parse_mode'suz düz metin."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", md)  # **kalın** -> kalın
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)  # # Başlık -> Başlık
    return text


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
def _post_telegram(url: str, data: dict) -> httpx.Response:
    resp = httpx.post(url, data=data, timeout=15.0)
    resp.raise_for_status()
    return resp


def send_telegram(text: str, silent: bool = False) -> bool:
    """`silent`: 2026-09-13 recovery backfill için eklendi (spec S: "Recovery
    sırasında Telegram spam yapma") - True iken HİÇBİR HTTP isteği atmadan
    True döner (mesaj zaten data/reports/recovery/'ye dosya olarak yazılmış
    olur, bkz. src/recovery/). Normal pipeline/digest çağrıları asla
    silent=True geçmez - varsayılan davranış BİREBİR korunur."""
    if silent:
        return True
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    plain = _plain_text(text)
    # Sayfa etiketi ("{başlık} [i/N]") her chunk'a EKLENECEĞİ için, chunk'ları
    # bu etiket eklendikten SONRA da _TELEGRAM_MAX_LEN altında kalacak şekilde
    # (etiket payı düşülmüş bir boyutla) bölüyoruz - bkz. proje notları.
    title_line = plain.split("\n", 1)[0].strip() or "Cyber Intelligence Radar"
    reserve = len(title_line) + _PAGE_LABEL_RESERVE
    chunks = _chunk(plain, size=max(500, _TELEGRAM_MAX_LEN - reserve))
    total = len(chunks)
    ok = True
    for i, chunk in enumerate(chunks, 1):
        if i > 1:
            time.sleep(_CHUNK_INTERVAL_SECONDS)
        body = chunk if total == 1 else f"{title_line} [{i}/{total}]\n\n{chunk}"
        try:
            _post_telegram(url, {"chat_id": config.TELEGRAM_CHAT_ID, "text": body})
        except httpx.HTTPError:
            ok = False
    return ok


# ---------------------------------------------------------------------------
# Faz 5 "geri bildirim döngüsü": tek bir makale/habere ait, buton'lu (inline
# keyboard) ayrı bir mesaj. Ana brifingden BİLİNÇLİ olarak ayrı - ana brifing
# tek parça düz metin (yukarıdaki _plain_text/_chunk mantığı), butonlar tek
# bir mesaja bağlanır, koca bir metin bloğunun ortasına iliştirilemez.
# send_telegram gibi parse_mode kullanmıyor (aynı "kaçışsız karakter" riski).
# ---------------------------------------------------------------------------
def send_interactive(text: str, buttons: list[list[tuple[str, str]]]) -> int | None:
    """buttons: satır satır [(görünen_metin, callback_data), ...].
    callback_data Telegram'da 64 byte sınırlı - kısa tutun (ör. "p:161:u").
    Başarılıysa Telegram message_id döner (telegram_message_map için),
    aksi halde None (bot/chat ayarlı değilse ya da istek başarısızsa).

    text ve keyboard AYNI mesajda kalmalı (Telegram inline keyboard tek
    bir mesajın reply_markup'ına bağlıdır, bölünemez - bkz. proje notları,
    2026-09-11 anchor-mesaj düzeltmesi) - bu yüzden aşan metin kelime
    sınırında GÜVENLE kısaltılır (karakter ortasında ASLA kesilmez),
    _chunk()'taki _word_wrap ile AYNI ilke."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return None
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    keyboard = {
        "inline_keyboard": [
            [{"text": label, "callback_data": data} for label, data in row]
            for row in buttons
        ]
    }
    safe_text = text
    if len(text) > _TELEGRAM_MAX_LEN:
        wrapped = _word_wrap(text, _TELEGRAM_MAX_LEN - 10)
        safe_text = wrapped[0] if wrapped else text[:_TELEGRAM_MAX_LEN]
    try:
        resp = _post_telegram(
            url,
            {
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": safe_text,
                "reply_markup": json.dumps(keyboard),
            },
        )
        return resp.json().get("result", {}).get("message_id")
    except httpx.HTTPError:
        return None


def feedback_buttons(prefix: str, item_id: int, notes: bool = False) -> list[list[tuple[str, str]]]:
    """prefix: 'p' (paper) | 'n' (news). callback_data formatı: "{prefix}:{id}:{aksiyon}"
    - bkz. telegram_listener.py'nin bunu nasıl çözümlediği.
    notes=True: 📝/💡 satırını da ekler (yalnızca makaleler için anlamlı -
    run_pipeline.py haberlerde notes=False geçer)."""
    rows = [
        [("👍 Faydalı", f"{prefix}:{item_id}:u"), ("👎 Gereksiz", f"{prefix}:{item_id}:x")],
        [("⭐ Çok önemli", f"{prefix}:{item_id}:i"), ("📌 Sonra oku", f"{prefix}:{item_id}:l")],
        [("✅ Okudum", f"{prefix}:{item_id}:d"), ("🚫 Bir daha gösterme", f"{prefix}:{item_id}:z")],
    ]
    if notes:
        rows.append([("📝 Not ekle", f"{prefix}:{item_id}:note"), ("💡 Fikir ekle", f"{prefix}:{item_id}:idea")])
        # Research Collections (bkz. src/research/collections.py) - SADECE
        # makalelerde (notes=True ile aynı koşul, haberlerde anlamsız).
        # Toggle butonları: basınca ekler/çıkarır, _handle_callback bunu
        # collections.toggle_collection ile çözer.
        rows.append([("📄 SCI'ya Ekle/Çıkar", f"{prefix}:{item_id}:csci"), ("🎓 Teze Ekle/Çıkar", f"{prefix}:{item_id}:cthe")])
        rows.append([("👀 Merak Listesi", f"{prefix}:{item_id}:ccur"), ("🔎 Benzerlerini Tara", f"{prefix}:{item_id}:csim")])
    return rows


def spaced_repetition_buttons(schedule_id: int) -> list[list[tuple[str, str]]]:
    """callback_data formatı: "r:{schedule_id}:{y|n}" - paper_id'ye değil
    doğrudan spaced_repetition_schedule satırına işaret eder, çünkü aynı
    makalenin birden fazla bekleyen (1/3/7/21 gün) satırı olabilir."""
    return [[("✅ Hatırlıyorum", f"r:{schedule_id}:y"), ("❌ Unuttum", f"r:{schedule_id}:n")]]
