"""Progress view: known words, due cards, streak, per-lesson mastery, errors, reading speed, activity."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from . import srs
from .db import rows_to_dicts
from .drills import top_errors

MASTERY_TO_ADVANCE = 0.8   # depth before breadth: suggest the next lesson at 80 % of words stable
TEXTS_PER_LESSON = 3       # narrow reading: 3-5 texts per lesson theme before moving on

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
            "write": wrote("write"), "listen": q("listen_log")}


def lesson_mastery(conn: sqlite3.Connection) -> list[dict]:
    return rows_to_dicts(conn.execute(
        """SELECT l.number, l.title, l.theme, l.status, l.book, COUNT(m.id) AS words,
                  SUM(k.state = 'known') AS known, SUM(k.state = 'learning') AS learning
           FROM lesson l LEFT JOIN lemma m ON m.lesson_id = l.id LEFT JOIN known_word k ON k.lemma_id = m.id
           GROUP BY l.id ORDER BY l.number""").fetchall())


def lesson_check(conn: sqlite3.Connection, number: int) -> dict:
    """How well the plan's ingredients have been covered for one lesson."""
    import json
    lid = conn.execute("SELECT id FROM lesson WHERE number = ?", (number,)).fetchone()[0]
    w = conn.execute(
        """SELECT COUNT(*) AS total, SUM(k.times_seen_in_text > 0) AS seen,
                  SUM(k.state = 'known') AS known, SUM(k.state = 'learning') AS learning
           FROM lemma m LEFT JOIN known_word k ON k.lemma_id = m.id
           WHERE m.lesson_id = ? AND m.pos != 'PHRASE'""", (lid,)).fetchone()
    texts = conn.execute("SELECT report_json, read_count FROM text WHERE lesson_id = ? AND kind = 'read'",
                         (lid,)).fetchall()
    texts_read = sum(1 for t in texts if t["read_count"])
    in_texts: dict[str, int] = {}
    for t in texts:
        if t["read_count"] and t["report_json"]:
            for code, used in (json.loads(t["report_json"]).get("target_grammar") or {}).items():
                in_texts[code] = in_texts.get(code, 0) + int(bool(used))
    codes = json.loads(conn.execute("SELECT grammar_points FROM lesson WHERE id = ?", (lid,)).fetchone()[0])
    grammar = []
    for code in codes:
        g = conn.execute(
            """SELECT g.name, COUNT(a.id) AS attempts, SUM(a.correct) AS right FROM grammar_point g
               LEFT JOIN drill_item i ON i.grammar_code = g.code LEFT JOIN drill_attempt a ON a.item_id = i.id
               WHERE g.code = ?""", (code,)).fetchone()
        grammar.append({"code": code, "name": g["name"], "attempts": g["attempts"],
                        "accuracy": round((g["right"] or 0) / g["attempts"], 2) if g["attempts"] else None,
                        "in_texts": in_texts.get(code, 0)})
    writings = conn.execute("SELECT COUNT(DISTINCT prompt) FROM writing WHERE lesson_id = ?", (lid,)).fetchone()[0]
    total = w["total"] or 0
    mastery = round((w["known"] or 0) / total, 3) if total else 0.0
    return {"number": number, "words_total": total, "words_seen": w["seen"] or 0, "words_known": w["known"] or 0,
            "words_learning": w["learning"] or 0, "mastery": mastery,
            "texts_read": texts_read, "texts_goal": TEXTS_PER_LESSON, "grammar": grammar,
            "writing_tasks_done": writings, "writing_tasks_goal": 3,
            "ready": mastery >= MASTERY_TO_ADVANCE and texts_read >= TEXTS_PER_LESSON}


def listening_stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute("""SELECT COUNT(DISTINCT text_id) AS tasks, SUM(correct) AS correct, SUM(total) AS total
                          FROM listen_log""").fetchone()
    return {"tasks": row["tasks"] or 0,
            "accuracy": round(row["correct"] / row["total"], 2) if row["total"] else None}


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
        "ready_for_next": current < max(l["number"] for l in lessons) and lesson_check(conn, current)["ready"],
        "current_check": lesson_check(conn, current),
        "top_errors": top_errors(conn, 5),
        "reading_speed": reading_speed(conn),
        "review_accuracy_7d": review_accuracy(conn),
        "texts_read": conn.execute("SELECT COUNT(*) FROM text WHERE read_count > 0 AND kind = 'read'").fetchone()[0],
        "listening": listening_stats(conn),
        "writings": conn.execute("SELECT COUNT(*) FROM writing").fetchone()[0],
    }
