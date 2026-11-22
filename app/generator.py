"""Reader pipeline: select → generate → verify → repair (≤3) → gloss → annotate → questions → cache."""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from spacy.tokens import Doc, Token

from . import srs
from .db import row_to_dict, transaction
from .llm import Draft, GenerationError, Writer
from .verifier import (Report, analyse, build_lexicon, candidates, grammar_presence, is_counted, separable_lemma,
                       unlocked_codes)

PERSONAL_PATH = Path(__file__).resolve().parent / "seed" / "personal.json"
TARGET_POS = ("NOUN", "VERB", "ADJ", "ADV")
MIN_COVERAGE = 0.96           # target for a clean pass
ACCEPT_COVERAGE = 0.95        # hard floor after repairs (plan: "reject if still under 95 %")
MIN_TARGET_USES = 3
MAX_REPAIRS = 3


@dataclass
class Result:
    text_id: int
    report: Report
    attempts: int


# ---- selection ---------------------------------------------------------------------

def select_targets(conn: sqlite3.Connection, lesson_number: int, n: int = 6, seed: int | None = None) -> list[dict]:
    """Lesson words the learner doesn't know yet; least-read first (narrow reading recycles them)."""
    rows = conn.execute(
        f"""SELECT m.*, COALESCE(k.times_seen_in_text, 0) AS seen FROM lemma m
            JOIN lesson l ON l.id = m.lesson_id AND l.number = ?
            LEFT JOIN known_word k ON k.lemma_id = m.id
            WHERE COALESCE(k.state, 'new') != 'known' AND m.pos IN ({','.join('?' * len(TARGET_POS))})
            ORDER BY seen, m.id""", (lesson_number, *TARGET_POS)).fetchall()
    rows = [row_to_dict(r) for r in rows]
    if not rows:
        return []
    least = min(r["seen"] for r in rows)
    pool = [r for r in rows if r["seen"] <= least + 1]
    random.Random(seed).shuffle(pool)
    return pool[:n]


def review_words(conn: sqlite3.Connection, limit: int = 8) -> list[dict]:
    rows = conn.execute(
        """SELECT DISTINCT m.* FROM card c JOIN lemma m ON m.id = c.lemma_id
           WHERE c.due <= ? AND m.pos != 'PHRASE' ORDER BY c.due LIMIT ?""",
        (srs.to_db(srs.now_utc()), limit)).fetchall()
    return [row_to_dict(r) for r in rows]


def known_word_list(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """SELECT m.lemma, m.pos, m.article FROM lemma m JOIN known_word k ON k.lemma_id = m.id
           WHERE k.state IN ('known', 'learning') ORDER BY m.lemma COLLATE NOCASE""").fetchall()
    return [f"{r['article']} {r['lemma']}" if r["article"] else r["lemma"] for r in rows]


def fmt_word(w: dict) -> str:
    base = f"{w['article']} {w['lemma']}" if w.get("article") else w["lemma"]
    return f"{base} ({w['gloss_en'] or w['gloss_es']})"


# ---- prompts -----------------------------------------------------------------------

SYSTEM = """You write short graded reading texts in German for one adult learner at level A2.1 \
(Momente A2.1). The learner's native language is Spanish; they also speak English.

Hard rules, in priority order:
1. Vocabulary: use ONLY words from the KNOWN WORDS list and the TARGET WORDS, in any inflected form. \
Personal names, place names and numbers are always fine. If a word is not on the lists, find another way \
to say it with listed words. Never use compound nouns that are not on the lists.
2. Grammar: use ONLY the ALLOWED GRAMMAR. Never use anything on the FORBIDDEN list, which means in practice: \
no relative clauses, no passive, no genitive (use von + Dativ), no Futur (use present + time word), \
no Präteritum except the forms explicitly allowed (use Perfekt), no subordinate clauses except with the \
allowed conjunctions. Prefer short main clauses.
3. Every TARGET WORD appears at least 3 times, naturally, in different sentences.
4. The text practises the lesson's TARGET GRAMMAR: use each target grammar point naturally at least \
2 times (e.g. several weil-sentences in a lesson about weil). This is what the lesson is about.
5. Length: 200-300 words, 4-6 short paragraphs separated by a blank line.

Content: an everyday story about the learner's life in Berlin, written so it is interesting to read: a small \
problem, a plan, a conversation. Use the PERSONAL CONTEXT and keep recurring characters consistent with \
earlier texts in the series (narrow reading: same theme, same people, new situation). Dialogue in quotation \
marks is welcome. Write natural German a native speaker would accept, never a word list in disguise.
The narrator is "ich" (the learner). Do not invent facts about the learner's past, hometown, family or \
job beyond the PERSONAL CONTEXT; invent freely for the other characters."""

