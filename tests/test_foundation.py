import csv
import json
from pathlib import Path

from app.db import connect
from app.seed import SEED_DIR, seed_all, validate_lemma_row


def test_seed_is_idempotent(tmp_path):
    conn = connect(tmp_path / "t.db")
    first = seed_all(conn)
    second = seed_all(conn)
    assert first == second
    assert conn.execute("SELECT COUNT(*) FROM lesson").fetchone()[0] == 12
    assert conn.execute("SELECT COUNT(*) FROM lemma").fetchone()[0] == first["a1_lemmas"]


def test_every_a1_noun_has_an_article():
    with open(SEED_DIR / "a1_core.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    bad = [r["lemma"] for r in rows if validate_lemma_row(r)]
    assert bad == []


def test_lesson_grammar_codes_exist():
    lessons = json.loads((SEED_DIR / "lessons.json").read_text(encoding="utf-8"))
    codes = {g["code"] for g in json.loads((SEED_DIR / "grammar_points.json").read_text(encoding="utf-8"))["points"]}
    for l in lessons:
        assert set(l["grammar_points"]) <= codes, l["number"]


def test_every_unlockable_grammar_point_has_full_note():
    pts = json.loads((SEED_DIR / "grammar_points.json").read_text(encoding="utf-8"))["points"]
    for g in pts:
        if not g["code"].startswith("BLOCK_"):
            assert all(g[k] for k in ("rule", "bridge", "example", "warning")), g["code"]


def test_validator_rejects_noun_without_article():
    assert validate_lemma_row({"lemma": "Hund", "pos": "NOUN", "article": ""})
    assert validate_lemma_row({"lemma": "der Hund", "pos": "NOUN", "article": "der"})
    assert not validate_lemma_row({"lemma": "Hund", "pos": "NOUN", "article": "der"})


def test_blocked_structures_stay_locked(tmp_path):
    conn = connect(tmp_path / "t.db")
    seed_all(conn)
    unlocked = conn.execute("SELECT COUNT(*) FROM grammar_point WHERE code LIKE 'BLOCK_%' AND unlocked = 1").fetchone()[0]
    assert unlocked == 0


def test_lessons_and_words_endpoints(client):
    lessons = client.get("/api/lessons").json()
    assert [l["number"] for l in lessons] == list(range(1, 13))
    assert lessons[0]["status"] == "active"

    words = client.get("/api/words", params={"lesson": 0, "q": "Fahrrad"}).json()
    assert words["items"][0]["article"] == "das"
    assert words["items"][0]["state"] == "known"

    detail = client.get("/api/lessons/2").json()
    assert detail["grammar"][0]["code"] == "KONJ_WEIL"
    assert detail["exercises"], "book exercise index should be linked to lesson 2"


def test_setting_current_lesson_unlocks_grammar(client):
    client.put("/api/settings", json={"current_lesson": 4})
    lessons = {l["number"]: l["status"] for l in client.get("/api/lessons").json()}
    assert lessons[3] == "done" and lessons[4] == "active" and lessons[5] == "locked"
    grammar = {g["code"]: g["unlocked"] for g in client.get("/api/grammar").json()}
    assert grammar["KONJ_DESHALB"] == 1 and grammar["KONJ_DASS"] == 0


def test_book_progress_roundtrip(client):
    ex = client.get("/api/lessons/3").json()["exercises"][:2]
    ids = [e["id"] for e in ex]
    r = client.put("/api/lessons/3/book-progress", json={"missed_exercise_ids": ids, "arbeitsbuch_done": True}).json()
    assert r["missed_exercise_ids"] == sorted(ids) and r["arbeitsbuch_done"] == 1


def test_frontend_served(client):
    assert "Deutsch-Trainer" in client.get("/").text
    assert client.get("/sw.js").status_code == 200
