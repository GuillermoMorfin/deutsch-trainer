"""The daily ~20-minute session (Nation's four strands) and Quick 5.

full : warm-up re-read (fluency) → due cards (language) → new text + questions (input)
       → new words, quick recall → grammar drill (language) → write (output)
quick: due cards (max 20) → 3 drill items

The new text is prepared in a background thread at session start, so it is usually ready
by the time the learner reaches it.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Callable

from . import generator, srs
from .db import connect, db_path, row_to_dict
from .llm import GenerationError, LLMUnavailable, Writer

_state = {"generating": False, "error": None}
_lock = threading.Lock()


def warmup_text(conn: sqlite3.Connection) -> dict | None:
    """The most recently read text from before today ("yesterday's text")."""
    return row_to_dict(conn.execute(
        """SELECT t.id, t.title FROM reading_log r JOIN text t ON t.id = r.text_id
           WHERE date(r.ts, 'localtime') < date('now', 'localtime')
           ORDER BY r.id DESC LIMIT 1""").fetchone())


def unread_text(conn: sqlite3.Connection) -> dict | None:
    return row_to_dict(conn.execute(
        """SELECT t.id, t.title FROM text t JOIN lesson l ON l.id = t.lesson_id
           WHERE t.read_count = 0 AND l.number = (SELECT current_lesson FROM settings WHERE id = 1)
           ORDER BY t.id DESC LIMIT 1""").fetchone())


def text_status(conn: sqlite3.Connection) -> dict:
    t = unread_text(conn)
    return {"text_id": t["id"] if t else None, "generating": _state["generating"], "error": _state["error"]}


def prepare_text(conn: sqlite3.Connection, writer_factory: Callable[[], Writer], *, wait: bool = False) -> dict:
    """Start writing a new text in the background unless an unread one exists or one is being written."""
    if unread_text(conn):
        return text_status(conn)
    with _lock:
        if _state["generating"]:
            return text_status(conn)
        _state.update(generating=True, error=None)

    def run():
        bg = connect(db_path())  # its own connection: never share a transaction with request threads
        try:
            generator.generate_text(bg, writer_factory())
        except (GenerationError, LLMUnavailable) as e:
            _state["error"] = str(e)
        except Exception as e:  # keep the session usable whatever happens
            _state["error"] = f"Unerwarteter Fehler: {e}"
        finally:
            bg.close()
            _state["generating"] = False

    th = threading.Thread(target=run, daemon=True)
    th.start()
    if wait:
        th.join()
    return text_status(conn)


# Session sizes by length. The extra time goes where it helps most: more cards, an extra recall
# round, more drills, and a speaking task (output), keeping the four strands roughly balanced.
SIZES = {
    20: {"review": 40, "rounds": 2, "drills": 8, "speak": False},
    30: {"review": 60, "rounds": 3, "drills": 12, "speak": True},
    40: {"review": 80, "rounds": 3, "drills": 16, "speak": True},
}


def size_for(minutes: int) -> tuple[int, dict]:
    m = min(SIZES, key=lambda k: abs(k - minutes))
    return m, SIZES[m]


def plan(conn: sqlite3.Connection, mode: str = "full") -> dict:
    due = srs.due_count(conn)
    minutes, size = size_for(conn.execute("SELECT session_minutes FROM settings WHERE id = 1").fetchone()[0])
    if mode == "quick":
        steps = [{"kind": "review", "label": "Wortschatz", "limit": 20, "due": due},
                 {"kind": "drill", "label": "Grammatik", "n": 3}]
    else:
        warm = warmup_text(conn)
        steps = []
        if warm:
            steps.append({"kind": "warmup", "label": "Aufwärmen", "text_id": warm["id"], "title": warm["title"]})
        steps += [
            {"kind": "review", "label": "Wortschatz", "limit": size["review"], "due": due},
            {"kind": "text", "label": "Neuer Text"},
            {"kind": "newwords", "label": "Neue Wörter", "rounds": size["rounds"]},
            {"kind": "drill", "label": "Grammatik", "n": size["drills"]},
            {"kind": "write", "label": "Schreiben"},
        ]
        if size["speak"]:
            steps.append({"kind": "speak", "label": "Sprechen"})
    return {"mode": mode, "minutes": minutes if mode == "full" else 5, "steps": steps, **text_status(conn)}
