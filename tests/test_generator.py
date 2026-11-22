import json
import re

import pytest

from app import generator, srs
from app.db import connect
from app.llm import Draft, GenerationError, Gloss, Question
from app.seed import seed_all


def targets_from_prompt(prompt: str) -> list[tuple[str, str | None]]:
    block = prompt.split("TARGET WORDS", 1)[1].split("\n\n", 1)[0]
    out = []
    for line in block.splitlines():
        m = re.match(r"- (?:(der|die|das) )?(\S+) \(", line)
        if m:
            out.append((m.group(2), m.group(1)))
    return out


def good_body(prompt: str) -> str:
    sentences = []
    for lemma, article in targets_from_prompt(prompt):
        for _ in range(3):
            if article:
                sentences.append(f"Das ist {article} {lemma}.")
            elif lemma[0].islower() and lemma.endswith(("en", "ern", "eln")):
                sentences.append(f"Ich möchte heute {lemma}.")
            else:
                sentences.append(f"Das ist sehr {lemma}.")
    return " ".join(sentences + ["Marco ist heute in Berlin. Wir sind zusammen im Park."])


class FakeWriter:
    def __init__(self, bad_drafts: int = 1, always_bad: bool = False):
        self.bad_drafts, self.always_bad = bad_drafts, always_bad
        self.prompts: list[str] = []

    def write(self, system, prompt):
        self.prompts.append(prompt)
        body = good_body(prompt)
        if self.always_bad or len(self.prompts) <= self.bad_drafts:
            body += " Das ist der Mann, der Quatsch macht."
        return Draft(title="Ein Tag mit Marco", body=body, summary="Marco spends a day in Berlin.")

    def questions(self, system, prompt):
        return [Question(type="true_false", prompt="Marco ist in Berlin.", options=["richtig", "falsch"],
                         answer="richtig"),
                Question(type="short_answer", prompt="Wo ist Marco?", options=[], answer="Er ist in Berlin.")]

    def gloss(self, prompt):
        return [Gloss(lemma="Quatsch", pos="NOUN", article="der", plural="-", aux="", partizip2="",
                      gloss_es="tonterías", gloss_en="nonsense")]


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    seed_all(c)
    return c


def test_repair_loop_fixes_unknown_words_and_blocked_grammar(conn):
    w = FakeWriter(bad_drafts=1)
    result = generator.generate_text(conn, w, seed=1)
    assert result.attempts == 2
    assert "Quatsch" in w.prompts[1] and "BLOCK_RELATIVSATZ" in w.prompts[1]
    assert result.report.coverage >= 0.96 and result.report.grammar == []
    t = conn.execute("SELECT * FROM text WHERE id = ?", (result.text_id,)).fetchone()
    assert t["title"] == "Ein Tag mit Marco" and t["summary"]
    tokens = json.loads(t["annotations"])
    targets = set(json.loads(t["target_lemma_ids"]))
    assert len(targets) == 4
    assert sum(1 for tok in tokens if tok.get("target")) >= 12
    assert conn.execute("SELECT COUNT(*) FROM question WHERE text_id = ?", (result.text_id,)).fetchone()[0] == 2


def test_prompt_contains_lists_and_personal_context(conn):
    w = FakeWriter(bad_drafts=0)
    generator.generate_text(conn, w, seed=2)
    p = w.prompts[0]
    assert "KNOWN WORDS" in p and "das Fahrrad" in p
    assert "FORBIDDEN GRAMMAR" in p and "Relative clauses" in p
    assert "ESMT" in p and "Marco" in p
    assert "Lektion 1" in p


def test_questions_with_blocked_grammar_are_retried_then_dropped(conn):
    class BadQuestions(FakeWriter):
        calls = 0

        def questions(self, system, prompt):
            BadQuestions.calls += 1
            good = Question(type="true_false", prompt="Marco ist in Berlin.", options=["richtig", "falsch"],
                            answer="richtig")
            bad = Question(type="short_answer", prompt="Was lernt die Person, die erzählt?", options=[],
                           answer="Du lernst Deutsch.")
            return [good, bad]

    w = BadQuestions(bad_drafts=0)
    result = generator.generate_text(conn, w, seed=8)
    assert BadQuestions.calls == 2  # one retry with feedback
    prompts = [r[0] for r in conn.execute("SELECT prompt FROM question WHERE text_id = ?", (result.text_id,))]
    assert prompts == ["Marco ist in Berlin."]


def test_gives_up_after_three_repairs(conn):
    w = FakeWriter(always_bad=True)
    with pytest.raises(GenerationError):
        generator.generate_text(conn, w, seed=3)
    assert len(w.prompts) == 1 + generator.MAX_REPAIRS
    assert conn.execute("SELECT COUNT(*) FROM text").fetchone()[0] == 0


