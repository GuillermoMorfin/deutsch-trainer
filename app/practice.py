"""Short practice formats that rotate between days, so vocabulary sessions don't feel identical.

Each day's vocab session uses 2-3 of these, never the same set as the previous session day:

  match   timed match-pairs: 6 German ↔ 6 English
  listen  listen-and-pick: the voice says a word, pick it from 4
  gender  der/die/das sorting: drag (or tap) nouns into the gender boxes
  odd     odd one out: 3 words from one lesson theme + 1 from elsewhere
  cloze   gaps in yesterday's text: pick the missing word

They use words you have met (ladder words, known lesson words; A1 words fill gaps) and don't move
words on the ladder: they are extra exposure, logged in practice_log for the activity stats.
"""

from __future__ import annotations

import json
import random
import sqlite3

from .db import row_to_dict
from .ladder import _sentences, display, gloss_column, gloss_of, tidy_quotes

FORMATS = {
    "match": "Paare finden",
    "listen": "Hören und wählen",
    "gender": "der · die · das",
    "odd": "Was passt nicht?",
    "cloze": "Lücken im Text von gestern",
}
ORDER = list(FORMATS)

_WORDS = """SELECT m.id, m.lemma, m.pos, m.article, m.gloss_en, m.gloss_es, m.cognate, m.source, m.deck,
                   l.number AS lesson_number, l.theme, k.ladder_step
            FROM lemma m JOIN known_word k ON k.lemma_id = m.id LEFT JOIN lesson l ON l.id = m.lesson_id"""


def met_words(conn: sqlite3.Connection, pos: str | None = None) -> list[dict]:
    """Words the learner has met, weakest first; A1 base words after them as filler."""
    where = "AND m.pos = ?" if pos else "AND m.pos IN ('NOUN', 'VERB', 'ADJ', 'ADV')"
    args = (pos,) if pos else ()
    mine = [dict(r) for r in conn.execute(
        _WORDS + f""" WHERE (k.ladder_step >= 1 OR (k.state = 'known' AND m.source != 'a1')) {where}
        ORDER BY COALESCE(k.ladder_step, 6), m.id""", args)]
    a1 = [dict(r) for r in conn.execute(
        _WORDS + f" WHERE m.source = 'a1' AND k.state = 'known' {where} ORDER BY m.id", args)]
    return mine + a1


def _take(words: list[dict], n: int, rng: random.Random, *, prefer: int = 0) -> list[dict]:
    """n distinct words: the first `prefer` from the front (weakest), the rest at random."""
    head = words[:prefer]
    rest = words[prefer:]
    rng.shuffle(rest)
    out, seen = [], set()
    for w in head + rest:
        key = (w["lemma"].lower(), w["pos"])
        if key not in seen:
            out.append(w)
            seen.add(key)
        if len(out) == n:
            break
    return out


def build_match(conn, rng, col):
    words = [w for w in met_words(conn) if gloss_of(w, col)]
    pick = _take(words, 6, rng, prefer=3)
    glosses = {gloss_of(w, col).lower() for w in pick}
    if len(pick) < 6 or len(glosses) < 6:
        return None
    return {"seconds": 60, "pairs": [{"id": w["id"], "de": display(w), "en": gloss_of(w, col)} for w in pick]}


def build_listen(conn, rng, col):
    words = met_words(conn)
    rounds = []
    for w in _take(words, 5, rng, prefer=3):
        same = [x for x in words if x["pos"] == w["pos"] and x["lemma"].lower() != w["lemma"].lower()]
        others = _take(same, 3, rng)
        if len(others) < 3:
            continue
        options = [display(w), *(display(o) for o in others)]
        rng.shuffle(options)
        rounds.append({"say": display(w), "answer": display(w), "gloss": gloss_of(w, col), "options": options})
    return {"rounds": rounds} if len(rounds) >= 4 else None


def build_gender(conn, rng, col):
    nouns = [w for w in met_words(conn, "NOUN") if w["article"]]
    pick = _take(nouns, 8, rng, prefer=4)
    if len(pick) < 6:
        return None
    return {"nouns": [{"id": w["id"], "lemma": w["lemma"], "article": w["article"], "gloss": gloss_of(w, col)}
                      for w in pick]}


def build_odd(conn, rng, col):
    current = conn.execute("SELECT current_lesson FROM settings WHERE id = 1").fetchone()[0]
    groups: dict[int, list[dict]] = {}
    for w in met_words(conn, "NOUN"):
        if w["lesson_number"] and w["lesson_number"] <= current:
            groups.setdefault(w["lesson_number"], []).append(w)
    if not any(len(g) >= 3 for g in groups.values()):   # early on: the lesson's own word list
        groups = {}
        for r in conn.execute(
                """SELECT m.id, m.lemma, m.pos, m.article, m.gloss_en, m.gloss_es, l.number AS lesson_number, l.theme
                   FROM lemma m JOIN lesson l ON l.id = m.lesson_id WHERE m.pos = 'NOUN' AND l.number <= ?""", (current,)):
            groups.setdefault(r["lesson_number"], []).append(dict(r))
    themes = {r["number"]: r["theme"] for r in conn.execute("SELECT number, theme FROM lesson")}
    outsiders = [w for w in met_words(conn, "NOUN") if not w["lesson_number"] or w["deck"] == "alltag"]
    rounds = []
    lessons = sorted(g for g in groups if len(groups[g]) >= 3)
    for _ in range(8 if lessons else 0):
        if len(rounds) == 4:
            break
        n = rng.choice(lessons)
        inside = _take(groups[n], 3, rng)
        pool = [w for k, ws in groups.items() if k != n for w in ws] + outsiders
        odd = _take(pool, 1, rng)
        if len(inside) < 3 or not odd:
            continue
        odd = odd[0]
        odd_theme = themes.get(odd["lesson_number"]) if odd.get("lesson_number") else ("Alltag" if odd.get("deck") == "alltag" else "A1")
        options = [display(w) for w in inside] + [display(odd)]
        rng.shuffle(options)
        rounds.append({"options": options, "answer": display(odd), "theme": themes[n], "odd_theme": odd_theme,
                       "glosses": {display(w): gloss_of(w, col) for w in [*inside, odd]}})
    return {"rounds": rounds} if len(rounds) >= 3 else None


