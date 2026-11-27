"""Distractors, the one-time migration from recognise/produce cards, the English gloss switch and
daily rotation of practice formats."""

import random
from datetime import datetime, timezone

import pytest

from app import glosses, ladder, practice, srs
from app.db import connect, init_schema
from app.llm import Gloss
from app.seed import seed_all
from fsrs import State

T0 = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    seed_all(c)
    return c


def word(conn, lemma, article=None):
    lid = conn.execute("SELECT id FROM lemma WHERE lemma = ? AND article IS ?", (lemma, article)).fetchone()[0]
    return ladder.word(conn, lid)


# ---- distractors -------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(5))
def test_en_de_options_include_the_noun_with_a_wrong_article(conn, seed):
    w = word(conn, "Baum", "der")
    options, answer = ladder.options_en_de(conn, w, random.Random(seed))
    assert answer == "der Baum" and answer in options and len(set(options)) == 4
    wrong = [o for o in options if o.endswith(" Baum") and o != answer]
    assert len(wrong) == 1 and wrong[0] in ("die Baum", "das Baum")
    others = [o for o in options if not o.endswith(" Baum")]
    assert len(others) == 2 and all(o.split()[0] in ("der", "die", "das") for o in others)   # nouns with articles


def test_wrong_article_variants():
    assert ladder.wrong_article_variants({"pos": "NOUN", "article": "der", "lemma": "Umzug"}) == ["die Umzug", "das Umzug"]
    assert ladder.wrong_article_variants({"pos": "VERB", "article": None, "lemma": "gehen"}) == []


def test_distractors_come_from_the_same_lesson_and_word_type(conn):
    w = word(conn, "Baum", "der")
    options, answer = ladder.options_de_en(conn, w, random.Random(1))
    assert answer == w["gloss_en"] and len(set(options)) == 4
    same_lesson = {r[0] for r in conn.execute(
        """SELECT m.gloss_en FROM lemma m JOIN lesson l ON l.id = m.lesson_id
           WHERE l.number = 1 AND m.pos = 'NOUN'""")}
    assert set(options) <= same_lesson
    verb = next(dict(r) for r in conn.execute(
        "SELECT m.id FROM lemma m JOIN lesson l ON l.id = m.lesson_id WHERE l.number = 2 AND m.pos = 'VERB'"))
    vw = ladder.word(conn, verb["id"])
    opts, ans = ladder.options_en_de(conn, vw, random.Random(2))
    pos = {r[0]: r[1] for r in conn.execute("SELECT lemma, pos FROM lemma WHERE pos = 'VERB'")}
    assert all(o in pos for o in opts)                          # all verbs, no articles


# ---- migration -------------------------------------------------------------------------------------

def _legacy_state(conn):
    """Cards as the two-card system left them, before the ladder columns were filled."""
    ids = [r[0] for r in conn.execute(
        "SELECT m.id FROM lemma m JOIN lesson l ON l.id = m.lesson_id WHERE l.number = 1 ORDER BY m.id LIMIT 4")]
    rec_only, learning, solid, rec_one_good = ids
    t = srs.to_db(T0)
    for lid in ids:
        conn.execute("INSERT INTO known_word (lemma_id, state, first_seen) VALUES (?, 'learning', ?)", (lid, t))
        conn.execute("""INSERT INTO card (lemma_id, direction, due, state, source_sentence)
                        VALUES (?, 'recognise', ?, 2, 'Satz.')""", (lid, t))
    conn.execute("INSERT INTO card (lemma_id, direction, due, state) VALUES (?, 'produce', ?, ?)",
                 (learning, t, State.Learning.value))
    conn.execute("INSERT INTO card (lemma_id, direction, due, state, stability) VALUES (?, 'produce', ?, ?, 12)",
                 (solid, t, State.Review.value))
    rec = conn.execute("SELECT id FROM card WHERE lemma_id = ? AND direction = 'recognise'", (rec_one_good,)).fetchone()[0]
    conn.execute("INSERT INTO review_log (card_id, rating, ts) VALUES (?, 3, ?)", (rec, t))
    conn.execute("UPDATE settings SET gloss_language = 'es', daily_new_word_cap = 12")
    conn.commit()
    return rec_only, learning, solid, rec_one_good


