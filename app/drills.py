"""Grammar drills: lesson-scoped items, error-weighted selection, rule → bridge → example → warning feedback.

Items come from a hand-written seed bank (app/seed/drills.json) and from Claude (via the Writer),
and are only shown if their correct sentence uses vocabulary the learner knows (known/learning words
plus the words of lessons up to the current one) and grammar that is unlocked.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
import unicodedata
from datetime import timedelta
from pathlib import Path

from . import srs
from .db import row_to_dict, rows_to_dicts, transaction
from .llm import GenerationError, Writer
from .verifier import analyse, build_lexicon, unlocked_codes

SEED_PATH = Path(__file__).resolve().parent / "seed" / "drills.json"
DEFAULT_SESSION = 8
MAX_PER_CODE = 3
RECENT_DAYS = 14
GENERATE_BATCH = 8


# ---- items ------------------------------------------------------------------------

def full_sentence(item_type: str, prompt: str, answers: list) -> str:
    if item_type == "order":
        words = " ".join(answers[0])
        end = "" if words.endswith((".", "!", "?")) else ("?" if prompt.rstrip().startswith(("Wissen", "Weißt", "Können", "Kannst")) else ".")
        return f"{prompt} {words}{end}"
    return prompt.replace("___", answers[0])


def upsert_item(conn: sqlite3.Connection, item: dict, source: str) -> int | None:
    answers = item["answers"]
    tokens = list(answers[0]) if item["type"] == "order" else None
    cur = conn.execute(
        """INSERT INTO drill_item (grammar_code, type, prompt, options, tokens, answers, hint, explanation,
                                   full_sentence, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(grammar_code, prompt) DO UPDATE SET
             type = excluded.type, options = excluded.options, tokens = excluded.tokens,
             answers = excluded.answers, hint = excluded.hint, explanation = excluded.explanation,
             full_sentence = excluded.full_sentence""",
        (item["code"], item["type"], item["prompt"],
         json.dumps(item.get("options"), ensure_ascii=False) if item.get("options") else None,
         json.dumps(tokens, ensure_ascii=False) if tokens else None,
         json.dumps(answers, ensure_ascii=False), item.get("hint"), item.get("explanation"),
         full_sentence(item["type"], item["prompt"], answers), source))
    return cur.lastrowid


def seed_drills(conn: sqlite3.Connection) -> int:
    items = json.loads(SEED_PATH.read_text(encoding="utf-8"))["items"]
    for it in items:
        upsert_item(conn, it, "seed")
    return len(items)


def _decode(item: dict) -> dict:
    for k in ("options", "tokens", "answers"):
        if isinstance(item.get(k), str):
            item[k] = json.loads(item[k])
    return item


# ---- usability: only known words and unlocked grammar ---------------------------------------

def allowed_lemma_ids(conn: sqlite3.Connection) -> set[int]:
    """Known/learning words plus the words of lessons up to the current one (taught in class)."""
    return {r[0] for r in conn.execute(
        """SELECT m.id FROM lemma m LEFT JOIN lesson l ON l.id = m.lesson_id
           WHERE m.id IN (SELECT lemma_id FROM known_word WHERE state IN ('known', 'learning'))
              OR l.number <= (SELECT current_lesson FROM settings WHERE id = 1)""")}


def usable(items: list[dict], conn: sqlite3.Connection) -> list[dict]:
    lex = build_lexicon(conn, extra_known=allowed_lemma_ids(conn))
    unlocked = unlocked_codes(conn)
    out = []
    for it in items:
        _, report = analyse(it["full_sentence"], lex, unlocked)
        if report.coverage == 1.0 and not report.grammar:
            out.append(it)
    return out


# ---- weighting ----------------------------------------------------------------------

def drillable_codes(conn: sqlite3.Connection) -> list[dict]:
    """Unlocked A2.1 grammar points up to the current lesson, plus any unlocked point with errors."""
    return rows_to_dicts(conn.execute(
        """SELECT g.code, g.name, l.number AS lesson_number FROM grammar_point g
           LEFT JOIN lesson l ON l.id = g.lesson_id
           WHERE g.unlocked = 1 AND (
                 (l.number IS NOT NULL AND l.number <= (SELECT current_lesson FROM settings WHERE id = 1))
              OR g.code IN (SELECT grammar_code FROM error_log WHERE grammar_code IS NOT NULL))
           ORDER BY l.number, g.id""").fetchall())


def code_weights(conn: sqlite3.Connection) -> dict[str, float]:
    current = conn.execute("SELECT current_lesson FROM settings WHERE id = 1").fetchone()[0]
    since = srs.to_db(srs.now_utc() - timedelta(days=RECENT_DAYS))
    recent = {r["grammar_code"]: (r["wrong"], r["right"]) for r in conn.execute(
        """SELECT i.grammar_code, SUM(a.correct = 0) AS wrong, SUM(a.correct = 1) AS right
           FROM drill_attempt a JOIN drill_item i ON i.id = a.item_id
           WHERE a.ts >= ? GROUP BY i.grammar_code""", (since,))}
    logged = {r[0]: r[1] for r in conn.execute(
        "SELECT grammar_code, SUM(count) FROM error_log WHERE grammar_code IS NOT NULL GROUP BY grammar_code")}
    # Arbeitsbuch/Kursbuch exercises the learner ticked as missed: grammar exercises weigh most.
    missed_lessons: dict[int, float] = {}
    for bp in conn.execute("""SELECT l.number, b.missed_exercise_ids FROM book_progress b
                              JOIN lesson l ON l.id = b.lesson_id"""):
        ids = json.loads(bp["missed_exercise_ids"] or "[]")
        if not ids:
            continue
        labels = [r[0] for r in conn.execute(
            f"SELECT label FROM book_exercise WHERE id IN ({','.join('?' * len(ids))})", ids)]
        missed_lessons[bp["number"]] = 1 + 2 * sum("Grammatik" in lb for lb in labels)

    weights = {}
    for c in drillable_codes(conn):
        w = 1.0
        if c["lesson_number"] == current:
            w += 3
        wrong, right = recent.get(c["code"], (0, 0))
        w += max(0.0, 2 * (wrong or 0) - (right or 0))          # recent weakness, fades as you get it right
        w += 0.5 * min(logged.get(c["code"], 0), 6)               # long-term error log (drills + writing)
        w += missed_lessons.get(c["lesson_number"], 0)
        weights[c["code"]] = w
    return weights


def pick_items(conn: sqlite3.Connection, code: str, k: int, exclude: set[int]) -> list[dict]:
    """Never-seen items first, then ones answered wrong last time, then the least recently seen."""
    rows = rows_to_dicts(conn.execute(
        """SELECT i.*,
                  (SELECT MAX(ts) FROM drill_attempt a WHERE a.item_id = i.id) AS last_seen,
                  (SELECT correct FROM drill_attempt a WHERE a.item_id = i.id ORDER BY a.id DESC LIMIT 1) AS last_correct
           FROM drill_item i WHERE i.grammar_code = ?""", (code,)).fetchall())
    rows = [_decode(r) for r in rows if r["id"] not in exclude]
    rows.sort(key=lambda r: (r["last_seen"] is not None, r["last_correct"] == 1, r["last_seen"] or "", random.random()))
    return usable(rows[: k * 3], conn)[:k]


def session(conn: sqlite3.Connection, *, n: int = DEFAULT_SESSION, code: str | None = None,
            seed: int | None = None) -> list[dict]:
    rng = random.Random(seed)
    if code:
        return [public_item(i, rng) for i in pick_items(conn, code, n, set())]
    weights = code_weights(conn)
    chosen: list[dict] = []
    per_code: dict[str, int] = {}
    pool = dict(weights)
    while len(chosen) < n and pool:
        codes, ws = zip(*pool.items())
        c = rng.choices(codes, weights=ws)[0]
        got = pick_items(conn, c, 1, {i["id"] for i in chosen})
        if not got:
            pool.pop(c)
            continue
        chosen += got
        per_code[c] = per_code.get(c, 0) + 1
        if per_code[c] >= MAX_PER_CODE:
            pool.pop(c)
    return [public_item(i, rng) for i in chosen]


def public_item(item: dict, rng: random.Random) -> dict:
    out = {k: item[k] for k in ("id", "grammar_code", "type", "prompt", "hint")}
    if item["type"] == "choice":
        out["options"] = item["options"]
    if item["type"] == "order":
        tokens = list(item["tokens"])
        while len(tokens) > 1 and tokens == item["tokens"]:
            rng.shuffle(tokens)
        out["tokens"] = tokens
    return out


# ---- checking + error log ------------------------------------------------------------------

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "").strip().rstrip(".!?").strip()
    return re.sub(r"\s+", " ", s)


def grade(item: dict, answer) -> bool:
    if item["type"] == "order":
        given = [w.strip() for w in (answer if isinstance(answer, list) else str(answer).split())]
        return any([w.lower() for w in given] == [w.lower() for w in a] for a in item["answers"])
    if item["type"] == "choice":
        return _norm(str(answer)) in {_norm(a) for a in item["answers"]}
    # gap: case-insensitive, but umlauts and spelling must be exact
    return _norm(str(answer)).lower() in {_norm(a).lower() for a in item["answers"]}


def log_error(conn: sqlite3.Connection, *, grammar_code: str | None = None, lemma_id: int | None = None,
              example: str | None = None) -> None:
    row = conn.execute("SELECT id FROM error_log WHERE grammar_code IS ? AND lemma_id IS ?",
                       (grammar_code, lemma_id)).fetchone()
    now = srs.to_db(srs.now_utc())
    if row:
        conn.execute("UPDATE error_log SET count = count + 1, example = COALESCE(?, example), last_seen = ? WHERE id = ?",
                     (example, now, row[0]))
    else:
        conn.execute("INSERT INTO error_log (grammar_code, lemma_id, example, count, last_seen) VALUES (?, ?, ?, 1, ?)",
                     (grammar_code, lemma_id, example, now))


def check(conn: sqlite3.Connection, item_id: int, answer) -> dict:
    row = conn.execute("SELECT * FROM drill_item WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(item_id)
    item = _decode(dict(row))
    correct = grade(item, answer)
    with transaction(conn):
        conn.execute("INSERT INTO drill_attempt (item_id, correct, answer, ts) VALUES (?, ?, ?, ?)",
                     (item_id, int(correct), json.dumps(answer, ensure_ascii=False), srs.to_db(srs.now_utc())))
        if not correct:
            log_error(conn, grammar_code=item["grammar_code"], example=item["full_sentence"])
    g = row_to_dict(conn.execute(
        "SELECT code, name, rule, spanish_bridge, example, warning FROM grammar_point WHERE code = ?",
        (item["grammar_code"],)).fetchone())
    expected = " ".join(item["answers"][0]) if item["type"] == "order" else item["answers"][0]
    return {"correct": correct, "expected": expected, "full_sentence": item["full_sentence"],
            "explanation": item.get("explanation"), "grammar": g}


# ---- stats -----------------------------------------------------------------------------

def top_errors(conn: sqlite3.Connection, limit: int = 5) -> list[dict]:
    return rows_to_dicts(conn.execute(
        """SELECT e.grammar_code, g.name, e.lemma_id, m.lemma, m.article, e.example, e.count, e.last_seen
           FROM error_log e LEFT JOIN grammar_point g ON g.code = e.grammar_code
           LEFT JOIN lemma m ON m.id = e.lemma_id
           ORDER BY e.count DESC, e.last_seen DESC LIMIT ?""", (limit,)).fetchall())


def stats(conn: sqlite3.Connection) -> list[dict]:
    weights = code_weights(conn)
    rows = rows_to_dicts(conn.execute(
        """SELECT g.code, g.name, l.number AS lesson_number,
                  (SELECT COUNT(*) FROM drill_item i WHERE i.grammar_code = g.code) AS items,
                  (SELECT COUNT(*) FROM drill_attempt a JOIN drill_item i ON i.id = a.item_id
                     WHERE i.grammar_code = g.code) AS attempts,
                  (SELECT SUM(a.correct) FROM drill_attempt a JOIN drill_item i ON i.id = a.item_id
                     WHERE i.grammar_code = g.code) AS right
           FROM grammar_point g LEFT JOIN lesson l ON l.id = g.lesson_id
           WHERE g.code IN (%s) ORDER BY l.number, g.id""" % ",".join("?" * len(weights)), list(weights)).fetchall()) \
        if weights else []
    for r in rows:
        r["accuracy"] = round((r["right"] or 0) / r["attempts"], 2) if r["attempts"] else None
        r["weight"] = round(weights[r["code"]], 1)
    return rows


# ---- generation (Claude) ------------------------------------------------------------------

DRILL_SYSTEM = """You write short German grammar exercises for one adult learner at level A2.1 (Momente A2.1, \
native Spanish). Every sentence must be natural, short (max 12 words), about everyday life in Berlin \
(running, cycling, studying, friends, the WG, work), and use ONLY words from the ALLOWED WORDS list \
(any inflection; names and numbers are fine) and only the ALLOWED GRAMMAR. Each exercise practises exactly \
the requested grammar point."""


def generate(conn: sqlite3.Connection, writer: Writer, code: str, n: int = GENERATE_BATCH) -> int:
    g = row_to_dict(conn.execute("SELECT * FROM grammar_point WHERE code = ? AND unlocked = 1", (code,)).fetchone())
    if g is None:
        raise GenerationError(f"Grammatikpunkt {code} ist nicht freigeschaltet.")
    allowed_ids = allowed_lemma_ids(conn)
    words = [f"{r['article']} {r['lemma']}" if r["article"] else r["lemma"] for r in conn.execute(
        f"SELECT lemma, article FROM lemma WHERE id IN ({','.join('?' * len(allowed_ids))}) AND pos != 'PHRASE' "
        "ORDER BY lemma COLLATE NOCASE", list(allowed_ids))]
    allowed_grammar = [r[0] for r in conn.execute("SELECT name FROM grammar_point WHERE unlocked = 1")]
    examples = [_decode(dict(r)) for r in conn.execute(
        "SELECT type, prompt, options, answers, hint FROM drill_item WHERE grammar_code = ? LIMIT 3", (code,))]
    existing = [r[0] for r in conn.execute("SELECT prompt FROM drill_item WHERE grammar_code = ?", (code,))]
    prompt = f"""GRAMMAR POINT: {g['name']}
Rule: {g['rule']}
Example: {g['example']}
Typical error: {g['warning']}

Write {n} new exercises for this point. Mix the types that fit it:
- "gap": prompt contains ___ ; answers = accepted fillers (1-3 words); hint = short German hint (e.g. "sein, Präteritum").
- "choice": prompt contains ___ ; options = 2-4 choices; answers = [the correct option, exactly as in options].
- "order": prompt = the fixed start of the sentence (e.g. "Ich bleibe zu Hause,"); answers = [[the remaining
  words in the correct order]] (each word a separate string, no final punctuation). Use for word order (verb position).
Give a one-sentence English explanation of why the answer is right.

FORMAT EXAMPLES (do not repeat): {json.dumps(examples, ensure_ascii=False)}
DO NOT REPEAT THESE PROMPTS: {json.dumps(existing, ensure_ascii=False)}

ALLOWED GRAMMAR: {"; ".join(allowed_grammar)}

ALLOWED WORDS ({len(words)}): {", ".join(words)}"""
    items = writer.drills(DRILL_SYSTEM, prompt)
    added = 0
    lex = build_lexicon(conn, extra_known=allowed_ids)
    unlocked = unlocked_codes(conn)
    with transaction(conn):
        for it in items:
            d = it.model_dump()
            d["code"] = code
            if d["type"] == "order":
                d["answers"] = [a.split() if isinstance(a, str) else a for a in d.pop("order_answers") or []]
            else:
                d.pop("order_answers", None)
            if not d["answers"] or (d["type"] in ("gap", "choice") and "___" not in d["prompt"]):
                continue
            if d["type"] == "choice" and not set(d["answers"]) <= set(d.get("options") or []):
                continue
            sentence = full_sentence(d["type"], d["prompt"], d["answers"])
            _, report = analyse(sentence, lex, unlocked)
            if report.coverage < 1.0 or report.grammar:
                continue
            if conn.execute("SELECT 1 FROM drill_item WHERE grammar_code = ? AND prompt = ?",
                            (code, d["prompt"])).fetchone():
                continue
            upsert_item(conn, d, "generated")
            added += 1
    return added
