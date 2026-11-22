"""Deutsch-Trainer API + static front end."""

from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import drills, generator, srs  # noqa: E402
from .db import connect, row_to_dict, rows_to_dicts, transaction  # noqa: E402
from .llm import GenerationError, LLMUnavailable, Writer, default_writer  # noqa: E402
from .seed import seed_all

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_conn: sqlite3.Connection | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _conn
    _conn = connect()
    seed_all(_conn)
    yield
    _conn.close()


app = FastAPI(title="Deutsch-Trainer", lifespan=lifespan)


def get_db() -> sqlite3.Connection:
    assert _conn is not None
    return _conn


def _lesson_or_404(db: sqlite3.Connection, number: int) -> dict:
    row = row_to_dict(db.execute("SELECT * FROM lesson WHERE number = ?", (number,)).fetchone())
    if row is None:
        raise HTTPException(404, f"Lesson {number} not found")
    return row


LESSON_STATS_SQL = """
SELECT l.*,
       COUNT(m.id)                                              AS word_count,
       SUM(CASE WHEN k.state = 'known' THEN 1 ELSE 0 END)       AS known_count,
       SUM(CASE WHEN k.state = 'learning' THEN 1 ELSE 0 END)    AS learning_count
FROM lesson l
LEFT JOIN lemma m ON m.lesson_id = l.id
LEFT JOIN known_word k ON k.lemma_id = m.id
"""


def _with_mastery(d: dict) -> dict:
    wc = d.get("word_count") or 0
    d["known_count"] = d.get("known_count") or 0
    d["learning_count"] = d.get("learning_count") or 0
    d["mastery"] = round(d["known_count"] / wc, 3) if wc else 0.0
    return d


@app.get("/api/overview")
def overview(db: sqlite3.Connection = Depends(get_db)):
    settings = row_to_dict(db.execute("SELECT * FROM settings WHERE id = 1").fetchone())
    known = db.execute("SELECT COUNT(*) FROM known_word WHERE state = 'known'").fetchone()[0]
    learning = db.execute("SELECT COUNT(*) FROM known_word WHERE state = 'learning'").fetchone()[0]
    total = db.execute("SELECT COUNT(*) FROM lemma").fetchone()[0]
    due = srs.due_count(db)
    current = _with_mastery(row_to_dict(db.execute(
        LESSON_STATS_SQL + " WHERE l.number = ? GROUP BY l.id", (settings["current_lesson"],)).fetchone()))
    return {"settings": settings, "known_words": known, "learning_words": learning,
            "total_words": total, "cards_due": due, "current_lesson": current}


