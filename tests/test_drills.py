import json

import pytest

from app import drills
from app.db import connect
from app.llm import DrillItemModel
from app.seed import seed_all
from app.verifier import analyse
from tests.test_verifier import state_at

SEED = json.loads(drills.SEED_PATH.read_text(encoding="utf-8"))["items"]


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    seed_all(c)
    return c


def lesson_of(conn, code):
    return conn.execute("""SELECT l.number FROM grammar_point g JOIN lesson l ON l.id = g.lesson_id
                           WHERE g.code = ?""", (code,)).fetchone()[0]


def set_lesson(client_or_conn, n):
    c = client_or_conn
    c.execute("UPDATE settings SET current_lesson = ?", (n,))
    c.execute("UPDATE grammar_point SET unlocked = 1 WHERE lesson_id IN (SELECT id FROM lesson WHERE number <= ?)", (n,))
    c.commit()


@pytest.mark.parametrize("item", SEED, ids=lambda i: f"{i['code']}:{i['prompt'][:30]}")
def test_every_seed_item_passes_the_verifier_at_its_lesson(tmp_path_factory, item):
    conn = _shared_conn(tmp_path_factory)
    lex, unlocked = state_at(conn, lesson_of(conn, item["code"]))
    sentence = drills.full_sentence(item["type"], item["prompt"], item["answers"])
    _, r = analyse(sentence, lex, unlocked)
    assert r.grammar == [], [g.to_dict() for g in r.grammar]
    assert r.coverage == 1.0, (sentence, r.unknown)


_CONN = {}


def _shared_conn(factory):
    if "c" not in _CONN:
        _CONN["c"] = connect(factory.mktemp("d") / "t.db")
        seed_all(_CONN["c"])
    return _CONN["c"]


def test_seed_bank_covers_every_a21_grammar_point():
    codes = {i["code"] for i in SEED}
    lesson_codes = {c for l in json.loads((drills.SEED_PATH.parent / "lessons.json").read_text()) for c in l["grammar_points"]}
    assert lesson_codes <= codes
    assert all(sum(i["code"] == c for i in SEED) >= 6 for c in lesson_codes)


def test_choice_answers_are_among_options():
    for i in SEED:
        if i["type"] == "choice":
            assert set(i["answers"]) <= set(i["options"]), i


def test_full_sentence():
    assert drills.full_sentence("gap", "Als Kind ___ ich oft draußen.", ["war"]) == "Als Kind war ich oft draußen."
    assert drills.full_sentence("order", "Ich bleibe zu Hause,", [["weil", "ich", "krank", "bin"]]) == \
        "Ich bleibe zu Hause, weil ich krank bin."
    assert drills.full_sentence("order", "Weißt du,", [["wo", "mein", "Pass", "ist"]]) == "Weißt du, wo mein Pass ist?"


@pytest.mark.parametrize("item, answer, ok", [
    ({"type": "gap", "answers": ["war"]}, " War. ", True),
    ({"type": "gap", "answers": ["wäre"]}, "ware", False),          # umlaut is strict
    ({"type": "gap", "answers": ["Überraschung"]}, "überraschung", True),
    ({"type": "choice", "answers": ["den"]}, "dem", False),
    ({"type": "order", "answers": [["weil", "ich", "krank", "bin"]]}, ["weil", "ich", "bin", "krank"], False),
    ({"type": "order", "answers": [["weil", "ich", "krank", "bin"]]}, ["Weil", "ich", "krank", "bin"], True),
    ({"type": "order", "answers": [["a", "b"], ["b", "a"]]}, "b a", True),
])
def test_grade(item, answer, ok):
    assert drills.grade(item, answer) is ok


def test_session_at_lesson_1_only_uses_lesson_1_grammar(conn):
    items = drills.session(conn, n=8, seed=1)
    assert len(items) == 8
    assert {i["grammar_code"] for i in items} <= {"PERFEKT_HABEN_SEIN", "PRAET_WAR_HATTE", "LETZT_NAECHST_JED"}
    assert all("answers" not in i for i in items)  # answers stay on the server


def test_session_caps_items_per_point(conn):
    set_lesson(conn, 4)
    items = drills.session(conn, n=8, seed=2)
    counts = {}
    for i in items:
        counts[i["grammar_code"]] = counts.get(i["grammar_code"], 0) + 1
    assert max(counts.values()) <= drills.MAX_PER_CODE


