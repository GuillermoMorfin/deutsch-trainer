import pytest

from app.db import connect
from app.seed import seed_all
from app.verifier import analyse, build_lexicon
from tests.fixtures.lesson_texts import FIXTURES


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    c = connect(tmp_path_factory.mktemp("v") / "t.db")
    seed_all(c)
    return c


def state_at(conn, lesson: int, targets=()):
    """Known words and grammar as if the learner had finished lessons 1..lesson."""
    ids = {r[0] for r in conn.execute(
        """SELECT m.id FROM lemma m LEFT JOIN lesson l ON l.id = m.lesson_id
           WHERE m.lesson_id IS NULL OR l.number <= ?""", (lesson,))}
    unlocked = {r[0] for r in conn.execute(
        """SELECT g.code FROM grammar_point g LEFT JOIN lesson l ON l.id = g.lesson_id
           WHERE (g.lesson_id IS NULL AND g.unlocked = 1) OR l.number <= ?""", (lesson,))}
    lex = build_lexicon(conn, set(targets), extra_known=ids)
    return lex, unlocked


def lid(conn, lemma):
    return conn.execute("SELECT id FROM lemma WHERE lemma = ?", (lemma,)).fetchone()[0]


@pytest.mark.parametrize("lesson", sorted(FIXTURES))
def test_fixture_text_passes_for_its_lesson(conn, lesson):
    lex, unlocked = state_at(conn, lesson)
    _, r = analyse(FIXTURES[lesson], lex, unlocked)
    assert r.grammar == [], [g.to_dict() for g in r.grammar]
    assert r.coverage >= 0.96, (r.coverage, r.unknown)


def test_coverage_maths(conn):
    lex, unlocked = state_at(conn, 1)
    # 4 counted tokens (Marco is a name, '.' is punctuation); "Quatsch" is unknown → 3/4
    _, r = analyse("Marco isst heute Quatsch gern.", lex, unlocked)
    assert r.counted == 4 and r.unknown == ["Quatsch"]
    assert r.coverage == pytest.approx(3 / 4)


def test_names_and_numbers_are_not_counted(conn):
    lex, unlocked = state_at(conn, 1)
    _, r = analyse("Marco läuft 42 Kilometer an der Spree in Berlin-Mitte.", lex, unlocked)
    assert r.coverage == 1.0, r.unknown


def test_separable_verb_counts_as_its_full_lemma(conn):
    target = lid(conn, "aufbauen")
    lex, unlocked = state_at(conn, 3, targets=[target])
    _, r = analyse("Marco baut das Zelt auf. Dann baut er den Tisch auf. Wir bauen alles auf.", lex, unlocked)
    assert r.target_counts[target] == 3


def test_target_uses_counted_across_inflections(conn):
    target = lid(conn, "Panne")
    lex, unlocked = state_at(conn, 2, targets=[target])
    _, r = analyse("Die Panne ist schlimm. Zwei Pannen an einem Tag! Mit der Panne warten wir.", lex, unlocked)
    assert r.target_counts[target] == 3


def test_participle_and_pronoun_forms_are_known(conn):
    lex, unlocked = state_at(conn, 1)
    _, r = analyse("Ich habe dich gestern gesehen und wir haben zusammen gegessen.", lex, unlocked)
    assert r.coverage == 1.0, r.unknown


@pytest.mark.parametrize("text, code", [
    ("Das ist der Mann, der in Berlin wohnt.", "BLOCK_RELATIVSATZ"),
    ("Das ist der Mann, der Quatsch macht.", "BLOCK_RELATIVSATZ"),  # spaCy tags this 'der' as ART
    ("Das Haus wird gebaut.", "BLOCK_PASSIV"),
    ("Morgen werde ich laufen.", "BLOCK_FUTUR"),
    ("Er ging nach Hause.", "BLOCK_PRAETERITUM"),
    ("Das Auto des Vaters ist neu.", "BLOCK_GENITIV"),
    ("Sie hatte schon gegessen.", "BLOCK_PLUSQUAMPERFEKT"),
    ("Ich lerne, obwohl ich müde bin.", "BLOCK_NEBENSATZ_ANDERE"),
    ("Wenn ich Zeit hätte, käme ich mit.", "BLOCK_KONJUNKTIV_ANDERE"),
])
def test_blocked_structures_are_flagged(conn, text, code):
    lex, unlocked = state_at(conn, 12)
    _, r = analyse(text, lex, unlocked)
    assert code in {g.code for g in r.grammar}


