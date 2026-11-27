"""Sprechen: a plan for speaking practice with a partner (no microphone, no grading).

Each day has its own conversation plan per lesson (table speaking_set): the hand-written one from
`seed/speaking.json` the first time, then a new set written by Claude Code every day (a new everyday
situation from the lesson's theme, the lesson grammar, 2 questions recycling earlier lessons, the
words being learned). Every German line passes the verifier at the learner's level; earlier sets are
passed in so nothing repeats. The page adds the Redemittel, grammar notes, words to use, frequent
mistakes and tips for the partner.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Callable

from .db import connect, db_path, row_to_dict, rows_to_dicts, transaction
from .drills import allowed_lemma_ids, top_errors
from .llm import GenerationError, LLMUnavailable, Writer

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


# ---- daily sets -------------------------------------------------------------------------------

_state: dict[int, dict] = {}          # lesson number -> {"generating": bool, "error": str | None}
_lock = threading.Lock()
MIN_QUESTIONS = 4


def _today(conn: sqlite3.Connection) -> str:
    return conn.execute("SELECT date('now', 'localtime')").fetchone()[0]


def _lesson(conn: sqlite3.Connection, number: int) -> dict:
    lesson = row_to_dict(conn.execute("SELECT * FROM lesson WHERE number = ?", (number,)).fetchone())
    if not lesson:
        raise LookupError(number)
    return lesson


def sets_for(conn: sqlite3.Connection, lesson_id: int) -> list[dict]:
    return [dict(r) | {"data": json.loads(r["data"])} for r in conn.execute(
        "SELECT * FROM speaking_set WHERE lesson_id = ? ORDER BY id", (lesson_id,))]


def seed_used(conn: sqlite3.Connection, lesson_id: int) -> bool:
    """The hand-written plan counts as used once it was shown on a day, or a conversation for this
    lesson was logged before today (before daily sets existed)."""
    if conn.execute("SELECT 1 FROM speaking_set WHERE lesson_id = ? AND source = 'seed'", (lesson_id,)).fetchone():
        return True
    return conn.execute("""SELECT 1 FROM speaking_log WHERE lesson_id = ?
                           AND date(ts, 'localtime') < date('now', 'localtime')""", (lesson_id,)).fetchone() is not None


def todays_set(conn: sqlite3.Connection, number: int) -> dict | None:
    """Today's plan for the lesson; the hand-written one if it hasn't been used yet. None = write a new one."""
    lesson = _lesson(conn, number)
    row = conn.execute("SELECT * FROM speaking_set WHERE lesson_id = ? AND day = ? ORDER BY id DESC LIMIT 1",
                       (lesson["id"], _today(conn))).fetchone()
    if row:
        return dict(row) | {"data": json.loads(row["data"])}
    seed = _seed().get(str(number))
    if seed and not seed_used(conn, lesson["id"]):
        data = {"topic": None, "focus": seed["focus"], "challenge": seed["challenge"], "questions": seed["questions"],
                "roleplay": seed.get("roleplay"), "phrases": []}
        with transaction(conn):
            cur = conn.execute("INSERT INTO speaking_set (lesson_id, day, source, data) VALUES (?, ?, 'seed', ?)",
                               (lesson["id"], _today(conn), json.dumps(data, ensure_ascii=False)))
        return {"id": cur.lastrowid, "source": "seed", "day": _today(conn), "data": data}
    return None


SYSTEM = """You plan a 15-20 minute German conversation for an adult learner at level A2.1 (Momente A2.1) \
and their partner (girlfriend), who asks the questions. The learner speaks Spanish and English.

Rules:
1. German lines (questions, role-play starter, phrases) use ONLY the ALLOWED WORDS (any inflected form; names, \
places and numbers are fine) and ONLY the ALLOWED GRAMMAR: no relative clauses, no passive, no genitive, no \
Futur, no Präteritum except war/hatte (and forms the list allows), no subordinate clauses except allowed \
conjunctions. Short, natural spoken German. Questions address the learner with "du".
2. Pick ONE new everyday situation that fits the lesson THEME and is different from every EARLIER SET (a new \
angle, not a rephrasing). Use the PERSONAL CONTEXT (Berlin, ESMT, running, cycling, friends, Marco).
3. 6 questions: 4 about today's situation that make the learner use the TARGET GRAMMAR in the answer, then 2 that \
recycle grammar from EARLIER LESSONS (say nothing about this in the question itself). Open questions (Warum? \
Wie? Was?), not yes/no.
4. The challenge is concrete and countable (e.g. "Answer every question with a weil-sentence; your partner counts \
the verbs at the end").
5. Weave in some of the WORDS BEING LEARNED.
6. The role play: a realistic scene with clear roles and a goal, written in English; the starter is its first \
German line.
7. Phrases: 3-4 German sentence starters for the situation that are NOT in the lesson's Redemittel, ending in "…"."""