def test_order_tokens_are_shuffled(conn):
    set_lesson(conn, 2)
    items = [i for i in drills.session(conn, n=12, code="KONJ_WEIL", seed=3) if i["type"] == "order"]
    assert items
    item = items[0]
    canon = json.loads(conn.execute("SELECT tokens FROM drill_item WHERE id = ?", (item["id"],)).fetchone()[0])
    assert sorted(item["tokens"]) == sorted(canon) and item["tokens"] != canon


def test_wrong_answer_is_logged_and_raises_weight(conn):
    set_lesson(conn, 2)
    before = drills.code_weights(conn)["PERFEKT_HABEN_SEIN"]
    item = conn.execute("SELECT id FROM drill_item WHERE grammar_code = 'PERFEKT_HABEN_SEIN' LIMIT 1").fetchone()[0]
    r = drills.check(conn, item, "falsch")
    assert r["correct"] is False and r["grammar"]["spanish_bridge"] and r["grammar"]["warning"]
    log = conn.execute("SELECT count, example FROM error_log WHERE grammar_code = 'PERFEKT_HABEN_SEIN'").fetchone()
    assert log["count"] == 1 and log["example"]
    assert drills.code_weights(conn)["PERFEKT_HABEN_SEIN"] > before
    assert drills.top_errors(conn)[0]["grammar_code"] == "PERFEKT_HABEN_SEIN"


def test_missed_grammar_exercises_boost_their_lesson(conn):
    set_lesson(conn, 2)
    before = drills.code_weights(conn)
    l1 = conn.execute("SELECT id FROM lesson WHERE number = 1").fetchone()[0]
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM book_exercise WHERE lesson_id = ? AND label LIKE '%Grammatik%' LIMIT 2", (l1,))]
    conn.execute("UPDATE book_progress SET missed_exercise_ids = ? WHERE lesson_id = ?", (json.dumps(ids), l1))
    after = drills.code_weights(conn)
    assert after["PRAET_WAR_HATTE"] > before["PRAET_WAR_HATTE"]
    assert after["KONJ_WEIL"] == before["KONJ_WEIL"]


def test_items_with_unknown_words_are_not_shown(conn):
    conn.execute("""INSERT INTO drill_item (grammar_code, type, prompt, answers, full_sentence)
                    VALUES ('PRAET_WAR_HATTE', 'gap', 'Der Quokka ___ müde.', '["war"]', 'Der Quokka war müde.')""")
    items = drills.session(conn, n=20, code="PRAET_WAR_HATTE", seed=4)
    assert all("Quokka" not in i["prompt"] for i in items)


class FakeDrillWriter:
    def drills(self, system, prompt):
        assert "GRAMMAR POINT" in prompt and "ALLOWED WORDS" in prompt and "NEVER give the answer away" in prompt
        return [
            DrillItemModel(type="gap", prompt="Heute ___ ich sehr müde.", options=[], answers=["bin"],
                           order_answers=[], hint="sein", explanation="sein, 1st person"),
            DrillItemModel(type="order", prompt="Ich trinke Kaffee,", options=[], answers=[],
                           order_answers=["weil ich müde bin"], hint="", explanation="verb last"),
            DrillItemModel(type="choice", prompt="Das ist ___ Mann, der Quatsch macht.", options=["der", "die"],
                           answers=["der"], order_answers=[], hint="", explanation="relative clause: rejected"),
            DrillItemModel(type="choice", prompt="Ich ___ müde.", options=["bin", "ist"], answers=["sind"],
                           order_answers=[], hint="", explanation="answer not in options: rejected"),
            DrillItemModel(type="rewrite", prompt="Der Hund ist im Garten. Ich sehe ... (den Hund)", options=[],
                           answers=["Ich sehe den Hund im Garten."], order_answers=[], hint="Schreib den Satz.",
                           explanation="answer in brackets: rejected"),
        ]


def test_generate_keeps_only_verified_items(conn):
    set_lesson(conn, 2)
    added = drills.generate(conn, FakeDrillWriter(), "KONJ_WEIL")
    assert added == 2
    rows = conn.execute("SELECT type, answers FROM drill_item WHERE source = 'generated'").fetchall()
    assert {r["type"] for r in rows} == {"gap", "order"}
    order = next(r for r in rows if r["type"] == "order")
    assert json.loads(order["answers"]) == [["weil", "ich", "müde", "bin"]]


