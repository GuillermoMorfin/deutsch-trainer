"""The vocabulary ladder: every word climbs five steps from recognition to free production.

  1  met in a reader text (the only way a new word enters; no bare new cards)
  2  multiple choice DE → EN (4 options, distractors from the same lesson and word type)
  3  multiple choice EN → DE (for nouns one distractor is the right noun with the wrong article)
  4  cued recall: the sentence from the text with a gap and the first letter       ┐ scheduled with
  5  full production: English cue → type the German (nouns with article)          ┘ FSRS (card table)

Rules: two correct answers at a step promote the word; a miss demotes it one step (never below 2,
never back to 1). Steps 2-3 are practised again within the session; steps 4-5 come back when FSRS
says so. Every card shows the sentence the word was met in.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
from datetime import datetime, timedelta

from fsrs import State

from .answers import ARTICLES, check_answer, expected_form
from .db import row_to_dict

STEP_NAMES = {0: "wartet auf einen Text", 1: "im Text gesehen", 2: "erkennen (DE → EN)",
              3: "auswählen (EN → DE)", 4: "mit Hilfe schreiben", 5: "frei schreiben"}
PROMOTE_AFTER = 2         # correct answers at a step before moving up
LOWEST_PRACTICE_STEP = 2  # misses never drop below this (step 1 = met in context, already done)
FSRS_FROM = 4             # steps 4-5 are scheduled with FSRS
FIRST_FSRS_DELAY = timedelta(days=1)
MC_PER_SESSION = 10       # words at steps 1-3 practised per session


def _now():
    from .srs import now_utc
    return now_utc()


def _db(dt: datetime) -> str:
    from .srs import to_db
    return to_db(dt)


def gloss_column(conn: sqlite3.Connection) -> str:
    lang = conn.execute("SELECT gloss_language FROM settings WHERE id = 1").fetchone()[0]
    return "gloss_es" if lang == "es" else "gloss_en"


def gloss_of(word: dict, col: str = "gloss_en") -> str:
    return (word.get(col) or word.get("gloss_en") or word.get("gloss_es") or "").strip()


def display(word: dict) -> str:
    return expected_form(word["lemma"], word["pos"], word.get("article"))


# ---- state -----------------------------------------------------------------------------

def step_of(conn: sqlite3.Connection, lemma_id: int) -> int | None:
    row = conn.execute("SELECT ladder_step FROM known_word WHERE lemma_id = ?", (lemma_id,)).fetchone()
    return row[0] if row else None


def ensure_card(conn: sqlite3.Connection, lemma_id: int, at: datetime) -> int:
    """The FSRS card for steps 4-5 (direction 'produce'). Created on reaching step 4; a card that
    already exists (e.g. the word was demoted and climbed back) is simply due again tomorrow."""
    due = _db(at + FIRST_FSRS_DELAY)
    row = conn.execute("SELECT id, due FROM card WHERE lemma_id = ? AND direction = 'produce'", (lemma_id,)).fetchone()
    if row:
        conn.execute("UPDATE card SET mode = NULL, due = MIN(due, ?) WHERE id = ?", (due, row["id"]))
        return row["id"]
    kw = conn.execute("SELECT source_sentence, source_text_id FROM known_word WHERE lemma_id = ?",
                      (lemma_id,)).fetchone()
    cur = conn.execute(
        """INSERT INTO card (lemma_id, direction, due, state, source_sentence, source_text_id, created_at)
           VALUES (?, 'produce', ?, ?, ?, ?, ?)""",
        (lemma_id, due, State.Learning.value, kw["source_sentence"] if kw else None,
         kw["source_text_id"] if kw else None, _db(at)))
    return cur.lastrowid


def record(conn: sqlite3.Connection, lemma_id: int, correct: bool, *, answer: str | None = None,
           at: datetime | None = None) -> dict:
    """Apply one answer to the ladder: 2 correct → up one step, a miss → down one step (min. 2)."""
    at = at or _now()
    row = conn.execute("SELECT ladder_step, ladder_correct FROM known_word WHERE lemma_id = ?", (lemma_id,)).fetchone()
    if row is None or not row["ladder_step"]:
        raise ValueError(f"word {lemma_id} is not on the ladder")
    before = row["ladder_step"]
    step = max(before, LOWEST_PRACTICE_STEP)          # answering at all means step 1 is behind you
    streak = row["ladder_correct"] if before >= LOWEST_PRACTICE_STEP else 0
    if correct:
        streak += 1
        if streak >= PROMOTE_AFTER and step < 5:
            step, streak = step + 1, 0
    else:
        step, streak = max(LOWEST_PRACTICE_STEP, step - 1), 0
    conn.execute("UPDATE known_word SET ladder_step = ?, ladder_correct = ? WHERE lemma_id = ?",
                 (step, streak, lemma_id))
    conn.execute("INSERT INTO ladder_attempt (lemma_id, step, correct, answer, ts) VALUES (?, ?, ?, ?, ?)",
                 (lemma_id, max(before, LOWEST_PRACTICE_STEP), int(correct), answer, _db(at)))
    if step >= FSRS_FROM > before:
        ensure_card(conn, lemma_id, at)
    from .srs import update_word_state
    state = update_word_state(conn, lemma_id)
    return {"lemma_id": lemma_id, "step_before": before, "step": step, "correct_at_step": streak,
            "promoted": step > max(before, LOWEST_PRACTICE_STEP), "demoted": step < max(before, LOWEST_PRACTICE_STEP),
            "word_state": state}


# ---- context: the sentence the word was met in --------------------------------------------

CLOSERS = {'"', "“", "”", "»", "«", ")", "'", "‘", "’"}


def _sentences(tokens: list[dict]) -> list[list[dict]]:
    out, cur = [], []
    for t in tokens:
        if t.get("br"):
            if cur:
                out.append(cur)
            cur = []
            continue
        if not cur and out and t["t"] in CLOSERS and not out[-1][-1].get("ws"):
            out[-1].append(t)              # closing quote after '.': belongs to the sentence before
            continue
        cur.append(t)
        if t["t"] in (".", "!", "?") or t["t"].endswith(("!", "?", "…")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


QUOTES = '"“”„«»'


def tidy_quotes(before: str, after: str) -> tuple[str, str]:
    """A sentence cut out of a dialogue can start or end with a lone quote mark: drop unbalanced ones."""
    def count(x: str) -> int:
        return sum(x.count(q) for q in QUOTES)
    while count(before + after) % 2 and after.rstrip()[-1:] in QUOTES:
        after = after.rstrip()[:-1]
    while count(before + after) % 2 and before.lstrip()[:1] in QUOTES:
        before = before.lstrip()[1:].lstrip()
    if count(after) >= 2 and after.rstrip()[-2:] in {'""', "“\"", "\"“", "““", "””"}:
        after = after.rstrip()[:-2]
    return before, after


def _join(tokens: list[dict]) -> str:
    return "".join(t["t"] + t.get("ws", "") for t in tokens).strip()


def find_in_texts(conn: sqlite3.Connection, lemma_id: int, text_id: int | None = None) -> dict | None:
    """First sentence containing the word: in the given text, else in any read text (newest first)."""
    rows = conn.execute("SELECT id, annotations FROM text WHERE id = ?", (text_id,)).fetchall() if text_id else []
    rows += conn.execute("SELECT id, annotations FROM text WHERE kind = 'read' ORDER BY id DESC").fetchall()
    for r in rows:
        tokens = json.loads(r["annotations"]) if isinstance(r["annotations"], str) else r["annotations"]
        for sent in _sentences(tokens):
            hits = [i for i, t in enumerate(sent) if t.get("id") == lemma_id and t["t"][:1].isalpha()]
            if hits:
                k = max(hits, key=lambda i: len(sent[i]["t"]))   # separable verb: the verb, not 'um'
                before = "".join(t["t"] + t.get("ws", "") for t in sent[:k]).lstrip()
                after = (sent[k].get("ws", "") + "".join(t["t"] + t.get("ws", "") for t in sent[k + 1:])).rstrip()
                before, after = tidy_quotes(before, after)
                return {"text_id": r["id"], "sentence": f"{before}{sent[k]['t']}{after}",
                        "before": before, "blank": sent[k]["t"], "after": after}
    return None


def context(conn: sqlite3.Connection, lemma_id: int) -> dict:
    """{sentence, before, blank, after} for the word; blank is the exact form used in the sentence.
    Fills in the stored source sentence when a text has one and the word didn't."""
    kw = row_to_dict(conn.execute("SELECT source_sentence, source_text_id FROM known_word WHERE lemma_id = ?",
                                  (lemma_id,)).fetchone()) or {}
    found = find_in_texts(conn, lemma_id, kw.get("source_text_id"))
    if found:
        if not kw.get("source_sentence") or not kw.get("source_text_id"):
            conn.execute("UPDATE known_word SET source_sentence = ?, source_text_id = ? WHERE lemma_id = ?",
                         (found["sentence"], found["text_id"], lemma_id))
        return found
    sentence = kw.get("source_sentence")
    if sentence:   # a stored sentence without token data: find the word by its spelling
        lemma = conn.execute("SELECT lemma FROM lemma WHERE id = ?", (lemma_id,)).fetchone()[0]
        stem = re.escape(lemma[:max(3, len(lemma) - 2)])
        m = re.search(rf"\b{stem}\w*", sentence, re.IGNORECASE)
        if m:
            return {"text_id": None, "sentence": sentence, "before": sentence[:m.start()],
                    "blank": m.group(0), "after": sentence[m.end():]}
        return {"text_id": None, "sentence": sentence, "before": None, "blank": None, "after": None}
    return {"text_id": None, "sentence": None, "before": None, "blank": None, "after": None}


