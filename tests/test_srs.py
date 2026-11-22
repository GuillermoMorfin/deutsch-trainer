from datetime import datetime, timedelta, timezone

import pytest

from app import srs
from app.db import connect
from app.seed import seed_all

T0 = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    seed_all(c)
    return c


def lemma_id(conn, lemma):
    return conn.execute("SELECT id FROM lemma WHERE lemma = ?", (lemma,)).fetchone()[0]


def cards(conn, lid):
    return {r["direction"]: r for r in conn.execute("SELECT * FROM card WHERE lemma_id = ?", (lid,))}


def test_daily_cap_limits_new_words(conn):
    first = srs.introduce_lesson_words(conn, at=T0)
    assert len(first) == 8  # default cap
    assert srs.introduce_lesson_words(conn, at=T0 + timedelta(hours=2)) == []
    assert len(srs.introduce_lesson_words(conn, at=T0 + timedelta(days=1))) == 8


def test_new_words_come_from_current_lesson_and_start_learning(conn):
    srs.introduce_lesson_words(conn, at=T0)
    rows = conn.execute("""SELECT l.number, k.state FROM card c JOIN lemma m ON m.id = c.lemma_id
                           JOIN lesson l ON l.id = m.lesson_id JOIN known_word k ON k.lemma_id = m.id""").fetchall()
    assert {r["number"] for r in rows} == {1}
    assert {r["state"] for r in rows} == {"learning"}


def test_produce_card_unlocks_after_two_good_recognitions(conn):
    lid = lemma_id(conn, "Kindheit")
    srs.introduce_word(conn, lid, at=T0)
    rec = cards(conn, lid)["recognise"]["id"]
    r1 = srs.review(conn, rec, rating=3, at=T0)
    assert not r1["produce_unlocked"]
    srs.review(conn, rec, rating=1, at=T0 + timedelta(minutes=1))   # Again doesn't count
    r3 = srs.review(conn, rec, rating=3, at=T0 + timedelta(minutes=2))
    assert r3["produce_unlocked"]
    assert "produce" in cards(conn, lid)


def test_produce_card_graded_from_typed_answer(conn):
    lid = lemma_id(conn, "Kindheit")
    srs.introduce_word(conn, lid, at=T0)
    rec = cards(conn, lid)["recognise"]["id"]
    srs.review(conn, rec, rating=4, at=T0)
    srs.review(conn, rec, rating=4, at=T0 + timedelta(days=3))
    prod = cards(conn, lid)["produce"]["id"]

    wrong = srs.review(conn, prod, answer="Kindheit", at=T0 + timedelta(days=3))
    assert wrong["rating"] == 1 and wrong["check"]["verdict"] == "missing_article"
    right = srs.review(conn, prod, answer="die Kindheit", at=T0 + timedelta(days=3, minutes=1))
    assert right["rating"] == 3 and right["check"]["correct"]


def test_word_becomes_known_once_production_is_stable(conn):
    lid = lemma_id(conn, "Kindheit")
    srs.introduce_word(conn, lid, at=T0)
    rec = cards(conn, lid)["recognise"]["id"]
    t = T0
    for _ in range(2):
        srs.review(conn, rec, rating=4, at=t)
        t += timedelta(days=1)
    prod = cards(conn, lid)["produce"]["id"]
    state = None
    for _ in range(6):  # spaced correct answers grow stability past the threshold
        state = srs.review(conn, prod, answer="die Kindheit", at=t)["word_state"]
        srs.review(conn, rec, rating=3, at=t)
        t = srs.from_db(conn.execute("SELECT due FROM card WHERE id = ?", (prod,)).fetchone()[0]) + timedelta(hours=1)
    assert state == "known"
    # a lapse drops it back to learning
    assert srs.review(conn, prod, answer="das Kindheit", at=t)["word_state"] == "learning"


def test_reviewing_a1_word_never_demotes_it(conn):
    lid = lemma_id(conn, "Fahrrad")
    srs.introduce_word(conn, lid, at=T0)
    rec = cards(conn, lid)["recognise"]["id"]
    assert srs.review(conn, rec, rating=1, at=T0)["word_state"] == "known"


def test_queue_includes_due_and_soon_learning_cards_only(conn):
    srs.introduce_lesson_words(conn, at=T0)
    q = srs.queue(conn, at=T0)
    assert len(q) == 8 and all(c["direction"] == "recognise" for c in q)
    first = q[0]["id"]
    srs.review(conn, first, rating=3, at=T0)          # learning step: due in ~10 min
    assert first in {c["id"] for c in srs.queue(conn, at=T0)}  # learn-ahead keeps it in session
    srs.review(conn, first, rating=4, at=T0 + timedelta(minutes=10))  # graduates to days
    assert first not in {c["id"] for c in srs.queue(conn, at=T0 + timedelta(minutes=10))}


def test_recognise_card_requires_rating(conn):
    lid = lemma_id(conn, "Kindheit")
    srs.introduce_word(conn, lid, at=T0)
    with pytest.raises(ValueError):
        srs.review(conn, cards(conn, lid)["recognise"]["id"], at=T0)


def test_review_api_roundtrip(client):
    start = client.post("/api/review/start", json={}).json()
    assert start["introduced"] == 8 and len(start["queue"]) == 8
    card = start["queue"][0]
    r = client.post(f"/api/review/{card['id']}", json={"rating": 3, "duration_ms": 1200}).json()
    assert r["rating"] == 3
    assert client.post("/api/review/999999", json={"rating": 3}).status_code == 404
    assert client.post(f"/api/review/{card['id']}", json={}).status_code == 422
