"""Claude calls used by the reader pipeline. Everything model-facing lives here so the
pipeline can be tested with a fake writer (see tests/test_generator.py)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, Protocol

import anthropic
from pydantic import BaseModel, Field

# Which backend writes the texts:
#   "claude-code" (default): the local Claude Code CLI, i.e. the learner's existing Claude subscription.
#   "api": the paid Anthropic API (needs ANTHROPIC_API_KEY).
WRITER = os.environ.get("TRAINER_WRITER", "claude-code")
CC_GEN_MODEL = os.environ.get("TRAINER_CC_GEN_MODEL", "sonnet")
CC_GLOSS_MODEL = os.environ.get("TRAINER_CC_GLOSS_MODEL", "haiku")
CC_TIMEOUT = int(os.environ.get("TRAINER_CC_TIMEOUT", "300"))

GEN_MODEL = os.environ.get("TRAINER_GEN_MODEL", "claude-sonnet-5-5")      # texts, repairs, questions
GLOSS_MODEL = os.environ.get("TRAINER_GLOSS_MODEL", "claude-haiku-5-5")   # glosses for new words
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMUnavailable(RuntimeError):
    """No credentials configured, or the key was rejected."""


class GenerationError(RuntimeError):
    pass


# ---- structured outputs -------------------------------------------------------------

class Draft(BaseModel):
    title: str = Field(description="Short German title, max 6 words")
    body: str = Field(description="The German text. Paragraphs separated by a blank line.")
    summary: str = Field(description="One English sentence summarising what happens, for continuity")


class Question(BaseModel):
    type: Literal["true_false", "multiple_choice", "short_answer"]
    prompt: str = Field(description="The question in simple German")
    options: list[str] = Field(description="['richtig', 'falsch'] for true_false; 3-4 options for "
                                           "multiple_choice; [] for short_answer")
    answer: str = Field(description="The correct option exactly as written, or a short model answer")


class QuestionSet(BaseModel):
    questions: list[Question]


class Gloss(BaseModel):
    lemma: str = Field(description="Dictionary form without article (nouns capitalised)")
    pos: Literal["NOUN", "VERB", "ADJ", "ADV", "ADP", "CONJ", "PRON", "DET", "NUM", "INTJ"]
    article: Literal["der", "die", "das", ""] = Field(description="Nouns only, else ''")
    plural: str = Field(description="Full plural form for nouns, '-' if none, '' for non-nouns")
    aux: Literal["haben", "sein", ""] = Field(description="Perfekt auxiliary for verbs, else ''")
    partizip2: str = Field(description="Partizip II for verbs, else ''")
    gloss_es: str = Field(description="Short Spanish translation (Spain/LatAm neutral)")
    gloss_en: str = Field(description="Short English translation")


class GlossSet(BaseModel):
    items: list[Gloss]


class DrillItemModel(BaseModel):
    type: Literal["gap", "choice", "order", "rewrite"]
    prompt: str = Field(description="gap/choice: sentence with ___ ; order: the fixed start of the sentence")
    options: list[str] = Field(description="choice: 2-4 options; otherwise []")
    answers: list[str] = Field(description="gap/choice: accepted answers (choice: exactly one option); "
                                           "rewrite: the full correct sentence(s); order: []")
    order_answers: list[str] = Field(description="order: each accepted solution as the remaining words separated "
                                                 "by single spaces, no final punctuation; otherwise []")
    hint: str = Field(description="Short German hint, may be ''")
    explanation: str = Field(description="One English sentence: why this answer is right")


class DrillSet(BaseModel):
    items: list[DrillItemModel]


class Correction(BaseModel):
    original: str = Field(description="The learner's wrong words, copied exactly (a few words, not the whole sentence)")
    corrected: str = Field(description="The corrected words")
    grammar_code: str = Field(description="One code from GRAMMAR CODES that this error belongs to, or '' if none fits")
    lemma: str = Field(description="For a vocabulary, gender/article or spelling error: the dictionary form of the word "
                                   "(nouns without article). Otherwise ''")
    explanation: str = Field(description="One short sentence in Spanish: the rule, with the correct form")


class WritingFeedback(BaseModel):
    corrected_text: str = Field(description="The learner's text with only the necessary corrections (keep their words "
                                            "and style; do not rewrite or make it more advanced)")
    corrections: list[Correction] = Field(description="At most 3, most important first; the lesson's target grammar first")
    more_errors: int = Field(description="How many further, smaller errors were corrected but not listed")
    praise: str = Field(description="One short, specific, encouraging sentence in simple German")


class Writer(Protocol):
    def write(self, system: str, prompt: str) -> Draft: ...
    def questions(self, system: str, prompt: str) -> list[Question]: ...
    def gloss(self, prompt: str) -> list[Gloss]: ...
    def drills(self, system: str, prompt: str) -> list[DrillItemModel]: ...
    def feedback(self, system: str, prompt: str) -> WritingFeedback: ...


# ---- Claude implementation -----------------------------------------------------------

class ClaudeWriter:
    def __init__(self, client: anthropic.Anthropic | None = None):
        if client is None:
            if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                raise LLMUnavailable(
                    "Kein Anthropic-API-Schlüssel gefunden. Lege ANTHROPIC_API_KEY in der Datei .env an "
                    "(siehe .env.example) und starte den Server neu.")
            client = anthropic.Anthropic()
        self.client = client

    def _parse_gen(self, system: str, prompt: str, fmt: type[BaseModel]) -> BaseModel:
        """Sonnet call with server-side refusal fallback and a cached system prompt."""
        try:
            response = self.client.beta.messages.parse(
                model=GEN_MODEL,
                max_tokens=16000,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}],
                output_format=fmt,
            )
        except anthropic.AuthenticationError as e:
            raise LLMUnavailable("Der API-Schlüssel wurde abgelehnt. Bitte in .env prüfen.") from e
        except anthropic.APIConnectionError as e:
            raise GenerationError("Keine Verbindung zur Claude API.") from e
        except anthropic.RateLimitError as e:
            raise GenerationError("Rate limit erreicht, bitte gleich nochmal versuchen.") from e
        except anthropic.APIStatusError as e:
            raise GenerationError(f"Claude API Fehler {e.status_code}: {e.message}") from e
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise GenerationError(f"Claude hat keine gültige Antwort geliefert (stop_reason={response.stop_reason}).")
        return response.parsed_output

    def write(self, system: str, prompt: str) -> Draft:
        return self._parse_gen(system, prompt, Draft)

    def questions(self, system: str, prompt: str) -> list[Question]:
        return self._parse_gen(system, prompt, QuestionSet).questions

    def drills(self, system: str, prompt: str) -> list[DrillItemModel]:
        return self._parse_gen(system, prompt, DrillSet).items

    def feedback(self, system: str, prompt: str) -> WritingFeedback:
        return self._parse_gen(system, prompt, WritingFeedback)

    def gloss(self, prompt: str) -> list[Gloss]:
        try:
            response = self.client.messages.parse(
                model=GLOSS_MODEL,
                max_tokens=4000,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": prompt}],
                output_format=GlossSet,
            )
        except anthropic.APIError as e:
            raise GenerationError(f"Glossen konnten nicht erstellt werden: {e}") from e
        if response.stop_reason == "refusal" or response.parsed_output is None:
            return []
        return response.parsed_output.items


# ---- Claude Code CLI implementation (no API key, uses the existing subscription) -----------

def find_claude_cli() -> str | None:
    return shutil.which("claude") or next(
        (str(p) for p in (Path.home() / ".local/bin/claude", Path("/opt/homebrew/bin/claude")) if p.exists()), None)


class ClaudeCodeWriter:
    """Runs `claude -p` headless with structured output. No tools, no project files, no MCP:
    the call can only return JSON matching the schema."""

    def __init__(self, cli: str | None = None):
        self.cli = cli or find_claude_cli()
        if not self.cli:
            raise LLMUnavailable("Claude Code wurde nicht gefunden. Installiere es oder melde dich mit "
                                 "`claude` im Terminal an, dann den Server neu starten.")

    def _run(self, prompt: str, schema: dict, *, model: str, system: str) -> dict:
        env = {k: v for k, v in os.environ.items()
               # never let a key in the environment switch this to paid API billing
               if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
        cmd = [self.cli, "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
               "--model", model, "--tools", "", "--system-prompt", system,
               "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"]
        with tempfile.TemporaryDirectory() as cwd:  # empty folder: no CLAUDE.md, no project context
            try:
                proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                      timeout=CC_TIMEOUT, cwd=cwd, env=env)
            except subprocess.TimeoutExpired as e:
                raise GenerationError("Claude Code hat zu lange gebraucht.") from e
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            msg = (proc.stderr or proc.stdout).strip()[:300]
            if "login" in msg.lower() or "auth" in msg.lower():
                raise LLMUnavailable(f"Claude Code ist nicht angemeldet: {msg}")
            raise GenerationError(f"Claude Code Fehler: {msg or 'keine Ausgabe'}")
        if out.get("is_error") or out.get("structured_output") is None:
            raise GenerationError(f"Claude Code: {str(out.get('result') or out.get('subtype'))[:300]}")
        return out["structured_output"]

    def write(self, system: str, prompt: str) -> Draft:
        return Draft.model_validate(self._run(prompt, Draft.model_json_schema(), model=CC_GEN_MODEL, system=system))

    def questions(self, system: str, prompt: str) -> list[Question]:
        data = self._run(prompt, QuestionSet.model_json_schema(), model=CC_GEN_MODEL, system=system)
        return QuestionSet.model_validate(data).questions

    def drills(self, system: str, prompt: str) -> list[DrillItemModel]:
        data = self._run(prompt, DrillSet.model_json_schema(), model=CC_GEN_MODEL, system=system)
        return DrillSet.model_validate(data).items

    def feedback(self, system: str, prompt: str) -> WritingFeedback:
        data = self._run(prompt, WritingFeedback.model_json_schema(), model=CC_GEN_MODEL, system=system)
        return WritingFeedback.model_validate(data)

    def gloss(self, prompt: str) -> list[Gloss]:
        try:
            data = self._run(prompt, GlossSet.model_json_schema(), model=CC_GLOSS_MODEL,
                             system="You write concise bilingual dictionary entries for German words.")
            return GlossSet.model_validate(data).items
        except GenerationError:
            return []  # glosses are a nice-to-have; the text is still usable


def default_writer() -> Writer:
    return ClaudeWriter() if WRITER == "api" else ClaudeCodeWriter()
