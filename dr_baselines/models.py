from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .config import ExperimentConfig


@dataclass(frozen=True)
class ModelResponse:
    text: str
    model_name: str | None = None
    model_version: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModelAdapter(Protocol):
    @property
    def identifier(self) -> str: ...

    def generate(self, prompt: str, config: ExperimentConfig) -> ModelResponse: ...


class DeterministicMockAdapter:
    """Fixed-response adapter for tests; it performs no network or model calls."""

    identifier = "deterministic-mock-v0.1"

    def __init__(self, response_text: str):
        self.response_text = response_text
        self.prompts: list[str] = []

    def generate(self, prompt: str, config: ExperimentConfig) -> ModelResponse:
        self.prompts.append(prompt)
        return ModelResponse(text=self.response_text)
