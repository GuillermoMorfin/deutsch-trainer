"""Seed the database: lessons, grammar points, A1 base vocabulary, book exercise index.

Idempotent: re-running updates seed rows in place and never touches learner progress
(known_word states, cards, logs, lesson status).

Usage:
    python -m app.seed                       # seed everything
    python -m app.seed --import words.csv --lesson 3   # import a lesson word list
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from pathlib import Path

from .db import connect, init_schema, transaction

SEED_DIR = Path(__file__).resolve().parent / "seed"

LEMMA_COLUMNS = ("lemma", "pos", "article", "plural", "aux", "partizip2", "gloss_es", "gloss_en")
VALID_POS = {"NOUN", "VERB", "ADJ", "ADV", "ADP", "CONJ", "PRON", "DET", "NUM", "INTJ", "PHRASE"}


def _none(v: str | None) -> str | None:
    v = (v or "").strip()
    return v or None


def seed_lessons(conn: sqlite3.Connection) -> int:
    lessons = json.loads((SEED_DIR / "lessons.json").read_text(encoding="utf-8"))
    for l in lessons:
        conn.execute(
            """INSERT INTO lesson (number, title, theme, word_field, grammar_points, redemittel)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(number) DO UPDATE SET
                 title=excluded.title, theme=excluded.theme, word_field=excluded.word_field,
                 grammar_points=excluded.grammar_points, redemittel=excluded.redemittel""",
            (l["number"], l["title"], l["theme"], l["word_field"],
             json.dumps(l["grammar_points"], ensure_ascii=False),
             json.dumps(l["redemittel"], ensure_ascii=False)),
        )
    # First run: make the current lesson active.
    if not conn.execute("SELECT 1 FROM lesson WHERE status != 'locked'").fetchone():
        current = conn.execute("SELECT current_lesson FROM settings WHERE id = 1").fetchone()[0]
        conn.execute("UPDATE lesson SET status = 'active' WHERE number = ?", (current,))
    return len(lessons)


def lesson_id(conn: sqlite3.Connection, number: int | None) -> int | None:
    if number is None:
        return None
    row = conn.execute("SELECT id FROM lesson WHERE number = ?", (number,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown lesson {number}")
    return row[0]


def seed_grammar(conn: sqlite3.Connection) -> int:
    data = json.loads((SEED_DIR / "grammar_points.json").read_text(encoding="utf-8"))
    current = conn.execute("SELECT current_lesson FROM settings WHERE id = 1").fetchone()[0]
    for g in data["points"]:
        lid = lesson_id(conn, g["lesson"])
        # Points of lessons up to the current one start unlocked; never re-lock on reseed.
        unlocked = 1 if g["unlocked"] or (g["lesson"] is not None and g["lesson"] <= current) else 0
        conn.execute(
            """INSERT INTO grammar_point (code, name, lesson_id, unlocked, rule, spanish_bridge, example, warning)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(code) DO UPDATE SET
                 name=excluded.name, lesson_id=excluded.lesson_id,
                 unlocked=MAX(grammar_point.unlocked, excluded.unlocked),
                 rule=excluded.rule, spanish_bridge=excluded.spanish_bridge,
                 example=excluded.example, warning=excluded.warning""",
            (g["code"], g["name"], lid, unlocked, g["rule"], g["bridge"], g["example"], g["warning"]),
        )
    return len(data["points"])


def validate_lemma_row(r: dict) -> list[str]:
    errs = []
    if not _none(r.get("lemma")):
        errs.append("missing lemma")
    pos = (r.get("pos") or "").strip().upper()
    if pos not in VALID_POS:
        errs.append(f"bad pos {pos!r}")
    art = _none(r.get("article"))
    if pos == "NOUN" and art not in ("der", "die", "das"):
        errs.append("noun without der/die/das")
    if pos == "NOUN" and re.match(r"^(der|die|das) ", r.get("lemma") or ""):
        errs.append("article inside lemma column")
    if pos == "VERB" and _none(r.get("aux")) not in (None, "haben", "sein"):
        errs.append("aux must be haben or sein")
    return errs


def upsert_lemmas(conn: sqlite3.Connection, rows: list[dict], *, lesson: int | None,
                  source: str, mark_known: bool) -> tuple[int, list[str]]:
    lid = lesson_id(conn, lesson)
    problems: list[str] = []
    count = 0
    for i, r in enumerate(rows, start=2):  # line 1 is the header
        errs = validate_lemma_row(r)
        if errs:
            problems.append(f"line {i} ({r.get('lemma')}): {', '.join(errs)}")
            continue
        vals = {c: _none(r.get(c)) for c in LEMMA_COLUMNS}
        vals["pos"] = vals["pos"].upper()
        if vals["pos"] != "NOUN":
            vals["article"] = None
        existing = conn.execute(
            "SELECT id FROM lemma WHERE lemma = ? AND pos = ? AND article IS ?",
            (vals["lemma"], vals["pos"], vals["article"]),
        ).fetchone()
        if existing:
            lemma_id = existing[0]
            conn.execute(
                """UPDATE lemma SET plural=COALESCE(?, plural), aux=COALESCE(?, aux),
                   partizip2=COALESCE(?, partizip2), gloss_es=COALESCE(?, gloss_es),
                   gloss_en=COALESCE(?, gloss_en) WHERE id = ?""",
                (vals["plural"], vals["aux"], vals["partizip2"], vals["gloss_es"], vals["gloss_en"], lemma_id),
            )
        else:
            cur = conn.execute(
                """INSERT INTO lemma (lemma, pos, article, plural, aux, partizip2, gloss_es, gloss_en, lesson_id, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (*[vals[c] for c in LEMMA_COLUMNS], lid, source),
            )
            lemma_id = cur.lastrowid
        if mark_known:
            conn.execute(
                "INSERT INTO known_word (lemma_id, state) VALUES (?, 'known') ON CONFLICT(lemma_id) DO NOTHING",
                (lemma_id,),
            )
        count += 1
    return count, problems


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def seed_a1(conn: sqlite3.Connection) -> int:
    n, problems = upsert_lemmas(conn, read_csv(SEED_DIR / "a1_core.csv"),
                                lesson=None, source="a1", mark_known=True)
    if problems:
        raise ValueError("A1 seed has invalid rows:\n" + "\n".join(problems))
    return n