def build_prompt(conn: sqlite3.Connection, number: int) -> str:
    from .generator import personal_context
    lesson = _lesson(conn, number)
    codes = json.loads(lesson["grammar_points"]) if isinstance(lesson["grammar_points"], str) else lesson["grammar_points"]
    target = rows_to_dicts(conn.execute(
        "SELECT name, rule, example FROM grammar_point WHERE code IN (%s)" % ",".join("?" * len(codes)), codes).fetchall()) \
        if codes else []
    earlier = [r[0] for r in conn.execute(
        """SELECT g.name FROM grammar_point g JOIN lesson l ON l.id = g.lesson_id
           WHERE g.unlocked = 1 AND l.number < ? ORDER BY l.number""", (number,))]
    allowed = [r[0] for r in conn.execute("SELECT name FROM grammar_point WHERE unlocked = 1 ORDER BY id")]
    ids = allowed_lemma_ids(conn)
    words = [f"{r['article']} {r['lemma']}" if r["article"] else r["lemma"] for r in conn.execute(
        f"SELECT lemma, article FROM lemma WHERE id IN ({','.join('?' * len(ids))}) AND pos != 'PHRASE' "
        "ORDER BY lemma COLLATE NOCASE", list(ids))] if ids else []
    learning = [f"{w['article']} {w['lemma']}" if w["article"] else w["lemma"] for w in words_to_use(conn, number, 12)]
    redemittel = json.loads(lesson["redemittel"]) if isinstance(lesson["redemittel"], str) else lesson["redemittel"]
    previous = sets_for(conn, lesson["id"])
    seed = _seed().get(str(number))
    history = [f"- {p['data'].get('topic') or 'first plan'}: " + " | ".join(p["data"]["questions"]) for p in previous]
    if seed and not any(p["source"] == "seed" for p in previous):
        history.append("- first plan: " + " | ".join(seed["questions"]))
    return f"""LESSON {number}: {lesson['title']} · THEME: {lesson['theme']} · WORD FIELD: {lesson['word_field']}
REDEMITTEL OF THE LESSON: {"; ".join(redemittel)}

TARGET GRAMMAR:
{chr(10).join(f"- {g['name']}: {g['rule']} Example: {g['example']}" for g in target)}

GRAMMAR FROM EARLIER LESSONS (recycle 2 questions): {"; ".join(earlier) or "A1 basics: Perfekt, modal verbs, dative, Akkusativ"}

EARLIER SETS FOR THIS LESSON (do not repeat situations or questions):
{chr(10).join(history) or "(none)"}

WORDS BEING LEARNED (use some): {", ".join(learning) or "(none yet)"}

PERSONAL CONTEXT:
{personal_context()}

ALLOWED GRAMMAR: {"; ".join(allowed)}

ALLOWED WORDS ({len(words)}): {", ".join(words)}"""


def check_lines(conn: sqlite3.Connection, lines: list[str]) -> list[tuple[str, list[str]]]:
    """German lines that fail the verifier at the learner's level, with the reasons."""
    from .verifier import analyse, build_lexicon, unlocked_codes
    lex = build_lexicon(conn, extra_known=allowed_lemma_ids(conn))
    unlocked = unlocked_codes(conn)
    bad = []
    for line in lines:
        text = line.replace("…", " ").replace("...", " ").strip()
        _, r = analyse(text, lex, unlocked)
        reasons = [f"unknown word: {u}" for u in r.unknown] + [f"grammar not allowed: {g.code} ('{g.text}')" for g in r.grammar]
        if reasons:
            bad.append((line, reasons))
    return bad


