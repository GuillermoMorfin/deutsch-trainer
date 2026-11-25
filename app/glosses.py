"""English glosses and the 'cognate' badge.

German and English are close relatives, so many words come almost for free (Haus/house,
Wasser/water, trinken/drink). `is_cognate` compares the German word with its English gloss after
undoing the regular sound shifts (t/d/ss/z, p/f/b/v, k/ch/g …) and dropping vowels. Because it
compares against the actual meaning, false friends (bekommen ≠ become) are never flagged.

CLI: `uv run python -m app.glosses` fills missing English glosses via Claude Code (no API cost)
and recomputes the cognate flags.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata

# consonant classes after the High German consonant shift (and a few spelling habits)
_CLASSES = [
    ("sch", "S"), ("ch", "K"), ("ck", "K"), ("ph", "P"), ("pf", "P"), ("th", "T"), ("tz", "T"), ("ss", "T"),
    ("ß", "T"), ("qu", "KW"), ("sh", "S"),
]
_SINGLE = {"t": "T", "d": "T", "z": "T", "s": "T", "c": "K", "k": "K", "g": "K", "q": "K", "x": "KT",
           "p": "P", "b": "P", "f": "P", "v": "P", "w": "W", "l": "L", "r": "R", "m": "M", "n": "N", "h": "H",
           "j": "J", "y": ""}
_VERB_END = re.compile(r"(e?n|ern|eln)$")


def _fold(s: str) -> str:
    s = s.lower().replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def skeleton(word: str) -> str:
    """Consonant skeleton: 'wasser' → 'WTR', 'water' → 'WTR', 'trink' → 'TRNK', 'drink' → 'TRNK'."""
    s = _fold(word)
    out = []
    i = 0
    while i < len(s):
        for pat, cls in _CLASSES:
            if s.startswith(pat, i):
                out.append(cls)
                i += len(pat)
                break
        else:
            c = s[i]
            if c in _SINGLE:
                out.append(_SINGLE[c])
            i += 1
    sk = "".join(out)
    return re.sub(r"(.)\1+", r"\1", sk)          # doubled consonants count once


def _edit1(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    return any(a == b[:i] + b[i + 1:] for i in range(len(b)))


def _german_core(lemma: str, pos: str) -> str:
    w = lemma.split()[-1] if pos != "PHRASE" else lemma
    if pos == "VERB":
        w = _VERB_END.sub("", w) or w
    return w


def _english_heads(gloss: str) -> list[str]:
    heads = []
    for part in re.split(r"[,;/]| or ", gloss or ""):
        part = re.sub(r"\(.*?\)", "", part).strip().lower()
        part = re.sub(r"^(to|the|a|an)\s+", "", part)
        if part:
            heads.append(part.split()[0])
    return heads


def is_cognate(lemma: str, pos: str, gloss_en: str | None) -> bool:
    if not gloss_en or pos in ("PHRASE", "PRON", "DET", "NUM", "INTJ"):
        return False
    de = skeleton(_german_core(lemma, pos))
    if len(de) < 2:
        return False
    for head in _english_heads(gloss_en):
        if _fold(head) == _fold(lemma):          # same word (Baby, Internet, Hotel)
            return True
        en = skeleton(head)
        if len(en) < 2 or de[0] != en[0]:
            continue
        if len(de) == 2 and _fold(head)[:1] != _fold(lemma)[:1]:
            continue                              # short words: same skeleton by chance (passen/fit)
        if de == en or (len(de) >= 3 and len(en) >= 3 and _edit1(de, en)):
            return True
    return False


def refresh_cognates(conn: sqlite3.Connection) -> int:
    rows = conn.execute("SELECT id, lemma, pos, gloss_en, cognate FROM lemma").fetchall()
    changes = [(int(flag), r["id"]) for r in rows
               if (flag := is_cognate(r["lemma"], r["pos"], r["gloss_en"])) != bool(r["cognate"])]
    conn.executemany("UPDATE lemma SET cognate = ? WHERE id = ?", changes)
    return conn.execute("SELECT COUNT(*) FROM lemma WHERE cognate = 1").fetchone()[0]


def missing_english(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, lemma, pos, article, gloss_es FROM lemma WHERE COALESCE(TRIM(gloss_en), '') = '' ORDER BY id")]


def fill_english(conn: sqlite3.Connection, writer, batch: int = 40) -> int:
    """(Re)generate English glosses for words that have none; Spanish glosses stay as they are."""
    todo = missing_english(conn)
    done = 0
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        listing = "\n".join(f"- {(w['article'] + ' ') if w['article'] else ''}{w['lemma']} ({w['pos']})" for w in chunk)
        got = {(g.lemma, g.pos): g for g in writer.gloss(
            "Give dictionary entries (short English glosses) for these German words:\n" + listing)}
        for w in chunk:
            g = got.get((w["lemma"], w["pos"])) or next((x for (lem, _), x in got.items() if lem == w["lemma"]), None)
            if g and g.gloss_en.strip():
                conn.execute("UPDATE lemma SET gloss_en = ? WHERE id = ?", (g.gloss_en.strip(), w["id"]))
                done += 1
    refresh_cognates(conn)
    return done


def main() -> None:
    from .db import connect, transaction
    from .llm import default_writer
    conn = connect()
    todo = missing_english(conn)
    print(f"{len(todo)} words without an English gloss")
    with transaction(conn):
        n = fill_english(conn, default_writer()) if todo else 0
        flagged = refresh_cognates(conn)
    print(f"filled {n}; {flagged} words flagged as cognates")


if __name__ == "__main__":
    main()
