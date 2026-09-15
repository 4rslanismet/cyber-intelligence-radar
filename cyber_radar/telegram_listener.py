"""Faz 5 "geri bildirim döngüsü": Telegram'dan GELEN buton tıklamalarını ve
yanıtları (reply) dinleyen, sürekli çalışan tek servis.

Diğer her şeyden (run_pipeline.py, kev_watch.py, weekly_digest.py) BİLİNÇLİ
olarak farklı: onlar systemd TIMER ile tetiklenen, işini bitirip çıkan
oneshot script'ler. Bu ise Telegram'ın `getUpdates` (long polling) uç
noktasını sürekli yoklaması gereken, hep açık kalan bir servis - bu yüzden
`cyber-radar-telegram-listener.service` (Type=simple, Restart=always) ile
çalıştırılır, timer'ı yok.

Long polling seçildi (webhook DEĞİL): webhook için public HTTPS + geçerli
TLS sertifikası + reverse proxy gerekir; long polling'de sunucu SADECE
dışarı istek atar, gelen firewall kuralı/sertifika derdi yok.

Kullanım: python3 -m src.telegram_listener
Zamanlama: systemd/cyber-radar-telegram-listener.service (sürekli)
"""
from __future__ import annotations

import time

import httpx

from . import config, db, ranking
from .research import collections

_POLL_TIMEOUT = 30  # Telegram'ın long-poll bekleme süresi (saniye)
_STATE_KEY = "telegram_update_offset"

_ACTION_FEEDBACK = {
    "u": "useful",
    "x": "not_useful",
    "i": "important",
    "l": "later",
    "z": "never_show",
}

# Okuma durumu state machine (yalnızca ilerleyen yönde - bkz. proje isteği
# UNREAD -> SAVED -> READING -> COMPLETED, yan dallar: skipped/abandoned).
# 👎 şimdilik reading_status'u değiştirmiyor (sadece feedback='not_useful'
# yazıyor) - "gereksiz" demek "atlandı" demek değil, hâlâ okunabilir.
_STATUS_BY_ACTION = {
    "l": "saved",       # 📌 Sonra oku
    "d": "completed",   # ✅ Okudum
    "z": "abandoned",   # 🚫 Bir daha gösterme
}

# Research Collections toggle aksiyonları (bkz. src/research/collections.py,
# notify.feedback_buttons) - action kodu -> collection adı.
_COLLECTION_ACTIONS = {"csci": collections.SCI, "cthe": collections.THESIS, "ccur": collections.CURIOSITY}


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"


def _answer_callback(callback_id: str, text: str) -> None:
    try:
        httpx.post(_api("answerCallbackQuery"), data={"callback_query_id": callback_id, "text": text}, timeout=15.0)
    except httpx.HTTPError:
        pass  # kullanıcıya sadece "yükleniyor" spinner'ı biraz uzun sürer, kritik değil


def _ask_for_text(chat_id: str, prompt: str) -> int | None:
    try:
        resp = httpx.post(_api("sendMessage"), data={"chat_id": chat_id, "text": prompt}, timeout=15.0)
        resp.raise_for_status()
        return resp.json().get("result", {}).get("message_id")
    except httpx.HTTPError:
        return None


def _handle_spaced_repetition_answer(conn, cq: dict, schedule_id_str: str, answer: str) -> None:
    """callback_data="r:{schedule_id}:{y|n}" - bkz. notify.spaced_repetition_buttons.
    paper_id'ye değil DOĞRUDAN schedule satırına işaret eder (aynı makalenin
    birden fazla bekleyen 1/3/7/21 günlük satırı olabileceği için)."""
    if not schedule_id_str.isdigit() or answer not in ("y", "n"):
        return
    conn.execute(
        "UPDATE spaced_repetition_schedule SET remembered = %s WHERE id = %s",
        (answer == "y", int(schedule_id_str)),
    )
    _answer_callback(cq["id"], "✅ Hatırlıyorsun, harika!" if answer == "y" else "❌ Not edildi - bu konuyu tekrar gözden geçir.")


