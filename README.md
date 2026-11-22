# Deutsch-Trainer

Personal web app for Momente A2.1: personalised reading texts at ~98 % known words,
FSRS-scheduled vocabulary, lesson-scoped grammar drills and short writing feedback.

## Run

```bash
uv sync
uv run uvicorn app.main:app --port 8000          # http://localhost:8000
uv run pytest
```

To open it on your phone on home Wi-Fi, start it with `--host 0.0.0.0` and visit
`http://<laptop-ip>:8000`, then "Add to Home Screen".

## Data

- `data/trainer.db`: SQLite, created and seeded on first start (git-ignored).
- `app/seed/lessons.json`: the 12 lessons, grammar codes and Redemittel.
- `app/seed/grammar_points.json`: every grammar point as rule → bridge → example → warning,
  plus `BLOCK_*` structures the verifier must reject.
- `app/seed/a1_core.csv`: starter known-word list (A1).
- `app/seed/lessons/_source.txt`: A2.1 lesson vocabulary (headwords from the Momente AB Lernwortschatz, glosses written fresh). Rebuild the `L<nn>.csv` files with `python3 scripts/build_wordlists.py`.
- `app/seed/book_exercises.json`: exercise labels from the Momente course backups (labels only).

Import a word list: `uv run python -m app.seed --import words.csv --lesson 3`

## Build phases

1. ✅ Foundation: schema, seeds, lesson/word browser, design tokens, PWA shell
2. Vocab SRS (py-fsrs, recognise + produce cards, article checking)
3. Reader + verifier (Claude generation → spaCy coverage check → repair loop)
4. Grammar drills + error log
5. Writing feedback
6. Daily session + progress dashboard + audio
