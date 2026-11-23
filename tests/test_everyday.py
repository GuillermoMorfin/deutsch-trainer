from datetime import timedelta

import pytest

from app import srs
from app.db import connect
from app.seed import seed_all

T0 = srs.now_utc()


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    seed_all(c)
    return c


def lid(conn, lemma, article=None):
    return conn.execute("SELECT id FROM lemma WHERE lemma = ? AND article IS ?", (lemma, article)).fetchone()[0]


def test_deck_tags_a1_words_and_adds_new_ones_but_no_lesson_words(conn):
    deck = conn.execute("SELECT lemma, source, lesson_id FROM lemma WHERE deck = 'alltag'").fetchall()
    names = {r["lemma"] for r in deck}
    assert {"Tür", "Fenster", "Apfel", "Heizung", "Bürgeramt", "lüften", "Kaution"} <= names
    assert all(r["lesson_id"] is None for r in deck)
    assert conn.execute("SELECT source FROM lemma WHERE lemma = 'Tür'").fetchone()[0] == "a1"   # tagged, not duplicated
    assert len(deck) >= 140


def test_everyday_checks_are_typing_cards_capped_per_day(conn):
    ids = srs.introduce_everyday(conn, at=T0)
    assert len(ids) == 15
    cards = conn.execute("SELECT direction, mode FROM card").fetchall()
    assert {(c["direction"], c["mode"]) for c in cards} == {("produce", "check")}
    assert srs.introduce_everyday(conn, at=T0) == []          # daily cap reached
    first = conn.execute("SELECT m.lemma FROM card c JOIN lemma m ON m.id = c.lemma_id ORDER BY m.deck_order LIMIT 1")
    assert first.fetchone()[0] == "Tür"                        # most useful first


def test_right_first_time_means_known_and_back_in_three_months(conn):
    srs.introduce_check(conn, lid(conn, "Heizung", "die"), at=T0)
    card = conn.execute("SELECT id FROM card").fetchone()[0]
    r = srs.review(conn, card, answer="die Heizung", at=T0)
    assert r["check_result"] == "known" and r["word_state"] == "known"
    assert r["interval_days"] == pytest.approx(srs.CHECK_PASS_DAYS)
    assert conn.execute("SELECT COUNT(*) FROM card").fetchone()[0] == 1      # no extra recognition card
    assert card not in {c["id"] for c in srs.queue(conn, at=T0 + timedelta(days=30))}   # not repeated soon


def test_typo_passes_with_shorter_interval(conn):
    srs.introduce_check(conn, lid(conn, "Kühlschrank", "der"), at=T0)
    card = conn.execute("SELECT id FROM card").fetchone()[0]
    r = srs.review(conn, card, answer="der Kühlschrnak", at=T0)
    assert r["check_result"] == "known" and r["interval_days"] == pytest.approx(srs.CHECK_TYPO_DAYS)


def test_wrong_becomes_a_learning_word_in_both_directions(conn):
    srs.introduce_check(conn, lid(conn, "Kaution", "die"), at=T0)
    card = conn.execute("SELECT id FROM card").fetchone()[0]
    r = srs.review(conn, card, answer="der Kaution", at=T0)
    assert r["check_result"] == "learn" and r["word_state"] == "learning"
    dirs = {c["direction"] for c in conn.execute("SELECT direction FROM card")}
    assert dirs == {"produce", "recognise"}
    due_soon = {c["id"] for c in srs.queue(conn, at=T0)}
    assert card in due_soon                                       # comes back in this session


def test_known_a1_word_answered_wrong_keeps_coverage_but_is_drilled(conn):
    srs.introduce_check(conn, lid(conn, "Apfel", "der"), at=T0)
    card = conn.execute("SELECT id FROM card").fetchone()[0]
    r = srs.review(conn, card, answer="die Apfel", at=T0)
    assert r["check_result"] == "learn"
    assert conn.execute("SELECT state FROM known_word WHERE lemma_id = ?", (lid(conn, "Apfel", "der"),)).fetchone()[0] == "known"
    assert conn.execute("SELECT COUNT(*) FROM card").fetchone()[0] == 2


def test_phrases_with_punctuation_can_be_answered(conn):
    srs.introduce_check(conn, lid(conn, "Wie bitte?"), at=T0)
    card = conn.execute("SELECT id FROM card").fetchone()[0]
    assert srs.review(conn, card, answer="wie bitte", at=T0)["check_result"] == "known"


def test_easy_on_first_sight_unlocks_typing_immediately(conn):
    w = lid(conn, "Kindheit", "die")
    srs.introduce_word(conn, w, at=T0)
    rec = conn.execute("SELECT id FROM card WHERE lemma_id = ?", (w,)).fetchone()[0]
    assert srs.review(conn, rec, rating=4, at=T0)["produce_unlocked"]


def test_good_on_first_sight_still_needs_two(conn):
    w = lid(conn, "Kindheit", "die")
    srs.introduce_word(conn, w, at=T0)
    rec = conn.execute("SELECT id FROM card WHERE lemma_id = ?", (w,)).fetchone()[0]
    assert not srs.review(conn, rec, rating=3, at=T0)["produce_unlocked"]


def test_everyday_setting_and_word_filter(client):
    assert client.put("/api/settings", json={"everyday_per_day": 25}).status_code == 200
    assert client.post("/api/review/start", json={"new_words": False}).json()["checks"] == 25
    words = client.get("/api/words", params={"lesson": -1, "limit": 500}).json()
    assert words["total"] >= 140
