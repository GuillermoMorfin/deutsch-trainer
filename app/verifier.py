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
    "war": "sein", "warst": "sein", "waren": "sein", "wart": "sein",
    "bin": "sein", "bist": "sein", "ist": "sein", "sind": "sein", "seid": "sein",
    "habe": "haben", "hast": "haben", "hat": "haben", "habt": "haben",
    "hatte": "haben", "hattest": "haben", "hatten": "haben", "hattet": "haben",
}
DET_FORMS = {f: "euer" for f in ("eure", "euren", "eurem", "eurer", "eures")}
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
    by_lemma: dict[str, list[int]]           # lowercased lemma -> lemma_ids ("mal" and "Mal" share a key)
    forms: dict[str, list[int]]              # lowercased inflected form (plural, Partizip II) -> lemma_ids
    known_ids: set[int]
    target_ids: set[int] = field(default_factory=set)

    def lookup(self, candidates: list[str]) -> int | None:
        """All matching lemmas; a target wins ('früher' is the target, not known 'früh'; 'das Mal' the
        target, not the adverb 'mal'), then a known word, then the first match."""
        found: list[int] = []
        for c in candidates:
            k = c.lower()
            for table in (self.by_lemma, self.forms):
                found += table.get(k, [])
        for pool in (self.target_ids, self.known_ids):
            for lid in found:
                if lid in pool:
                    return lid
        return found[0] if found else None


# Words a grammar point is made of: once the point is unlocked they count as known
# (a lesson about letzt-/nächst-/jed- must be able to say "letzten Sommer").
GRAMMAR_WORDS = {
    "LETZT_NAECHST_JED": ("letzt", "nächst", "jeder"), "KONJ_WEIL": ("weil",), "KONJ_DESHALB": ("deshalb",),
    "KONJ_DASS": ("dass",), "KONJ_WENN": ("wenn",), "INDIREKTE_FRAGE": ("ob",),
}


def personal_names() -> set[str]:
    """Places and people from personal.json count as names (Tiergarten, Prenzlauer Berg, Marco …)."""
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parent / "seed" / "personal.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    names = list(data.get("places", [])) + list(data.get("friends", [])) + list(data.get("recurring_characters", {}))
    words = set()
    for n in names:
        for w in re.findall(r"[A-ZÄÖÜ][\wäöüß-]+", n):
            words.add(w.lower())
    return words


def build_lexicon(conn: sqlite3.Connection, target_ids: set[int] | None = None,
                  extra_known: set[int] | None = None) -> Lexicon:
    by_lemma: dict[str, list[int]] = {}
    forms: dict[str, list[int]] = {}
    for r in conn.execute("SELECT id, lemma, pos, plural, partizip2 FROM lemma ORDER BY id"):
        if r["pos"] == "PHRASE":
            continue
        by_lemma.setdefault(r["lemma"].lower(), []).append(r["id"])
        if r["plural"] and r["plural"] != "-":
            forms.setdefault(r["plural"].lower(), []).append(r["id"])
            if not r["plural"].endswith(("n", "s")):
                forms.setdefault(r["plural"].lower() + "n", []).append(r["id"])  # dative plural
        if r["partizip2"]:
            for p in r["partizip2"].split("/"):
                forms.setdefault(p.strip().lower(), []).append(r["id"])
    known = {r[0] for r in conn.execute("SELECT lemma_id FROM known_word WHERE state IN ('known', 'learning')")}
    unlocked = {r[0] for r in conn.execute("SELECT code FROM grammar_point WHERE unlocked = 1")}
    for code, words in GRAMMAR_WORDS.items():
        if code in unlocked:
            known |= {lid for w in words for lid in by_lemma.get(w, [])}
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
    if tok.text.lower() in DET_FORMS:
        out.append(DET_FORMS[tok.text.lower()])
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
    if any(ch.isdigit() for ch in tok.text) or not any(ch.isalpha() for ch in tok.text):
        return False
    if tok.tag_ == "PTKVZ" and tok.dep_ == "svp":
        return False  # the particle is counted with its verb
    if tok.ent_type_ in ("PER", "LOC", "ORG") and tok.text[:1].isupper() and tok.pos_ != "NOUN":
        return False
    if tok.text[:1].isupper() and tok.text.lower() in _names():
        return False
    return True


_NAMES: set[str] | None = None


