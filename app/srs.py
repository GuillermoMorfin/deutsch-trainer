"""Spaced repetition on top of py-fsrs.

Card flow per word:
  1. A recognise card (DE → ES, reveal + self-rate) is created when the word is introduced.
  2. After 2 successful recognitions (Good/Easy) a produce card (ES → DE, typed, article
     required) is created and is due immediately.
  3. The word counts as 'known' once its produce card is stable (≥ KNOWN_STABILITY days);
     a lapse on either card drops it back to 'learning'.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from fsrs import Card, Rating, Scheduler, State

from .answers import check_answer
from .db import row_to_dict

DB_TIME = "%Y-%m-%d %H:%M:%S"          # same format as sqlite datetime('now'), UTC
RECOGNITIONS_TO_UNLOCK_PRODUCE = 2
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
                   text_id: int | None = None, at: datetime | None = None) -> int | None:
    """Create the recognise card for a word (idempotent). Returns the card id if created."""
    at = at or now_utc()
    cur = conn.execute(
        """INSERT INTO card (lemma_id, direction, due, state, source_sentence, source_text_id)
           VALUES (?, 'recognise', ?, ?, ?, ?) ON CONFLICT(lemma_id, direction) DO NOTHING""",
        (lemma_id, to_db(at), State.Learning.value, sentence, text_id),
    )
    conn.execute(
        """INSERT INTO known_word (lemma_id, state, first_seen) VALUES (?, 'learning', ?)
           ON CONFLICT(lemma_id) DO UPDATE SET state = CASE WHEN known_word.state = 'new'
             THEN 'learning' ELSE known_word.state END""",
        (lemma_id, to_db(at)),
    )
    return cur.lastrowid if cur.rowcount else None


CHECK_PASS_DAYS = 90      # everyday word typed right first time: you know it, see it again in ~3 months
CHECK_TYPO_DAYS = 21      # right but with a small typo


def introduce_check(conn: sqlite3.Connection, lemma_id: int, *, at: datetime | None = None) -> int | None:
    """Everyday words start as a typing check (ES → DE). Right first time → known, back in months.
    Wrong → normal learning in both directions."""
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


def introduce_everyday(conn: sqlite3.Connection, *, limit: int | None = None, at: datetime | None = None) -> list[int]:
    """Today's everyday checks, most useful words first, up to the daily setting."""
    at = at or now_utc()
    per_day = conn.execute("SELECT everyday_per_day FROM settings WHERE id = 1").fetchone()[0]
    room = max(0, per_day - checks_today(conn, at))
    if limit is not None:
        room = min(room, limit)
    if room == 0:
        return []
    rows = conn.execute(
        """SELECT m.id FROM lemma m WHERE m.deck = 'alltag'
           AND NOT EXISTS (SELECT 1 FROM card c WHERE c.lemma_id = m.id)
           ORDER BY m.deck_order LIMIT ?""", (room,)).fetchall()
    return [cid for r in rows if (cid := introduce_check(conn, r["id"], at=at))]


def new_cards_today(conn: sqlite3.Connection, at: datetime | None = None) -> int:
    at = at or now_utc()
    day_start = at.replace(hour=0, minute=0, second=0)
    return conn.execute(
        """SELECT COUNT(*) FROM card c JOIN known_word k ON k.lemma_id = c.lemma_id
           WHERE c.direction = 'recognise' AND k.first_seen >= ?""", (to_db(day_start),)
    ).fetchone()[0]


def introduce_lesson_words(conn: sqlite3.Connection, *, limit: int | None = None,
                           at: datetime | None = None) -> list[int]:
    """Introduce not-yet-seen words of the current lesson, up to the daily cap."""
    at = at or now_utc()
    s = conn.execute("SELECT current_lesson, daily_new_word_cap FROM settings WHERE id = 1").fetchone()
    room = max(0, s["daily_new_word_cap"] - new_cards_today(conn, at))
    if limit is not None:
        room = min(room, limit)
    if room == 0:
        return []
    # Nouns, verbs and adjectives first: they carry the meaning of the texts.
    rows = conn.execute(
        """SELECT m.id FROM lemma m
           JOIN lesson l ON l.id = m.lesson_id AND l.number = ?
           LEFT JOIN card c ON c.lemma_id = m.id
           WHERE c.id IS NULL
           ORDER BY CASE m.pos WHEN 'NOUN' THEN 0 WHEN 'VERB' THEN 0 WHEN 'ADJ' THEN 1 ELSE 2 END, m.id
           LIMIT ?""", (s["current_lesson"], room)).fetchall()
    return [cid for r in rows if (cid := introduce_word(conn, r["id"], at=at))]


