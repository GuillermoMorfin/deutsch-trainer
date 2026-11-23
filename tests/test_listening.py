import json

import pytest

from app import generator, progress, session
from app.db import connect
from app.seed import seed_all
from tests.test_generator import FakeWriter


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    seed_all(c)
    return c


class SpyWriter(FakeWriter):
    systems, questions_asked = [], []

    def write(self, system, prompt):
        SpyWriter.systems.append(system)
        return super().write(system, prompt)

    def questions(self, system, prompt):
        SpyWriter.questions_asked.append(prompt)
        return super().questions(system, prompt)


def test_listening_text_uses_listening_rules(conn):
    SpyWriter.systems, SpyWriter.questions_asked = [], []
    r = generator.generate_text(conn, SpyWriter(bad_drafts=0), kind="listen", seed=1)
    t = conn.execute("SELECT kind, target_lemma_ids FROM text WHERE id = ?", (r.text_id,)).fetchone()
    assert t["kind"] == "listen" and len(json.loads(t["target_lemma_ids"])) == 2
    assert "LISTENING" in SpyWriter.systems[0] and "Name: text" in SpyWriter.systems[0]
    assert "listening-comprehension" in SpyWriter.questions_asked[0]


def test_listening_texts_stay_out_of_reading(conn):
    generator.generate_text(conn, FakeWriter(bad_drafts=0), kind="listen", seed=2)
    assert session.unread_text(conn) is None                 # the daily session won't pick it
    assert progress.lesson_check(conn, 1)["texts_read"] == 0


def test_api_lists_by_kind_and_logs_results(client):
    from app.main import app, get_writer
    app.dependency_overrides[get_writer] = lambda: FakeWriter(bad_drafts=0)
    try:
        lid = client.post("/api/texts/generate", json={"kind": "listen"}).json()["text_id"]
        rid = client.post("/api/texts/generate", json={}).json()["text_id"]
        assert [t["id"] for t in client.get("/api/texts", params={"kind": "listen"}).json()] == [lid]
        assert [t["id"] for t in client.get("/api/texts").json()] == [rid]
        assert client.get(f"/api/texts/{lid}").json()["text"]["kind"] == "listen"
        assert client.post(f"/api/texts/{lid}/listen-result", json={"plays": 2, "correct": 4, "total": 5}).json()["ok"]
        assert client.post(f"/api/texts/{rid}/listen-result", json={"plays": 1, "correct": 1, "total": 1}).status_code == 404
        listed = client.get("/api/texts", params={"kind": "listen"}).json()[0]
        assert listed["best_score"] == pytest.approx(0.8) and listed["attempts"] == 1
        p = client.get("/api/progress").json()
        assert p["listening"] == {"tasks": 1, "accuracy": 0.8} and p["done_today"]["listen"]
    finally:
        app.dependency_overrides.clear()
