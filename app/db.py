"""SQLite access. One file, one user; plain sqlite3 keeps it easy to inspect and back up."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

APP_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = APP_DIR / "schema.sql"
DEFAULT_DB_PATH = APP_DIR.parent / "data" / "trainer.db"


def db_path() -> Path:
    return Path(os.environ.get("TRAINER_DB", DEFAULT_DB_PATH))


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path) if path else db_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# Columns added after the first release; CREATE TABLE IF NOT EXISTS doesn't add them to old DBs.
MIGRATIONS = [
    ("text", "summary", "TEXT"),
    ("text", "report_json", "TEXT"),
    ("lesson", "book", "TEXT NOT NULL DEFAULT 'A2.1'"),
    ("writing", "kind", "TEXT NOT NULL DEFAULT 'write'"),
    ("settings", "fsrs_parameters", "TEXT"),              # JSON list of 21 floats once optimised
    ("settings", "fsrs_optimized_at", "TEXT"),
    ("settings", "fsrs_optimized_reviews", "INTEGER"),
    ("lemma", "deck", "TEXT"),                            # 'alltag' = everyday words for life in Germany
    ("lemma", "deck_order", "INTEGER"),
    ("card", "mode", "TEXT"),                             # 'check' until the first answer, then 'checked'/'learn'
    ("card", "created_at", "TEXT"),
    ("settings", "everyday_per_day", "INTEGER NOT NULL DEFAULT 10"),   # max NEW everyday words per day
    ("text", "kind", "TEXT NOT NULL DEFAULT 'read'"),     # 'read' (reader) or 'listen' (Hören tasks)
    # vocabulary ladder (app/ladder.py): NULL = not on the ladder, 0 = waiting for a text, 1-5 = step
    ("known_word", "ladder_step", "INTEGER"),
    ("known_word", "ladder_correct", "INTEGER NOT NULL DEFAULT 0"),   # correct answers at the current step
    ("known_word", "ladder_since", "TEXT"),                           # when a text introduced the word
    ("known_word", "source_sentence", "TEXT"),
    ("known_word", "source_text_id", "INTEGER"),
    ("lemma", "cognate", "INTEGER NOT NULL DEFAULT 0"),               # English cognate (Haus/house)
]


def _allow_rewrite_drills(conn: sqlite3.Connection) -> None:
    """drill_item's CHECK constraint gained 'rewrite'. SQLite can't alter a CHECK, so rebuild the table
    (same columns, same ids) once for databases created before that."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'drill_item'").fetchone()
    if row is None or "'rewrite'" in row[0]:
        return
    new_sql = row[0].replace("'order')", "'order', 'rewrite')").replace("CREATE TABLE drill_item", "CREATE TABLE drill_item_new", 1)
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        conn.execute(new_sql)
        conn.execute("INSERT INTO drill_item_new SELECT * FROM drill_item")
        conn.execute("DROP TABLE drill_item")
        conn.execute("ALTER TABLE drill_item_new RENAME TO drill_item")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def init_schema(conn: sqlite3.Connection) -> None:
    _allow_rewrite_drills(conn)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    before_ladder = "ladder_step" not in {r[1] for r in conn.execute("PRAGMA table_info(known_word)")}
    for table, column, decl in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")
    if before_ladder:   # one-time: move existing cards onto the ladder, switch glosses to English
        from .ladder import migrate_to_ladder
        migrate_to_ladder(conn)
    conn.commit()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


JSON_FIELDS = {"grammar_points", "redemittel", "target_lemma_ids", "wpm_log",
               "options", "feedback_json", "missed_exercise_ids", "annotations", "report_json"}


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in JSON_FIELDS & d.keys():
        if isinstance(d[k], str):
            d[k] = json.loads(d[k])
    return d


def rows_to_dicts(rows) -> list[dict]:
    return [row_to_dict(r) for r in rows]