QUESTION_SYSTEM = """You write comprehension questions for a German A2.1 learner about a text they just read. \
Use only simple words that appear in the text or are very basic, and the same simple grammar as the text: \
no relative clauses, no passive, no genitive, no Präteritum except war/hatte. The narrator "ich" of the text is \
the learner, so ask about the narrator with "du" (e.g. "Was machst du am Sonntag?"). \
Test understanding of meaning, not memory of exact sentences."""


def personal_context() -> str:
    data = json.loads(PERSONAL_PATH.read_text(encoding="utf-8"))
    data.pop("_comment", None)
    if not data.get("partner_name"):
        data.pop("partner_name", None)
        data.pop("partner_noun", None)
        data["note"] = "Do not mention a partner by name or gendered noun."
    return json.dumps(data, ensure_ascii=False, indent=1)


def grammar_lists(conn: sqlite3.Connection) -> tuple[list[str], list[str]]:
    rows = conn.execute("SELECT name, unlocked, rule FROM grammar_point ORDER BY id").fetchall()
    allowed = [r["name"] for r in rows if r["unlocked"]]
    forbidden = [f"{r['name']} ({r['rule']})" if r["rule"] and r["rule"].startswith("Blocked") else r["name"]
                 for r in rows if not r["unlocked"]]
    return allowed, forbidden


def build_prompt(conn: sqlite3.Connection, lesson: dict, targets: list[dict], review: list[dict]) -> str:
    allowed, forbidden = grammar_lists(conn)
    previous = conn.execute(
        "SELECT title, summary FROM text WHERE lesson_id = ? ORDER BY id DESC LIMIT 4", (lesson["id"],)).fetchall()
    series = "\n".join(f"- {r['title']}: {r['summary']}" for r in reversed(previous)) or "- (first text of the series)"
    target_grammar = target_grammar_points(conn, lesson)
    return f"""THEME (Lektion {lesson['number']}): {lesson['theme']} · word field: {lesson['word_field']}
Useful phrases from the lesson (use 1-2 if they fit): {"; ".join(lesson['redemittel'])}

TARGET GRAMMAR of this lesson (use each at least 2 times):
{chr(10).join(f"- {g['name']}: {g['rule']} Example: {g['example']}" for g in target_grammar)}

TARGET WORDS (each at least 3 times):
{chr(10).join("- " + fmt_word(t) for t in targets)}

REVIEW WORDS (include several if natural):
{", ".join(fmt_word(w) for w in review) or "(none)"}

EARLIER TEXTS IN THIS SERIES:
{series}

PERSONAL CONTEXT:
{personal_context()}

ALLOWED GRAMMAR:
{chr(10).join("- " + a for a in allowed)}

FORBIDDEN GRAMMAR:
{chr(10).join("- " + f for f in forbidden)}

KNOWN WORDS ({len(known := known_word_list(conn))}):
{", ".join(known)}"""


def target_grammar_points(conn: sqlite3.Connection, lesson: dict) -> list[dict]:
    codes = lesson["grammar_points"]
    if not codes:
        return []
    rows = [dict(r) for r in conn.execute(
        f"SELECT code, name, rule, example FROM grammar_point WHERE unlocked = 1 AND code IN ({','.join('?' * len(codes))})",
        codes)]
    rows.sort(key=lambda g: codes.index(g["code"]))
    return rows


