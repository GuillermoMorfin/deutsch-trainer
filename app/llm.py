"""Claude calls used by the reader pipeline. Everything model-facing lives here so the
pipeline can be tested with a fake writer (see tests/test_generator.py)."""

from __future__ import annotations

import os
from typing import Literal, Protocol

import anthropic
from pydantic import BaseModel, Field

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


class Writer(Protocol):
    def write(self, system: str, prompt: str) -> Draft: ...
    def questions(self, system: str, prompt: str) -> list[Question]: ...
    def gloss(self, prompt: str) -> list[Gloss]: ...


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