def blanked(ctx: dict) -> str | None:
    if ctx.get("blank"):
        return f"{ctx['before']}____{ctx['after']}"
    return None


# ---- distractors ----------------------------------------------------------------------------

def _pool(conn: sqlite3.Connection, word: dict, col: str, limit: int = 40) -> list[dict]:
    """Same word type, same lesson first, then neighbouring lessons, then everything else."""
    lesson = word.get("lesson_number")
    rows = conn.execute(
        f"""SELECT m.id, m.lemma, m.pos, m.article, m.gloss_en, m.gloss_es, l.number AS lesson_number
            FROM lemma m LEFT JOIN lesson l ON l.id = m.lesson_id
            WHERE m.pos = ? AND m.id != ? AND COALESCE(m.{col}, m.gloss_en, '') != ''
            ORDER BY CASE WHEN l.number = ? THEN 0 WHEN l.number IS NOT NULL THEN 1 + ABS(l.number - ?) ELSE 50 END,
                     m.id""", (word["pos"], word["id"], lesson or -1, lesson or 0)).fetchall()
    return [dict(r) for r in rows[:limit]]


def options_de_en(conn: sqlite3.Connection, word: dict, rng: random.Random, col: str = "gloss_en") -> tuple[list[str], str]:
    answer = gloss_of(word, col)
    pool = _pool(conn, word, col)
    same = [p for p in pool if p["lesson_number"] == word.get("lesson_number")] or pool
    rng.shuffle(same)
    picks, seen = [], {answer.lower()}
    for p in same + pool:
        g = gloss_of(p, col)
        if g and g.lower() not in seen:
            picks.append(g)
            seen.add(g.lower())
        if len(picks) == 3:
            break
    options = [answer, *picks]
    rng.shuffle(options)
    return options, answer