def _handle_callback(conn, cq: dict) -> None:
    data = cq.get("data") or ""
    parts = data.split(":")
    if len(parts) != 3:
        return
    prefix, item_id_str, action = parts

    if prefix == "r":
        _handle_spaced_repetition_answer(conn, cq, item_id_str, action)
        return

    if prefix not in ("p", "n") or not item_id_str.isdigit():
        return
    item_id = int(item_id_str)
    table = "papers" if prefix == "p" else "news_events"
    chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))

    # 📝 Not Ekle / 💡 Fikir Ekle: hemen DB yazmıyoruz - kullanıcıdan metin
    # istiyoruz, o mesajın ID'sini telegram_message_map'e field ile
    # kaydediyoruz ki _handle_reply gelen yanıtı doğru kolona yazsın.
    if action in ("note", "idea") and prefix == "p":
        field = "my_note" if action == "note" else "research_idea"
        label = "📝 Notunu yaz" if action == "note" else "💡 Fikrini yaz"
        msg_id = _ask_for_text(chat_id, f"{label} ve BU MESAJA yanıt (reply) olarak gönder:")
        if msg_id:
            conn.execute(
                "INSERT INTO telegram_message_map (message_id, item_type, item_id, field) VALUES (%s, 'paper', %s, %s)",
                (msg_id, item_id, field),
            )
        _answer_callback(cq["id"], "Yanıtını bekliyorum...")
        return

    # Research Collections (bkz. src/research/collections.py) - feedback/
    # reading_status/relevance/screening'den TAMAMEN AYRI, sadece makalelerde.
    # csci/cthe/ccur: toggle (yok->ekle, varsa->çıkar). csim: 🔎 Benzerlerini
    # Tara - manuel snowball seed kuyruğuna ekler, DAHA FAZLA Gemini çağrısı
    # TETİKLEMEZ (kuyruk sadece işaretlenir, işleme ayrı bir CLI/koşuda olur).
    if action in _COLLECTION_ACTIONS and prefix == "p":
        added = collections.toggle_collection(conn, item_id, _COLLECTION_ACTIONS[action])
        label = {"csci": "SCI", "cthe": "Tez", "ccur": "Merak Listesi"}[action]
        _answer_callback(cq["id"], f"{'➕ ' + label + ' koleksiyonuna eklendi' if added else '➖ ' + label + ' koleksiyonundan çıkarıldı'}")
        return
    if action == "csim" and prefix == "p":
        collections.request_snowball_seed(conn, item_id)
        _answer_callback(cq["id"], "🔎 Benzer makaleler için kuyruğa eklendi.")
        return

    # 1) Okuma durumu state machine'i (yalnızca l/d/z bir durum değişikliği
    # tetikler - 👍/👎/⭐ salt nitel geri bildirimdir, durum değiştirmez).
    new_status = _STATUS_BY_ACTION.get(action)
    if new_status == "completed":
        conn.execute(
            f"UPDATE {table} SET reading_status = 'completed', completed_at = now(), "
            "started_at = COALESCE(started_at, now()) WHERE id = %s",
            (item_id,),
        )
    elif new_status:
        conn.execute(f"UPDATE {table} SET reading_status = %s WHERE id = %s", (new_status, item_id))

    # 2) `feedback` kolonu yalnızca nitel etiketler için (useful/not_useful/
    # important/later/never_show) - "done" bunlardan biri DEĞİL, o yüzden
    # buraya yazılmıyor (aksi halde ⭐ sonra ✅ basılırsa "important" etiketi
    # sessizce "done" ile ezilirdi).
    feedback_label = _ACTION_FEEDBACK.get(action)
    if feedback_label:
        conn.execute(f"UPDATE {table} SET feedback = %s WHERE id = %s", (feedback_label, item_id))

    # 3) Kişisel sıralamaya (ranking.py) HER aksiyon (done dahil) puan olarak
    # yansır - bkz. ranking.FEEDBACK_POINTS. Bu, feedback kolonundan bağımsız.
    ranking_action = feedback_label or ("done" if action == "d" else None)
    if ranking_action:
        if prefix == "p":
            ranking.apply_paper_feedback(conn, item_id, ranking_action)
        else:
            ranking.apply_news_feedback(conn, item_id, ranking_action)

    if action == "d" and prefix == "p":
        ranking.schedule_spaced_repetition(conn, item_id)

    confirm = {"d": "✅ Okundu olarak işaretlendi", "z": "🚫 Bir daha gösterilmeyecek"}.get(action, "Kaydedildi, teşekkürler!")
    _answer_callback(cq["id"], confirm)