def seed_lesson_wordlists(conn: sqlite3.Connection) -> int:
    """Import seed/lessons/L<n>.csv files if present (A2.1 lesson word lists)."""
    total = 0
    folder = SEED_DIR / "lessons"
    for path in sorted(folder.glob("L*.csv")) if folder.exists() else []:
        number = int(re.search(r"L(\d+)", path.stem).group(1))
        n, problems = upsert_lemmas(conn, read_csv(path), lesson=number, source="glossary", mark_known=False)
        if problems:
            raise ValueError(f"{path.name} has invalid rows:\n" + "\n".join(problems))
        total += n
    return total


def seed_exercises(conn: sqlite3.Connection) -> int:
    items = json.loads((SEED_DIR / "book_exercises.json").read_text(encoding="utf-8"))
    for it in items:
        # Labels like "Übung: L3, 11" carry the lesson even inside review sections.
        m = re.search(r"\bL(\d+)\b", it["label"])
        number = it["lesson"] or (int(m.group(1)) if m else None)
        conn.execute(
            """INSERT INTO book_exercise (book, lesson_id, section, label) VALUES (?, ?, ?, ?)
               ON CONFLICT(book, section, label) DO UPDATE SET lesson_id = excluded.lesson_id""",
            (it["book"], lesson_id(conn, number), it["section"], it["label"]),
        )
    conn.execute("INSERT OR IGNORE INTO book_progress (lesson_id) SELECT id FROM lesson")
    return len(items)


def seed_drills(conn: sqlite3.Connection) -> int:
    from .drills import seed_drills as _seed  # local import: drills pulls in spaCy
    return _seed(conn)


def seed_all(conn: sqlite3.Connection) -> dict[str, int]:
    init_schema(conn)
    with transaction(conn):
        return {
            "lessons": seed_lessons(conn),
            "grammar_points": seed_grammar(conn),
            "a1_lemmas": seed_a1(conn),
            "lesson_lemmas": seed_lesson_wordlists(conn),
            "book_exercises": seed_exercises(conn),
            "drills": seed_drills(conn),
        }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--import", dest="import_csv", type=Path, help="CSV with columns " + ",".join(LEMMA_COLUMNS))
    ap.add_argument("--lesson", type=int, help="lesson number for --import (omit for A1 base words)")
    ap.add_argument("--known", action="store_true", help="mark imported words as already known")
    args = ap.parse_args()

    conn = connect()
    print("Seeded:", seed_all(conn))
    if args.import_csv:
        with transaction(conn):
            n, problems = upsert_lemmas(conn, read_csv(args.import_csv), lesson=args.lesson,
                                        source="glossary" if args.lesson else "manual", mark_known=args.known)
        print(f"Imported {n} words from {args.import_csv}")
        for p in problems:
            print("  skipped", p)


if __name__ == "__main__":
    main()