def wrong_article_variants(word: dict) -> list[str]:
    if word["pos"] != "NOUN" or not word.get("article"):
        return []
    return [f"{a} {word['lemma']}" for a in ARTICLES if a != word["article"]]


def options_en_de(conn: sqlite3.Connection, word: dict, rng: random.Random) -> tuple[list[str], str]:
    """For nouns: the right noun with a wrong article is always one of the distractors."""
    answer = display(word)
    wrong = wrong_article_variants(word)
    picks = [rng.choice(wrong)] if wrong else []
    pool = _pool(conn, word, "gloss_en")
    same = [p for p in pool if p["lesson_number"] == word.get("lesson_number")] or pool
    rng.shuffle(same)
    seen = {answer.lower(), *(p.lower() for p in picks)}
    for p in same + pool:
        d = display(p)
        if d.lower() not in seen and p["lemma"].lower() != word["lemma"].lower():
            picks.append(d)
            seen.add(d.lower())
        if len(picks) == 3:
            break
    options = [answer, *picks]
    rng.shuffle(options)
    return options, answer


# ---- items ----------------------------------------------------------------------------------

WORD_SELECT = """SELECT m.id, m.lemma, m.pos, m.article, m.plural, m.aux, m.partizip2, m.gloss_en, m.gloss_es,
                        m.cognate, m.deck, l.number AS lesson_number, k.ladder_step, k.ladder_correct
                 FROM lemma m LEFT JOIN lesson l ON l.id = m.lesson_id
                 LEFT JOIN known_word k ON k.lemma_id = m.id"""


def word(conn: sqlite3.Connection, lemma_id: int) -> dict:
    row = conn.execute(WORD_SELECT + " WHERE m.id = ?", (lemma_id,)).fetchone()
    if row is None:
        raise KeyError(lemma_id)
    return dict(row)


def _public_word(w: dict, col: str) -> dict:
    return {k: w.get(k) for k in ("id", "lemma", "pos", "article", "plural", "aux", "partizip2", "cognate",
                                  "lesson_number", "deck")} | {"gloss": gloss_of(w, col)}


