"""Progress view: known words, due cards, streak, per-lesson mastery, errors, reading speed, activity."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from . import srs
from .db import rows_to_dicts
from .drills import top_errors

MASTERY_TO_ADVANCE = 0.8   # depth before breadth: suggest the next lesson at 80 % of words stable

# Every learning event, as (UTC timestamp) rows; days are counted in local time.
ACTIVITY_SQL = """
SELECT ts FROM review_log
UNION ALL SELECT ts FROM drill_attempt
UNION ALL SELECT ts FROM writing
UNION ALL SELECT ts FROM reading_log
"""


def activity_by_day(conn: sqlite3.Connection, days: int = 14) -> list[dict]:
    counts = {r[0]: r[1] for r in conn.execute(
        f"SELECT date(ts, 'localtime') AS d, COUNT(*) FROM ({ACTIVITY_SQL}) GROUP BY d")}
    today = date.fromisoformat(conn.execute("SELECT date('now', 'localtime')").fetchone()[0])
    return [{"day": (d := (today - timedelta(days=i)).isoformat()), "count": counts.get(d, 0)}
            for i in range(days - 1, -1, -1)]


def streak(conn: sqlite3.Connection) -> int:
    """Consecutive active days ending today (or yesterday, so the streak isn't lost before you start today)."""
    active = {r[0] for r in conn.execute(f"SELECT DISTINCT date(ts, 'localtime') FROM ({ACTIVITY_SQL})")}
    day = date.fromisoformat(conn.execute("SELECT date('now', 'localtime')").fetchone()[0])
    if day.isoformat() not in active:
        day -= timedelta(days=1)
    n = 0
    while day.isoformat() in active:
        n += 1
        day -= timedelta(days=1)
    return n


def done_today(conn: sqlite3.Connection) -> dict[str, bool]:
    q = lambda table: conn.execute(  # noqa: E731
        f"SELECT 1 FROM {table} WHERE date(ts, 'localtime') = date('now', 'localtime') LIMIT 1").fetchone() is not None
    reread = conn.execute("""SELECT 1 FROM reading_log WHERE kind = 'reread'
                             AND date(ts, 'localtime') = date('now', 'localtime') LIMIT 1""").fetchone() is not None
    read = conn.execute("""SELECT 1 FROM reading_log WHERE kind = 'read'
                           AND date(ts, 'localtime') = date('now', 'localtime') LIMIT 1""").fetchone() is not None
    wrote = lambda kind: conn.execute(  # noqa: E731
        """SELECT 1 FROM writing WHERE kind = ? AND date(ts, 'localtime') = date('now', 'localtime')
           LIMIT 1""", (kind,)).fetchone() is not None
    return {"warmup": reread, "review": q("review_log"), "text": read, "drill": q("drill_attempt"),
            "write": wrote("write"), "speak": wrote("speak")}


def lesson_mastery(conn: sqlite3.Connection) -> list[dict]:
    return rows_to_dicts(conn.execute(
        """SELECT l.number, l.title, l.theme, l.status, l.book, COUNT(m.id) AS words,
                  SUM(k.state = 'known') AS known, SUM(k.state = 'learning') AS learning
           FROM lesson l LEFT JOIN lemma m ON m.lesson_id = l.id LEFT JOIN known_word k ON k.lemma_id = m.id
           GROUP BY l.id ORDER BY l.number""").fetchall())


def reading_speed(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    return list(reversed(rows_to_dicts(conn.execute(
        """SELECT r.wpm, r.kind, r.ts, t.title FROM reading_log r JOIN text t ON t.id = r.text_id
           WHERE r.wpm IS NOT NULL ORDER BY r.id DESC LIMIT ?""", (limit,)).fetchall())))


def review_accuracy(conn: sqlite3.Connection, days: int = 7) -> float | None:
    since = srs.to_db(srs.now_utc() - timedelta(days=days))
    row = conn.execute("SELECT COUNT(*), SUM(rating >= 3) FROM review_log WHERE ts >= ?", (since,)).fetchone()
    return round(row[1] / row[0], 2) if row[0] else None


def summary(conn: sqlite3.Connection) -> dict:
    lessons = lesson_mastery(conn)
    for l in lessons:
        l["known"] = l["known"] or 0
        l["learning"] = l["learning"] or 0
        l["mastery"] = round(l["known"] / l["words"], 3) if l["words"] else 0.0
    current = conn.execute("SELECT current_lesson FROM settings WHERE id = 1").fetchone()[0]
    cur = next(l for l in lessons if l["number"] == current)
    return {
        "known_words": conn.execute("SELECT COUNT(*) FROM known_word WHERE state = 'known'").fetchone()[0],
        "learning_words": conn.execute("SELECT COUNT(*) FROM known_word WHERE state = 'learning'").fetchone()[0],
        "cards_due": srs.due_count(conn),
        "streak": streak(conn),
        "done_today": done_today(conn),
        "activity": activity_by_day(conn),
        "lessons": lessons,
        "current_lesson": current,
        "ready_for_next": current < max(l["number"] for l in lessons) and cur["mastery"] >= MASTERY_TO_ADVANCE,
        "top_errors": top_errors(conn, 5),
        "reading_speed": reading_speed(conn),
        "review_accuracy_7d": review_accuracy(conn),
        "texts_read": conn.execute("SELECT COUNT(*) FROM text WHERE read_count > 0").fetchone()[0],
        "writings": conn.execute("SELECT COUNT(*) FROM writing").fetchone()[0],
    }