def _names() -> set[str]:
    global _NAMES
    if _NAMES is None:
        _NAMES = personal_names()
    return _NAMES


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
            if any(c.tag_ in ("PWAV", "PWS", "PWAT") or c.text.lower() == "ob" for c in tok.subtree):
                flag("INDIREKTE_FRAGE", tok)   # "Weißt du, wo mein Pass ist?" parsed as rc
            else:
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
                    if any(u in low for u in UMLAUTS):          # hätte, wäre
                        flag("KONJ2_WUNSCH_HAETTE_WAERE", tok)
                    elif low.startswith("sei"):                  # Konjunktiv I
                        flag("BLOCK_KONJUNKTIV_ANDERE", tok)
                    # "habe" after wenn/ob is the indicative form; spaCy sometimes tags it Sub
                elif lemma not in ("mögen", "möchten") and any(
                        u in low and u not in lemma.lower() for u in UMLAUTS):
                    # only real Konjunktiv II stems (käme, ginge→ no, bräuchte, wüsste …); regular
                    # verbs look identical to the indicative ("ob ich … brauche") and are fine
                    flag("BLOCK_KONJUNKTIV_ANDERE", tok)
            elif "Past" in tense:
                if lemma == "sollen":
                    # "sollte" looks the same in Präteritum and Konjunktiv II; at A2 it's advice
                    flag("KONJ2_RAT_KOENNTE_SOLLTE", tok)
                elif lemma in ("haben", "sein") and _has_child(tok, ("VVPP", "VAPP", "VMPP")):
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


# ---- target grammar: does the text actually practise the lesson's grammar? -----------------

TWO_WAY = {"an", "auf", "hinter", "in", "neben", "über", "unter", "vor", "zwischen", "im", "am", "ins", "ans"}


def grammar_presence(doc: Doc) -> set[str]:
    """Grammar point codes that the text uses (positive detection, not a check for errors)."""
    found: set[str] = set()
    for i, tok in enumerate(doc):
        low = tok.text.lower()
        lemma = VERB_FORMS.get(low, tok.lemma_).lower()
        nxt = doc[i + 1].text.lower() if i + 1 < len(doc) else ""
        if tok.tag_ == "KOUS" and low in SUBORDINATORS:
            found.add(SUBORDINATORS[low])
        if low == "deshalb":
            found.add("KONJ_DESHALB")
        if tok.tag_.endswith("FIN"):
            mood, tense = tok.morph.get("Mood"), tok.morph.get("Tense")
            if lemma in ("haben", "sein") and "Pres" in tense and _has_child(tok, ("VVPP", "VAPP", "VMPP")):
                found.add("PERFEKT_HABEN_SEIN")
            if lemma in ("haben", "sein") and "Past" in tense and "Sub" not in mood and not _has_child(tok, ("VVPP", "VAPP", "VMPP")):
                found.add("PRAET_WAR_HATTE")
            if (lemma in ("sollen", "können") and ("Sub" in mood or low.startswith(("sollt", "könnt")))) or \
                    (lemma == "werden" and "Sub" in mood):
                found.add("KONJ2_RAT_KOENNTE_SOLLTE")
            if lemma in ("haben", "sein") and any(u in low for u in UMLAUTS) and "Sub" in mood:
                found.add("KONJ2_WUNSCH_HAETTE_WAERE")
        if tok.tag_ in ("PWAV", "PWS", "PWAT") and tok.head.dep_ in ("oc", "rc") and tok.head.i > tok.i:
            found.add("INDIREKTE_FRAGE")
        if re.match(r"^(letzt|nächst|jed)(e|en|er|es|em)?$", low):
            found.add("LETZT_NAECHST_JED")
        if tok.tag_ == "PPOSAT" and re.match(r"^(unser|euer|eur|ihr)", low):
            found.add("POSS_UNSER_EUER_IHR")
        if low == "über" and tok.pos_ == "ADP":
            found.add("PREP_UEBER_AKK")
        if low == "seit" and tok.pos_ == "ADP":
            found.add("PREP_SEIT_DAT")
        if low == "bis" and nxt in ("zum", "zur"):
            found.add("PREP_VON_BIS_ZUM")
        if low in ("zum", "zur", "beim", "vom", "bei", "von", "zu") and tok.pos_ == "ADP":
            found.add("PREP_VON_BEI_ZU_DAT")
        if lemma in ("legen", "stellen", "hängen", "liegen", "stehen") and tok.pos_ == "VERB":
            found.add("VERBEN_LEGEN_STELLEN_HAENGEN")
        if low in TWO_WAY and tok.pos_ == "ADP":
            found.add("WECHSELPRAEP")
        if tok.pos_ == "NOUN" and low.endswith("ung") and len(low) > 5:
            found.add("NOMEN_UNG")
    return found