def mc_item(conn: sqlite3.Connection, lemma_id: int, *, seed: int | None = None) -> dict:
    """A multiple-choice item for a word at step 1-3 (step 1 is asked as step 2)."""
    w = word(conn, lemma_id)
    step = max(w["ladder_step"] or LOWEST_PRACTICE_STEP, LOWEST_PRACTICE_STEP)
    if step >= FSRS_FROM:
        raise ValueError("steps 4-5 are FSRS cards")
    rng = random.Random(seed)
    col = gloss_column(conn)
    ctx = context(conn, lemma_id)
    if step == 2:
        options, _ = options_de_en(conn, w, rng, col)
    else:
        options, _ = options_en_de(conn, w, rng)
    return {"kind": "mc", "step": step, "lemma_id": lemma_id, "word": _public_word(w, col),
            "correct_at_step": w["ladder_correct"] if (w["ladder_step"] or 0) >= 2 else 0,
            "options": options, "sentence": ctx["sentence"], "before": ctx["before"], "blank": ctx["blank"],
            "after": ctx["after"], "blanked": blanked(ctx)}


def mc_answer_for(conn: sqlite3.Connection, lemma_id: int, step: int) -> str:
    w = word(conn, lemma_id)
    return gloss_of(w, gloss_column(conn)) if step == 2 else display(w)


def answer_mc(conn: sqlite3.Connection, lemma_id: int, step: int, choice: str, *, at: datetime | None = None) -> dict:
    current = max(step_of(conn, lemma_id) or 0, LOWEST_PRACTICE_STEP)
    if current >= FSRS_FROM:
        raise ValueError("this word is already at the typing steps")
    if step != current:
        step = current          # the word moved on in another tab: grade against where it is now
    answer = mc_answer_for(conn, lemma_id, step)
    correct = (choice or "").strip() == answer
    result = record(conn, lemma_id, correct, answer=choice, at=at)
    w = word(conn, lemma_id)
    result.update(correct=correct, answer=answer, word=_public_word(w, gloss_column(conn)))
    if result["step"] < FSRS_FROM:
        result["next_item"] = mc_item(conn, lemma_id)
    return result


def practice_words(conn: sqlite3.Connection, limit: int = MC_PER_SESSION) -> list[int]:
    """Words at steps 1-3: newest first, then the ones stuck lowest."""
    return [r[0] for r in conn.execute(
        """SELECT lemma_id FROM known_word WHERE ladder_step BETWEEN 1 AND 3
           ORDER BY date(ladder_since) DESC, ladder_step, lemma_id LIMIT ?""", (limit,))]


def card_item(conn: sqlite3.Connection, card: dict, *, seed: int | None = None) -> dict:
    """An FSRS card shown as a ladder item: 'check' (everyday MC), 'cloze' (step 4) or 'type' (step 5)."""
    col = gloss_column(conn)
    w = word(conn, card["lemma_id"])
    base = {"card_id": card["id"], "lemma_id": card["lemma_id"], "word": _public_word(w, col),
            "reps": card["reps"], "mode": card.get("mode")}
    if card.get("mode") == "check":
        options, _ = options_en_de(conn, w, random.Random(seed))
        return base | {"kind": "check", "step": 3, "options": options, "sentence": None, "blanked": None}
    ctx = context(conn, card["lemma_id"])
    step = w["ladder_step"] or 5
    if step == FSRS_FROM:
        if ctx["blank"]:
            return base | {"kind": "cloze", "step": 4, "before": ctx["before"], "after": ctx["after"],
                           "first_letter": ctx["blank"][0], "length": len(ctx["blank"]), "sentence": ctx["sentence"]}
        return base | {"kind": "cloze", "step": 4, "before": None, "after": None, "sentence": ctx["sentence"],
                       "first_letter": w["lemma"][0], "length": len(w["lemma"])}
    return base | {"kind": "type", "step": 5, "sentence": ctx["sentence"], "blanked": blanked(ctx)}


