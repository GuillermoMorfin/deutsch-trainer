"""Spaced repetition on top of py-fsrs, for the typing steps of the vocabulary ladder.

Words enter through reader texts (`introduce_word`, ladder step 1) and climb by multiple choice
(steps 2-3, app/ladder.py, in-session). From step 4 they have one FSRS card (direction 'produce'):
step 4 shows it as a cloze with the first letter, step 5 as free typing. A word is 'known' once it
is at step 5 and its card is stable (≥ KNOWN_STABILITY days). Old 'recognise' cards are kept in the
database for history but no longer scheduled.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from fsrs import Card, Rating, Scheduler, State

from .answers import check_answer
from .db import row_to_dict

DB_TIME = "%Y-%m-%d %H:%M:%S"          # same format as sqlite datetime('now'), UTC
KNOWN_STABILITY = 7.0                   # days
MAX_REVIEWS_PER_SESSION = 40
LEARN_AHEAD = timedelta(minutes=20)     # learning-step cards due soon are shown in the same session


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_db(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(DB_TIME)


def from_db(s: str | None) -> datetime | None:
    return datetime.strptime(s, DB_TIME).replace(tzinfo=timezone.utc) if s else None


def scheduler(conn: sqlite3.Connection) -> Scheduler:
    row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    params = row["fsrs_parameters"] if "fsrs_parameters" in row.keys() else None
    if params:  # fitted to the learner's own history (app/optimize.py)
        return Scheduler(parameters=json.loads(params), desired_retention=row["target_retention"])
    return Scheduler(desired_retention=row["target_retention"])


def _fsrs_card(row: sqlite3.Row) -> Card:
    return Card(card_id=row["id"], state=State(row["state"]), step=row["step"],
                stability=row["stability"], difficulty=row["difficulty"],
                due=from_db(row["due"]), last_review=from_db(row["last_review"]))


# ---- creating cards -----------------------------------------------------------

def introduce_word(conn: sqlite3.Connection, lemma_id: int, *, sentence: str | None = None,
                   text_id: int | None = None, at: datetime | None = None) -> bool:
    """A reader text introduced the word: it goes on the ladder at step 1 (idempotent).
    Returns True if the word is new on the ladder."""
    at = at or now_utc()
    row = conn.execute("SELECT state, ladder_step, source_sentence FROM known_word WHERE lemma_id = ?",
                       (lemma_id,)).fetchone()
    if row and row["ladder_step"]:          # already climbing: just keep a sentence if it had none
        if sentence and not row["source_sentence"]:
            conn.execute("UPDATE known_word SET source_sentence = ?, source_text_id = ? WHERE lemma_id = ?",
                         (sentence, text_id, lemma_id))
        return False
    if row and row["state"] == "known" and row["ladder_step"] != 0:   # 0 = failed its everyday check
        return False
    conn.execute(
        """INSERT INTO known_word (lemma_id, state, first_seen, ladder_step, ladder_correct, ladder_since,
                                   source_sentence, source_text_id)
           VALUES (?, 'learning', ?, 1, 0, ?, ?, ?)
           ON CONFLICT(lemma_id) DO UPDATE SET ladder_step = 1, ladder_correct = 0,
             state = CASE WHEN known_word.state = 'known' THEN 'known' ELSE 'learning' END,
             ladder_since = excluded.ladder_since,
             source_sentence = COALESCE(excluded.source_sentence, known_word.source_sentence),
             source_text_id = COALESCE(excluded.source_text_id, known_word.source_text_id)""",
        (lemma_id, to_db(at), to_db(at), sentence, text_id))
    return True


CHECK_PASS_DAYS = 90      # everyday word typed right first time: you know it, see it again in ~3 months
CHECK_TYPO_DAYS = 21      # right but with a small typo


def introduce_check(conn: sqlite3.Connection, lemma_id: int, *, at: datetime | None = None) -> int | None:
    """Everyday words start as a quick multiple-choice check (EN → DE, article included).
    Right → known, back in months. Wrong → the word waits for a reader text (ladder step 0)."""
    at = at or now_utc()
    cur = conn.execute(
        """INSERT INTO card (lemma_id, direction, due, state, mode, created_at)
           VALUES (?, 'produce', ?, ?, 'check', ?) ON CONFLICT(lemma_id, direction) DO NOTHING""",
        (lemma_id, to_db(at), State.Learning.value, to_db(at)))
    conn.execute("INSERT INTO known_word (lemma_id, state, first_seen) VALUES (?, 'new', ?) ON CONFLICT DO NOTHING",
                 (lemma_id, to_db(at)))
    return cur.lastrowid if cur.rowcount else None


def checks_today(conn: sqlite3.Connection, at: datetime | None = None) -> int:
    at = at or now_utc()
    return conn.execute("SELECT COUNT(*) FROM card WHERE mode IS NOT NULL AND created_at >= ?",
                        (to_db(at.replace(hour=0, minute=0, second=0)),)).fetchone()[0]


EVERYDAY_BATCH = 5            # checks are handed out in small batches …
MAX_CHECKS_PER_DAY = 40       # … known words are quick, but keep a ceiling


def everyday_new_today(conn: sqlite3.Connection, at: datetime | None = None) -> int:
    """Everyday words that turned out new today, plus checks still waiting (they might be new too)."""
    at = at or now_utc()
    return conn.execute(
        "SELECT COUNT(*) FROM card WHERE mode IN ('pending', 'check') AND created_at >= ?",
        (to_db(at.replace(hour=0, minute=0, second=0)),)).fetchone()[0]


def introduce_everyday(conn: sqlite3.Connection, *, limit: int | None = None, at: datetime | None = None) -> list[int]:
    """Next batch of everyday checks, most useful words first.

    The daily setting caps how many *new* everyday words (ones you didn't know) you take on per day:
    words you already know don't count, so a good day moves quickly through the deck, and a day
    full of unknown words stops early instead of piling up."""
    at = at or now_utc()
    cap_new = conn.execute("SELECT everyday_per_day FROM settings WHERE id = 1").fetchone()[0]
    room = min(EVERYDAY_BATCH, cap_new - everyday_new_today(conn, at), MAX_CHECKS_PER_DAY - checks_today(conn, at))
    if limit is not None:
        room = min(room, limit)
    if room <= 0:
        return []
    rows = conn.execute(
        """SELECT m.id FROM lemma m WHERE m.deck = 'alltag'
           AND NOT EXISTS (SELECT 1 FROM card c WHERE c.lemma_id = m.id)
           ORDER BY m.deck_order LIMIT ?""", (room,)).fetchall()
    return [cid for r in rows if (cid := introduce_check(conn, r["id"], at=at))]


def words_introduced_today(conn: sqlite3.Connection, at: datetime | None = None) -> int:
    """Words that texts put on the ladder today (local day)."""
    return conn.execute(
        """SELECT COUNT(*) FROM known_word WHERE ladder_since IS NOT NULL
           AND date(ladder_since, 'localtime') = date(?, 'localtime')""", (to_db(at or now_utc()),)).fetchone()[0]


def new_word_room(conn: sqlite3.Connection, at: datetime | None = None) -> int:
    cap = conn.execute("SELECT daily_new_word_cap FROM settings WHERE id = 1").fetchone()[0]
    return max(0, cap - words_introduced_today(conn, at))


# ---- queue ----------------------------------------------------------------------

CARD_SELECT = """
SELECT c.*, m.lemma, m.pos, m.article, m.plural, m.aux, m.partizip2, m.gloss_es, m.gloss_en,
       m.deck, m.cognate, l.number AS lesson_number, k.ladder_step
FROM card c JOIN lemma m ON m.id = c.lemma_id LEFT JOIN lesson l ON l.id = m.lesson_id
LEFT JOIN known_word k ON k.lemma_id = c.lemma_id
"""
# Scheduled = everyday checks + typing cards of words at ladder step 4-5. Recognise cards are history.
SCHEDULED = "c.direction = 'produce' AND (c.mode = 'check' OR COALESCE(k.ladder_step, 0) >= 4)"


def queue(conn: sqlite3.Connection, *, limit: int = MAX_REVIEWS_PER_SESSION,
          at: datetime | None = None) -> list[dict]:
    at = at or now_utc()
    rows = conn.execute(
        CARD_SELECT + f"""
        WHERE {SCHEDULED} AND (c.due <= ? OR (c.state IN (1, 3) AND c.due <= ?))
        ORDER BY c.due, c.id LIMIT ?""",
        (to_db(at), to_db(at + LEARN_AHEAD), limit),
    ).fetchall()
    return [public_card(r) for r in rows]


def due_count(conn: sqlite3.Connection, at: datetime | None = None) -> int:
    at = at or now_utc()
    return conn.execute(f"""SELECT COUNT(*) FROM card c LEFT JOIN known_word k ON k.lemma_id = c.lemma_id
                             WHERE {SCHEDULED} AND c.due <= ?""", (to_db(at),)).fetchone()[0]


def public_card(row: sqlite3.Row) -> dict:
    d = row_to_dict(row)
    return {
        "id": d["id"], "direction": d["direction"], "due": d["due"], "state": d["state"],
        "reps": d["reps"], "lapses": d["lapses"], "lemma_id": d["lemma_id"],
        "lemma": d["lemma"], "pos": d["pos"], "article": d["article"], "plural": d["plural"],
        "aux": d["aux"], "partizip2": d["partizip2"], "gloss_es": d["gloss_es"],
        "gloss_en": d["gloss_en"], "lesson_number": d["lesson_number"],
        "source_sentence": d["source_sentence"], "mode": d.get("mode"), "deck": d.get("deck"),
        "cognate": d.get("cognate"), "ladder_step": d.get("ladder_step"),
    }


# ---- reviewing ------------------------------------------------------------------

def rating_for_check(verdict: str) -> Rating:
    return {"exact": Rating.Good, "typo": Rating.Hard}.get(verdict, Rating.Again)


def review(conn: sqlite3.Connection, card_id: int, *, rating: int | None = None,
           answer: str | None = None, duration_ms: int | None = None,
           at: datetime | None = None) -> dict:
    """Grade one scheduled card: an everyday check (multiple choice) or a step 4-5 typing card.
    The typed answer sets the FSRS rating and moves the word on the ladder."""
    from . import ladder
    at = at or now_utc()
    row = conn.execute(CARD_SELECT + " WHERE c.id = ?", (card_id,)).fetchone()
    if row is None:
        raise KeyError(card_id)
    if row["direction"] != "produce":
        raise ValueError("recognise cards are retired; words are practised on the ladder")

    if row["mode"] == "check" and row["reps"] == 0:
        expected = ladder.display(dict(row))
        correct = (answer or "").strip() == expected
        return _finish_check(conn, row, Rating.Good if correct else Rating.Again, expected, answer, duration_ms, at)

    if answer is None and rating is None:
        raise ValueError("answer is required")
    check = None
    if answer is not None:
        ascii_ok = bool(conn.execute("SELECT umlaut_ascii_ok FROM settings WHERE id = 1").fetchone()[0])
        check = ladder.grade_typed(conn, row["lemma_id"], answer, ascii_ok=ascii_ok)
        if rating is None:
            rating = rating_for_check(check.verdict)
    r = Rating(rating)

    kw = conn.execute("SELECT ladder_step, ladder_correct FROM known_word WHERE lemma_id = ?",
                      (row["lemma_id"],)).fetchone()
    prev = {k: row[k] for k in _CARD_FIELDS} | ({"ladder_step": kw["ladder_step"], "ladder_correct": kw["ladder_correct"]}
                                                if kw else {})
    card, _ = scheduler(conn).review_card(_fsrs_card(row), r, review_datetime=at)
    conn.execute(
        """UPDATE card SET stability = ?, difficulty = ?, due = ?, state = ?, step = ?,
             reps = reps + 1, lapses = lapses + ?, last_review = ? WHERE id = ?""",
        (card.stability, card.difficulty, to_db(card.due), card.state.value, card.step,
         1 if r == Rating.Again and row["state"] == State.Review.value else 0, to_db(at), card_id),
    )
    conn.execute(
        "INSERT INTO review_log (card_id, rating, answer_given, duration_ms, ts, prev_json) VALUES (?, ?, ?, ?, ?, ?)",
        (card_id, r.value, answer, duration_ms, to_db(at), json.dumps(prev)),
    )
    step = None
    if row["ladder_step"]:
        step = ladder.record(conn, row["lemma_id"], r >= Rating.Hard, answer=answer, at=at)
    word_state = update_word_state(conn, row["lemma_id"])
    return {"card_id": card_id, "rating": r.value, "check": check.to_dict() if check else None,
            "next_due": to_db(card.due), "interval_days": round((card.due - at).total_seconds() / 86400, 2),
            "ladder": step, "word_state": word_state}


_CARD_FIELDS = ("stability", "difficulty", "due", "state", "step", "reps", "lapses", "last_review")


def override(conn: sqlite3.Connection, card_id: int, *, at: datetime | None = None) -> dict:
    """'Ich hatte es richtig': undo the last (wrong) typed answer on this card and count it as right.
    Card and ladder go back to how they were before, then the answer is graded Good."""
    log = conn.execute("SELECT * FROM review_log WHERE card_id = ? ORDER BY id DESC LIMIT 1", (card_id,)).fetchone()
    if log is None or not log["prev_json"] or log["rating"] >= Rating.Hard:
        raise ValueError("nothing to correct: the last answer on this card was not marked wrong")
    prev = json.loads(log["prev_json"])
    lemma_id = conn.execute("SELECT lemma_id FROM card WHERE id = ?", (card_id,)).fetchone()[0]
    conn.execute(f"UPDATE card SET {', '.join(f'{k} = ?' for k in _CARD_FIELDS)} WHERE id = ?",
                 (*(prev[k] for k in _CARD_FIELDS), card_id))
    if "ladder_step" in prev:
        conn.execute("UPDATE known_word SET ladder_step = ?, ladder_correct = ? WHERE lemma_id = ?",
                     (prev["ladder_step"], prev["ladder_correct"], lemma_id))
        conn.execute("""DELETE FROM ladder_attempt WHERE id = (SELECT MAX(id) FROM ladder_attempt WHERE lemma_id = ?)""",
                     (lemma_id,))
    conn.execute("DELETE FROM review_log WHERE id = ?", (log["id"],))
    result = review(conn, card_id, rating=Rating.Good.value, answer=log["answer_given"], at=at or from_db(log["ts"]))
    result["overridden"] = True
    return result


def _finish_check(conn: sqlite3.Connection, row: sqlite3.Row, r: Rating, expected: str, answer: str | None,
                  duration_ms: int | None, at: datetime) -> dict:
    """First answer on an everyday check card (multiple choice EN → DE)."""
    conn.execute("INSERT INTO review_log (card_id, rating, answer_given, duration_ms, ts) VALUES (?, ?, ?, ?, ?)",
                 (row["id"], r.value, answer, duration_ms, to_db(at)))
    if r >= Rating.Good:   # you know it: don't drill it, see it again in a few months (typed, step 5)
        due = at + timedelta(days=CHECK_PASS_DAYS)
        conn.execute("""UPDATE card SET state = ?, step = NULL, stability = ?, difficulty = ?, due = ?, reps = 1,
                        last_review = ?, mode = 'checked' WHERE id = ?""",
                     (State.Review.value, float(CHECK_PASS_DAYS), 3.0, to_db(due), to_db(at), row["id"]))
        conn.execute("UPDATE known_word SET ladder_step = 5, ladder_correct = 0 WHERE lemma_id = ?", (row["lemma_id"],))
        if conn.execute("SELECT source FROM lemma WHERE id = ?", (row["lemma_id"],)).fetchone()[0] != "a1":
            conn.execute("UPDATE known_word SET state = 'known' WHERE lemma_id = ?", (row["lemma_id"],))
        result = "known"
    else:                  # new for you: it waits for a reader text, then climbs the ladder
        due = at + timedelta(days=CHECK_PASS_DAYS)
        conn.execute("UPDATE card SET reps = 1, last_review = ?, mode = 'pending', due = ? WHERE id = ?",
                     (to_db(at), to_db(due), row["id"]))
        conn.execute("UPDATE known_word SET ladder_step = 0, state = CASE WHEN state = 'known' THEN state ELSE 'new' END "
                     "WHERE lemma_id = ?", (row["lemma_id"],))
        result = "learn"
    word_state = conn.execute("SELECT state FROM known_word WHERE lemma_id = ?", (row["lemma_id"],)).fetchone()[0]
    return {"card_id": row["id"], "rating": r.value, "correct": r >= Rating.Good, "answer": expected,
            "check": None, "next_due": to_db(due), "interval_days": round((due - at).total_seconds() / 86400, 2),
            "word_state": word_state, "check_result": result, "ladder": None}


def update_word_state(conn: sqlite3.Connection, lemma_id: int) -> str:
    # A1 base words are the coverage baseline: reviewing them never demotes them.
    if conn.execute("SELECT source FROM lemma WHERE id = ?", (lemma_id,)).fetchone()[0] == "a1":
        return conn.execute("SELECT state FROM known_word WHERE lemma_id = ?", (lemma_id,)).fetchone()[0]
    kw = conn.execute("SELECT ladder_step, state FROM known_word WHERE lemma_id = ?", (lemma_id,)).fetchone()
    if kw is None or kw["ladder_step"] is None:
        return kw["state"] if kw else "new"
    if kw["ladder_step"] == 0:
        return kw["state"]
    prod = conn.execute("SELECT stability, state, mode FROM card WHERE lemma_id = ? AND direction = 'produce'",
                        (lemma_id,)).fetchone()
    known = (kw["ladder_step"] == 5 and prod is not None and prod["state"] == State.Review.value
             and (prod["stability"] or 0) >= KNOWN_STABILITY)
    state = "known" if known else "learning"
    conn.execute("UPDATE known_word SET state = ? WHERE lemma_id = ?", (state, lemma_id))
    return state