def generate_set(conn: sqlite3.Connection, writer: Writer, number: int) -> dict:
    """Write, verify (one repair round), store and return today's new set."""
    lesson = _lesson(conn, number)
    prompt = build_prompt(conn, number)
    s = writer.speaking(SYSTEM, prompt)
    bad = check_lines(conn, [*s.questions, s.roleplay_starter, *s.phrases])
    if bad:
        notes = "\n".join(f"- \"{line}\": {'; '.join(why)}" for line, why in bad)
        s = writer.speaking(SYSTEM, f"{prompt}\n\nA checker rejected these lines of your previous plan "
                                    f"(topic: {s.topic}). Write the plan again, keeping the situation, and fix them:\n{notes}")
        bad = check_lines(conn, [*s.questions, s.roleplay_starter, *s.phrases])
    rejected = {line for line, _ in bad}
    questions = [q for q in s.questions if q not in rejected][:6]
    if len(questions) < MIN_QUESTIONS:
        raise GenerationError("Die neuen Gesprächsfragen waren zu schwer für dein Niveau. Bitte nochmal versuchen.")
    data = {"topic": s.topic, "focus": s.focus, "challenge": s.challenge, "questions": questions,
            "roleplay": {"setup": s.roleplay_setup, "starter": s.roleplay_starter}
            if s.roleplay_starter not in rejected else {"setup": s.roleplay_setup, "starter": None},
            "phrases": [p for p in s.phrases if p not in rejected][:4]}
    with transaction(conn):
        cur = conn.execute("INSERT INTO speaking_set (lesson_id, day, source, data) VALUES (?, ?, 'generated', ?)",
                           (lesson["id"], _today(conn), json.dumps(data, ensure_ascii=False)))
    return {"id": cur.lastrowid, "source": "generated", "data": data}


def status(number: int) -> dict:
    st = _state.get(number, {})
    return {"generating": bool(st.get("generating")), "error": st.get("error")}


def start_generation(writer_factory: Callable[[], Writer], number: int, *, wait: bool = False) -> dict:
    """Write a new set in the background (its own DB connection); one at a time per lesson."""
    with _lock:
        if _state.get(number, {}).get("generating"):
            return status(number)
        _state[number] = {"generating": True, "error": None}

    def run():
        bg = connect(db_path())
        try:
            generate_set(bg, writer_factory(), number)
        except (GenerationError, LLMUnavailable) as e:
            _state[number]["error"] = str(e)
        except Exception as e:      # keep the page usable whatever happens
            _state[number]["error"] = f"Unerwarteter Fehler: {e}"
        finally:
            bg.close()
            _state[number]["generating"] = False

    th = threading.Thread(target=run, daemon=True)
    th.start()
    if wait:
        th.join()
    return status(number)


# ---- the page ---------------------------------------------------------------------------------

def guide(conn: sqlite3.Connection, lesson_number: int | None = None) -> dict:
    current = conn.execute("SELECT current_lesson FROM settings WHERE id = 1").fetchone()[0]
    number = lesson_number or current
    lesson = _lesson(conn, number)
    codes = json.loads(lesson["grammar_points"]) if isinstance(lesson["grammar_points"], str) else lesson["grammar_points"]
    grammar = rows_to_dicts(conn.execute(
        "SELECT code, name, rule, example, warning FROM grammar_point WHERE code IN (%s)" % ",".join("?" * len(codes)),
        codes).fetchall()) if codes else []
    grammar.sort(key=lambda g: codes.index(g["code"]))
    today = todays_set(conn, number)
    plan = today["data"] if today else None
    redemittel = json.loads(lesson["redemittel"]) if isinstance(lesson["redemittel"], str) else lesson["redemittel"]
    errors = [e for e in top_errors(conn, 4) if e["grammar_code"] or e["lemma"]]
    sessions = conn.execute("SELECT COUNT(*), COALESCE(SUM(minutes), 0) FROM speaking_log").fetchone()
    n_sets = conn.execute("SELECT COUNT(*) FROM speaking_set WHERE lesson_id = ?", (lesson["id"],)).fetchone()[0]
    return {
        "lesson": {"number": lesson["number"], "title": lesson["title"], "theme": lesson["theme"]},
        "current_lesson": current,
        "lessons": [r[0] for r in conn.execute("SELECT number FROM lesson WHERE number <= ? ORDER BY number",
                                                (current,))],
        "pending": plan is None, **status(number),
        "set": {"id": today["id"], "source": today["source"], "number": n_sets} if today else None,
        "topic": plan.get("topic") if plan else None,
        "focus": plan["focus"] if plan else None, "challenge": plan["challenge"] if plan else None,
        "questions": plan["questions"] if plan else [], "roleplay": plan.get("roleplay") if plan else None,
        "phrases": plan.get("phrases", []) if plan else [],
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