@app.get("/api/lessons")
def list_lessons(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(LESSON_STATS_SQL + " GROUP BY l.id ORDER BY l.number").fetchall()
    return [_with_mastery(r) for r in rows_to_dicts(rows)]


@app.get("/api/lessons/{number}")
def get_lesson(number: int, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute(LESSON_STATS_SQL + " WHERE l.number = ? GROUP BY l.id", (number,)).fetchone()
    if row is None:
        raise HTTPException(404, f"Lesson {number} not found")
    lesson = _with_mastery(row_to_dict(row))
    codes = lesson["grammar_points"]
    grammar = rows_to_dicts(db.execute(
        f"SELECT * FROM grammar_point WHERE code IN ({','.join('?' * len(codes))})", codes).fetchall()) if codes else []
    grammar.sort(key=lambda g: codes.index(g["code"]))
    words = rows_to_dicts(db.execute(
        """SELECT m.*, COALESCE(k.state, 'unseen') AS state FROM lemma m
           LEFT JOIN known_word k ON k.lemma_id = m.id
           WHERE m.lesson_id = ? ORDER BY m.pos, m.lemma""", (lesson["id"],)).fetchall())
    exercises = rows_to_dicts(db.execute(
        "SELECT * FROM book_exercise WHERE lesson_id = ? ORDER BY book DESC, id", (lesson["id"],)).fetchall())
    progress = row_to_dict(db.execute(
        "SELECT * FROM book_progress WHERE lesson_id = ?", (lesson["id"],)).fetchone())
    return {"lesson": lesson, "grammar": grammar, "words": words,
            "exercises": exercises, "book_progress": progress}


@app.get("/api/words")
def list_words(
    db: sqlite3.Connection = Depends(get_db),
    lesson: int | None = Query(None, description="lesson number; 0 = A1 base words"),
    q: str | None = None,
    pos: str | None = None,
    limit: int = Query(200, le=2000),
    offset: int = 0,
):
    where, args = [], []
    if lesson == 0:
        where.append("m.lesson_id IS NULL")
    elif lesson is not None:
        where.append("m.lesson_id = (SELECT id FROM lesson WHERE number = ?)")
        args.append(lesson)
    if q:
        where.append("(m.lemma LIKE ? OR m.gloss_es LIKE ? OR m.gloss_en LIKE ?)")
        args += [f"%{q}%"] * 3
    if pos:
        where.append("m.pos = ?")
        args.append(pos.upper())
    sql = """SELECT m.*, COALESCE(k.state, 'unseen') AS state FROM lemma m
             LEFT JOIN known_word k ON k.lemma_id = m.id"""
    if where:
        sql += " WHERE " + " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM ({sql})", args).fetchone()[0]
    rows = db.execute(sql + " ORDER BY m.lemma COLLATE NOCASE LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
    return {"total": total, "items": rows_to_dicts(rows)}


@app.get("/api/grammar")
def list_grammar(db: sqlite3.Connection = Depends(get_db)):
    return rows_to_dicts(db.execute(
        """SELECT g.*, l.number AS lesson_number FROM grammar_point g
           LEFT JOIN lesson l ON l.id = g.lesson_id
           ORDER BY g.lesson_id IS NULL DESC, l.number, g.id""").fetchall())


class SettingsUpdate(BaseModel):
    current_lesson: int | None = Field(None, ge=1, le=12)
    daily_new_word_cap: int | None = Field(None, ge=0, le=50)
    target_retention: float | None = Field(None, ge=0.7, le=0.97)
    session_minutes: int | None = Field(None, ge=5, le=60)
    umlaut_ascii_ok: bool | None = None


@app.put("/api/settings")
def update_settings(body: SettingsUpdate, db: sqlite3.Connection = Depends(get_db)):
    changes = body.model_dump(exclude_none=True)
    with transaction(db):
        for k, v in changes.items():
            db.execute(f"UPDATE settings SET {k} = ? WHERE id = 1", (int(v) if isinstance(v, bool) else v,))
        if "current_lesson" in changes:
            n = changes["current_lesson"]
            # Manual setting mirrors the class: earlier lessons done, this one active, later locked.
            # Grammar is only ever unlocked, never re-locked (it has been taught).
            db.execute("""UPDATE lesson SET status = CASE
                            WHEN number < ? THEN 'done' WHEN number = ? THEN 'active' ELSE 'locked' END""", (n, n))
            db.execute("""UPDATE grammar_point SET unlocked = 1
                          WHERE lesson_id IN (SELECT id FROM lesson WHERE number <= ?)""", (n,))
    return overview(db)


class BookProgressUpdate(BaseModel):
    kursbuch_done: bool | None = None
    arbeitsbuch_done: bool | None = None
    missed_exercise_ids: list[int] | None = None
    missed_items_note: str | None = None


@app.put("/api/lessons/{number}/book-progress")
def update_book_progress(number: int, body: BookProgressUpdate, db: sqlite3.Connection = Depends(get_db)):
    lesson = _lesson_or_404(db, number)
    changes = body.model_dump(exclude_none=True)
    with transaction(db):
        for k, v in changes.items():
            if k == "missed_exercise_ids":
                v = json.dumps(sorted(set(v)))
            elif isinstance(v, bool):
                v = int(v)
            db.execute(f"UPDATE book_progress SET {k} = ? WHERE lesson_id = ?", (v, lesson["id"]))
    return row_to_dict(db.execute("SELECT * FROM book_progress WHERE lesson_id = ?", (lesson["id"],)).fetchone())


# ---- vocabulary review (FSRS) ----------------------------------------------------

class ReviewStart(BaseModel):
    new_words: bool = True


@app.post("/api/review/start")
def review_start(body: ReviewStart, db: sqlite3.Connection = Depends(get_db)):
    """Introduce today's new lesson words (respecting the daily cap) and return the queue."""
    with transaction(db):
        introduced = srs.introduce_lesson_words(db) if body.new_words else []
    return {"introduced": len(introduced), "queue": srs.queue(db), "due_count": srs.due_count(db),
            "new_today": srs.new_cards_today(db)}


@app.get("/api/review/queue")
def review_queue(db: sqlite3.Connection = Depends(get_db)):
    return {"queue": srs.queue(db), "due_count": srs.due_count(db)}


class ReviewAnswer(BaseModel):
    rating: int | None = Field(None, ge=1, le=4)
    answer: str | None = Field(None, max_length=200)
    duration_ms: int | None = Field(None, ge=0)


@app.post("/api/review/{card_id}")
def review_card(card_id: int, body: ReviewAnswer, db: sqlite3.Connection = Depends(get_db)):
    try:
        with transaction(db):
            return srs.review(db, card_id, rating=body.rating, answer=body.answer, duration_ms=body.duration_ms)
    except KeyError:
        raise HTTPException(404, f"Card {card_id} not found")
    except ValueError as e:
        raise HTTPException(422, str(e))


# ---- reader ---------------------------------------------------------------------------

def get_writer() -> Writer:
    return default_writer()


@app.get("/api/llm/status")
def llm_status():
    try:
        get_writer()
        return {"configured": True}
    except LLMUnavailable as e:
        return {"configured": False, "message": str(e)}


class GenerateRequest(BaseModel):
    lesson: int | None = Field(None, ge=1, le=12)


@app.post("/api/texts/generate")
def generate_text(body: GenerateRequest, db: sqlite3.Connection = Depends(get_db)):
    """Slow (30-90 s): writes, verifies and repairs a text, then writes its questions."""
    try:
        writer = app.dependency_overrides.get(get_writer, get_writer)()
        result = generator.generate_text(db, writer, lesson_number=body.lesson)
    except LLMUnavailable as e:
        raise HTTPException(503, str(e))
    except GenerationError as e:
        raise HTTPException(502, str(e))
    return {"text_id": result.text_id, "coverage": result.report.coverage, "attempts": result.attempts}


@app.get("/api/texts")
def list_texts(lesson: int | None = None, db: sqlite3.Connection = Depends(get_db)):
    sql = """SELECT t.id, t.title, t.summary, t.coverage, t.read_count, t.created_at, l.number AS lesson_number
             FROM text t JOIN lesson l ON l.id = t.lesson_id"""
    args: list = []
    if lesson is not None:
        sql += " WHERE l.number = ?"
        args.append(lesson)
    return rows_to_dicts(db.execute(sql + " ORDER BY t.id DESC", args).fetchall())


@app.get("/api/texts/{text_id}")
def get_text(text_id: int, db: sqlite3.Connection = Depends(get_db)):
    t = row_to_dict(db.execute(
        """SELECT t.*, l.number AS lesson_number, l.theme FROM text t JOIN lesson l ON l.id = t.lesson_id
           WHERE t.id = ?""", (text_id,)).fetchone())
    if t is None:
        raise HTTPException(404, f"Text {text_id} not found")
    ids = sorted({tok["id"] for tok in t["annotations"] if tok.get("id")})
    lemmas = {r["id"]: r for r in rows_to_dicts(db.execute(
        f"""SELECT m.id, m.lemma, m.pos, m.article, m.plural, m.aux, m.partizip2, m.gloss_es, m.gloss_en,
                   COALESCE(k.state, 'unseen') AS state
            FROM lemma m LEFT JOIN known_word k ON k.lemma_id = m.id
            WHERE m.id IN ({','.join('?' * len(ids))})""", ids).fetchall())} if ids else {}
    questions = [{k: q[k] for k in ("id", "type", "prompt", "options")} for q in rows_to_dicts(
        db.execute("SELECT * FROM question WHERE text_id = ? ORDER BY id", (text_id,)).fetchall())]
    return {"text": {k: t[k] for k in ("id", "title", "lesson_number", "theme", "coverage", "read_count",
                                       "target_lemma_ids", "wpm_log", "created_at")},
            "tokens": t["annotations"], "lemmas": lemmas, "questions": questions}


class QuestionAnswer(BaseModel):
    answer: str = Field(..., max_length=500)


@app.post("/api/questions/{question_id}/check")
def check_question(question_id: int, body: QuestionAnswer, db: sqlite3.Connection = Depends(get_db)):
    q = row_to_dict(db.execute("SELECT * FROM question WHERE id = ?", (question_id,)).fetchone())
    if q is None:
        raise HTTPException(404, f"Question {question_id} not found")
    if q["type"] == "short_answer":
        return {"correct": None, "answer": q["answer"]}  # learner compares with the model answer
    norm = lambda s: s.strip().lower().rstrip(".!")
    return {"correct": norm(body.answer) == norm(q["answer"]), "answer": q["answer"]}


class FinishReading(BaseModel):
    seconds: float | None = Field(None, ge=0)


@app.post("/api/texts/{text_id}/finish")
def finish_text(text_id: int, body: FinishReading, db: sqlite3.Connection = Depends(get_db)):
    try:
        return generator.finish_reading(db, text_id, seconds=body.seconds)
    except KeyError:
        raise HTTPException(404, f"Text {text_id} not found")


class WordState(BaseModel):
    state: Literal["known", "learning", "new"]


@app.put("/api/words/{lemma_id}/state")
def set_word_state(lemma_id: int, body: WordState, db: sqlite3.Connection = Depends(get_db)):
    """Manual override, e.g. 'I already know this word' from the word list."""
    if not db.execute("SELECT 1 FROM lemma WHERE id = ?", (lemma_id,)).fetchone():
        raise HTTPException(404, f"Word {lemma_id} not found")
    with transaction(db):
        db.execute("""INSERT INTO known_word (lemma_id, state) VALUES (?, ?)
                      ON CONFLICT(lemma_id) DO UPDATE SET state = excluded.state""", (lemma_id, body.state))
    return {"lemma_id": lemma_id, "state": body.state}


# ---- grammar drills ------------------------------------------------------------------

@app.get("/api/drills/session")
def drill_session(n: int = Query(drills.DEFAULT_SESSION, ge=1, le=20), code: str | None = None,
                  db: sqlite3.Connection = Depends(get_db)):
    items = drills.session(db, n=n, code=code)
    return {"items": items, "code": code}


class DrillAnswer(BaseModel):
    answer: str | list[str]


@app.post("/api/drills/{item_id}/check")
def drill_check(item_id: int, body: DrillAnswer, db: sqlite3.Connection = Depends(get_db)):
    try:
        return drills.check(db, item_id, body.answer)
    except KeyError:
        raise HTTPException(404, f"Drill item {item_id} not found")


class DrillGenerate(BaseModel):
    code: str


@app.post("/api/drills/generate")
def drill_generate(body: DrillGenerate, db: sqlite3.Connection = Depends(get_db)):
    """Slow (~30 s): Claude writes new items for one grammar point; only verified ones are kept."""
    try:
        writer = app.dependency_overrides.get(get_writer, get_writer)()
        return {"added": drills.generate(db, writer, body.code)}
    except LLMUnavailable as e:
        raise HTTPException(503, str(e))
    except GenerationError as e:
        raise HTTPException(502, str(e))


@app.get("/api/drills/stats")
def drill_stats(db: sqlite3.Connection = Depends(get_db)):
    return drills.stats(db)


@app.get("/api/errors")
def errors(limit: int = Query(5, ge=1, le=50), db: sqlite3.Connection = Depends(get_db)):
    return drills.top_errors(db, limit)


@app.get("/api/health")
def health() -> dict[Literal["ok"], bool]:
    return {"ok": True}


# Front end: static files, with index.html for the root.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Served from the root so its scope covers the whole app.
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")
