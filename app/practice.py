"""Short practice formats that rotate between days, so vocabulary sessions don't feel identical.

Each day's vocab session uses 2-3 of these, never the same set as the previous session day:

  match    timed match-pairs: 6 German ↔ 6 English (recall of meaning)
  listen   hear a German word, pick its meaning (know it by ear, not just its spelling)
  gender   der/die/das sorting: drag (or tap) nouns into the gender boxes
  plural   der Baum → die Bäume / Baume / Bäumen / Baums (plural patterns)
  perfekt  fahren → ist gefahren / hat gefahren / ist gefahrt / hat gefahrt (haben/sein + Partizip II)
  cloze    gaps in yesterday's text: pick the missing word

Every format has to need real German knowledge: meaning, gender, a form, or a word in context.
(An 'odd one out' by lesson theme and a hear-the-word-pick-the-spelling game were dropped: the book's
lesson themes aren't real categories, and matching a sound to its spelling needs no German.)

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
    "listen": "Hören: Was bedeutet das?",
    "gender": "der · die · das",
    "plural": "Der Plural",
    "perfekt": "Perfekt: hat oder ist?",
    "cloze": "Lücken im Text von gestern",
}
ORDER = list(FORMATS)

_WORDS = """SELECT m.id, m.lemma, m.pos, m.article, m.plural, m.aux, m.partizip2, m.gloss_en, m.gloss_es, m.cognate, m.source, m.deck,
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
    """Hear the word (with its article), choose what it means: you have to know it by ear."""
    words = [w for w in met_words(conn) if gloss_of(w, col)]
    rounds = []
    for w in _take(words, 6, rng, prefer=4):
        answer = gloss_of(w, col)
        same = [x for x in words if x["pos"] == w["pos"] and gloss_of(x, col).lower() != answer.lower()]
        others, seen = [], {answer.lower()}
        for o in _take(same, 12, rng):
            g = gloss_of(o, col)
            if g.lower() not in seen:
                others.append(g)
                seen.add(g.lower())
            if len(others) == 3:
                break
        if len(others) < 3:
            continue
        options = [answer, *others]
        rng.shuffle(options)
        rounds.append({"say": display(w), "answer": answer, "word": display(w), "options": options})
    return {"rounds": rounds[:5]} if len(rounds) >= 4 else None


def build_gender(conn, rng, col):
    nouns = [w for w in met_words(conn, "NOUN") if w["article"]]
    pick = _take(nouns, 8, rng, prefer=4)
    if len(pick) < 6:
        return None
    return {"nouns": [{"id": w["id"], "lemma": w["lemma"], "article": w["article"], "gloss": gloss_of(w, col)}
                      for w in pick]}


UMLAUT = {"a": "ä", "o": "ö", "u": "ü", "au": "äu", "A": "Ä", "O": "Ö", "U": "Ü", "Au": "Äu"}
MODALS = {"können", "müssen", "wollen", "sollen", "dürfen", "mögen", "möchten"}


def umlauted(word: str) -> str:
    """Umlaut on the last a/o/u/au, but only in the last part of the word (Baum → Bäum, but never
    Hältestelle: compounds change only their last element)."""
    import re as _re
    stem = _re.sub(r"(e|er|el|en)$", "", word)
    m = None
    for m in _re.finditer(r"(?<![eE])(?:au|Au|[aouAOU])(?![iyuIY])", stem):   # never inside ai/ei/eu/ou
        pass
    if m is None or len(stem) - m.start() > 4:
        return word
    return word[:m.start()] + UMLAUT[m.group(0)] + word[m.end():]


