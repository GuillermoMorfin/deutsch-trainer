-- Deutsch-Trainer schema. Single user, single SQLite file.
-- JSON arrays are stored as TEXT and decoded in Python.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS lesson (
    id              INTEGER PRIMARY KEY,
    number          INTEGER NOT NULL UNIQUE,          -- 1..12
    title           TEXT NOT NULL,                    -- the book's lesson title
    theme           TEXT NOT NULL,
    word_field      TEXT NOT NULL,
    grammar_points  TEXT NOT NULL DEFAULT '[]',       -- JSON list of grammar_point.code
    redemittel      TEXT NOT NULL DEFAULT '[]',       -- JSON list of short phrase patterns
    status          TEXT NOT NULL DEFAULT 'locked'
                    CHECK (status IN ('locked', 'active', 'done'))
);

CREATE TABLE IF NOT EXISTS lemma (
    id          INTEGER PRIMARY KEY,
    lemma       TEXT NOT NULL,
    pos         TEXT NOT NULL,                        -- NOUN VERB ADJ ADV ADP CONJ PRON DET NUM INTJ PHRASE
    article     TEXT CHECK (article IN ('der', 'die', 'das') OR article IS NULL),
    plural      TEXT,                                 -- full plural form, '-' if none
    aux         TEXT CHECK (aux IN ('haben', 'sein') OR aux IS NULL),  -- verbs: Perfekt auxiliary
    partizip2   TEXT,                                 -- verbs: Partizip II
    gloss_es    TEXT,
    gloss_en    TEXT,
    lesson_id   INTEGER REFERENCES lesson(id),        -- NULL = A1 base vocabulary
    source      TEXT NOT NULL DEFAULT 'manual'
                CHECK (source IN ('a1', 'glossary', 'text', 'manual')),
    UNIQUE (lemma, pos, article),
    CHECK (pos <> 'NOUN' OR article IS NOT NULL)      -- nouns always carry an article
);
CREATE INDEX IF NOT EXISTS idx_lemma_lesson ON lemma(lesson_id);
CREATE INDEX IF NOT EXISTS idx_lemma_lemma ON lemma(lemma);

CREATE TABLE IF NOT EXISTS known_word (
    lemma_id            INTEGER PRIMARY KEY REFERENCES lemma(id) ON DELETE CASCADE,
    state               TEXT NOT NULL DEFAULT 'new'
                        CHECK (state IN ('new', 'learning', 'known')),
    first_seen          TEXT NOT NULL DEFAULT (datetime('now')),
    times_seen_in_text  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS card (
    id          INTEGER PRIMARY KEY,
    lemma_id    INTEGER NOT NULL REFERENCES lemma(id) ON DELETE CASCADE,
    direction   TEXT NOT NULL CHECK (direction IN ('recognise', 'produce')),
    stability   REAL,
    difficulty  REAL,
    due         TEXT NOT NULL DEFAULT (datetime('now')),
    state       INTEGER NOT NULL DEFAULT 1,           -- py-fsrs State enum value
    step        INTEGER,
    reps        INTEGER NOT NULL DEFAULT 0,
    lapses      INTEGER NOT NULL DEFAULT 0,
    last_review TEXT,
    source_sentence TEXT,                             -- sentence the word was met in
    source_text_id  INTEGER REFERENCES text(id),
    UNIQUE (lemma_id, direction)
);
CREATE INDEX IF NOT EXISTS idx_card_due ON card(due);

CREATE TABLE IF NOT EXISTS review_log (
    id           INTEGER PRIMARY KEY,
    card_id      INTEGER NOT NULL REFERENCES card(id) ON DELETE CASCADE,
    rating       INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 4),
    answer_given TEXT,
    duration_ms  INTEGER,
    ts           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS grammar_point (
    id              INTEGER PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    lesson_id       INTEGER REFERENCES lesson(id),    -- NULL = A1 base or blocked structure
    unlocked        INTEGER NOT NULL DEFAULT 0,
    rule            TEXT,
    spanish_bridge  TEXT,                             -- English or Spanish parallel, whichever fits best
    example         TEXT,
    warning         TEXT
);

CREATE TABLE IF NOT EXISTS text (
    id                INTEGER PRIMARY KEY,
    lesson_id         INTEGER NOT NULL REFERENCES lesson(id),
    title             TEXT NOT NULL,
    body              TEXT NOT NULL,
    annotations       TEXT,                           -- JSON token annotations for tap-to-gloss
    coverage          REAL,
    target_lemma_ids  TEXT NOT NULL DEFAULT '[]',
    audio_url         TEXT,
    read_count        INTEGER NOT NULL DEFAULT 0,
    wpm_log           TEXT NOT NULL DEFAULT '[]',
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS question (
    id       INTEGER PRIMARY KEY,
    text_id  INTEGER NOT NULL REFERENCES text(id) ON DELETE CASCADE,
    type     TEXT NOT NULL CHECK (type IN ('true_false', 'multiple_choice', 'short_answer')),
    prompt   TEXT NOT NULL,
    options  TEXT,
    answer   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS writing (
    id             INTEGER PRIMARY KEY,
    lesson_id      INTEGER REFERENCES lesson(id),
    prompt         TEXT NOT NULL,
    submission     TEXT NOT NULL,
    corrected      TEXT,
    feedback_json  TEXT,
    ts             TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS error_log (
    id            INTEGER PRIMARY KEY,
    grammar_code  TEXT REFERENCES grammar_point(code),
    lemma_id      INTEGER REFERENCES lemma(id),
    example       TEXT,
    count         INTEGER NOT NULL DEFAULT 1,
    last_seen     TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (grammar_code IS NOT NULL OR lemma_id IS NOT NULL)
);

-- Exercise index from the Momente course backups (labels only, no book content).
CREATE TABLE IF NOT EXISTS book_exercise (
    id         INTEGER PRIMARY KEY,
    book       TEXT NOT NULL CHECK (book IN ('KB', 'AB')),
    lesson_id  INTEGER REFERENCES lesson(id),
    section    TEXT NOT NULL,
    label      TEXT NOT NULL,
    UNIQUE (book, section, label)
);

CREATE TABLE IF NOT EXISTS book_progress (
    lesson_id          INTEGER PRIMARY KEY REFERENCES lesson(id),
    kursbuch_done      INTEGER NOT NULL DEFAULT 0,
    arbeitsbuch_done   INTEGER NOT NULL DEFAULT 0,
    missed_exercise_ids TEXT NOT NULL DEFAULT '[]',   -- JSON list of book_exercise.id
    missed_items_note  TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    gloss_language      TEXT NOT NULL DEFAULT 'es',
    daily_new_word_cap  INTEGER NOT NULL DEFAULT 8,
    target_retention    REAL NOT NULL DEFAULT 0.9,
    session_minutes     INTEGER NOT NULL DEFAULT 20,
    current_lesson      INTEGER NOT NULL DEFAULT 1,
    umlaut_ascii_ok     INTEGER NOT NULL DEFAULT 0     -- accept "ae" for "ä" only if opted in
);