def test_migration_puts_existing_cards_on_the_ladder(conn):
    rec_only, learning, solid, rec_one_good = _legacy_state(conn)
    logs_before = conn.execute("SELECT COUNT(*) FROM review_log").fetchone()[0]
    ladder.migrate_to_ladder(conn)
    s = {lid: conn.execute("SELECT ladder_step, ladder_correct FROM known_word WHERE lemma_id = ?", (lid,)).fetchone()
         for lid in (rec_only, learning, solid, rec_one_good)}
    assert tuple(s[rec_only]) == (2, 0)
    assert tuple(s[rec_one_good]) == (2, 1)             # one good recognition counts toward step 2
    assert s[learning][0] == 3                          # couldn't type it yet: choices again
    assert s[solid][0] == 5
    assert conn.execute("SELECT COUNT(*) FROM review_log").fetchone()[0] == logs_before   # history kept
    assert conn.execute("SELECT COUNT(*) FROM card").fetchone()[0] == 6                    # no card deleted
    assert conn.execute("SELECT gloss_language, daily_new_word_cap FROM settings").fetchone()[:] == ("en", 5)


def test_old_database_is_migrated_once_on_startup(tmp_path):
    c = connect(tmp_path / "old.db")
    seed_all(c)
    rec_only, *_ = _legacy_state(c)
    for col in ("ladder_step", "ladder_correct", "ladder_since", "source_sentence", "source_text_id"):
        c.execute(f"ALTER TABLE known_word DROP COLUMN {col}")      # what a pre-ladder database looks like
    c.commit()
    init_schema(c)
    assert ladder.step_of(c, rec_only) == 2
    c.execute("UPDATE known_word SET ladder_step = 4 WHERE lemma_id = ?", (rec_only,))
    c.commit()
    init_schema(c)                                                   # second start: no re-migration
    assert ladder.step_of(c, rec_only) == 4


# ---- glosses -------------------------------------------------------------------------------------

def test_gloss_migration_switches_to_english_and_keeps_spanish(conn):
    _legacy_state(conn)
    ladder.migrate_to_ladder(conn)
    assert conn.execute("SELECT gloss_language FROM settings").fetchone()[0] == "en"
    assert ladder.gloss_column(conn) == "gloss_en"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(lemma)")}
    assert {"gloss_en", "gloss_es"} <= cols                          # Spanish kept, nullable
    assert conn.execute("SELECT COUNT(*) FROM lemma WHERE COALESCE(gloss_en, '') = ''").fetchone()[0] == 0


def test_missing_english_glosses_are_regenerated(conn):
    lid = conn.execute("SELECT id FROM lemma WHERE lemma = 'Baum'").fetchone()[0]
    conn.execute("UPDATE lemma SET gloss_en = NULL WHERE id = ?", (lid,))

    class FakeWriter:
        def gloss(self, prompt):
            assert "der Baum" in prompt
            return [Gloss(lemma="Baum", pos="NOUN", article="der", plural="Bäume", aux="", partizip2="", gloss_en="tree")]

    assert glosses.fill_english(conn, FakeWriter()) == 1
    assert conn.execute("SELECT gloss_en, gloss_es FROM lemma WHERE id = ?", (lid,)).fetchone()[:] == ("tree", "el árbol")


@pytest.mark.parametrize("lemma, pos, gloss, expected", [
    ("Haus", "NOUN", "house", True), ("Wasser", "NOUN", "water", True), ("trinken", "VERB", "to drink", True),
    ("Buch", "NOUN", "book", True), ("Hotel", "NOUN", "hotel", True), ("Schiff", "NOUN", "ship", True),
    ("bekommen", "VERB", "to get, receive", False), ("Gift", "NOUN", "poison", False),
    ("Stuhl", "NOUN", "chair", False), ("passen", "VERB", "to fit", False),
])
def test_cognates(lemma, pos, gloss, expected):
    assert glosses.is_cognate(lemma, pos, gloss) is expected


