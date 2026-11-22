"""Non-LLM verifier: lexical coverage and allowed grammar for a German text.

coverage = tokens whose lemma is known or a target / all counted tokens
Counted tokens exclude punctuation, numbers and proper names (Marco, Berlin, Spree…).

Grammar is checked against the unlocked grammar points; anything the learner hasn't
been taught yet (relative clauses, passive, genitive, Präteritum of most verbs, …)
is reported as an issue with the grammar_point code that blocks it.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache

import spacy
from spacy.tokens import Doc, Token

SPACY_MODEL = "de_core_news_md"

# Inflected forms spaCy doesn't reduce to the dictionary lemma we store.
PRONOUN_FORMS = {
    "mich": "ich", "mir": "ich", "dich": "du", "dir": "du", "ihn": "er", "ihm": "er",
    "uns": "wir", "euch": "ihr", "ihnen": "sie", "Ihnen": "Sie", "sich": "sich",
}
VERB_FORMS = {
    # modal / auxiliary forms incl. Konjunktiv II
    "sollte": "sollen", "solltest": "sollen", "sollten": "sollen", "solltet": "sollen",
    "könnte": "können", "könntest": "können", "könnten": "können", "könntet": "können",
    "konnte": "können", "konntest": "können", "konnten": "können",
    "musste": "müssen", "musstest": "müssen", "mussten": "müssen", "müsste": "müssen",
    "wollte": "wollen", "wolltest": "wollen", "wollten": "wollen",
    "durfte": "dürfen", "dürfte": "dürfen", "mochte": "mögen", "möchte": "möchten",
    "möchtest": "möchten", "möchten": "möchten", "möchtet": "möchten",
    "hätte": "haben", "hättest": "haben", "hätten": "haben", "hättet": "haben",
    "wäre": "sein", "wärst": "sein", "wären": "sein", "wärt": "sein",
    "würde": "werden", "würdest": "werden", "würden": "werden", "würdet": "werden",
    "weiß": "wissen", "weißt": "wissen", "wusste": "wissen",
    "muss": "müssen", "musst": "müssen", "kann": "können", "kannst": "können",
    "will": "wollen", "willst": "wollen", "darf": "dürfen", "darfst": "dürfen",
    "mag": "mögen", "magst": "mögen",
    "nimmt": "nehmen", "nimmst": "nehmen", "hält": "halten", "hältst": "halten",
}
# strong verbs change the stem vowel in du/er forms: isst → essen, liest → lesen, fährt → fahren
VOWEL_SWAPS = (("ie", "e"), ("i", "e"), ("äu", "au"), ("ä", "a"), ("ö", "o"))
UMLAUTS = "äöü"
EXCLUDED_POS = {"PUNCT", "SPACE", "NUM", "PROPN", "SYM", "X"}

GENITIVE_ONLY = {"des", "eines", "keines", "meines", "deines", "seines", "ihres", "unseres", "eures",
                 "dieses", "jedes", "welches"}

SUBORDINATORS = {"weil": "KONJ_WEIL", "dass": "KONJ_DASS", "wenn": "KONJ_WENN", "ob": "INDIREKTE_FRAGE"}


@lru_cache(maxsize=1)
def nlp():
    return spacy.load(SPACY_MODEL)


# ---- vocabulary index ------------------------------------------------------------

@dataclass
class Lexicon:
    by_lemma: dict[str, int]                 # lowercased lemma -> lemma_id
    forms: dict[str, int]                    # lowercased inflected form (plural, Partizip II) -> lemma_id
    known_ids: set[int]
    target_ids: set[int] = field(default_factory=set)

    def lookup(self, candidates: list[str]) -> int | None:
        """First matching lemma, but a target wins: 'früher' is the target, not known 'früh'."""
        found: list[int] = []
        for c in candidates:
            k = c.lower()
            for table in (self.by_lemma, self.forms):
                if k in table:
                    found.append(table[k])
        for lid in found:
            if lid in self.target_ids:
                return lid
        return found[0] if found else None


def build_lexicon(conn: sqlite3.Connection, target_ids: set[int] | None = None,
                  extra_known: set[int] | None = None) -> Lexicon:
    by_lemma: dict[str, int] = {}
    forms: dict[str, int] = {}
    for r in conn.execute("SELECT id, lemma, pos, plural, partizip2 FROM lemma ORDER BY id"):
        if r["pos"] == "PHRASE":
            continue
        by_lemma.setdefault(r["lemma"].lower(), r["id"])
        if r["plural"] and r["plural"] != "-":
            forms.setdefault(r["plural"].lower(), r["id"])
            if not r["plural"].endswith(("n", "s")):
                forms.setdefault(r["plural"].lower() + "n", r["id"])  # dative plural
        if r["partizip2"]:
            for p in r["partizip2"].split("/"):
                forms.setdefault(p.strip().lower(), r["id"])
    known = {r[0] for r in conn.execute("SELECT lemma_id FROM known_word WHERE state IN ('known', 'learning')")}
    return Lexicon(by_lemma, forms, known | (extra_known or set()), set(target_ids or ()))


# ---- token analysis ------------------------------------------------------------

def separable_lemma(tok: Token) -> str | None:
    """'baut … auf' → 'aufbauen': join a verb with its separated particle (dep 'svp')."""
    for child in tok.children:
        if child.dep_ == "svp" and child.tag_ == "PTKVZ":
            return child.text.lower() + tok.lemma_
    return None


def candidates(tok: Token) -> list[str]:
    out: list[str] = []
    if tok.pos_ in ("VERB", "AUX"):
        sep = separable_lemma(tok)
        if sep:
            out.append(sep)
    out += [tok.lemma_, tok.text]
    if tok.text in PRONOUN_FORMS or tok.text.lower() in PRONOUN_FORMS:
        out.append(PRONOUN_FORMS.get(tok.text, PRONOUN_FORMS.get(tok.text.lower(), "")))
    if tok.text.lower() in VERB_FORMS:
        out.append(VERB_FORMS[tok.text.lower()])
    if tok.pos_ in ("ADJ", "DET", "ADV", "PRON") or tok.tag_ in ("ADJA", "ADJD"):
        # inflected adjectives/determiners: "Letzten" → "letzt", "nächste" → "nächst", "lange" → "lang"
        stem = re.sub(r"(en|em|er|es|e)$", "", tok.text.lower())
        out += [stem, stem + "er"]
    if tok.pos_ in ("VERB", "AUX") and tok.tag_ not in ("VVPP", "VAPP", "VMPP"):
        # crude stemmer for regular forms spaCy misses: "arbeitest" → "arbeiten"
        low = tok.text.lower()
        stems = {low[: -len(suf)] for suf in ("est", "st", "et", "t", "e", "en") if low.endswith(suf)}
        for stem in stems:  # "isst" → "iss" and "is"; try them all
            out += [stem + "en", stem + "n"]
            for a, b in VOWEL_SWAPS:
                if a in stem:
                    out.append(stem.replace(a, b, 1) + "en")
    return [c for c in out if c]


def is_counted(tok: Token) -> bool:
    if tok.pos_ in EXCLUDED_POS or tok.is_punct or tok.is_space or tok.like_num:
        return False
    if any(ch.isdigit() for ch in tok.text):
        return False
    if tok.tag_ == "PTKVZ" and tok.dep_ == "svp":
        return False  # the particle is counted with its verb
    if tok.ent_type_ in ("PER", "LOC", "ORG") and tok.text[:1].isupper() and tok.pos_ != "NOUN":
        return False
    return True


# ---- grammar ---------------------------------------------------------------------

@dataclass
class GrammarIssue:
    code: str
    text: str
    sentence: str

    def to_dict(self) -> dict:
        return {"code": self.code, "text": self.text, "sentence": self.sentence}


def _has_child(tok: Token, tags: tuple[str, ...], dep: str = "oc") -> Token | None:
    for c in tok.children:
        if c.dep_ == dep and c.tag_ in tags:
            return c
    return None


def grammar_issues(doc: Doc, unlocked: set[str]) -> list[GrammarIssue]:
    issues: list[GrammarIssue] = []

    def flag(code: str, tok: Token, span_text: str | None = None):
        if code not in unlocked:
            issues.append(GrammarIssue(code, span_text or tok.text, tok.sent.text.strip()))

    for tok in doc:
        low = tok.text.lower()
        mood = tok.morph.get("Mood")
        tense = tok.morph.get("Tense")

        # Relative clauses: the pronoun tag, or the clause marker when spaCy mis-tags the pronoun as ART
        if tok.tag_ in ("PRELS", "PRELAT"):
            flag("BLOCK_RELATIVSATZ", tok)
        elif tok.dep_ == "rc" and tok.pos_ in ("VERB", "AUX") and not any(
                c.tag_ in ("PRELS", "PRELAT") for c in tok.subtree):
            flag("BLOCK_RELATIVSATZ", tok, tok.sent.text.strip())

        # Genitive: unambiguous genitive determiners, or a noun used as genitive attribute.
        # ("der" alone is ambiguous; names with -s like "Marcos Rad" are tolerated.)
        if "Gen" in tok.morph.get("Case") and (
                (tok.pos_ == "DET" and low in GENITIVE_ONLY) or (tok.pos_ == "NOUN" and tok.dep_ == "ag")):
            flag("BLOCK_GENITIV", tok)

        # Subordinate clauses
        if tok.tag_ == "KOUS":
            flag(SUBORDINATORS.get(low, "BLOCK_NEBENSATZ_ANDERE"), tok)
        if low == "deshalb":
            flag("KONJ_DESHALB", tok)
        if tok.tag_ in ("PWAV", "PWS", "PWAT") and tok.head.dep_ == "oc" and tok.head.i > tok.i \
                and tok.head.tag_.endswith("FIN"):
            flag("INDIREKTE_FRAGE", tok)

        # werden: passive, future, Konjunktiv II
        lemma = VERB_FORMS.get(low, tok.lemma_)
        if lemma == "werden" and tok.pos_ == "AUX":
            if _has_child(tok, ("VVPP", "VAPP", "VMPP")):
                flag("BLOCK_PASSIV", tok)
            elif _has_child(tok, ("VVINF", "VAINF", "VMINF")):
                flag("KONJ2_RAT_KOENNTE_SOLLTE" if "Sub" in mood else "BLOCK_FUTUR", tok)

        if tok.tag_.endswith("FIN"):
            if "Sub" in mood:
                if lemma in ("sollen", "können", "werden"):
                    flag("KONJ2_RAT_KOENNTE_SOLLTE", tok)
                elif lemma in ("haben", "sein"):
                    flag("KONJ2_WUNSCH_HAETTE_WAERE", tok)
                elif lemma not in ("mögen", "möchten") and any(
                        u in low and u not in lemma.lower() for u in UMLAUTS):
                    # only real Konjunktiv II stems (käme, ginge→ no, bräuchte, wüsste …); regular
                    # verbs look identical to the indicative ("ob ich … brauche") and are fine
                    flag("BLOCK_KONJUNKTIV_ANDERE", tok)
            elif "Past" in tense:
                if lemma in ("haben", "sein") and _has_child(tok, ("VVPP", "VAPP", "VMPP")):
                    flag("BLOCK_PLUSQUAMPERFEKT", tok)
                elif lemma in ("haben", "sein"):
                    flag("PRAET_WAR_HATTE", tok)
                elif lemma != "werden":
                    flag("BLOCK_PRAETERITUM", tok)
    # one issue per (code, text) is enough for the repair prompt
    seen, unique = set(), []
    for i in issues:
        if (i.code, i.text.lower()) not in seen:
            seen.add((i.code, i.text.lower()))
            unique.append(i)
    return unique


# ---- report ------------------------------------------------------------------

@dataclass
class Report:
    coverage: float
    counted: int
    word_count: int
    unknown: list[str]                       # unique unknown surface lemmas
    target_counts: dict[int, int]
    grammar: list[GrammarIssue]

    def to_dict(self) -> dict:
        return {"coverage": round(self.coverage, 4), "counted": self.counted, "word_count": self.word_count,
                "unknown": self.unknown, "target_counts": self.target_counts,
                "grammar": [g.to_dict() for g in self.grammar]}

    def passes(self, *, min_coverage: float, min_target_uses: int = 3) -> bool:
        return (self.coverage >= min_coverage and not self.grammar
                and all(c >= min_target_uses for c in self.target_counts.values()))


def unlocked_codes(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT code FROM grammar_point WHERE unlocked = 1")}


def analyse(text: str, lex: Lexicon, unlocked: set[str]) -> tuple[Doc, Report]:
    doc = nlp()(text)
    counted = ok = 0
    unknown: list[str] = []
    target_counts = {tid: 0 for tid in lex.target_ids}
    for tok in doc:
        lid = lex.lookup(candidates(tok)) if not (tok.is_punct or tok.is_space) else None
        # a target always counts, even if spaCy calls it a name (e.g. the acronym "EM")
        if not is_counted(tok) and not (lid is not None and lid in lex.target_ids and tok.pos_ == "PROPN"):
            continue
        counted += 1
        if lid is not None and lid in lex.target_ids:
            target_counts[lid] += 1
            ok += 1
        elif lid is not None and lid in lex.known_ids:
            ok += 1
        else:
            label = (separable_lemma(tok) or tok.lemma_) if tok.pos_ in ("VERB", "AUX") else tok.lemma_
            if label not in unknown:
                unknown.append(label)
    words = sum(1 for t in doc if not (t.is_punct or t.is_space))
    report = Report(ok / counted if counted else 1.0, counted, words, unknown, target_counts,
                    grammar_issues(doc, unlocked))
    return doc, report


def verify(conn: sqlite3.Connection, text: str, target_ids: set[int] | None = None) -> Report:
    return analyse(text, build_lexicon(conn, target_ids), unlocked_codes(conn))[1]
