import json

import pytest

from app import speaking, srs
from app.db import connect
from app.seed import seed_all
from app.verifier import analyse
from tests.test_drills import _shared_conn, set_lesson
from tests.test_verifier import state_at

SEED = json.loads(speaking.SEED_PATH.read_text(encoding="utf-8"))["lessons"]
SENTENCES = [(int(n), s) for n, g in SEED.items() for s in g["questions"] + [g["roleplay"]["starter"]]]


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    seed_all(c)
    return c


def test_every_lesson_has_a_guide():
    assert set(SEED) == {str(n) for n in range(1, 13)}
    for g in SEED.values():
        assert g["focus"] and g["challenge"] and len(g["questions"]) >= 5 and g["roleplay"]["setup"]


@pytest.mark.parametrize("lesson, sentence", SENTENCES, ids=lambda x: str(x)[:30])
def test_speaking_sentences_pass_the_verifier_at_their_lesson(tmp_path_factory, lesson, sentence):
    conn = _shared_conn(tmp_path_factory)
    lex, unlocked = state_at(conn, lesson)
    _, r = analyse(sentence, lex, unlocked)
    assert r.grammar == [], [g.to_dict() for g in r.grammar]
    assert r.coverage == 1.0, (sentence, r.unknown)


def test_guide_combines_lesson_words_and_errors(conn):
    set_lesson(conn, 2)
    wid = conn.execute("SELECT m.id FROM lemma m JOIN lesson l ON l.id = m.lesson_id WHERE l.number = 2 LIMIT 1").fetchone()[0]
    srs.introduce_word(conn, wid)
    conn.execute("UPDATE known_word SET state = 'learning' WHERE lemma_id = ?", (wid,))
    conn.execute("INSERT INTO error_log (grammar_code, example, count) VALUES ('KONJ_WEIL', 'weil ich bin krank', 3)")
    conn.commit()
    g = speaking.guide(conn)
    assert g["lesson"]["number"] == 2 and g["lessons"] == [1, 2]
    assert [x["code"] for x in g["grammar"]] == ["KONJ_WEIL"]
    assert wid in [w["id"] for w in g["words"]]
    assert g["errors"][0]["grammar_code"] == "KONJ_WEIL"
    assert g["redemittel"] and g["questions"] and g["partner_tips"]
    assert speaking.guide(conn, 1)["lesson"]["number"] == 1


def test_log_counts_for_today(conn):
    from app import progress
    speaking.log(conn, lesson_number=1, minutes=20, note="  weil war schwer ")
    assert progress.done_today(conn)["speak"]
    h = speaking.guide(conn)["history"]
    assert h["sessions"] == 1 and h["minutes"] == 20 and h["recent"][0]["note"] == "weil war schwer"
    assert progress.activity_by_day(conn, 1)[0]["count"] >= 1


def test_speaking_api(client):
    if True:
        r = client.get("/api/speaking")
        assert r.status_code == 200 and r.json()["lesson"]["number"] == 1
        assert client.get("/api/speaking?lesson=99").status_code == 404
        assert client.post("/api/speaking/log", json={"lesson": 1, "minutes": 15}).status_code == 200
        assert client.post("/api/speaking/log", json={"lesson": 1, "minutes": 0}).status_code == 422
        assert client.get("/api/speaking").json()["history"]["sessions"] == 1
