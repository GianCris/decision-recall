from __future__ import annotations

from typing import Any

from dr_bench import candidate_view

from .baselines import get_baseline
from .config import ExperimentConfig
from .models import ModelAdapter
from .output import OutputValidationError, parse_discovery_response
from .records import RunRecord


def run_baseline(
    baseline_id: str,
    scenario: dict[str, Any],
    adapter: ModelAdapter,
    config: ExperimentConfig,
    repetition_id: str | None = None,
) -> RunRecord:
    """Create the permitted view before any baseline or adapter receives input."""
    baseline = get_baseline(baseline_id)
    visible = candidate_view(scenario, phase="discovery", condition=baseline.condition)
    prompt = baseline.build_prompt(visible)
    response = adapter.generate(prompt, config)
    decision_ids = [item["id"] for item in visible["decisions"]]
    try:
        parsed = parse_discovery_response(response.text, decision_ids)
        status, error = "valid", None
    except OutputValidationError as exc:
        parsed, status, error = None, "invalid", str(exc)
    return RunRecord(
        baseline_id=baseline.baseline_id, scenario_id=visible["id"], condition=baseline.condition,
        prompt_version=baseline.prompt_version, experiment_config_version=config.version,
        model_adapter=adapter.identifier, raw_model_response=response.text,
        parsed_candidate_response=parsed, validation_status=status, validation_error=error,
        experiment_config=config.to_dict(),
        model_name=response.model_name or config.model_name,
        model_version=response.model_version or config.model_version,
        latency_ms=response.latency_ms, input_tokens=response.input_tokens,
        output_tokens=response.output_tokens, repetition_id=repetition_id,
    )
