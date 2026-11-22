from datetime import timedelta

import pytest

from app import generator, progress, session, srs
from app.db import connect
from app.seed import seed_all
from tests.test_generator import FakeWriter


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAINER_DB", str(tmp_path / "t.db"))
    c = connect(tmp_path / "t.db")
    seed_all(c)
    return c


def log_review_days_ago(conn, days: int):
    ts = srs.to_db(srs.now_utc() - timedelta(days=days))
    conn.execute("INSERT INTO card (lemma_id, direction, due) VALUES ((SELECT MIN(id) FROM lemma), 'recognise', ?) "
                 "ON CONFLICT DO NOTHING", (ts,))
    cid = conn.execute("SELECT id FROM card LIMIT 1").fetchone()[0]
    conn.execute("INSERT INTO review_log (card_id, rating, ts) VALUES (?, 3, ?)", (cid, ts))
    conn.commit()


def test_streak_counts_consecutive_days(conn):
    assert progress.streak(conn) == 0
    for d in (1, 2, 3, 5):
        log_review_days_ago(conn, d)
    assert progress.streak(conn) == 3          # yesterday, 2, 3 days ago; gap at 4
    log_review_days_ago(conn, 0)
    assert progress.streak(conn) == 4


def test_activity_has_14_days_ending_today(conn):
    log_review_days_ago(conn, 0)
    days = progress.activity_by_day(conn)
    assert len(days) == 14 and days[-1]["count"] == 1 and sum(d["count"] for d in days) == 1


def test_summary_and_ready_for_next(conn):
    s = progress.summary(conn)
    assert s["known_words"] > 400 and s["current_lesson"] == 1 and not s["ready_for_next"]
    assert len(s["lessons"]) == 12 and s["lessons"][0]["words"] > 0
    conn.execute("""INSERT INTO known_word (lemma_id, state) SELECT m.id, 'known' FROM lemma m
                    JOIN lesson l ON l.id = m.lesson_id WHERE l.number = 1
                    ON CONFLICT(lemma_id) DO UPDATE SET state = 'known'""")
    s = progress.summary(conn)
    assert s["lessons"][0]["mastery"] == 1.0 and s["ready_for_next"]


def test_done_today_flags(conn):
    assert not any(progress.done_today(conn).values())
    log_review_days_ago(conn, 0)
    assert progress.done_today(conn)["review"]


def test_full_plan_without_history_skips_warmup(conn):
    p = session.plan(conn, "full")
    assert [s["kind"] for s in p["steps"]] == ["review", "text", "newwords", "drill", "write", "speak"]
    assert [s["kind"] for s in session.plan(conn, "quick")["steps"]] == ["review", "drill"]


def test_warmup_uses_a_text_read_before_today(conn):
    r = generator.generate_text(conn, FakeWriter(bad_drafts=0), seed=1)
    generator.finish_reading(conn, r.text_id, seconds=60)
    assert session.warmup_text(conn) is None          # read today → not "yesterday's text"
    conn.execute("UPDATE reading_log SET ts = datetime('now', '-1 day')")
    conn.commit()
    p = session.plan(conn, "full")
    assert p["steps"][0] == {"kind": "warmup", "label": "Aufwärmen", "text_id": r.text_id, "title": "Ein Tag mit Marco"}


def test_reread_is_logged_separately(conn):
    r = generator.generate_text(conn, FakeWriter(bad_drafts=0), seed=2)
    generator.finish_reading(conn, r.text_id, seconds=60)
    generator.finish_reading(conn, r.text_id, seconds=30, reread=True)
    kinds = [row[0] for row in conn.execute("SELECT kind FROM reading_log ORDER BY id")]
    assert kinds == ["read", "reread"]
    assert progress.done_today(conn)["warmup"] and progress.done_today(conn)["text"]
    speeds = progress.reading_speed(conn)
    assert speeds[-1]["wpm"] > speeds[0]["wpm"]       # same text, faster the second time


def test_prepare_text_in_background(conn):
    status = session.prepare_text(conn, lambda: FakeWriter(bad_drafts=0), wait=True)
    assert status["error"] is None and not status["generating"]
    assert session.unread_text(conn) is not None
    # an unread text already exists → nothing new is generated
    before = conn.execute("SELECT COUNT(*) FROM text").fetchone()[0]
    session.prepare_text(conn, lambda: FakeWriter(bad_drafts=0), wait=True)
    assert conn.execute("SELECT COUNT(*) FROM text").fetchone()[0] == before


def test_prepare_text_reports_errors(conn):
    status = session.prepare_text(conn, lambda: FakeWriter(always_bad=True), wait=True)
    assert status["text_id"] is None and "Prüfung" in status["error"]


def test_session_and_progress_api(client):
    assert [s["kind"] for s in client.get("/api/session/plan", params={"mode": "quick"}).json()["steps"]] == \
        ["review", "drill"]
    p = client.get("/api/progress").json()
    assert {"streak", "lessons", "top_errors", "activity", "done_today", "ready_for_next"} <= p.keys()
    r = client.post("/api/review/start", json={"new_words": False, "limit": 5}).json()
    assert r["introduced"] == 0


def test_concurrent_requests_do_not_share_a_connection(client):
    from concurrent.futures import ThreadPoolExecutor
    paths = ["/api/overview", "/api/progress", "/api/lessons", "/api/progress"] * 10
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda p: client.get(p).status_code, paths))
    assert set(codes) == {200}


@pytest.mark.parametrize("minutes, review, rounds, drills, speak", [
    (20, 40, 2, 8, False), (30, 60, 3, 12, True), (40, 80, 3, 16, True)])
def test_plan_scales_with_session_length(conn, minutes, review, rounds, drills, speak):
    conn.execute("UPDATE settings SET session_minutes = ?", (minutes,))
    p = session.plan(conn, "full")
    by = {s["kind"]: s for s in p["steps"]}
    assert p["minutes"] == minutes
    assert by["review"]["limit"] == review and by["newwords"]["rounds"] == rounds and by["drill"]["n"] == drills
    assert ("speak" in by) is speak


def test_default_session_is_30_minutes(conn):
    assert conn.execute("SELECT session_minutes FROM settings").fetchone()[0] == 30


def test_speaking_counts_for_today(conn):
    from tests.test_writing import FakeTeacher
    from app import writing
    writing.submit(conn, FakeTeacher([]), task="t", text="ich bin gelaufen", kind="speak")
    d = progress.done_today(conn)
    assert d["speak"] and not d["write"]


def test_session_minutes_setting_validated(client):
    assert client.put("/api/settings", json={"session_minutes": 30}).status_code == 200
    assert client.put("/api/settings", json={"session_minutes": 25}).status_code == 422