@pytest.mark.parametrize("text, code, unlocked_at", [
    ("Ich bleibe zu Hause, weil ich krank bin.", "KONJ_WEIL", 2),
    ("Ich bin krank. Deshalb bleibe ich zu Hause.", "KONJ_DESHALB", 4),
    ("Du solltest mehr schlafen.", "KONJ2_RAT_KOENNTE_SOLLTE", 6),
    ("Ich finde gut, dass du kommst.", "KONJ_DASS", 7),
    ("Wenn ich Zeit habe, laufe ich.", "KONJ_WENN", 8),
    ("Ich wäre gern am Meer.", "KONJ2_WUNSCH_HAETTE_WAERE", 11),
    ("Weißt du, ob der Bus fährt?", "INDIREKTE_FRAGE", 12),
])
def test_lesson_grammar_is_locked_until_its_lesson(conn, text, code, unlocked_at):
    lex, before = state_at(conn, unlocked_at - 1)
    assert code in {g.code for g in analyse(text, lex, before)[1].grammar}
    lex, after = state_at(conn, unlocked_at)
    assert code not in {g.code for g in analyse(text, lex, after)[1].grammar}


def test_war_hatte_need_lesson_1(conn):
    lex, unlocked = state_at(conn, 1)
    unlocked = unlocked - {"PRAET_WAR_HATTE"}
    assert "PRAET_WAR_HATTE" in {g.code for g in analyse("Ich war müde.", lex, unlocked)[1].grammar}


@pytest.mark.parametrize("text, lesson", [
    ("Wo warst du gestern? Ihr wart am Meer.", 1),          # war-forms map to sein
    ("Wie ist eure WG?", 3),                                # eure → euer
    ("Sie ist krank. Sie sollte zum Arzt gehen.", 6),       # sollte = advice, not Präteritum
    ("Wenn ich Zeit habe, koche ich.", 8),                  # 'habe' is not Konjunktiv II
    ("Weißt du, wo mein Pass ist?", 12),                    # indirect question, not a relative clause
    ("wohnen → die Wohnung", 8),                            # symbols aren't words
])
def test_regressions_found_by_drill_bank(conn, text, lesson):
    lex, unlocked = state_at(conn, lesson)
    _, r = analyse(text, lex, unlocked)
    assert r.grammar == [] and r.coverage == 1.0, (r.to_dict())


def test_sollte_before_lesson_6_is_still_blocked(conn):
    lex, unlocked = state_at(conn, 5)
    assert "KONJ2_RAT_KOENNTE_SOLLTE" in {g.code for g in analyse("Du sollte gehen.", lex, unlocked)[1].grammar}


def test_case_colliding_lemmas_resolve_to_the_target(conn):
    noun = conn.execute("SELECT id FROM lemma WHERE lemma = 'Mal' AND pos = 'NOUN'").fetchone()[0]
    lex, unlocked = state_at(conn, 1, targets=[noun])
    _, r = analyse("Das war das erste Mal. Noch ein Mal! Jedes Mal laufe ich.", lex, unlocked)
    assert r.target_counts[noun] == 3


def test_redemittel_only_use_grammar_of_their_lesson(conn):
    import json as _json
    from app.seed import SEED_DIR
    for lesson in _json.loads((SEED_DIR / "lessons.json").read_text(encoding="utf-8")):
        lex, unlocked = state_at(conn, lesson["number"])
        for phrase in lesson["redemittel"]:
            text = phrase.replace("…", "Marco kommt").replace(" ,", ",")
            if text.rstrip().endswith(("…", ",")) or text.endswith("Marco kommt"):
                text = text.rstrip(" ,") + ("" if text.endswith(("?", "!", ".")) else ".")
            issues = [g.code for g in analyse(text, lex, unlocked)[1].grammar]
            assert issues == [], (lesson["number"], phrase, issues)
