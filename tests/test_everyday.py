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


def answer_all_checks(conn, right: bool):
    for c in conn.execute("""SELECT c.id, m.lemma, m.article FROM card c JOIN lemma m ON m.id = c.lemma_id
                             WHERE c.mode = 'check'""").fetchall():
        good = f"{c['article']} {c['lemma']}" if c["article"] else c["lemma"]
        srs.review(conn, c["id"], answer=good if right else "falsch", at=T0)


def test_everyday_checks_come_in_small_batches(conn):
    ids = srs.introduce_everyday(conn, at=T0)
    assert len(ids) == srs.EVERYDAY_BATCH == 5
    cards = conn.execute("SELECT direction, mode FROM card").fetchall()
    assert {(c["direction"], c["mode"]) for c in cards} == {("produce", "check")}
    assert len(srs.introduce_everyday(conn, at=T0)) == 5      # pending checks count, room left: 10 - 5
    first = conn.execute("SELECT m.lemma FROM card c JOIN lemma m ON m.id = c.lemma_id ORDER BY m.deck_order LIMIT 1")
    assert first.fetchone()[0] == "Tür"                        # most useful first


def test_unknown_everyday_words_are_capped_per_day(conn):
    for _ in range(3):
        srs.introduce_everyday(conn, at=T0)
        answer_all_checks(conn, right=False)                   # every word turns out new
    assert srs.everyday_new_today(conn, T0) == 10              # the daily setting
    assert srs.introduce_everyday(conn, at=T0) == []           # no more new words today


def test_known_everyday_words_do_not_use_up_the_limit(conn):
    for _ in range(4):
        assert len(srs.introduce_everyday(conn, at=T0)) == 5
        answer_all_checks(conn, right=True)                    # all known: quick checks
    assert srs.everyday_new_today(conn, T0) == 0
    assert len(srs.introduce_everyday(conn, at=T0)) == 5       # keeps going through the deck


def test_right_first_time_means_known_and_back_in_three_months(conn):
    srs.introduce_check(conn, lid(conn, "Heizung", "die"), at=T0)
    card = conn.execute("SELECT id FROM card").fetchone()[0]
    r = srs.review(conn, card, answer="die Heizung", at=T0)
    assert r["check_result"] == "known" and r["word_state"] == "known"
    assert r["interval_days"] == pytest.approx(srs.CHECK_PASS_DAYS)
    assert conn.execute("SELECT COUNT(*) FROM card").fetchone()[0] == 1      # no extra recognition card
    assert card not in {c["id"] for c in srs.queue(conn, at=T0 + timedelta(days=30))}   # not repeated soon


def test_check_is_multiple_choice_with_a_wrong_article_option(conn):
    from app import ladder
    srs.introduce_check(conn, lid(conn, "Kühlschrank", "der"), at=T0)
    card = srs.queue(conn, at=T0)[0]
    item = ladder.card_item(conn, card, seed=1)
    assert item["kind"] == "check" and "der Kühlschrank" in item["options"]
    assert any(o in item["options"] for o in ("die Kühlschrank", "das Kühlschrank"))


def test_wrong_check_waits_for_a_text_instead_of_a_bare_card(conn):
    w = lid(conn, "Kaution", "die")
    srs.introduce_check(conn, w, at=T0)
    card = conn.execute("SELECT id FROM card").fetchone()[0]
    r = srs.review(conn, card, answer="der Kaution", at=T0)
    assert r["check_result"] == "learn" and not r["correct"] and r["answer"] == "die Kaution"
    assert conn.execute("SELECT ladder_step FROM known_word WHERE lemma_id = ?", (w,)).fetchone()[0] == 0
    assert {c["direction"] for c in conn.execute("SELECT direction FROM card")} == {"produce"}   # no recognise card
    assert srs.queue(conn, at=T0) == []                         # nothing to drill before a text introduces it
    assert srs.introduce_word(conn, w, sentence="Die Kaution ist hoch.", at=T0)    # a text brings it in
    assert conn.execute("SELECT ladder_step FROM known_word WHERE lemma_id = ?", (w,)).fetchone()[0] == 1


def test_known_a1_word_answered_wrong_keeps_coverage_but_is_learned(conn):
    w = lid(conn, "Apfel", "der")
    srs.introduce_check(conn, w, at=T0)
    card = conn.execute("SELECT id FROM card").fetchone()[0]
    assert srs.review(conn, card, answer="die Apfel", at=T0)["check_result"] == "learn"
    assert conn.execute("SELECT state, ladder_step FROM known_word WHERE lemma_id = ?", (w,)).fetchone()[:] == ("known", 0)
    assert srs.introduce_word(conn, w, at=T0)                   # can still be introduced by a text


def test_phrases_with_punctuation_can_be_answered(conn):
    srs.introduce_check(conn, lid(conn, "Wie bitte?"), at=T0)
    card = conn.execute("SELECT id FROM card").fetchone()[0]
    assert srs.review(conn, card, answer="Wie bitte?", at=T0)["check_result"] == "known"


def test_everyday_setting_and_word_filter(client):
    assert client.put("/api/settings", json={"everyday_per_day": 15}).status_code == 200
    assert client.put("/api/settings", json={"everyday_per_day": 25}).status_code == 422
    assert client.post("/api/review/start", json={}).json()["checks"] == 5
    assert client.post("/api/review/more").json()["checks"] == 5          # next batch on request
    words = client.get("/api/words", params={"lesson": -1, "limit": 500}).json()
    assert words["total"] >= 140