def test_cognate_flags_are_seeded(conn):
    assert conn.execute("SELECT cognate FROM lemma WHERE lemma = 'Haus'").fetchone()[0] == 1
    assert conn.execute("SELECT cognate FROM lemma WHERE lemma = 'bekommen'").fetchone()[0] == 0


def test_spanish_gloss_language_is_optional(client):
    assert client.put("/api/settings", json={"gloss_language": "es"}).status_code == 200
    assert client.put("/api/settings", json={"gloss_language": "fr"}).status_code == 422


# ---- practice formats ------------------------------------------------------------------------------

def test_two_consecutive_session_days_use_different_formats(conn):
    d1 = practice.formats_for_day(conn, "2026-11-23")
    d2 = practice.formats_for_day(conn, "2026-11-24")
    d3 = practice.formats_for_day(conn, "2026-11-25")
    assert 2 <= len(d1) <= 3 and 2 <= len(d2) <= 3
    assert set(d1) != set(d2) and set(d2) != set(d3)
    assert practice.formats_for_day(conn, "2026-11-23") == d1        # fixed for the day


@pytest.mark.parametrize("kind", ["match", "listen", "gender", "plural", "perfekt"])
def test_practice_formats_build_from_met_words(conn, kind):
    g = practice.build(conn, kind, seed=3)
    assert g and g["kind"] == kind
    if kind == "match":
        assert len(g["pairs"]) == 12 and len({p["en"] for p in g["pairs"]}) == 12     # two boards of 6
        assert [len(b) for b in g["boards"]] == [6, 6]
    if kind == "gender":
        assert len(g["nouns"]) == practice.GENDER_NOUNS
    if kind == "plural":
        assert len(g["rounds"]) == practice.PLURAL_ROUNDS
    if kind == "gender":
        assert all(n["article"] in ("der", "die", "das") for n in g["nouns"])
    if kind in ("listen", "plural", "perfekt"):
        assert all(r["answer"] in r["options"] and len(set(r["options"])) == 4 for r in g["rounds"])
    if kind == "listen":   # you hear German and must know the meaning, not just match the sound
        assert all(r["say"] not in r["options"] for r in g["rounds"])
    if kind == "perfekt":
        r = g["rounds"][0]
        aux, p2 = r["answer"].split()
        assert {o.split()[0] for o in r["options"]} == {"hat", "ist"} and sum(o.endswith(p2) for o in r["options"]) == 2


@pytest.mark.parametrize("lemma, plural, absent", [
    ("Baum", "Bäume", {"Baumn", "Bäum"}), ("Frau", "Frauen", {"Fräue"}), ("Mutter", "Mütter", {"Muttere"}),
    ("Tasche", "Taschen", {"Taschee"}), ("Haus", "Häuser", {"Hauss"}),
])
def test_wrong_plurals_are_plausible(lemma, plural, absent):
    wrong = practice.wrong_plurals(lemma, plural)
    assert len(wrong) >= 3 and plural not in wrong and not (absent & set(wrong))


def test_old_odd_one_out_days_are_replaced(conn):
    conn.execute("INSERT INTO practice_day (day, formats) VALUES ('2026-11-26', '[\"odd\", \"match\"]')")
    assert "odd" not in practice.formats_for_day(conn, "2026-11-26")


def test_cloze_needs_yesterdays_text(conn):
    assert practice.build(conn, "cloze") is None


def test_practice_api(client):
    today = client.get("/api/practice/today").json()
    assert 2 <= len(today["formats"]) <= 3 and today["games"]
    assert client.post("/api/practice/result", json={"kind": today["formats"][0], "correct": 5, "total": 6}).status_code == 200
    assert client.get("/api/progress").json()["done_today"]["review"]
