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


# ---- a new plan every day -------------------------------------------------------------------------

from app.llm import SpeakingSetModel  # noqa: E402

GOOD_QUESTIONS = ["Was hast du als Kind gern gemacht?", "Wo hast du letzten Sommer gewohnt?",
                  "Was hast du gestern gekocht?", "Wie war dein Wochenende?",
                  "Was machst du am Sonntag?", "Was hast du heute gegessen?"]


class FakeSpeakingWriter:
    def __init__(self, first_bad: bool = False):
        self.prompts, self.first_bad = [], first_bad

    def speaking(self, system, prompt):
        self.prompts.append(prompt)
        qs = list(GOOD_QUESTIONS)
        if self.first_bad and len(self.prompts) == 1:
            qs[0] = "Was ist das Buch, das du gelesen hast?"          # relative clause: rejected
        return SpeakingSetModel(topic="Ein Sonntag im Park", focus="Talk about last weekend in the Perfekt.",
                                challenge="Five sentences in the Perfekt.", questions=qs,
                                roleplay_setup="Your partner meets you in the park.",
                                roleplay_starter="Hallo! Was hast du heute gemacht?",
                                phrases=["Am Sonntag bin ich …", "Gestern habe ich …"])


def test_first_plan_is_the_hand_written_one(conn):
    g = speaking.guide(conn, 1)
    assert not g["pending"] and g["set"]["source"] == "seed" and g["questions"] == SEED["1"]["questions"]
    assert speaking.guide(conn, 1)["set"]["id"] == g["set"]["id"]           # same plan all day


def test_next_day_needs_a_new_plan(conn):
    speaking.guide(conn, 1)
    conn.execute("UPDATE speaking_set SET day = date('now', 'localtime', '-1 day')")
    conn.commit()
    assert speaking.guide(conn, 1)["pending"]


def test_a_conversation_logged_before_today_uses_up_the_hand_written_plan(conn):
    speaking.log(conn, lesson_number=1, minutes=15)
    conn.execute("UPDATE speaking_log SET ts = datetime('now', '-1 day')")
    conn.commit()
    assert speaking.guide(conn, 1)["pending"]


def test_generated_plan_is_verified_and_never_repeats(conn):
    speaking.guide(conn, 1)                                                  # the seed plan was used
    w = FakeSpeakingWriter(first_bad=True)
    speaking.generate_set(conn, w, 1)
    assert len(w.prompts) == 2                                                # one repair round
    assert "A checker rejected" in w.prompts[1] and "Was ist das Buch, das du gelesen hast?" in w.prompts[1]
    assert "Was hast du als Kind gern gemacht?" in w.prompts[0]               # earlier questions passed in
    g = speaking.guide(conn, 1)
    assert g["topic"] == "Ein Sonntag im Park" and g["questions"] == GOOD_QUESTIONS
    assert g["phrases"] == ["Am Sonntag bin ich …", "Gestern habe ich …"] and g["set"]["number"] == 2
    w2 = FakeSpeakingWriter()
    speaking.generate_set(conn, w2, 1)
    assert "Ein Sonntag im Park" in w2.prompts[0]                             # today's set is history next time


def test_lines_above_the_level_are_dropped(conn):
    class Hard(FakeSpeakingWriter):
        def speaking(self, system, prompt):
            s = super().speaking(system, prompt)
            s.questions[1] = "Welches Quokka hast du gesehen?"
            return s
    speaking.generate_set(conn, Hard(), 1)
    assert "Welches Quokka hast du gesehen?" not in speaking.guide(conn, 1)["questions"]


def test_new_plan_api(client):
    from app.main import app, get_writer
    app.dependency_overrides[get_writer] = lambda: FakeSpeakingWriter()
    try:
        first = client.get("/api/speaking").json()
        assert first["set"]["source"] == "seed"
        client.post("/api/speaking/new")
        for _ in range(50):
            if not client.get("/api/speaking/status").json()["generating"]:
                break
            import time
            time.sleep(0.1)
        g = client.get("/api/speaking").json()
        assert g["topic"] == "Ein Sonntag im Park" and g["set"]["source"] == "generated"
    finally:
        app.dependency_overrides.clear()
