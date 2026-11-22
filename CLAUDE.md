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
- UI: cream/amber tokens in `static/styles.css`, Lora + DM Sans, `color-scheme: only light`,
  mobile first, vanilla JS (no build step).

## Layout
- `app/main.py` FastAPI routes; `app/db.py` sqlite helpers; `app/seed.py` idempotent seeding.
- `app/srs.py` FSRS scheduling (py-fsrs 6): `introduce_word` creates the recognise card; 2 Good/Easy
  recognitions create the produce card; a word is `known` once both cards are in Review and the
  produce card's stability ≥ 7 days. A1 words are never demoted. Times in DB are UTC `YYYY-MM-DD HH:MM:SS`.
- `app/answers.py` typed-answer checker: article required, umlaut mistakes never forgiven,
  small stem typos → Hard. Phase 3 should call `srs.introduce_word(..., sentence=, text_id=)`.
- `app/verifier.py` (no LLM): spaCy `de_core_news_md` lemmas + fallbacks (separable verbs via `svp`,
  plural/Partizip forms, pronoun/modal forms, strong-verb vowel swaps); targets win lookups; grammar
  checks map to `grammar_point.code`. `tests/fixtures/lesson_texts.py` holds one text per lesson that must pass.
- `app/generator.py` pipeline; `app/llm.py` is the only place that calls Claude (`Writer` protocol;
  tests use a fake writer, never the API).
- `static/` front end (hash router in `app.js`), served by FastAPI; `sw.js` at root scope.
- Tests: `uv run pytest`. Each test gets its own DB via `TRAINER_DB`.
