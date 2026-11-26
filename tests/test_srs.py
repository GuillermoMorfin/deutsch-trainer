"""The vocabulary ladder end to end: introduction through texts, promotion/demotion, FSRS for steps 4-5."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app import ladder, srs
from app.db import connect
from app.seed import seed_all

T0 = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    seed_all(c)
    return c


def lemma_id(conn, lemma, article=None):
    return conn.execute("SELECT id FROM lemma WHERE lemma = ? AND article IS ?", (lemma, article)).fetchone()[0]


def add_text(conn, lid, words=("Der", "Baum", "war", "sehr", "alt")) -> int:
    """A read text whose sentence contains the word (tokens as the annotator stores them)."""
    toks = [{"t": w, "ws": " "} for w in words]
    toks[1]["id"] = lid
    toks[-1]["ws"] = ""
    toks.append({"t": ".", "ws": ""})
    lesson = conn.execute("SELECT id FROM lesson WHERE number = 1").fetchone()[0]
    cur = conn.execute("""INSERT INTO text (lesson_id, title, body, annotations, coverage, target_lemma_ids, kind)
                          VALUES (?, 'T', ?, ?, 1.0, ?, 'read')""",
                       (lesson, " ".join(words) + ".", json.dumps(toks), json.dumps([lid])))
    return cur.lastrowid


def step(conn, lid):
    return ladder.step_of(conn, lid)


def climb(conn, lid, n, at=T0):
    for _ in range(n):
        ladder.answer_mc(conn, lid, max(step(conn, lid), 2), ladder.mc_answer_for(conn, lid, max(step(conn, lid), 2)), at=at)


@pytest.fixture()
def baum(conn):
    lid = lemma_id(conn, "Baum", "der")
    tid = add_text(conn, lid)
    assert srs.introduce_word(conn, lid, sentence="Der Baum war sehr alt.", text_id=tid, at=T0)
    return lid


# ---- introduction ------------------------------------------------------------------------------

def test_new_words_enter_at_step_1_through_a_text_without_cards(conn, baum):
    assert step(conn, baum) == 1
    assert conn.execute("SELECT COUNT(*) FROM card WHERE lemma_id = ?", (baum,)).fetchone()[0] == 0
    assert not srs.introduce_word(conn, baum, at=T0)          # idempotent
    assert srs.words_introduced_today(conn, T0) == 1


def test_default_new_word_cap_is_five(conn):
    assert conn.execute("SELECT daily_new_word_cap FROM settings").fetchone()[0] == 5
    assert srs.new_word_room(conn) == 5


# ---- promotion / demotion -------------------------------------------------------------------------

def test_two_correct_answers_promote(conn, baum):
    r = ladder.answer_mc(conn, baum, 2, ladder.mc_answer_for(conn, baum, 2), at=T0)
    assert r["correct"] and r["step"] == 2 and r["correct_at_step"] == 1 and not r["promoted"]
    r = ladder.answer_mc(conn, baum, 2, ladder.mc_answer_for(conn, baum, 2), at=T0)
    assert r["step"] == 3 and r["promoted"] and r["next_item"]["step"] == 3


def test_a_miss_drops_one_step_only_and_never_to_step_1(conn, baum):
    climb(conn, baum, 2)
    assert step(conn, baum) == 3
    climb(conn, baum, 1)                                        # one right at step 3 …
    r = ladder.answer_mc(conn, baum, 3, "die Baum", at=T0)      # … then a miss
    assert not r["correct"] and r["step"] == 2 and r["demoted"] and r["correct_at_step"] == 0
    r = ladder.answer_mc(conn, baum, 2, "wrong", at=T0)
    assert r["step"] == 2                                       # floor: step 2


def test_no_typing_before_steps_1_to_3_are_passed(conn, baum):
    for _ in range(3):
        assert not srs.queue(conn, at=T0 + timedelta(days=30))  # nothing to type yet
        climb(conn, baum, 1)
    climb(conn, baum, 1)                                        # 4th correct answer: step 3 passed
    assert step(conn, baum) == 4
    assert srs.queue(conn, at=T0 + timedelta(hours=1)) == []    # FSRS takes over: due tomorrow
    q = srs.queue(conn, at=T0 + timedelta(days=1, minutes=1))
    assert [c["lemma_id"] for c in q] == [baum]


def test_steps_4_and_5_are_scheduled_cards(conn, baum):
    climb(conn, baum, 4)
    t1 = T0 + timedelta(days=1, minutes=1)
    card = srs.queue(conn, at=t1)[0]
    item = ladder.card_item(conn, card)
    assert item["kind"] == "cloze" and item["first_letter"] == "B"
    assert item["before"] == "Der " and item["after"] == " war sehr alt."
    r = srs.review(conn, card["id"], answer="Baum", at=t1)     # the form in the sentence, no article needed
    assert r["check"]["correct"] and r["ladder"]["step"] == 4 and r["ladder"]["correct_at_step"] == 1
    t2 = t1 + timedelta(days=3)
    srs.review(conn, card["id"], answer="Baum", at=t2)
    assert step(conn, baum) == 5
    item = ladder.card_item(conn, dict(conn.execute(srs.CARD_SELECT + " WHERE c.id = ?", (card["id"],)).fetchone()))
    assert item["kind"] == "type" and item["blanked"] == "Der ____ war sehr alt."
    r = srs.review(conn, card["id"], answer="Baum", at=t2 + timedelta(days=5))   # article missing at step 5
    assert r["check"]["verdict"] == "missing_article"
    assert r["ladder"]["step"] == 4 and r["ladder"]["demoted"]                     # back to the cloze, not to zero


def test_word_becomes_known_at_step_5_once_stable(conn, baum):
    climb(conn, baum, 4)
    card = conn.execute("SELECT id FROM card WHERE lemma_id = ?", (baum,)).fetchone()[0]
    t = T0 + timedelta(days=1)
    for gap in (0, 3, 10, 30):
        t += timedelta(days=gap)
        srs.review(conn, card, answer="der Baum" if step(conn, baum) == 5 else "Baum", at=t)
    assert step(conn, baum) == 5
    assert conn.execute("SELECT state FROM known_word WHERE lemma_id = ?", (baum,)).fetchone()[0] == "known"


def test_reviewing_a1_word_never_demotes_it(conn):
    lid = lemma_id(conn, "Haus", "das")
    conn.execute("UPDATE known_word SET ladder_step = 3 WHERE lemma_id = ?", (lid,))
    ladder.answer_mc(conn, lid, 3, "nope", at=T0)
    assert conn.execute("SELECT state FROM known_word WHERE lemma_id = ?", (lid,)).fetchone()[0] == "known"


def test_retired_recognise_cards_are_not_scheduled(conn, baum):
    conn.execute("INSERT INTO card (lemma_id, direction, due, state) VALUES (?, 'recognise', ?, 1)",
                 (baum, srs.to_db(T0)))
    assert srs.queue(conn, at=T0 + timedelta(days=2)) == []
    rec = conn.execute("SELECT id FROM card WHERE direction = 'recognise'").fetchone()[0]
    with pytest.raises(ValueError):
        srs.review(conn, rec, rating=3, at=T0)


def test_every_item_shows_the_source_sentence(conn, baum):
    item = ladder.mc_item(conn, baum, seed=1)
    assert item["sentence"] == "Der Baum war sehr alt." and item["blank"] == "Baum"
    climb(conn, baum, 2)
    assert ladder.mc_item(conn, baum)["blanked"] == "Der ____ war sehr alt."


def test_review_api_roundtrip(client):
    conn = connect(os.environ["TRAINER_DB"])
    lid = lemma_id(conn, "Baum", "der")
    tid = add_text(conn, lid)
    srs.introduce_word(conn, lid, sentence="Der Baum war sehr alt.", text_id=tid)
    conn.commit()
    start = client.post("/api/review/start", json={"everyday": False}).json()
    mc = [i for i in start["items"] if i.get("kind") == "mc"]
    assert [i["lemma_id"] for i in mc] == [lid] and mc[0]["step"] == 2 and len(mc[0]["options"]) == 4
    right = mc[0]["word"]["gloss"]
    assert right in mc[0]["options"]
    r = client.post(f"/api/ladder/{lid}/answer", json={"step": 2, "choice": right}).json()
    assert r["correct"] and r["next_item"]["kind"] == "mc"
    assert client.post(f"/api/ladder/{lid}/answer", json={"step": 2, "choice": "x"}).json()["correct"] is False
    assert client.get("/api/ladder").json()["counts"]["2"] == 1


def test_step_5_accepts_the_form_that_fills_the_gap(conn):
    lid = lemma_id(conn, "letzt")
    tid = add_text(conn, lid, words=("Ich", "letzten", "Samstag", "gelaufen"))
    srs.introduce_word(conn, lid, text_id=tid, at=T0)
    conn.execute("UPDATE known_word SET ladder_step = 5 WHERE lemma_id = ?", (lid,))
    ladder.ensure_card(conn, lid, T0)
    card = conn.execute("SELECT id FROM card WHERE lemma_id = ?", (lid,)).fetchone()[0]
    r = srs.review(conn, card, answer="letzten", at=T0 + timedelta(days=2))
    assert r["check"]["correct"] and step(conn, lid) == 5
    assert ladder.grade_typed(conn, lid, "letzt").correct            # dictionary form still fine


def test_nouns_at_step_5_still_need_the_article(conn, baum):
    conn.execute("UPDATE known_word SET ladder_step = 5 WHERE lemma_id = ?", (baum,))
    assert ladder.grade_typed(conn, baum, "Baum").verdict == "missing_article"
    assert ladder.grade_typed(conn, baum, "der Baum").correct


def test_ich_hatte_es_richtig_undoes_a_wrong_mark(conn, baum):
    climb(conn, baum, 4)
    conn.execute("UPDATE known_word SET ladder_step = 5 WHERE lemma_id = ?", (baum,))
    card = conn.execute("SELECT id FROM card WHERE lemma_id = ?", (baum,)).fetchone()[0]
    t = T0 + timedelta(days=2)
    before = dict(conn.execute("SELECT * FROM card WHERE id = ?", (card,)).fetchone())
    r = srs.review(conn, card, answer="Bäume", at=t)
    assert not r["check"]["correct"] and step(conn, baum) == 4
    o = srs.override(conn, card, at=t)
    assert o["overridden"] and step(conn, baum) == 5
    assert conn.execute("SELECT ladder_correct FROM known_word WHERE lemma_id = ?", (baum,)).fetchone()[0] == 1
    logs = conn.execute("SELECT rating FROM review_log WHERE card_id = ?", (card,)).fetchall()
    assert [x[0] for x in logs] == [3]                                # the wrong rating is gone
    after = conn.execute("SELECT reps, lapses FROM card WHERE id = ?", (card,)).fetchone()
    assert after["reps"] == before["reps"] + 1 and after["lapses"] == before["lapses"]
    with pytest.raises(ValueError):
        srs.override(conn, card, at=t)                                # only right after a wrong mark
