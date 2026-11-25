import json

import pytest

from app import srs, writing
from app.db import connect
from app.llm import Correction, WritingFeedback
from app.seed import seed_all


class FakeTeacher:
    def __init__(self, corrections=None):
        self.prompts = []
        self.corrections = corrections if corrections is not None else [
            Correction(original="ich habe gelaufen", corrected="ich bin gelaufen", grammar_code="PERFEKT_HABEN_SEIN",
                       lemma="", explanation="laufen forma el Perfekt con sein."),
            Correction(original="der Kindheit", corrected="die Kindheit", grammar_code="",
                       lemma="Kindheit", explanation="Kindheit es femenino: die Kindheit."),
            Correction(original="weil ich bin müde", corrected="weil ich müde bin", grammar_code="KONJ_WEIL",
                       lemma="", explanation="Con weil el verbo va al final."),
            Correction(original="x", corrected="y", grammar_code="MADE_UP_CODE", lemma="", explanation="extra"),
        ]

    def feedback(self, system, prompt):
        self.prompts.append((system, prompt))
        return WritingFeedback(corrected_text="Gestern bin ich gelaufen.", corrections=self.corrections,
                               more_errors=2, praise="Schöne Sätze!")


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    seed_all(c)
    return c


def test_every_lesson_has_three_prompts():
    for n in range(1, 13):
        ps = writing.prompts_for(n)
        assert len(ps) == 3 and all(p["de"] and p["en"] for p in ps)


def test_prompt_rotation_prefers_unused_tasks(conn):
    first = writing.next_prompt(conn, seed=1)
    assert first["lesson_number"] == 1 and first["redemittel"]
    writing.submit(conn, FakeTeacher([]), task=first["prompt"], text="Ich war müde.")
    second = writing.next_prompt(conn, seed=1)
    assert second["prompt"] != first["prompt"]
    assert writing.next_prompt(conn, exclude=second["prompt"], seed=1)["prompt"] != second["prompt"]


def test_submit_caps_corrections_and_logs_errors(conn):
    t = FakeTeacher()
    r = writing.submit(conn, t, task="Erzähl von gestern.", text="Gestern ich habe gelaufen, weil ich bin müde.")
    assert len(r["corrections"]) == 3
    assert r["corrections"][0]["grammar_code"] == "PERFEKT_HABEN_SEIN"
    assert r["corrections"][1]["lemma_id"] and r["corrections"][1]["grammar_code"] is None
    assert r["more_errors"] == 2 and r["praise"]
    assert set(r["grammar"]) == {"PERFEKT_HABEN_SEIN", "KONJ_WEIL"}
    codes = {row[0]: row[1] for row in conn.execute(
        "SELECT grammar_code, count FROM error_log WHERE grammar_code IS NOT NULL")}
    assert codes == {"PERFEKT_HABEN_SEIN": 1, "KONJ_WEIL": 1}
    assert conn.execute("SELECT COUNT(*) FROM error_log WHERE lemma_id IS NOT NULL").fetchone()[0] == 1
    saved = conn.execute("SELECT * FROM writing").fetchone()
    assert saved["corrected"] == "Gestern bin ich gelaufen." and json.loads(saved["feedback_json"])["praise"]


def test_prompt_lists_target_grammar_and_codes(conn):
    t = FakeTeacher([])
    conn.execute("UPDATE settings SET current_lesson = 6")
    conn.execute("UPDATE grammar_point SET unlocked = 1 WHERE lesson_id IN (SELECT id FROM lesson WHERE number <= 6)")
    writing.submit(conn, t, task="Gib einem Freund einen Rat.", text="Du solltest mehr schlafen.")
    system, prompt = t.prompts[0]
    assert "max" in system.lower() or "at most 3" in system
    assert "TARGET GRAMMAR: KONJ2_RAT_KOENNTE_SOLLTE" in prompt
    assert "KONJ_WEIL" in prompt and "BLOCK_RELATIVSATZ" not in prompt  # only unlocked codes are offered
    assert "Du solltest mehr schlafen." in prompt


def test_word_error_makes_its_card_due(conn):
    lid = conn.execute("SELECT id FROM lemma WHERE lemma = 'Kindheit'").fetchone()[0]
    later = srs.to_db(srs.now_utc().replace(year=2030))
    conn.execute("INSERT INTO card (lemma_id, direction, due, state) VALUES (?, 'produce', ?, 2)", (lid, later))
    writing.submit(conn, FakeTeacher(), task="t", text="Meine Kindheit war schön.")
    due = conn.execute("SELECT due FROM card WHERE lemma_id = ? AND direction = 'produce'", (lid,)).fetchone()[0]
    assert due < later


@pytest.mark.parametrize("text", ["", "   ", "x" * (writing.MAX_CHARS + 1)])
def test_rejects_empty_or_too_long(conn, text):
    with pytest.raises(ValueError):
        writing.submit(conn, FakeTeacher(), task="t", text=text)


def test_writing_api(client):
    from app.main import app, get_writer
    app.dependency_overrides[get_writer] = lambda: FakeTeacher()
    try:
        p = client.get("/api/writing/prompt").json()
        r = client.post("/api/writing", json={"prompt": p["prompt"], "text": "Gestern ich habe gelaufen."}).json()
        assert r["corrected"] and len(r["corrections"]) == 3
        assert client.post("/api/writing", json={"prompt": "t", "text": " "}).status_code == 422
        hist = client.get("/api/writing").json()
        assert hist[0]["corrections"] and hist[0]["submission"] == "Gestern ich habe gelaufen."
        assert client.get("/api/errors").json()
    finally:
        app.dependency_overrides.clear()
