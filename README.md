# Deutsch-Trainer

My own app for learning German. I'm at A2.1 and working through the *Momente A2.1* textbook, and I wanted one place that
gives me reading I can actually follow, brings back the words I'm learning at the right time, and drills the grammar of the
lesson I'm on. So I built it. It runs on my laptop and I use it in the browser.

## What it does

- **Lesen (reading):** a new short story every day, written for me by Claude with about 98% words I already know, so only a
  few are new. Before I see it, a checker makes sure it only uses vocabulary and grammar from lessons I've done, and has it
  rewritten if not (up to 3 times). I can tap any word for its meaning, listen to the text and answer a few questions.
- **Karten (vocabulary):** new words come from the texts, then climb a ladder: recognise the meaning, pick the German word with
  the right article, fill a gap with the first letter given, then type it. The FSRS algorithm decides when each word comes
  back. Small games mix it up: match pairs, der/die/das sorting, plurals, Perfekt with *hat* or *ist*.
- **Grammatik (drills):** gap, multiple-choice and word-order exercises for each lesson's grammar, 176 written by hand and more
  generated and checked by the app. My mistakes are logged and come back more often.
- **Schreiben (writing):** three short writing tasks per lesson. Claude corrects them lightly and explains at most three
  things, the lesson's grammar first.
- **Hören and Sprechen (listening and speaking):** listening playlists with natural offline voices, and a new conversation plan
  every day for practising with a partner: questions to ask, a short role play and words to use.
- **Daily session:** one button starts a 20, 30 or 40 minute session that mixes all of the above, and *Quick 5* is there for
  busy days. A progress page shows my streak, the words I know, my most common mistakes and my reading speed.
- **Spickzettel:** a cheat sheet for der/den/dem, mich/mir and prepositions.

## How it works

The back end is Python (FastAPI and SQLite) and the front end is plain JavaScript that can be installed like an app. Texts,
corrections and new exercises come from Claude: by default through the Claude Code command line on my Mac, so they use my
existing Claude subscription and I don't need an API key. spaCy's German model checks every text against what I've learned,
FSRS schedules the reviews, and Piper reads German aloud offline.

The teaching choices follow language-learning research: Paul Nation's four strands (a balance of reading, writing, focused
practice and fluency), reading texts at 96–98% known words, and writing feedback limited to a few points at a time. The plan
I started from is in [`docs/PLAN.md`](docs/PLAN.md).

There are about 170 automated tests. One kind I like: every example sentence, exercise and conversation plan may only use
grammar that its lesson has already unlocked, and the tests fail if one doesn't.

## Run it

You need [uv](https://docs.astral.sh/uv/) and, for new texts and corrections, Claude Code installed and signed in.

```bash
uv sync                                    # install the dependencies (first time, or after changes)
uv run uvicorn app.main:app --port 8000    # start the app
```

Then open <http://localhost:8000>. Stop it with Ctrl+C. The database (`data/trainer.db`) is created and filled on the first
start. To run the tests: `uv run pytest`.

<details>
<summary>Settings</summary>

Set these as environment variables or in a `.env` file.

| variable | default | what it does |
|---|---|---|
| `TRAINER_WRITER` | `claude-code` | who writes texts and corrections: the Claude Code CLI, or `api` for the Anthropic API |
| `TRAINER_CC_GEN_MODEL` | `sonnet` | Claude Code model for texts, corrections and exercises |
| `TRAINER_CC_GLOSS_MODEL` | `haiku` | Claude Code model for word meanings |
| `TRAINER_CC_TIMEOUT` | `300` | seconds to wait for Claude Code |
| `ANTHROPIC_API_KEY` | | needed only with `TRAINER_WRITER=api` (paid per use) |
| `TRAINER_GEN_MODEL` | `claude-sonnet-5-5` | API model for texts, corrections and exercises |
| `TRAINER_GLOSS_MODEL` | `claude-haiku-5-5` | API model for word meanings |
| `TRAINER_DB` | `data/trainer.db` | where the database lives |

Personal context for the stories (names, places, interests) is in `app/seed/personal.json`.

</details>

<details>
<summary>Where the content comes from</summary>

- `app/seed/lessons.json`: the 12 lessons of Momente A2.1 with their grammar and useful phrases (Redemittel).
- `app/seed/grammar_points.json`: each grammar point as rule, bridge, example and warning, plus structures that aren't
  allowed yet and that the checker must reject.
- `app/seed/a1_core.csv`: the A1 words I started with.
- `app/seed/lessons/_source.txt`: the A2.1 vocabulary (headwords from the Momente workbook's word list, meanings written
  fresh). `python3 scripts/build_wordlists.py` turns it into one `L<nn>.csv` file per lesson.
- `app/seed/drills.json`: the hand-written exercises. Each one must pass the checker at its lesson.
- `app/seed/writing_prompts.json`: three writing tasks per lesson.
- `app/seed/speaking.json`: the first conversation plan for each lesson. After that, a new plan is written every day.
- `app/seed/book_exercises.json`: names of the textbook's exercises (names only), so missed ones can boost their lesson.

To import your own word list for a lesson: `uv run python -m app.seed --import words.csv --lesson 3`

</details>

<details>
<summary>Adding Momente A2.2 (or another book)</summary>

The app is driven by its data, so a new book is mostly new data:

1. Add lessons 13–24 to `app/seed/lessons.json` with `"book": "A2.2"`, their grammar and Redemittel.
2. Add their grammar points to `app/seed/grammar_points.json` (`"lesson": 13`, and so on).
3. Add `@13` … `@24` blocks to `app/seed/lessons/_source.txt` and run `python3 scripts/build_wordlists.py`.
4. Optional: writing tasks in `writing_prompts.json` (lessons without them get general tasks from their Redemittel) and
   exercises in `drills.json` (or generate them in the app).
5. Restart the server. Seeding can run again safely and keeps your progress.

</details>

<details>
<summary>Voices, word meanings, review tuning and Quizlet</summary>

**Voices.** Reading aloud uses Piper, an open-source voice that runs offline. The voices aren't in git; on a new machine:

```bash
uv run python -m piper.download_voices --download-dir data/voices de_DE-thorsten-high de_DE-kerstin-low
```

Without them the app uses the browser's voices. Spoken sentences are cached in `data/tts_cache`.

**Word meanings.** Meanings are in English by default, and words that look alike in both languages (Haus/house) get a small
*cognate* badge. Spanish is available in the settings. `uv run python -m app.glosses` fills in missing meanings.

**Review tuning.** After 512 reviews, *Einstellungen → Wiederholungsplan anpassen* fits the FSRS scheduler to my own
history. It needs `uv sync --extra optimizer` (installs PyTorch). From the command line: `uv run python -m app.optimize`.

**Quizlet.** Any lesson's words, or all the words I'm learning, can be copied or downloaded for Quizlet from the lesson page
or *Wörter*.

</details>
