"""Typed-answer checking for production cards (ES → DE).

Rules from the learner profile:
- Nouns are wrong without the right der/die/das.
- A wrong umlaut is wrong. "ae/oe/ue/ss" for "ä/ö/ü/ß" counts only if the learner opted in.
- Small typos in the stem are accepted (and rated Hard), never on article or umlaut.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

ARTICLES = ("der", "die", "das")
UMLAUT_BASE = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "Ä": "A", "Ö": "O", "Ü": "U", "ß": "ss"})
ASCII_SPELLING = (("ae", "ä"), ("oe", "ö"), ("ue", "ü"), ("Ae", "Ä"), ("Oe", "Ö"), ("Ue", "Ü"))


@dataclass
class Check:
    correct: bool
    verdict: str          # exact | typo | wrong_article | missing_article | umlaut | wrong
    expected: str         # what should have been typed, e.g. "die Panne"
    given: str
    message: str          # short German feedback for the UI

    def to_dict(self) -> dict:
        return asdict(self)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = s.replace(" ", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s.rstrip(".!?")


def _fold_ascii(s: str) -> str:
    """Learner opted in: 'Faehre' may stand for 'Fähre'. Only applied to the given answer."""
    for a, u in ASCII_SPELLING:
        s = s.replace(a, u)
    return s


def damerau_levenshtein(a: str, b: str) -> int:
    """Optimal string alignment distance (adjacent swaps count as one edit)."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


def typo_budget(word: str) -> int:
    n = len(word)
    if n <= 4:
        return 0
    if n <= 8:
        return 1
    return 2


def expected_form(lemma: str, pos: str, article: str | None) -> str:
    return f"{article} {lemma}" if pos == "NOUN" and article else lemma


def _compare_stem(expected: str, given: str, *, ascii_ok: bool) -> str:
    """Return 'exact', 'typo', 'umlaut' or 'wrong' for the word without article."""
    if given == expected:
        return "exact"
    if ascii_ok and _fold_ascii(given) == expected:
        return "exact"
    # Same word except for umlauts → an umlaut mistake, never forgiven as a typo.
    if given.translate(UMLAUT_BASE).lower() == expected.translate(UMLAUT_BASE).lower() and \
            given.lower() != expected.lower():
        return "umlaut"
    # German capitalisation matters for nouns, but a capitalisation slip alone is a typo.
    candidate = _fold_ascii(given) if ascii_ok else given
    dist = damerau_levenshtein(candidate.lower(), expected.lower())
    if dist == 0:
        return "typo"
    if dist <= typo_budget(expected):
        # A typo that touches an umlaut letter is still an umlaut mistake.
        if any(c in "äöüÄÖÜß" for c in expected) and \
                damerau_levenshtein(candidate.translate(UMLAUT_BASE).lower(),
                                    expected.translate(UMLAUT_BASE).lower()) < dist:
            return "umlaut"
        return "typo"
    return "wrong"


def check_answer(given: str, *, lemma: str, pos: str, article: str | None,
                 ascii_ok: bool = False) -> Check:
    exp = expected_form(lemma, pos, article)
    raw = _norm(given)
    if not raw:
        return Check(False, "wrong", exp, given, f"Richtig: {exp}")

    if pos == "NOUN" and article:
        parts = raw.split(" ", 1)
        given_article = parts[0].lower() if parts[0].lower() in ARTICLES else None
        stem = parts[1] if given_article and len(parts) > 1 else (raw if not given_article else "")
        stem_result = _compare_stem(lemma, stem, ascii_ok=ascii_ok)
        if stem_result == "wrong":
            return Check(False, "wrong", exp, given, f"Richtig: {exp}")
        if stem_result == "umlaut":
            return Check(False, "umlaut", exp, given, f"Achte auf den Umlaut: {exp}")
        if given_article is None:
            return Check(False, "missing_article", exp, given, f"Artikel fehlt: {exp}")
        if given_article != article:
            return Check(False, "wrong_article", exp, given, f"Falscher Artikel: {exp}")
        if stem_result == "typo":
            return Check(True, "typo", exp, given, f"Fast! Genau: {exp}")
        return Check(True, "exact", exp, given, "Richtig!")

    result = _compare_stem(_norm(lemma), raw, ascii_ok=ascii_ok)
    if result == "exact":
        return Check(True, "exact", exp, given, "Richtig!")
    if result == "typo":
        return Check(True, "typo", exp, given, f"Fast! Genau: {exp}")
    if result == "umlaut":
        return Check(False, "umlaut", exp, given, f"Achte auf den Umlaut: {exp}")
    return Check(False, "wrong", exp, given, f"Richtig: {exp}")
