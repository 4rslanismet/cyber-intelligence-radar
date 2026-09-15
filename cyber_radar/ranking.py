"""Faz 6 "kişisel sıralama" + "spaced repetition".

Bilinçli mimari karar: kullanıcının tercih profili LLM'e HİÇ danışılmadan,
Telegram buton davranışından (bkz. telegram_listener.py) deterministik Python
koduyla hesaplanır. Böylece Gemini modeli değişse/güncellense bile kullanıcının
profili sabit kalır - "içerik analizi" (LLM) ve "kullanıcı davranışı" (bu
modül) bilinçli olarak ayrı katmanlar.

    Gemini/LLM  -> content analysis (domain_contribution_scores, paper_role, ...)
    Python/DB   -> user behavior (bu modül)   -> personal ranking
"""
from __future__ import annotations

from datetime import timedelta

# Buton başına sabit puan - "neden bu sayı" sorusunun cevabı burada, kullanıcı
# tarafından belirlendi. LLM'in ürettiği herhangi bir skorla karıştırılmaz.
FEEDBACK_POINTS = {
    "useful": 1,        # 👍 Faydalı
    "important": 3,     # ⭐ Çok Faydalı
    "done": 1,          # ✅ Okudum
    "later": 1,         # 📌 Sonra Oku
    "not_useful": -3,   # 👎 Gereksiz
    "never_show": -8,   # 🚫 Bir daha gösterme
}

# Bir domain/role'e puan yansıtmak için domain_contribution_scores eşiği
# (10 üzerinden) - gürültülü/ilgisiz boyutlara puan sızmasın diye.
_DOMAIN_THRESHOLD = 5
_ROLE_WEIGHT = 0.5  # rol sinyali domain kadar güçlü değil, daha düşük ağırlık

_SPACED_INTERVALS = [1, 3, 7, 21]


def _bump(conn, dimension: str, key: str, delta: float) -> None:
    conn.execute(
        """
        INSERT INTO personal_preference_scores (dimension, key, score, updated_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (dimension, key) DO UPDATE
        SET score = personal_preference_scores.score + EXCLUDED.score, updated_at = now()
        """,
        (dimension, key, delta),
    )


def apply_paper_feedback(conn, paper_id: int, action: str) -> None:
    """⭐ Çok Faydalı -> paper'ın domain_contribution_scores'undaki her
    anlamlı (>=5) alana ağırlıklı puan, paper_role'lerine daha hafif puan.
    Örnek: CTI=10/10 olan bir makaleye ⭐ (+3) basılırsa CTI +3.0 alır;
    SOC=6/10 ise SOC +1.8 alır (3 * 6/10)."""
    points = FEEDBACK_POINTS.get(action)
    if points is None:
        return
    conn.execute(
        "INSERT INTO personal_feedback_log (item_type, item_id, action, points) VALUES ('paper', %s, %s, %s)",
        (paper_id, action, points),
    )
    row = conn.execute("SELECT analysis FROM papers WHERE id = %s", (paper_id,)).fetchone()
    a = (row["analysis"] if row else None) or {}

    for domain, score in (a.get("domain_contribution_scores") or {}).items():
        if score and score >= _DOMAIN_THRESHOLD:
            _bump(conn, "domain", domain, points * (score / 10))

    for role in a.get("paper_role") or []:
        _bump(conn, "paper_role", role, points * _ROLE_WEIGHT)


def apply_news_feedback(conn, news_id: int, action: str) -> None:
    points = FEEDBACK_POINTS.get(action)
    if points is None:
        return
    conn.execute(
        "INSERT INTO personal_feedback_log (item_type, item_id, action, points) VALUES ('news', %s, %s, %s)",
        (news_id, action, points),
    )
    row = conn.execute("SELECT analysis FROM news_events WHERE id = %s", (news_id,)).fetchone()
    event_type = ((row["analysis"] if row else None) or {}).get("event_type")
    if event_type:
        _bump(conn, "news_event_type", event_type, points)


def top_preferences(conn, dimension: str, n: int = 10) -> list[dict]:
    return conn.execute(
        "SELECT key, score FROM personal_preference_scores WHERE dimension = %s ORDER BY score DESC LIMIT %s",
        (dimension, n),
    ).fetchall()


# ---------------------------------------------------------------------------
# Spaced repetition: her makale için değil, yalnızca MUST_READ veya
# "foundation" nitelikli olanlar için (kullanıcı isteği - "her makale için
# değil, MUST_READ ve FOUNDATIONAL için yeterli").
# ---------------------------------------------------------------------------
def _qualifies_for_spaced_repetition(analysis: dict) -> bool:
    if not analysis:
        return False
    if analysis.get("reading_priority") == "MUST_READ":
        return True
    if "FOUNDATION" in (analysis.get("paper_role") or []):
        return True
    if (analysis.get("foundational_value_score") or 0) >= 7:
        return True
    return False


def schedule_spaced_repetition(conn, paper_id: int) -> int:
    """Bir makale COMPLETED olduğunda çağrılır (bkz. telegram_listener.py).
    Uygun değilse hiçbir satır eklemez, 0 döner. ON CONFLICT DO NOTHING
    sayesinde aynı makale ikinci kez COMPLETED işaretlense de tekrar
    zamanlama oluşturulmaz (aynı paper_id+interval_days çifti tek satır)."""
    row = conn.execute("SELECT analysis, completed_at FROM papers WHERE id = %s", (paper_id,)).fetchone()
    if not row or not row["completed_at"] or not _qualifies_for_spaced_repetition(row["analysis"] or {}):
        return 0
    base = row["completed_at"]
    count = 0
    for days in _SPACED_INTERVALS:
        result = conn.execute(
            """
            INSERT INTO spaced_repetition_schedule (paper_id, interval_days, due_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (paper_id, interval_days) DO NOTHING
            RETURNING id
            """,
            (paper_id, days, base + timedelta(days=days)),
        ).fetchone()
        if result:
            count += 1
    return count
