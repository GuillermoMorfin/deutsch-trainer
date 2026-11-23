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

## Who writes the texts

By default the app calls the local **Claude Code** CLI (`claude -p`, headless, no tools, run from an empty
temp folder), so texts use your existing Claude subscription: no API key, no extra bill. Claude Code must
be installed and signed in on this Mac. Models: `TRAINER_CC_GEN_MODEL` (default `sonnet`) and
`TRAINER_CC_GLOSS_MODEL` (default `haiku`).

Optional: `TRAINER_WRITER=api` plus `ANTHROPIC_API_KEY` in `.env` switches to the paid Anthropic API.
Personal story context lives in `app/seed/personal.json`.

## Data

- `data/trainer.db`: SQLite, created and seeded on first start (git-ignored).
- `app/seed/lessons.json`: the 12 lessons, grammar codes and Redemittel.
- `app/seed/grammar_points.json`: every grammar point as rule → bridge → example → warning,
  plus `BLOCK_*` structures the verifier must reject.
- `app/seed/a1_core.csv`: starter known-word list (A1).
- `app/seed/lessons/_source.txt`: A2.1 lesson vocabulary (headwords from the Momente AB Lernwortschatz, glosses written fresh). Rebuild the `L<nn>.csv` files with `python3 scripts/build_wordlists.py`.
- `app/seed/drills.json`: hand-written starter drills, ≥ 6 per A2.1 grammar point (each must pass the verifier at its lesson).
- `app/seed/book_exercises.json`: exercise labels from the Momente course backups (labels only).

Import a word list: `uv run python -m app.seed --import words.csv --lesson 3`

## Build phases

1. ✅ Foundation: schema, seeds, lesson/word browser, design tokens, PWA shell
2. ✅ Vocab SRS: FSRS cards, recognise (reveal + self-rate) → produce (typed, article + umlaut checked)
3. ✅ Reader + verifier: Claude (via Claude Code, Sonnet) writes → spaCy verifier checks coverage + blocked grammar → up to 3 repairs → Haiku glosses new words → tap-to-gloss reader, audio, comprehension questions
4. ✅ Grammar drills + error log: gap / choice / word-order items (109 hand-written, more via Claude Code, all verifier-checked), error-weighted sessions, rule → bridge → example → warning feedback, missed book exercises boost their lesson
5. ✅ Writing feedback: 3 tasks per lesson, Claude Code corrects minimally, max 3 points (lesson grammar first) with Spanish explanations, word diff, errors feed drills and word cards
6. ✅ Daily session + progress + audio: one-button 20-min flow (warm-up re-read → cards → new text → new-word recall → drills → writing; the text is prepared in the background), Quick 5, progress page (streak, mastery, errors, WPM, 14-day activity), listening playlist
7. ✅ FSRS optimisation on your own reviews, Quizlet export; ready for Momente A2.2 (see below). Speaking practice was built and later removed at the learner's request (speaks with a roommate instead).

## Adding Momente A2.2 (or another book)

The app is data-driven, so a new book is just data:

1. Append lessons 13–24 to `app/seed/lessons.json` with `"book": "A2.2"`, their grammar codes and Redemittel.
2. Add their grammar points to `app/seed/grammar_points.json` (`"lesson": 13`, …) with rule → bridge → example → warning.
3. Add `@13` … `@24` blocks to `app/seed/lessons/_source.txt` and run `python3 scripts/build_wordlists.py`.
4. Optional: writing tasks in `app/seed/writing_prompts.json` (lessons without them get generic tasks from their
   Redemittel) and drills in `app/seed/drills.json` (or generate them in the app).
5. Restart the server; seeding is idempotent and keeps your progress.

The tests (`uv run pytest`) check that every Redemittel, drill and fixture only uses grammar unlocked by its lesson.

## Phase 7 extras

- **Quizlet**: copy or download any lesson's words (or all words you're learning) from the lesson page or *Wörter*.
- **FSRS optimisation**: after 512 reviews, *Einstellungen → Wiederholungsplan anpassen* fits the scheduler to your
  own history. Needs `uv sync --extra optimizer` (PyTorch). CLI: `uv run python -m app.optimize`.

## Natural voices (Piper)

Read-aloud, playlists and Hören use local neural voices (Piper, open source, offline). They live in
`data/voices` (not in git). On a new machine:

```bash
uv run python -m piper.download_voices --download-dir data/voices de_DE-thorsten-high de_DE-kerstin-low
```

Without them the app falls back to the browser's voices. Synthesised sentences are cached in `data/tts_cache`.