def _handle_reply(conn, message: dict) -> None:
    """Kullanıcı, notify.send_interactive() (ya da _ask_for_text) ile
    gönderilmiş bir mesaja REPLY yaptıysa, telegram_message_map üzerinden
    hangi makaleye/habere ve hangi ALANA (field - my_note/research_idea)
    ait olduğunu bulup metni oraya yazar. field NULL ise (normal bir
    brifing/öğe mesajıysa) varsayılan olarak my_note'a yazılır."""
    reply_to = message.get("reply_to_message")
    text = message.get("text")
    if not reply_to or not text:
        return
    mapped = conn.execute(
        "SELECT item_type, item_id, field FROM telegram_message_map WHERE message_id = %s", (reply_to["message_id"],)
    ).fetchone()
    if not mapped:
        return
    field = mapped["field"] or "my_note"
    if field not in ("my_note", "research_idea"):
        field = "my_note"
    table = "papers" if mapped["item_type"] == "paper" else "news_events"
    if field == "research_idea" and table != "papers":
        field = "my_note"  # news_events'te research_idea kolonu yok
    conn.execute(f"UPDATE {table} SET {field} = %s WHERE id = %s", (text, mapped["item_id"]))
    label = "💡 Fikrin" if field == "research_idea" else "📝 Notun"
    try:
        httpx.post(
            _api("sendMessage"),
            data={"chat_id": config.TELEGRAM_CHAT_ID, "text": f"{label} kaydedildi."},
            timeout=15.0,
        )
    except httpx.HTTPError:
        pass


def _process_update(conn, update: dict) -> None:
    chat_id = None
    if "callback_query" in update:
        chat_id = str(update["callback_query"].get("message", {}).get("chat", {}).get("id", ""))
    elif "message" in update:
        chat_id = str(update["message"].get("chat", {}).get("id", ""))

    # Güvenlik: sadece kendi TELEGRAM_CHAT_ID'mizden gelen etkileşimleri işle.
    if chat_id != str(config.TELEGRAM_CHAT_ID):
        return

    if "callback_query" in update:
        _handle_callback(conn, update["callback_query"])
    elif "message" in update:
        _handle_reply(conn, update["message"])


def run_forever() -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[HATA] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID tanımlı değil, listener başlatılamıyor.")
        return

    with db.get_conn() as conn:
        offset_str = db.get_state(conn, _STATE_KEY)
    offset = int(offset_str) + 1 if offset_str else None

    print("Telegram listener başladı (long polling).")
    while True:
        try:
            params = {"timeout": _POLL_TIMEOUT, "allowed_updates": '["message","callback_query"]'}
            if offset is not None:
                params["offset"] = offset
            resp = httpx.get(_api("getUpdates"), params=params, timeout=_POLL_TIMEOUT + 10)
            resp.raise_for_status()
            updates = resp.json().get("result", [])
        except httpx.HTTPError as e:
            print(f"[UYARI] getUpdates başarısız: {e}, 10sn sonra tekrar denenecek.")
            time.sleep(10)
            continue

        if not updates:
            continue

        with db.get_conn() as conn:
            for update in updates:
                try:
                    _process_update(conn, update)
                except Exception as e:  # noqa: BLE001 - tek update hatası servisi durdurmasın
                    print(f"[UYARI] update işlenemedi ({update.get('update_id')}): {e}")
                offset = update["update_id"] + 1
            db.set_state(conn, _STATE_KEY, str(offset - 1))


if __name__ == "__main__":
    run_forever()
