# Deutsch-Trainer plan (summary)

Source: "Deutsch-Trainer — App Plan for Claude Code", 22 Nov 2026.

**Learner:** A2.1, DeutschAkademie, redoing Momente A2.1 KB + AB. Native Spanish, fluent English.

**Research → features:** Four Strands balance (read, write, drill, fluency re-read); extensive
reading is the spine; texts at 96–98 % known lemmas (max ~1 new word per 30); FSRS spacing with
2–3 in-session reps for new words; recognition card (DE→ES) first, production (ES→DE, typed,
article required) after 2 correct recalls; narrow reading (3–5 texts per lesson theme,
recurring characters); written corrective feedback (max 3 points, target grammar first).

**Depth before breadth:** next lesson unlocks at ~80 % of current lesson words stable.
Current lesson is set manually to match class (auto-advance is optional later).

**Pipeline:** select 3–6 targets + 5–10 due review words → Claude (Sonnet) generates 150–350
words, each target 3+ times → spaCy `de_core_news_md` verifies coverage (names/numbers excluded)
and blocked structures → repair loop up to 3× (reject < 95 %) → annotate (Haiku glosses,
article/plural, grammar tags) and write 4–6 comprehension questions → cache.

**Daily loop (~20 min):** warm-up re-read with WPM (2) · due cards ≤ 40 (5) · new text +
questions (6) · new words 2–3 recalls (2) · grammar drill 6–10 items weighted by error log (3)
· one writing prompt (2–3). "Quick 5" = reviews + 3 drill items.

**Phases:** 1 Foundation · 2 Vocab SRS · 3 Reader + verifier (done when a Lektion 3 text arrives
at ≥ 96 % with no blocked grammar) · 4 Drills + error log · 5 Writing · 6 Session + progress +
audio · 7 Later: speaking, FSRS optimisation, A2.2, Quizlet export.

**Tests asked for:** verifier coverage maths, separable verb lemma matching (baut … auf →
aufbauen), one fixture text per lesson that must pass.
