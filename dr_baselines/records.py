from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RunRecord:
    baseline_id: str
    scenario_id: str
    condition: str
    prompt_version: str
    experiment_config_version: str
    model_adapter: str
    raw_model_response: str
    parsed_candidate_response: dict[str, Any] | None
    validation_status: str
    validation_error: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    repetition_id: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