def test_drill_api(client):
    items = client.get("/api/drills/session", params={"n": 5}).json()["items"]
    assert len(items) == 5
    r = client.post(f"/api/drills/{items[0]['id']}/check", json={"answer": "xyz"}).json()
    assert r["correct"] is False and r["grammar"]["rule"]
    assert client.get("/api/errors").json()[0]["count"] == 1
    assert client.get("/api/drills/stats").json()
    assert client.post("/api/drills/999999/check", json={"answer": "x"}).status_code == 404


def test_every_grammar_point_has_rewrite_exercises():
    codes = {i["code"] for i in SEED}
    for c in codes:
        assert sum(i["code"] == c and i["type"] == "rewrite" for i in SEED) >= 3, c


@pytest.mark.parametrize("answer, verdict", [
    ("Ich bleibe zu Hause, weil ich krank bin.", "correct"),
    ("ich bleibe zu hause weil ich krank bin", "correct"),          # capitals and punctuation don't matter
    ("Ich bleibe zu Hause, weil ich bin krank.", "word_order"),     # the typical weil mistake
    ("Ich bleibe zu Hause, denn ich bin krank.", "wrong"),
])
def test_rewrite_verdicts(answer, verdict):
    item = {"type": "rewrite", "answers": ["Ich bleibe zu Hause, weil ich krank bin."]}
    assert drills.rewrite_verdict(item, answer) == verdict
    assert drills.grade(item, answer) is (verdict == "correct")


def test_rewrite_accepts_listed_variants():
    item = {"type": "rewrite", "answers": ["Es regnet. Deshalb nehme ich den Bus.", "Es regnet, deshalb nehme ich den Bus."]}
    assert drills.grade(item, "Es regnet, deshalb nehme ich den Bus")


def test_rewrite_check_and_override(conn):
    set_lesson(conn, 2)
    item = conn.execute("SELECT id FROM drill_item WHERE type = 'rewrite' AND grammar_code = 'KONJ_WEIL' LIMIT 1").fetchone()[0]
    r = drills.check(conn, item, "Ich bleibe zu Hause, weil ich bin krank.")
    assert r["correct"] is False and r["verdict"] in ("word_order", "wrong")
    assert conn.execute("SELECT count FROM error_log WHERE grammar_code = 'KONJ_WEIL'").fetchone()[0] == 1
    drills.override(conn, item)                                       # "Ich hatte es richtig"
    assert conn.execute("SELECT correct FROM drill_attempt ORDER BY id DESC LIMIT 1").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM error_log WHERE grammar_code = 'KONJ_WEIL'").fetchone()[0] == 0


@pytest.mark.parametrize("item", SEED, ids=lambda i: f"{i['code']}:{i['prompt'][:30]}")
def test_no_seed_item_shows_its_answer_before_answering(item):
    assert drills.leaks(item) == []


@pytest.mark.parametrize("item, leak", [
    ({"type": "rewrite", "prompt": "Der Hund ist im Garten. Ich sehe ... (den Hund)", "hint": "",
      "answers": ["Ich sehe den Hund im Garten."]}, True),
    ({"type": "rewrite", "prompt": "Der Hund ist im Garten. Ich sehe ... (der Hund)", "hint": "",
      "answers": ["Ich sehe den Hund im Garten."]}, False),
    ({"type": "rewrite", "prompt": "Ich bin krank. Ich bleibe zu Hause.", "hint": "Verbinde mit weil.",
      "answers": ["Ich bleibe zu Hause, weil ich krank bin."]}, False),
    ({"type": "order", "prompt": "Ich zeige", "hint": "dem Freund, das Foto",
      "answers": [["dem", "Freund", "das", "Foto"]]}, True),
    ({"type": "gap", "prompt": "Ich sehe ___ Frau. (die)", "hint": "Akkusativ", "answers": ["die"]}, True),
    ({"type": "choice", "prompt": "Wir sprechen über ___ Festival.", "hint": "das Festival", "answers": ["das"]}, True),
])
def test_leak_detection(item, leak):
    assert bool(drills.leaks(item)) is leak
