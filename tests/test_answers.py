import pytest

from app.answers import check_answer, damerau_levenshtein


def noun(given, lemma="Panne", article="die", **kw):
    return check_answer(given, lemma=lemma, pos="NOUN", article=article, **kw)


def verb(given, lemma="übernehmen", **kw):
    return check_answer(given, lemma=lemma, pos="VERB", article=None, **kw)


def test_exact_noun_with_article():
    assert noun("die Panne").verdict == "exact"
    assert noun("  Die  Panne. ").correct  # spacing, capitalised article, trailing dot


def test_noun_without_article_is_wrong():
    r = noun("Panne")
    assert not r.correct and r.verdict == "missing_article" and r.expected == "die Panne"


def test_wrong_article_is_wrong_even_if_stem_perfect():
    r = noun("der Panne")
    assert not r.correct and r.verdict == "wrong_article"


def test_small_typo_on_stem_is_accepted_as_typo():
    r = noun("die Überaschung", lemma="Überraschung")
    assert r.correct and r.verdict == "typo"


def test_typo_never_rescues_wrong_article():
    assert noun("das Überaschung", lemma="Überraschung").verdict == "wrong_article"


@pytest.mark.parametrize("given", ["die Kuh", "die Kuh"])
def test_short_words_get_no_typo_budget(given):
    assert noun("die Kuhh", lemma="Kuh").verdict == "wrong"
    assert noun(given, lemma="Kuh").verdict == "exact"


def test_missing_umlaut_is_wrong():
    r = verb("ubernehmen")
    assert not r.correct and r.verdict == "umlaut"
    assert noun("die Kuhe", lemma="Kühe").verdict == "umlaut"


def test_ascii_umlaut_only_with_opt_in():
    assert verb("uebernehmen").verdict != "exact"
    assert verb("uebernehmen", ascii_ok=True).verdict == "exact"
    assert noun("die Ueberraschung", lemma="Überraschung", ascii_ok=True).verdict == "exact"


def test_umlaut_error_hidden_inside_typo_is_still_umlaut():
    # one umlaut slip + nothing else must not pass as a typo
    assert noun("die Uberraschung", lemma="Überraschung").verdict == "umlaut"


def test_eszett():
    assert verb("geniessen", lemma="genießen").verdict == "umlaut"
    assert verb("geniessen", lemma="genießen", ascii_ok=True).verdict != "exact"  # ss→ß not in opt-in


def test_wrong_word():
    assert verb("bekommen").verdict == "wrong"
    assert verb("").verdict == "wrong"


def test_capitalisation_slip_is_typo():
    assert noun("die panne").verdict == "typo"


def test_adjacent_swap_counts_once():
    assert damerau_levenshtein("Vertrag", "Vertarg") == 1