def introduced_today(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT m.id, m.lemma, m.pos, m.article, m.plural, m.aux, m.partizip2, m.gloss_es, m.gloss_en,
                  c.source_sentence
           FROM known_word k JOIN lemma m ON m.id = k.lemma_id
           JOIN card c ON c.lemma_id = m.id AND c.direction = 'recognise'
           WHERE m.lesson_id IS NOT NULL AND date(k.first_seen, 'localtime') = date('now', 'localtime')
           ORDER BY k.first_seen, m.id""").fetchall()
    return [dict(r) for r in rows]


# ---- queue ----------------------------------------------------------------------

CARD_SELECT = """
SELECT c.*, m.lemma, m.pos, m.article, m.plural, m.aux, m.partizip2, m.gloss_es, m.gloss_en,
       m.deck, l.number AS lesson_number
FROM card c JOIN lemma m ON m.id = c.lemma_id LEFT JOIN lesson l ON l.id = m.lesson_id
"""


def queue(conn: sqlite3.Connection, *, limit: int = MAX_REVIEWS_PER_SESSION,
          at: datetime | None = None) -> list[dict]:
    at = at or now_utc()
    rows = conn.execute(
        CARD_SELECT + """
        WHERE c.due <= ? OR (c.state IN (1, 3) AND c.due <= ?)
        ORDER BY c.due, c.id LIMIT ?""",
        (to_db(at), to_db(at + LEARN_AHEAD), limit),
    ).fetchall()
    return [public_card(r) for r in rows]


def due_count(conn: sqlite3.Connection, at: datetime | None = None) -> int:
    at = at or now_utc()
    return conn.execute("SELECT COUNT(*) FROM card WHERE due <= ?", (to_db(at),)).fetchone()[0]


def public_card(row: sqlite3.Row) -> dict:
    d = row_to_dict(row)
    return {
        "id": d["id"], "direction": d["direction"], "due": d["due"], "state": d["state"],
        "reps": d["reps"], "lapses": d["lapses"], "lemma_id": d["lemma_id"],
        "lemma": d["lemma"], "pos": d["pos"], "article": d["article"], "plural": d["plural"],
        "aux": d["aux"], "partizip2": d["partizip2"], "gloss_es": d["gloss_es"],
        "gloss_en": d["gloss_en"], "lesson_number": d["lesson_number"],
        "source_sentence": d["source_sentence"], "mode": d.get("mode"), "deck": d.get("deck"),
    }


# ---- reviewing ------------------------------------------------------------------

def rating_for_check(verdict: str) -> Rating:
    return {"exact": Rating.Good, "typo": Rating.Hard}.get(verdict, Rating.Again)


def review(conn: sqlite3.Connection, card_id: int, *, rating: int | None = None,
           answer: str | None = None, duration_ms: int | None = None,
           at: datetime | None = None) -> dict:
    """Grade one card. Produce cards are graded from the typed answer unless a rating is given."""
    at = at or now_utc()
    row = conn.execute(CARD_SELECT + " WHERE c.id = ?", (card_id,)).fetchone()
    if row is None:
        raise KeyError(card_id)

    check = None
    if row["direction"] == "produce" and answer is not None:
        ascii_ok = bool(conn.execute("SELECT umlaut_ascii_ok FROM settings WHERE id = 1").fetchone()[0])
        check = check_answer(answer, lemma=row["lemma"], pos=row["pos"], article=row["article"],
                             ascii_ok=ascii_ok)
        if rating is None:
            rating = rating_for_check(check.verdict)
    if rating is None:
        raise ValueError("rating is required for recognise cards")
    r = Rating(rating)

    if row["mode"] == "check" and row["reps"] == 0:
        return _finish_check(conn, row, r, check, answer, duration_ms, at)

    card, _ = scheduler(conn).review_card(_fsrs_card(row), r, review_datetime=at)
    conn.execute(
        """UPDATE card SET stability = ?, difficulty = ?, due = ?, state = ?, step = ?,
             reps = reps + 1, lapses = lapses + ?, last_review = ? WHERE id = ?""",
        (card.stability, card.difficulty, to_db(card.due), card.state.value, card.step,
         1 if r == Rating.Again and row["state"] == State.Review.value else 0, to_db(at), card_id),
    )
    conn.execute(
        "INSERT INTO review_log (card_id, rating, answer_given, duration_ms, ts) VALUES (?, ?, ?, ?, ?)",
        (card_id, r.value, answer, duration_ms, to_db(at)),
    )

    unlocked = None
    if row["direction"] == "recognise" and r >= Rating.Good:
        good = conn.execute("SELECT COUNT(*) FROM review_log WHERE card_id = ? AND rating >= 3",
                            (card_id,)).fetchone()[0]
        # 'Leicht' the very first time = you already know it: go straight to the typing test
        easy_first = r == Rating.Easy and row["reps"] == 0
        if good >= RECOGNITIONS_TO_UNLOCK_PRODUCE or easy_first:
            cur = conn.execute(
                """INSERT INTO card (lemma_id, direction, due, state, source_sentence, source_text_id)
                   VALUES (?, 'produce', ?, ?, ?, ?) ON CONFLICT(lemma_id, direction) DO NOTHING""",
                (row["lemma_id"], to_db(at), State.Learning.value, row["source_sentence"], row["source_text_id"]),
            )
            unlocked = cur.lastrowid if cur.rowcount else None

    word_state = update_word_state(conn, row["lemma_id"])
    return {"card_id": card_id, "rating": r.value, "check": check.to_dict() if check else None,
            "next_due": to_db(card.due), "interval_days": round((card.due - at).total_seconds() / 86400, 2),
            "produce_unlocked": unlocked is not None, "word_state": word_state}


def _finish_check(conn: sqlite3.Connection, row: sqlite3.Row, r: Rating, check, answer: str | None,
                  duration_ms: int | None, at: datetime) -> dict:
    """First answer on an everyday check card."""
    conn.execute("INSERT INTO review_log (card_id, rating, answer_given, duration_ms, ts) VALUES (?, ?, ?, ?, ?)",
                 (row["id"], r.value, answer, duration_ms, to_db(at)))
    if r >= Rating.Hard:   # right (Hard = small typo): you know it, don't drill it
        days = CHECK_PASS_DAYS if r >= Rating.Good else CHECK_TYPO_DAYS
        due = at + timedelta(days=days)
        conn.execute("""UPDATE card SET state = ?, step = NULL, stability = ?, difficulty = ?, due = ?, reps = 1,
                        last_review = ?, mode = 'checked' WHERE id = ?""",
                     (State.Review.value, float(days), 3.0, to_db(due), to_db(at), row["id"]))
        if conn.execute("SELECT source FROM lemma WHERE id = ?", (row["lemma_id"],)).fetchone()[0] != "a1":
            conn.execute("UPDATE known_word SET state = 'known' WHERE lemma_id = ?", (row["lemma_id"],))
        result, word_state = "known", "known"
    else:                  # new for you: learn it properly, both directions
        card, _ = scheduler(conn).review_card(_fsrs_card(row), r, review_datetime=at)
        due = card.due
        conn.execute("""UPDATE card SET stability = ?, difficulty = ?, due = ?, state = ?, step = ?, reps = 1,
                        last_review = ?, mode = 'learn' WHERE id = ?""",
                     (card.stability, card.difficulty, to_db(due), card.state.value, card.step, to_db(at), row["id"]))
        conn.execute("""INSERT INTO card (lemma_id, direction, due, state, created_at)
                        VALUES (?, 'recognise', ?, ?, ?) ON CONFLICT(lemma_id, direction) DO NOTHING""",
                     (row["lemma_id"], to_db(at), State.Learning.value, to_db(at)))
        conn.execute("UPDATE known_word SET state = CASE WHEN state = 'known' THEN state ELSE 'learning' END "
                     "WHERE lemma_id = ?", (row["lemma_id"],))
        result = "learn"
        word_state = conn.execute("SELECT state FROM known_word WHERE lemma_id = ?", (row["lemma_id"],)).fetchone()[0]
    return {"card_id": row["id"], "rating": r.value, "check": check.to_dict() if check else None,
            "next_due": to_db(due), "interval_days": round((due - at).total_seconds() / 86400, 2),
            "produce_unlocked": False, "word_state": word_state, "check_result": result}


def update_word_state(conn: sqlite3.Connection, lemma_id: int) -> str:
    # A1 base words are the coverage baseline: reviewing them never demotes them.
    if conn.execute("SELECT source FROM lemma WHERE id = ?", (lemma_id,)).fetchone()[0] == "a1":
        return conn.execute("SELECT state FROM known_word WHERE lemma_id = ?", (lemma_id,)).fetchone()[0]
    cards ={r["direction"]: r for r in conn.execute(
        "SELECT direction, stability, state FROM card WHERE lemma_id = ?", (lemma_id,)).fetchall()}
    prod = cards.get("produce")
    rec = cards.get("recognise")
    if rec is None and prod is not None and prod["state"] == State.Review.value:
        # everyday word that passed its check (no recognition card needed)
        state = "known" if (prod["stability"] or 0) >= KNOWN_STABILITY else "learning"
        conn.execute("UPDATE known_word SET state = ? WHERE lemma_id = ?", (state, lemma_id))
        return state
    known = (prod is not None and prod["state"] == State.Review.value and (prod["stability"] or 0) >= KNOWN_STABILITY
             and rec is not None and rec["state"] == State.Review.value)
    state = "known" if known else "learning"
    conn.execute("UPDATE known_word SET state = ? WHERE lemma_id = ?", (state, lemma_id))
    return state