def test_second_text_in_series_sees_the_first(conn):
    w = FakeWriter(bad_drafts=0)
    generator.generate_text(conn, w, seed=4)
    generator.generate_text(conn, w, seed=5)
    assert "Ein Tag mit Marco: Marco spends a day in Berlin." in w.prompts[-1]


def test_finish_reading_puts_targets_into_srs_with_sentence(conn):
    result = generator.generate_text(conn, FakeWriter(bad_drafts=0), seed=6)
    out = generator.finish_reading(conn, result.text_id, seconds=60)
    assert out["introduced"] == 4 and out["wpm"] > 0
    cards = conn.execute("SELECT * FROM card WHERE source_text_id = ?", (result.text_id,)).fetchall()
    assert len(cards) == 4 and all(c["source_sentence"].startswith("Das ist") or "möchte" in c["source_sentence"]
                                   for c in cards)
    # reading again doesn't duplicate cards
    assert generator.finish_reading(conn, result.text_id)["introduced"] == 0


def test_targets_prefer_least_seen_words(conn):
    first = {t["id"] for t in generator.select_targets(conn, 1, n=4, seed=1)}
    conn.executemany("INSERT INTO known_word (lemma_id, state, times_seen_in_text) VALUES (?, 'learning', 3)",
                     [(i,) for i in first])
    second = {t["id"] for t in generator.select_targets(conn, 1, n=4, seed=1)}
    assert not first & second


def test_api_flow_with_fake_writer(client):
    from app.main import app, get_writer
    app.dependency_overrides[get_writer] = lambda: FakeWriter(bad_drafts=0)
    try:
        r = client.post("/api/texts/generate", json={}).json()
        text = client.get(f"/api/texts/{r['text_id']}").json()
        assert text["tokens"] and text["questions"] and "answer" not in text["questions"][0]
        tid = next(t["id"] for t in text["tokens"] if t.get("id"))
        assert str(tid) in {str(k) for k in text["lemmas"]}
        q = text["questions"][0]
        assert client.post(f"/api/questions/{q['id']}/check", json={"answer": "Richtig"}).json()["correct"]
        assert client.post(f"/api/texts/{r['text_id']}/finish", json={"seconds": 40}).json()["introduced"] == 4
        assert len(client.get("/api/texts", params={"lesson": 1}).json()) == 1
    finally:
        app.dependency_overrides.clear()


def test_generate_without_claude_code_is_503(client, monkeypatch):
    import app.llm as llm
    monkeypatch.setattr(llm, "find_claude_cli", lambda: None)
    r = client.post("/api/texts/generate", json={})
    assert r.status_code == 503 and "Claude Code" in r.json()["detail"]
    assert client.get("/api/llm/status").json()["configured"] is False


FAKE_CLI = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
schema = json.loads(args[args.index("--json-schema") + 1])
prompt = sys.stdin.read()
log = {"args": args, "prompt": prompt, "has_key": "ANTHROPIC_API_KEY" in os.environ, "cwd": os.getcwd()}
open(os.environ["FAKE_CLI_LOG"], "w").write(json.dumps(log))
if "body" in schema["properties"]:
    out = {"title": "T", "body": "Das ist gut.", "summary": "s"}
else:
    out = {"items": []}
print(json.dumps({"type": "result", "is_error": False, "structured_output": out, "result": ""}))
"""


def test_claude_code_writer_runs_cli_safely(tmp_path, monkeypatch):
    from app.llm import ClaudeCodeWriter
    cli = tmp_path / "claude"
    cli.write_text(FAKE_CLI)
    cli.chmod(0o755)
    log = tmp_path / "log.json"
    monkeypatch.setenv("FAKE_CLI_LOG", str(log))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    draft = ClaudeCodeWriter(cli=str(cli)).write("SYS", "PROMPT über Berlin")
    assert draft.body == "Das ist gut."
    seen = json.loads(log.read_text())
    assert seen["prompt"] == "PROMPT über Berlin"           # prompt goes via stdin
    assert seen["has_key"] is False                          # never bills the API
    assert "--tools" in seen["args"] and seen["args"][seen["args"].index("--tools") + 1] == ""
    assert "German app" not in seen["cwd"]                   # runs outside the project


def test_claude_code_error_becomes_generation_error(tmp_path):
    from app.llm import ClaudeCodeWriter
    cli = tmp_path / "claude"
    cli.write_text("#!/bin/sh\necho '{\"is_error\": true, \"result\": \"usage limit reached\"}'\n")
    cli.chmod(0o755)
    with pytest.raises(GenerationError, match="usage limit"):
        ClaudeCodeWriter(cli=str(cli)).write("S", "P")


def test_word_state_override(client):
    wid = client.get("/api/words", params={"q": "Jubiläum"}).json()["items"][0]["id"]
    assert client.put(f"/api/words/{wid}/state", json={"state": "known"}).status_code == 200
    assert client.get("/api/words", params={"q": "Jubiläum"}).json()["items"][0]["state"] == "known"
