import json
import random
from datetime import timedelta

import pytest

from app import export, optimize, progress, srs, writing
from app.db import connect
from app.seed import seed_all
from tests.test_writing import FakeTeacher


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    seed_all(c)
    return c


# ---- Quizlet export ----------------------------------------------------------------

def test_quizlet_lines_are_term_tab_definition(conn):
    name, text = export.quizlet(conn, lesson=1)
    assert name == "momente-lektion-1.txt"
    lines = text.splitlines()
    assert len(lines) == conn.execute("""SELECT COUNT(*) FROM lemma m JOIN lesson l ON l.id = m.lesson_id
                                         WHERE l.number = 1 AND m.pos != 'PHRASE'""").fetchone()[0]
    assert all(line.count("\t") == 1 for line in lines)
    assert "das Jubiläum, die Jubiläen\tel aniversario · anniversary" in lines
    assert any(line.startswith("klettern (ist geklettert)\t") for line in lines)


def test_quizlet_filters_by_state_and_all_lessons(conn):
    lid = conn.execute("SELECT id FROM lemma WHERE lemma = 'Panne'").fetchone()[0]
    conn.execute("INSERT INTO known_word (lemma_id, state) VALUES (?, 'learning')", (lid,))
    name, text = export.quizlet(conn, state="learning")
    assert name == "momente-alle-lektionen-learning.txt" and text == "die Panne, die Pannen\tla avería · breakdown"


def test_quizlet_api_download(client):
    r = client.get("/api/export/quizlet", params={"lesson": 2})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert "die Panne" in r.text


# ---- ready for Momente A2.2 ------------------------------------------------------------

def add_lesson_13(conn):
    conn.execute("""INSERT INTO lesson (number, title, theme, word_field, grammar_points, redemittel, book)
                    VALUES (13, 'Test', 'Wohnen in der Stadt', 'Stadt', '[]', '["Ich wohne lieber …"]', 'A2.2')""")
    conn.commit()


def test_lesson_beyond_12_can_be_current(client):
    from app.db import connect as _c
    import os
    c = _c(os.environ["TRAINER_DB"])
    add_lesson_13(c)
    assert client.put("/api/settings", json={"current_lesson": 13}).status_code == 200
    assert client.put("/api/settings", json={"current_lesson": 14}).status_code == 422


def test_generic_writing_prompts_for_new_lessons(conn):
    add_lesson_13(conn)
    p = writing.next_prompt(conn, lesson_number=13)
    assert "Wohnen in der Stadt" in p["prompt"] and "Ich wohne lieber" in p["prompt"]


def test_ready_for_next_uses_last_lesson_in_db(conn):
    conn.execute("UPDATE settings SET current_lesson = 12")
    conn.execute("""INSERT INTO known_word (lemma_id, state) SELECT m.id, 'known' FROM lemma m
                    JOIN lesson l ON l.id = m.lesson_id WHERE l.number = 12""")
    from tests.test_session import read_three_texts
    read_three_texts(conn, 12)
    assert progress.summary(conn)["ready_for_next"] is False      # 12 is the last lesson
    add_lesson_13(conn)
    assert progress.summary(conn)["ready_for_next"] is True


# ---- FSRS optimisation ----------------------------------------------------------------

def test_status_before_enough_reviews(conn):
    st = optimize.status(conn)
    assert st["reviews"] == 0 and not st["ready"] and not st["optimized"]
    if st["installed"]:
        with pytest.raises(ValueError):
            optimize.optimize(conn)


def simulate_reviews(conn, n_cards=60, days=60, seed=1):
    """A learner who remembers most cards: enough history for the optimizer."""
    rng = random.Random(seed)
    ids = [r[0] for r in conn.execute("SELECT id FROM lemma LIMIT ?", (n_cards,))]
    start = srs.now_utc() - timedelta(days=days)
    for lid in ids:
        srs.introduce_word(conn, lid, at=start)
    conn.commit()
    cards = [r[0] for r in conn.execute("SELECT id FROM card")]
    for cid in cards:
        t = start
        while t < srs.now_utc() - timedelta(hours=1):
            rating = rng.choices([1, 2, 3, 4], weights=[1, 1, 6, 2])[0]
            srs.review(conn, cid, rating=rating, at=t)
            due = srs.from_db(conn.execute("SELECT due FROM card WHERE id = ?", (cid,)).fetchone()[0])
            t = max(due, t + timedelta(minutes=10))
    conn.commit()


def test_optimizer_fits_and_scheduler_uses_parameters(conn):
    pytest.importorskip("torch")
    simulate_reviews(conn, n_cards=100, days=120)
    n = conn.execute("SELECT COUNT(*) FROM review_log").fetchone()[0]
    assert n >= optimize.MIN_REVIEWS, n
    result = optimize.optimize(conn)
    assert len(result["parameters"]) == 21
    st = optimize.status(conn)
    assert st["optimized"] and st["optimized_reviews"] == n
    sched = srs.scheduler(conn)
    assert [round(p, 4) for p in sched.parameters] == result["parameters"]
    optimize.reset(conn)
    assert not optimize.status(conn)["optimized"]


def test_fsrs_api(client):
    st = client.get("/api/fsrs").json()
    assert st["reviews"] == 0 and st["min_reviews"] == optimize.MIN_REVIEWS
    assert client.post("/api/fsrs/optimize").status_code in (422, 503)
