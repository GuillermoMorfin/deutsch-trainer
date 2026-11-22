"""Export word lists for Quizlet (tab between term and definition, one card per line)."""

from __future__ import annotations

import sqlite3


def term(row: sqlite3.Row) -> str:
    if row["pos"] == "NOUN":
        t = f"{row['article']} {row['lemma']}"
        if row["plural"] and row["plural"] != "-":
            t += f", die {row['plural']}"
        return t
    if row["pos"] == "VERB" and row["partizip2"]:
        return f"{row['lemma']} ({'ist' if row['aux'] == 'sein' else 'hat'} {row['partizip2']})"
    return row["lemma"]


def definition(row: sqlite3.Row) -> str:
    d = row["gloss_es"] or ""
    if row["gloss_en"]:
        d += f" · {row['gloss_en']}"
    return d


def quizlet(conn: sqlite3.Connection, *, lesson: int | None = None, state: str | None = None) -> tuple[str, str]:
    """Returns (filename, text). lesson=None exports every lesson word; state='learning' only words in progress."""
    where, args = ["m.lesson_id IS NOT NULL", "m.pos != 'PHRASE'"], []
    if lesson is not None:
        where.append("l.number = ?")
        args.append(lesson)
    if state:
        where.append("COALESCE(k.state, 'new') = ?")
        args.append(state)
    rows = conn.execute(
        f"""SELECT m.*, l.number AS lesson_number, l.book FROM lemma m JOIN lesson l ON l.id = m.lesson_id
            LEFT JOIN known_word k ON k.lemma_id = m.id
            WHERE {' AND '.join(where)} ORDER BY l.number, m.id""", args).fetchall()
    clean = lambda s: s.replace("\t", " ").replace("\n", " ").strip()  # noqa: E731
    text = "\n".join(f"{clean(term(r))}\t{clean(definition(r))}" for r in rows)
    name = f"momente-lektion-{lesson}" if lesson is not None else "momente-alle-lektionen"
    if state:
        name += f"-{state}"
    return f"{name}.txt", text