def grade_typed(conn: sqlite3.Connection, lemma_id: int, answer: str, *, ascii_ok: bool = False):
    """Step 4 is graded against the form in the sentence. Step 5 accepts the dictionary form (nouns
    with article) and, because the card shows the sentence with a gap, also the exact form that fills
    the gap (letzten for letzt, gefahren for fahren). Nouns always need their article at step 5."""
    w = word(conn, lemma_id)
    ctx = context(conn, lemma_id)
    if (w["ladder_step"] or 5) == FSRS_FROM and ctx["blank"]:
        return check_answer(answer, lemma=ctx["blank"], pos="FORM", article=None, ascii_ok=ascii_ok)
    full = check_answer(answer, lemma=w["lemma"], pos=w["pos"], article=w["article"], ascii_ok=ascii_ok)
    if full.verdict == "exact" or w["pos"] == "NOUN" or not ctx["blank"]:
        return full
    in_sentence = check_answer(answer, lemma=ctx["blank"], pos="FORM", article=None, ascii_ok=ascii_ok)
    if in_sentence.correct and (in_sentence.verdict == "exact" or not full.correct):
        in_sentence.message = f"Richtig! Grundform: {w['lemma']}"
        return in_sentence
    return full


# ---- progress ---------------------------------------------------------------------------------

def ladder_overview(conn: sqlite3.Connection, limit: int = 200) -> dict:
    col = gloss_column(conn)
    rows = [dict(r) for r in conn.execute(
        WORD_SELECT + """ WHERE k.ladder_step BETWEEN 1 AND 5
        ORDER BY k.ladder_step, k.ladder_since DESC, m.lemma LIMIT ?""", (limit,))]
    counts = {s: 0 for s in range(1, 6)}
    for s, n in conn.execute("SELECT ladder_step, COUNT(*) FROM known_word WHERE ladder_step BETWEEN 1 AND 5 "
                             "GROUP BY ladder_step"):
        counts[s] = n
    waiting = conn.execute("SELECT COUNT(*) FROM known_word WHERE ladder_step = 0").fetchone()[0]
    return {"steps": STEP_NAMES, "counts": counts, "waiting": waiting,
            "words": [_public_word(r, col) | {"step": r["ladder_step"], "correct_at_step": r["ladder_correct"]}
                      for r in rows]}


# ---- one-time migration from recognise/produce cards -----------------------------------------------

def migrate_to_ladder(conn: sqlite3.Connection) -> dict:
    """Put every word that already has cards on the ladder without losing anything:

      produce card in Review (typed right before)      → step 5, FSRS card kept
      produce card still learning / relearning          → step 3 (choices again until it sits), card kept
      everyday word that passed its check              → step 5
      everyday check not answered yet                  → stays a check
      only a recognise card                            → step 2 (1 good recognition counts toward it)

    Recognise cards and all review logs stay in the database; the queue simply no longer shows
    recognise cards. Also switches the glosses to English and lowers the daily new-word cap to 5."""
    moved = {s: 0 for s in range(2, 6)}
    words = conn.execute("SELECT DISTINCT lemma_id FROM card").fetchall()
    for (lid,) in words:
        cards = {r["direction"]: dict(r) for r in conn.execute("SELECT * FROM card WHERE lemma_id = ?", (lid,))}
        prod, rec = cards.get("produce"), cards.get("recognise")
        if prod and prod["mode"] == "check" and prod["reps"] == 0:
            continue
        if prod and (prod["mode"] == "checked" or prod["state"] == State.Review.value):
            step, streak = 5, 0
        elif prod:
            step, streak = 3, 0
        else:
            good = conn.execute("SELECT COUNT(*) FROM review_log WHERE card_id = ? AND rating >= 3",
                                (rec["id"],)).fetchone()[0]
            step, streak = 2, min(good, PROMOTE_AFTER - 1)
        src = next((c for c in (rec, prod) if c and c.get("source_sentence")), None)
        conn.execute(
            """INSERT INTO known_word (lemma_id, state, ladder_step, ladder_correct, ladder_since, source_sentence,
                                       source_text_id)
               VALUES (?, 'learning', ?, ?, datetime('now'), ?, ?)
               ON CONFLICT(lemma_id) DO UPDATE SET ladder_step = excluded.ladder_step,
                 ladder_correct = excluded.ladder_correct,
                 ladder_since = COALESCE(known_word.first_seen, excluded.ladder_since),
                 source_sentence = excluded.source_sentence, source_text_id = excluded.source_text_id""",
            (lid, step, streak, src["source_sentence"] if src else None, src["source_text_id"] if src else None))
        if prod and prod["mode"] == "learn":
            conn.execute("UPDATE card SET mode = NULL WHERE id = ?", (prod["id"],))
        moved[step] += 1
    for (lid,) in conn.execute("SELECT lemma_id FROM known_word WHERE ladder_step >= 2 AND source_sentence IS NULL").fetchall():
        context(conn, lid)          # backfill sentences from texts already read
    conn.execute("UPDATE settings SET gloss_language = 'en', daily_new_word_cap = MIN(daily_new_word_cap, 5) WHERE id = 1")
    return moved