def build_cloze(conn, rng, col):
    from .session import warmup_text
    t = warmup_text(conn)
    if not t:
        return None
    row = row_to_dict(conn.execute("SELECT id, title, annotations, target_lemma_ids FROM text WHERE id = ?",
                                   (t["id"],)).fetchone())
    targets = set(row["target_lemma_ids"] or [])
    items, forms = [], {}
    for sent in _sentences(row["annotations"]):
        hits = [i for i, tok in enumerate(sent) if tok.get("id") in targets and tok["t"][:1].isalpha()]
        for i in hits:
            forms.setdefault(sent[i]["id"], set()).add(sent[i]["t"])
        if hits:
            k = rng.choice(hits)
            before = "".join(x["t"] + x.get("ws", "") for x in sent[:k]).lstrip()
            after = (sent[k].get("ws", "") + "".join(x["t"] + x.get("ws", "") for x in sent[k + 1:])).rstrip()
            before, after = tidy_quotes(before, after)
            items.append({"before": before, "after": after, "answer": sent[k]["t"], "lemma_id": sent[k]["id"]})
    if len({it["lemma_id"] for it in items}) < 4:
        return None
    rng.shuffle(items)
    chosen, used = [], set()
    for it in items:                       # one gap per word, max 5
        if it["lemma_id"] not in used:
            chosen.append(it)
            used.add(it["lemma_id"])
        if len(chosen) == 5:
            break
    all_forms = sorted({f for fs in forms.values() for f in fs})
    for it in chosen:
        others = [f for lid, fs in forms.items() if lid != it["lemma_id"] for f in fs]
        others = sorted(set(others))
        rng.shuffle(others)
        opts = [it["answer"], *others[:3]]
        rng.shuffle(opts)
        it["options"] = opts
        del it["lemma_id"]
    return {"text_id": row["id"], "text_title": row["title"], "items": chosen} if all_forms else None


BUILDERS = {"match": build_match, "listen": build_listen, "gender": build_gender, "odd": build_odd, "cloze": build_cloze}


def build(conn: sqlite3.Connection, kind: str, seed: int | None = None) -> dict | None:
    rng = random.Random(seed)
    data = BUILDERS[kind](conn, rng, gloss_column(conn))
    return {"kind": kind, "title": FORMATS[kind], **data} if data else None


def _today(conn: sqlite3.Connection) -> str:
    return conn.execute("SELECT date('now', 'localtime')").fetchone()[0]


def formats_for_day(conn: sqlite3.Connection, day: str | None = None) -> list[str]:
    """The day's formats: fixed once chosen; 2-3 that the previous session day didn't use."""
    day = day or _today(conn)
    row = conn.execute("SELECT formats FROM practice_day WHERE day = ?", (day,)).fetchone()
    if row:
        return json.loads(row[0])
    prev_row = conn.execute("SELECT formats FROM practice_day WHERE day < ? ORDER BY day DESC LIMIT 1", (day,)).fetchone()
    prev = set(json.loads(prev_row[0])) if prev_row else set()
    minutes = conn.execute("SELECT session_minutes FROM settings WHERE id = 1").fetchone()[0]
    n = 3 if minutes >= 30 else 2
    eligible = [k for k in ORDER if build(conn, k, seed=0)]
    rng = random.Random(day)
    fresh = [k for k in eligible if k not in prev]
    rng.shuffle(fresh)
    chosen = fresh[:n]
    if len(chosen) < 2:                    # few formats possible yet: top up, but keep the set different
        again = [k for k in eligible if k not in chosen]
        rng.shuffle(again)
        chosen += again[:2 - len(chosen)]
    chosen.sort(key=ORDER.index)
    conn.execute("INSERT OR REPLACE INTO practice_day (day, formats) VALUES (?, ?)", (day, json.dumps(chosen)))
    return chosen


def today(conn: sqlite3.Connection, seed: int | None = None) -> dict:
    kinds = formats_for_day(conn)
    games = [g for k in kinds if (g := build(conn, k, seed=seed))]
    return {"day": _today(conn), "formats": kinds, "games": games}


def log_result(conn: sqlite3.Connection, kind: str, correct: int, total: int) -> None:
    conn.execute("INSERT INTO practice_log (kind, correct, total) VALUES (?, ?, ?)", (kind, correct, total))
