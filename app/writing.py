"""Phase 5: short writing tasks with focused feedback (max 3 corrections, lesson grammar first).

Every listed correction feeds the error log: grammar errors raise that point's drill weight;
word errors (e.g. wrong article) make the word's production card due again.
"""

from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path

from . import srs
from .db import row_to_dict, rows_to_dicts, transaction
from .drills import log_error
from .llm import Writer, WritingFeedback

PROMPTS_PATH = Path(__file__).resolve().parent / "seed" / "writing_prompts.json"
MAX_CORRECTIONS = 3
MAX_CHARS = 1200


def prompts_for(lesson_number: int, conn: sqlite3.Connection | None = None) -> list[dict]:
    data = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))["prompts"]
    if str(lesson_number) in data or conn is None:
        return data.get(str(lesson_number), [])
    # lessons added later (e.g. Momente A2.2) get generic tasks built from their Redemittel
    lesson = row_to_dict(conn.execute("SELECT theme, redemittel FROM lesson WHERE number = ?",
                                      (lesson_number,)).fetchone())
    if not lesson:
        return []
    return [{"de": f"Schreib 3 Sätze zum Thema „{lesson['theme']}“. Benutz: „{r}“",
             "es": f"Escribe 3 frases sobre «{lesson['theme']}». Usa: «{r}»"} for r in lesson["redemittel"][:3]]


def next_prompt(conn: sqlite3.Connection, *, lesson_number: int | None = None, exclude: str | None = None,
                seed: int | None = None) -> dict:
    """The current lesson's task used least often (ties broken randomly), skipping `exclude`."""
    if lesson_number is None:
        lesson_number = conn.execute("SELECT current_lesson FROM settings WHERE id = 1").fetchone()[0]
    lesson = row_to_dict(conn.execute("SELECT * FROM lesson WHERE number = ?", (lesson_number,)).fetchone())
    all_prompts = prompts_for(lesson_number, conn)
    options = [p for p in all_prompts if p["de"] != exclude] or all_prompts
    used = {r[0]: r[1] for r in conn.execute("SELECT prompt, COUNT(*) FROM writing GROUP BY prompt")}
    rng = random.Random(seed)
    options.sort(key=lambda p: (used.get(p["de"], 0), rng.random()))
    p = options[0]
    return {"lesson_number": lesson_number, "prompt": p["de"], "prompt_es": p["es"],
            "redemittel": lesson["redemittel"], "theme": lesson["theme"]}


SYSTEM = """You are a kind, precise German teacher. Your student is an adult at level A2.1 (Momente A2.1), \
native Spanish speaker who also speaks English. They write 2-4 sentences for a task.

Correct the text minimally: fix real errors (grammar, word order, endings, articles, spelling, wrong words); \
keep their words, ideas and style; never rewrite to sound more advanced. If something is correct but unusual, \
leave it.

List at most 3 corrections, the most useful ones. The lesson's TARGET GRAMMAR comes first whenever there is an \
error in it, then errors that block understanding, then frequent A1/A2 errors (verb position, Perfekt with \
haben/sein, articles and cases). Each explanation is one short Spanish sentence that states the rule and the \
correct form. Count other corrected errors in more_errors. If the text has no errors, return no corrections \
and say so in the praise."""


SPEAKING_NOTE = """The STUDENT TEXT is an automatic speech-to-text transcript of the student speaking. Ignore \
punctuation, capitalisation and obvious transcription glitches (homophones, missing commas); judge grammar, \
word order, endings and word choice as you would in speech. In corrected_text, write what they meant with \
correct grammar and normal punctuation."""


def build_prompt(conn: sqlite3.Connection, task: str, text: str, lesson_number: int, kind: str = "write") -> str:
    lesson = row_to_dict(conn.execute("SELECT * FROM lesson WHERE number = ?", (lesson_number,)).fetchone())
    target = rows_to_dicts(conn.execute(
        f"SELECT code, name FROM grammar_point WHERE code IN ({','.join('?' * len(lesson['grammar_points']))})",
        lesson["grammar_points"]).fetchall()) if lesson["grammar_points"] else []
    codes = rows_to_dicts(conn.execute(
        "SELECT code, name FROM grammar_point WHERE unlocked = 1 ORDER BY id").fetchall())
    return f"""LESSON {lesson_number}: {lesson['theme']}
TARGET GRAMMAR: {"; ".join(f"{g['code']} = {g['name']}" for g in target)}
GRAMMAR CODES (use one of these or ''):
{chr(10).join(f"- {g['code']}: {g['name']}" for g in codes)}

TASK: {task}
{SPEAKING_NOTE if kind == "speak" else ""}
STUDENT TEXT:
{text}"""