def wrong_plurals(lemma: str, plural: str) -> list[str]:
    """Wrong plurals a learner would really produce, chosen by how the word ends (the endings that
    exist for that kind of noun, umlaut only where German uses it). Words ending in other vowels
    (Auto, Kino) only take -s, so they get no question."""
    low = lemma.lower()
    uml = umlauted(lemma)
    if low.endswith(("ung", "heit", "keit", "schaft", "ion", "tät")):
        cands = [lemma + "e", lemma + "s", lemma, lemma + "er"]
    elif low.endswith("in"):
        cands = [lemma + "en", lemma + "e", lemma + "s", lemma]
    elif low.endswith(("er", "el", "en")):
        cands = [lemma, uml, lemma + "n", lemma + "s", uml + "n"]
    elif low.endswith("e"):
        cands = [lemma, lemma + "s", lemma + "n", uml + "n"]
    elif low.endswith(("au", "ei", "eu")):
        cands = [lemma + "e", lemma + "s", lemma, lemma + "n"]
    elif low[-1] in "aiouy":
        return []
    else:
        cands = [lemma + "e", uml + "e", lemma + "er", uml + "er", lemma + "en",
                 lemma + ("e" if low.endswith("s") else "s"), lemma]
    out = []
    for f in cands:
        if f != plural and f not in out:
            out.append(f)
    return out


def build_plural(conn, rng, col):
    nouns = [w for w in met_words(conn, "NOUN")
             if w["article"] and w["plural"] and w["plural"] not in ("-", "") and " " not in w["lemma"]]
    rounds = []
    for w in _take(nouns, 8, rng, prefer=4):
        wrong = wrong_plurals(w["lemma"], w["plural"])
        rng.shuffle(wrong)
        if len(wrong) < 3:
            continue
        options = [w["plural"], *wrong[:3]]
        rng.shuffle(options)
        rounds.append({"prompt": f"{w['article']} {w['lemma']}", "gloss": gloss_of(w, col),
                       "answer": w["plural"], "options": options})
    return {"rounds": rounds[:6]} if len(rounds) >= 4 else None


def wrong_partizip(p2: str) -> str:
    """The typical mix-ups: strong vs weak ending (gefahren ↔ gefahrt, gelüftet → gelüften) and
    ge- on -ieren verbs (probiert → geprobiert)."""
    if p2.endswith("iert") and not p2.startswith("ge"):
        return "ge" + p2
    if p2.endswith("en"):
        return p2[:-2] + "t"
    if p2.endswith("et"):
        return p2[:-2] + "en"
    if p2.endswith("t"):
        return p2[:-1] + "en"
    return p2 + "t"


def build_perfekt(conn, rng, col):
    verbs = [w for w in met_words(conn, "VERB")
             if w["aux"] in ("haben", "sein") and w["partizip2"] and w["lemma"] not in MODALS]
    sein = [w for w in verbs if w["aux"] == "sein" and w["lemma"] != "sein"]
    picks = _take(sein, 2, rng)                     # always some sein verbs, or 'hat' is a safe guess
    picks += [w for w in _take(verbs, 10, rng, prefer=3) if w not in picks][:6 - len(picks)]
    rng.shuffle(picks)
    rounds = []
    for w in picks:
        aux = "ist" if w["aux"] == "sein" else "hat"
        other = "hat" if aux == "ist" else "ist"
        bad = wrong_partizip(w["partizip2"])
        options = [f"{aux} {w['partizip2']}", f"{other} {w['partizip2']}", f"{aux} {bad}", f"{other} {bad}"]
        answer = options[0]
        rng.shuffle(options)
        rounds.append({"prompt": w["lemma"], "gloss": gloss_of(w, col), "answer": answer, "options": options,
                       "why": "Bewegung/Veränderung → sein" if aux == "ist" else "die meisten Verben → haben"})
    return {"rounds": rounds[:6]} if len(rounds) >= 4 else None


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


BUILDERS = {"match": build_match, "listen": build_listen, "gender": build_gender, "plural": build_plural,
            "perfekt": build_perfekt, "cloze": build_cloze}


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
    if row and all(k in FORMATS for k in json.loads(row[0])):
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