def repair_prompt(base_prompt: str, draft: Draft, report: Report, targets: list[dict],
                  missing_grammar: list[dict] | None = None) -> str:
    problems = []
    for g in missing_grammar or []:
        problems.append(f"The text does not use the lesson's target grammar '{g['name']}' yet. "
                        f"Use it naturally at least 2 times (example: {g['example']}).")
    if report.unknown:
        problems.append("These words are NOT on the lists. Replace each with known words or rephrase: "
                        + ", ".join(report.unknown))
    for g in report.grammar:
        problems.append(f"Forbidden grammar ({g.code}) at '{g.text}' in: \"{g.sentence}\" → rewrite that sentence.")
    by_id = {t["id"]: t for t in targets}
    for tid, n in report.target_counts.items():
        if n < MIN_TARGET_USES:
            problems.append(f"Target word '{fmt_word(by_id[tid])}' appears {n}× – use it at least {MIN_TARGET_USES}×.")
    return f"""{base_prompt}

YOUR PREVIOUS DRAFT (title: {draft.title}):
{draft.body}

A checker found these problems. Rewrite the whole text, keeping the story, and fix every problem:
{chr(10).join("- " + p for p in problems)}"""


# ---- annotation -----------------------------------------------------------------------

CASES = {"Nom": "Nominativ", "Acc": "Akkusativ", "Dat": "Dativ", "Gen": "Genitiv"}
CONTRACTIONS = {"im": "in + dem", "am": "an + dem", "zum": "zu + dem", "zur": "zu + der",
                "vom": "von + dem", "beim": "bei + dem", "ins": "in + das", "ans": "an + das"}


def token_note(tok: Token, lemma: dict | None) -> str | None:
    low = tok.text.lower()
    if low in CONTRACTIONS:
        return f"{tok.text} = {CONTRACTIONS[low]}"
    if tok.tag_ in ("VVPP", "VAPP", "VMPP"):
        aux = lemma.get("aux") if lemma else None
        return f"Partizip II de {lemma['lemma'] if lemma else tok.lemma_}" + (f" · Perfekt con {aux}" if aux else "")
    if tok.pos_ in ("VERB", "AUX") and tok.tag_.endswith("FIN"):
        sep = separable_lemma(tok)
        bits = []
        if sep:
            bits.append(f"verbo separable: {sep}")
        mood, tense = tok.morph.get("Mood"), tok.morph.get("Tense")
        if "Sub" in mood:
            bits.append("Konjunktiv II")
        elif "Past" in tense:
            bits.append("Präteritum")
        elif lemma and lemma["lemma"].lower() != low:
            bits.append(f"Präsens de {lemma['lemma']}")
        return " · ".join(bits) or None
    if tok.pos_ == "NOUN":
        case = tok.morph.get("Case")
        num = tok.morph.get("Number")
        parts = [CASES[c] for c in case if c in CASES][:1] + (["Plural"] if "Plur" in num else [])
        return " · ".join(parts) or None
    if tok.tag_ == "KOUS":
        return "conjunción subordinante: el verbo va al final"
    return None


def annotate(doc: Doc, lex, lemma_rows: dict[int, dict]) -> list[dict]:
    out: list[dict] = []
    for tok in doc:
        if tok.is_space:
            if "\n" in tok.text:
                out.append({"br": True})
            continue
        entry: dict = {"t": tok.text, "ws": tok.whitespace_}
        src = tok.head if (tok.tag_ == "PTKVZ" and tok.dep_ == "svp") else tok
        lid = lex.lookup(candidates(src)) if not tok.is_punct else None
        if is_counted(tok) or src is not tok or (lid is not None and lid in lex.target_ids):
            if lid is not None:
                entry["id"] = lid
                if lid in lex.target_ids:
                    entry["target"] = True
            note = token_note(tok, lemma_rows.get(lid) if lid else None)
            if note:
                entry["note"] = note
        out.append(entry)
    return out