def _lemma_id(conn: sqlite3.Connection, lemma: str) -> int | None:
    if not lemma:
        return None
    row = conn.execute("SELECT id FROM lemma WHERE lemma = ? COLLATE NOCASE ORDER BY pos = 'NOUN' DESC LIMIT 1",
                       (lemma.strip(),)).fetchone()
    return row[0] if row else None


def submit(conn: sqlite3.Connection, writer: Writer, *, task: str, text: str,
           lesson_number: int | None = None, kind: str = "write") -> dict:
    text = text.strip()
    if not text:
        raise ValueError("Bitte schreib zuerst etwas.")
    if len(text) > MAX_CHARS:
        raise ValueError(f"Bitte kürzer schreiben (max. {MAX_CHARS} Zeichen).")
    if lesson_number is None:
        lesson_number = conn.execute("SELECT current_lesson FROM settings WHERE id = 1").fetchone()[0]

    fb: WritingFeedback = writer.feedback(SYSTEM, build_prompt(conn, task, text, lesson_number, kind))
    valid_codes = {r[0] for r in conn.execute("SELECT code FROM grammar_point")}
    corrections = []
    for c in fb.corrections[:MAX_CORRECTIONS]:
        code = c.grammar_code if c.grammar_code in valid_codes else None
        lid = _lemma_id(conn, c.lemma)
        corrections.append({"original": c.original, "corrected": c.corrected, "grammar_code": code,
                            "lemma_id": lid, "lemma": c.lemma or None, "explanation": c.explanation})
    feedback = {"corrections": corrections, "more_errors": max(0, fb.more_errors), "praise": fb.praise}

    lesson_id = conn.execute("SELECT id FROM lesson WHERE number = ?", (lesson_number,)).fetchone()[0]
    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO writing (lesson_id, prompt, submission, corrected, feedback_json, ts, kind)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (lesson_id, task, text, fb.corrected_text, json.dumps(feedback, ensure_ascii=False),
             srs.to_db(srs.now_utc()), kind))
        for c in corrections:
            example = f"{c['original']} → {c['corrected']}"
            if c["grammar_code"]:
                log_error(conn, grammar_code=c["grammar_code"], example=example)
            if c["lemma_id"]:
                log_error(conn, lemma_id=c["lemma_id"], example=example)
                # a word the learner got wrong comes back in today's review
                conn.execute("UPDATE card SET due = ? WHERE lemma_id = ? AND direction = 'produce'",
                             (srs.to_db(srs.now_utc()), c["lemma_id"]))
    return {"id": cur.lastrowid, "kind": kind, "submission": text, "corrected": fb.corrected_text, **feedback,
            "grammar": grammar_notes(conn, [c["grammar_code"] for c in corrections if c["grammar_code"]])}


def grammar_notes(conn: sqlite3.Connection, codes: list[str]) -> dict[str, dict]:
    if not codes:
        return {}
    rows = rows_to_dicts(conn.execute(
        f"""SELECT g.code, g.name, g.rule, g.spanish_bridge, g.example, g.warning, g.unlocked, g.lesson_id
            FROM grammar_point g WHERE g.code IN ({','.join('?' * len(codes))})""", codes).fetchall())
    return {r["code"]: r for r in rows}


def history(conn: sqlite3.Connection, limit: int = 10, kind: str = "write") -> list[dict]:
    rows = rows_to_dicts(conn.execute(
        """SELECT w.id, w.prompt, w.submission, w.corrected, w.feedback_json, w.ts, w.kind, l.number AS lesson_number
           FROM writing w LEFT JOIN lesson l ON l.id = w.lesson_id WHERE w.kind = ?
           ORDER BY w.id DESC LIMIT ?""", (kind, limit)).fetchall())
    for r in rows:
        fb = r.pop("feedback_json") or {}
        r.update(fb)
    return rows
