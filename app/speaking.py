"""Sprechen: a plan for speaking practice with a partner (no microphone, no grading).

The guide combines hand-written material per lesson (`seed/speaking.json`: focus, challenge,
questions for the partner, a role play) with the learner's own state: the lesson's Redemittel and
grammar notes, words still being learned (use them out loud) and the most frequent mistakes.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .db import row_to_dict, rows_to_dicts, transaction
from .drills import top_errors

SEED_PATH = Path(__file__).resolve().parent / "seed" / "speaking.json"
WORDS_TO_USE = 8

PARTNER_TIPS = [
    "Speak slowly and simply. Short questions are better than long ones.",
    "Let them finish the sentence, even when it takes a while. Silence is fine.",
    "Correct at most one thing per answer: repeat the sentence the right way, then move on.",
    "Ask a follow-up: Warum? Und dann? Wie war das?",
    "Write down 2-3 mistakes you hear and go through them at the end.",
]


def _seed() -> dict:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))["lessons"]


def words_to_use(conn: sqlite3.Connection, lesson_number: int, limit: int = WORDS_TO_USE) -> list[dict]:
    """Words met but not yet sure, newest first: saying them out loud helps them stick."""
    return rows_to_dicts(conn.execute(
        """SELECT m.id, m.lemma, m.pos, m.article, m.gloss_es, m.gloss_en
           FROM known_word k JOIN lemma m ON m.id = k.lemma_id
           LEFT JOIN lesson l ON l.id = m.lesson_id
           WHERE k.state = 'learning' AND k.ladder_step >= 1 AND (l.number IS NULL OR l.number <= ?)
           ORDER BY k.ladder_since DESC, m.id LIMIT ?""", (lesson_number, limit)).fetchall())


def guide(conn: sqlite3.Connection, lesson_number: int | None = None) -> dict:
    current = conn.execute("SELECT current_lesson FROM settings WHERE id = 1").fetchone()[0]
    number = lesson_number or current
    lesson = row_to_dict(conn.execute(
        "SELECT id, number, title, theme, grammar_points, redemittel FROM lesson WHERE number = ?",
        (number,)).fetchone())
    if not lesson:
        raise LookupError(number)
    codes = json.loads(lesson["grammar_points"]) if isinstance(lesson["grammar_points"], str) else lesson["grammar_points"]
    grammar = rows_to_dicts(conn.execute(
        "SELECT code, name, rule, example, warning FROM grammar_point WHERE code IN (%s)" % ",".join("?" * len(codes)),
        codes).fetchall()) if codes else []
    grammar.sort(key=lambda g: codes.index(g["code"]))
    plan = _seed().get(str(number)) or {
        "focus": f"Talk about the lesson topic: {lesson['theme']}.",
        "challenge": "Use each sentence starter below at least once.",
        "questions": [], "roleplay": None}
    redemittel = json.loads(lesson["redemittel"]) if isinstance(lesson["redemittel"], str) else lesson["redemittel"]
    errors = [e for e in top_errors(conn, 4) if e["grammar_code"] or e["lemma"]]
    sessions = conn.execute("SELECT COUNT(*), COALESCE(SUM(minutes), 0) FROM speaking_log").fetchone()
    return {
        "lesson": {"number": lesson["number"], "title": lesson["title"], "theme": lesson["theme"]},
        "current_lesson": current,
        "lessons": [r[0] for r in conn.execute("SELECT number FROM lesson WHERE number <= ? ORDER BY number",
                                                (current,))],
        "focus": plan["focus"], "challenge": plan["challenge"],
        "questions": plan["questions"], "roleplay": plan.get("roleplay"),
        "redemittel": redemittel, "grammar": grammar,
        "words": words_to_use(conn, number), "errors": errors,
        "partner_tips": PARTNER_TIPS,
        "history": {"sessions": sessions[0], "minutes": sessions[1],
                    "recent": rows_to_dicts(conn.execute(
                        """SELECT s.minutes, s.note, s.ts, l.number AS lesson_number FROM speaking_log s
                           LEFT JOIN lesson l ON l.id = s.lesson_id ORDER BY s.id DESC LIMIT 5""").fetchall())},
    }


def log(conn: sqlite3.Connection, *, lesson_number: int, minutes: int, note: str | None = None) -> dict:
    lid = conn.execute("SELECT id FROM lesson WHERE number = ?", (lesson_number,)).fetchone()
    with transaction(conn):
        cur = conn.execute("INSERT INTO speaking_log (lesson_id, minutes, note) VALUES (?, ?, ?)",
                           (lid[0] if lid else None, minutes, (note or "").strip()[:500] or None))
    return {"id": cur.lastrowid}