# ---- pipeline ----------------------------------------------------------------------------

def _store_glosses(conn: sqlite3.Connection, writer: Writer, words: list[str], body: str) -> None:
    if not words:
        return
    prompt = (f"Give dictionary entries for these German words as used in the text below. "
              f"Words: {', '.join(words)}\n\nText:\n{body}")
    for g in writer.gloss(prompt):
        if g.pos == "NOUN" and g.article not in ("der", "die", "das"):
            continue
        conn.execute(
            """INSERT INTO lemma (lemma, pos, article, plural, aux, partizip2, gloss_es, gloss_en, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'text') ON CONFLICT(lemma, pos, article) DO NOTHING""",
            (g.lemma, g.pos, g.article or None, g.plural or None, g.aux or None, g.partizip2 or None,
             g.gloss_es, g.gloss_en))


def generate_text(conn: sqlite3.Connection, writer: Writer, *, lesson_number: int | None = None,
                  n_targets: int = 6, seed: int | None = None) -> Result:
    if lesson_number is None:
        lesson_number = conn.execute("SELECT current_lesson FROM settings WHERE id = 1").fetchone()[0]
    lesson = row_to_dict(conn.execute("SELECT * FROM lesson WHERE number = ?", (lesson_number,)).fetchone())
    targets = select_targets(conn, lesson_number, n_targets, seed)
    if not targets:
        raise GenerationError(f"Lektion {lesson_number}: alle Wörter sind schon bekannt.")
    target_ids = {t["id"] for t in targets}
    base = build_prompt(conn, lesson, targets, review_words(conn))

    lex = build_lexicon(conn, target_ids)
    unlocked = unlocked_codes(conn)
    wanted = target_grammar_points(conn, lesson)
    missing = lambda d: [g for g in wanted if g["code"] not in grammar_presence(d)]  # noqa: E731
    draft = writer.write(SYSTEM, base)
    doc, report = analyse(draft.body, lex, unlocked)
    attempts = 1
    while (not report.passes(min_coverage=MIN_COVERAGE, min_target_uses=MIN_TARGET_USES) or missing(doc)) \
            and attempts <= MAX_REPAIRS:
        draft = writer.write(SYSTEM, repair_prompt(base, draft, report, targets, missing(doc)))
        doc, report = analyse(draft.body, lex, unlocked)
        attempts += 1
    # Target grammar is strongly requested and repaired, but a text that is otherwise good is kept even
    # if one point is missing; the report records it.
    used = grammar_presence(doc)
    report_extra = {"target_grammar": {g["code"]: g["code"] in used for g in wanted}}

    if report.grammar or report.coverage < ACCEPT_COVERAGE or any(c < 2 for c in report.target_counts.values()):
        raise GenerationError(
            f"Kein Text hat die Prüfung bestanden (Abdeckung {report.coverage:.0%}, "
            f"Grammatik: {[g.code for g in report.grammar]}, unbekannt: {report.unknown[:8]}).")

    with transaction(conn):
        _store_glosses(conn, writer, report.unknown, draft.body)
        lex = build_lexicon(conn, target_ids)  # include the freshly glossed words for tap-to-gloss
        ids = {i for t in annotate(doc, lex, {}) if (i := t.get("id"))}
        lemma_rows = {r["id"]: dict(r) for r in conn.execute(
            f"SELECT * FROM lemma WHERE id IN ({','.join('?' * len(ids))})", list(ids))} if ids else {}
        tokens = annotate(doc, lex, lemma_rows)
        cur = conn.execute(
            """INSERT INTO text (lesson_id, title, body, summary, annotations, coverage, target_lemma_ids, report_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (lesson["id"], draft.title, draft.body, draft.summary, json.dumps(tokens, ensure_ascii=False),
             report.coverage, json.dumps(sorted(target_ids)),
             json.dumps({**report.to_dict(), **report_extra}, ensure_ascii=False)))
        text_id = cur.lastrowid

    questions = checked_questions(writer, draft, lex, unlocked)
    with transaction(conn):
        for q in questions[:6]:
            conn.execute("INSERT INTO question (text_id, type, prompt, options, answer) VALUES (?, ?, ?, ?, ?)",
                         (text_id, q.type, q.prompt, json.dumps(q.options, ensure_ascii=False), q.answer))
    return Result(text_id, report, attempts)


def checked_questions(writer: Writer, draft: Draft, lex, unlocked: set[str]) -> list:
    """Questions get the same grammar check as the text: one retry with feedback, then drop offenders."""
    ask = (f"Write 5 questions about this text: 2 true_false, 2 multiple_choice (3 options), 1 short_answer "
           f"that can be answered in one short German sentence.\n\nTitle: {draft.title}\n\n{draft.body}")
    questions = writer.questions(QUESTION_SYSTEM, ask)

    def problems(q) -> list:
        return analyse(" ".join([q.prompt, *q.options, q.answer]), lex, unlocked)[1].grammar

    bad = [(q, problems(q)) for q in questions]
    bad = [(q, p) for q, p in bad if p]
    if bad:
        notes = "\n".join(f"- \"{q.prompt}\" uses forbidden grammar ({p[0].code} at '{p[0].text}')" for q, p in bad)
        questions = writer.questions(QUESTION_SYSTEM, f"{ask}\n\nA checker rejected earlier questions:\n{notes}\n"
                                                      "Rewrite all 5 without these structures.")
    return [q for q in questions if not problems(q)]


# ---- after reading ---------------------------------------------------------------------

def first_sentence_with(doc_text: str, tokens: list[dict], lemma_id: int) -> str | None:
    sentence, found = [], False
    for t in tokens:
        if t.get("br"):
            sentence = []
            continue
        sentence.append(t["t"] + t["ws"])
        if t.get("id") == lemma_id:
            found = True
        if t["t"] in (".", "!", "?") or t["t"].endswith(("!", "?")):
            if found:
                return "".join(sentence).strip()
            sentence = []
    return "".join(sentence).strip() if found else None


def finish_reading(conn: sqlite3.Connection, text_id: int, *, seconds: float | None = None,
                   reread: bool = False) -> dict:
    t = row_to_dict(conn.execute("SELECT * FROM text WHERE id = ?", (text_id,)).fetchone())
    if t is None:
        raise KeyError(text_id)
    tokens = json.loads(t["annotations"]) if isinstance(t["annotations"], str) else t["annotations"]
    seen = {tok["id"] for tok in tokens if tok.get("id")}
    with transaction(conn):
        introduced = []
        for lid in t["target_lemma_ids"]:
            sentence = first_sentence_with(t["body"], tokens, lid)
            if srs.introduce_word(conn, lid, sentence=sentence, text_id=text_id):
                introduced.append(lid)
        # every word met in the text counts, also ones without a card yet (state stays 'new')
        conn.executemany(
            """INSERT INTO known_word (lemma_id, state, times_seen_in_text) VALUES (?, 'new', 1)
               ON CONFLICT(lemma_id) DO UPDATE SET times_seen_in_text = times_seen_in_text + 1""",
            [(lid,) for lid in seen])
        wpm = None
        if seconds and seconds > 5:
            words = sum(1 for tok in tokens if tok.get("t", "").isalpha())
            wpm = round(words / (seconds / 60))
            log = (t["wpm_log"] or []) + [{"ts": srs.to_db(srs.now_utc()), "wpm": wpm}]
            conn.execute("UPDATE text SET wpm_log = ? WHERE id = ?", (json.dumps(log), text_id))
        conn.execute("UPDATE text SET read_count = read_count + 1 WHERE id = ?", (text_id,))
        conn.execute("INSERT INTO reading_log (text_id, kind, seconds, wpm, ts) VALUES (?, ?, ?, ?, ?)",
                     (text_id, "reread" if reread else "read", seconds, wpm, srs.to_db(srs.now_utc())))
    return {"introduced": len(introduced), "wpm": wpm}
