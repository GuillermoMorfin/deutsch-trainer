"""Fit FSRS parameters to the learner's own review history (plan phase 7).

Needs the optional extra:  uv sync --extra optimizer   (installs PyTorch)
CLI:                        uv run python -m app.optimize
"""

from __future__ import annotations

import json
import sqlite3

from fsrs import Rating, ReviewLog

from . import srs
from .db import connect, transaction

MIN_REVIEWS = 512   # below this py-fsrs returns the default parameters anyway


def review_logs(conn: sqlite3.Connection) -> list[ReviewLog]:
    return [ReviewLog(card_id=r["card_id"], rating=Rating(r["rating"]), review_datetime=srs.from_db(r["ts"]),
                      review_duration=r["duration_ms"])
            for r in conn.execute("SELECT card_id, rating, ts, duration_ms FROM review_log ORDER BY id")]


def status(conn: sqlite3.Connection) -> dict:
    s = conn.execute("SELECT fsrs_parameters, fsrs_optimized_at, fsrs_optimized_reviews, target_retention "
                     "FROM settings WHERE id = 1").fetchone()
    try:
        import fsrs.optimizer  # noqa: F401
        from fsrs import Optimizer  # noqa: F401
        import torch  # noqa: F401
        installed = True
    except ImportError:
        installed = False
    reviews = conn.execute("SELECT COUNT(*) FROM review_log").fetchone()[0]
    return {"reviews": reviews, "min_reviews": MIN_REVIEWS, "installed": installed,
            "optimized": s["fsrs_parameters"] is not None, "optimized_at": s["fsrs_optimized_at"],
            "optimized_reviews": s["fsrs_optimized_reviews"], "target_retention": s["target_retention"],
            "ready": installed and reviews >= MIN_REVIEWS}


def optimize(conn: sqlite3.Connection, *, force: bool = False) -> dict:
    st = status(conn)
    if not st["installed"]:
        raise RuntimeError("Der Optimierer ist nicht installiert. Im Projektordner: uv sync --extra optimizer")
    if not force and st["reviews"] < MIN_REVIEWS:
        raise ValueError(f"Noch zu wenige Bewertungen: {st['reviews']} von {MIN_REVIEWS}.")
    from fsrs import Optimizer

    logs = review_logs(conn)
    optimizer = Optimizer(logs)
    params = [round(float(p), 4) for p in optimizer.compute_optimal_parameters()]
    # The retention suggestion needs review durations (the app records them; imports may not).
    suggested = None
    timed = [lg for lg in logs if lg.review_duration is not None]
    if len(timed) >= 512:
        try:
            suggested = round(float(Optimizer(timed).compute_optimal_retention(params)), 2)
        except (ValueError, RuntimeError):  # optional extra; the parameters are the main result
            suggested = None
    with transaction(conn):
        conn.execute("""UPDATE settings SET fsrs_parameters = ?, fsrs_optimized_at = ?, fsrs_optimized_reviews = ?
                        WHERE id = 1""", (json.dumps(params), srs.to_db(srs.now_utc()), len(logs)))
    return {"parameters": params, "reviews": len(logs), "suggested_retention": suggested}


def reset(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        conn.execute("UPDATE settings SET fsrs_parameters = NULL, fsrs_optimized_at = NULL, "
                     "fsrs_optimized_reviews = NULL WHERE id = 1")


if __name__ == "__main__":
    c = connect()
    result = optimize(c)
    print(f"Optimised on {result['reviews']} reviews.")
    if result["suggested_retention"]:
        print(f"Suggested target retention: {result['suggested_retention']}")
