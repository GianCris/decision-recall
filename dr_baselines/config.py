from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int | None = None
    retryable_error_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExperimentConfig:
    """Versioned fields to freeze before a real experiment; values are intentionally unset."""

    version: str = "0.1"
    model_name: str | None = None
    model_version: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    retry_policy: RetryPolicy = RetryPolicy()
    repetitions: int | None = None
    dataset_id: str | None = None
    dataset_version: str | None = None
    scenario_ids: tuple[str, ...] = ()
    candidate_view_contract_version: str | None = None
    generation_config: tuple[tuple[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
