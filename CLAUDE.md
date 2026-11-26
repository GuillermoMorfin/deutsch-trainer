# Deutsch-Trainer: notes for Claude Code

Spec: `docs/PLAN.md` (summary of the original plan). Build one phase at a time.

## Hard rules
- Never store or reproduce Kursbuch/Arbeitsbuch texts or exercises. Only lesson structure,
  word lists and exercise *labels*. All reading texts are newly generated.
- No assumed knowledge: texts and drills may use only unlocked grammar (`grammar_point.unlocked = 1`)
  and known/target lemmas. `BLOCK_*` points are never unlocked automatically.
- Nouns always carry der/die/das (enforced by a CHECK constraint and `validate_lemma_row`).
  Typed noun answers are wrong without the right article; wrong umlaut is wrong unless
  `settings.umlaut_ascii_ok` and the learner typed ae/oe/ue.
- Grammar notes follow rule → bridge (English or Spanish, whichever fits) → example → warning.
- Personal anchors for texts: Berlin-Mitte, ESMT / MAAI programme, running and marathon
  training, cycling, partner and friends; recurring character Marco.
- UI: cream/amber tokens in `static/styles.css` plus the 'warm & modern' layer in `static/theme.css`
  (rings, icons via `icon()`, flip cards, skeletons, confetti; respects reduced motion). Lora + DM Sans,
  `color-scheme: only light`, mobile first, vanilla JS (no build step). No greeting on the home screen.

## Layout
- `app/main.py` FastAPI routes; `app/db.py` sqlite helpers; `app/seed.py` idempotent seeding.
- Vocabulary ladder (`app/ladder.py`, state in `known_word.ladder_step/ladder_correct`): new words enter ONLY
  through reader texts (`srs.introduce_word` → step 1; no bare new cards; default cap 5/day). Steps: 2 MC DE→EN,
  3 MC EN→DE (a wrong-article variant is always a distractor), 4 cloze from the source sentence + first letter,
  5 typed EN→DE with article. 2 correct → up; a miss → down one step, never below 2. Steps 2-3 repeat in-session;
  steps 4-5 are one FSRS card (`card.direction = 'produce'`). Known = step 5 + stability ≥ 7 days. Old
  'recognise' cards are kept but never scheduled; `migrate_to_ladder` ran once on existing DBs.
- `app/srs.py` FSRS (py-fsrs 6) for steps 4-5 + everyday checks. A1 words are never demoted. Times in DB are UTC.
- `app/practice.py`: rotating formats (match, listen = hear word → pick meaning, gender, plural, perfekt, cloze on
  yesterday's text), 2-3 per day, never the same set as the previous day (`practice_day`). They don't move ladder
  steps. Every format must need real German knowledge (the learner rejected 'odd one out' by lesson theme and
  sound-to-spelling matching); distractors must be plausible learner errors, not nonsense.
- Glosses are English (`settings.gloss_language`, default 'en'; `gloss_es` kept, optional). Spanish only as an
  optional bridge in grammar notes/feedback. `app/glosses.py`: cognate flag (`lemma.cognate`), missing-gloss fill.
- `app/answers.py` typed-answer checker: article required, umlaut mistakes never forgiven, small stem typos → Hard.
- `app/verifier.py` (no LLM): spaCy `de_core_news_md` lemmas + fallbacks (separable verbs via `svp`,
  plural/Partizip forms, pronoun/modal forms, strong-verb vowel swaps); targets win lookups; grammar
  checks map to `grammar_point.code`. `tests/fixtures/lesson_texts.py` holds one text per lesson that must pass.
- `app/generator.py` pipeline; `app/llm.py` is the only place that calls Claude (`Writer` protocol;
  tests use a fake writer, never the API). Default writer is `ClaudeCodeWriter` (`claude -p` on the
  learner's subscription; strips ANTHROPIC_API_KEY so it can never bill the API). The learner does not
  want to pay for API usage: keep Claude Code the default.
- `app/drills.py`: drill items are shown only if their `full_sentence` passes the verifier with the
  learner's known words + words of lessons ≤ current. Session weighting = current lesson + recent wrong
  answers + error_log + missed Grammatik exercises from book_progress. Wrong answers write `error_log`.
- Drills never show their answer before you answer: `drills.leaks()` (answer in hint or brackets, rewrite giving
  the forms to produce, order hint listing the words). Leaking items are skipped, rejected when generated, and
  the seed bank is tested. Give base forms in brackets: '(der Hund)', never '(den Hund)'.
- `app/writing.py`: tasks in `app/seed/writing_prompts.json`; feedback capped at 3 corrections; codes are
  validated against grammar_point; a word error makes that word's produce card due now.
- Texts must practise the lesson's grammar: `verifier.grammar_presence` detects each lesson point and the
  generator repairs drafts that miss it; 6 target words per text; words of unlocked grammar points
  (`GRAMMAR_WORDS`) and places/people from personal.json count as known.
- `progress.lesson_check` = the plan's per-lesson ingredients (texts read ≥ 3, words met, words known ≥ 80 %,
  grammar drilled, writing tasks); next lesson is suggested only when ready.
- Everyday deck (`app/seed/everyday.txt`, lemma.deck = 'alltag'): starts as a multiple-choice *check*;
  right → known, due in 90 days; wrong → ladder step 0 (waits for a text, up to 2 per text as targets).
  The learner asked not to be drilled on words they already know.
- Reading texts: 250-450 words (`generator.TEXT_WORDS`, enforced by the repair loop), 3-6 targets: new words
  first (within the daily cap), then words still climbing.
- `app/speaking.py` (Sprechen): a plan for talking with the partner, no microphone or grading (the learner
  asked for that after speech recognition was removed). Seed `app/seed/speaking.json`; `speaking_log` counts as activity.
- `app/session.py` plans the daily flow and writes the day's text in a background thread with its own
  DB connection; `app/progress.py` computes streak (local days), mastery, errors, WPM.
- `get_db` opens one sqlite connection per request; never share a connection across threads.
- Seed text (Redemittel, drills, fixtures) must pass the verifier at its lesson; tests enforce this.
- `static/` front end (hash router in `app.js`), served by FastAPI; `sw.js` at root scope.
- Tests: `uv run pytest`. Each test gets its own DB via `TRAINER_DB`.
