from __future__ import annotations

from dataclasses import replace
from typing import Any

from dr_bench import candidate_view

from .baselines import get_baseline
from .config import ExperimentConfig
from .models import ModelAdapter
from .output import (
    DISCOVERY_RESPONSE_JSON_SCHEMA,
    DISCOVERY_RESPONSE_MIME_TYPE,
    DISCOVERY_RESPONSE_SCHEMA_VERSION,
    OutputValidationError,
    parse_discovery_response,
)
from .records import RunRecord


def with_structured_output_metadata(
    config: ExperimentConfig,
    enabled: bool,
) -> ExperimentConfig:
    keys = {"native_structured_output", "response_mime_type", "response_schema_version"}
    retained = tuple(item for item in config.generation_config if item[0] not in keys)
    metadata = (
        ("native_structured_output", enabled),
        ("response_mime_type", DISCOVERY_RESPONSE_MIME_TYPE if enabled else None),
        ("response_schema_version", DISCOVERY_RESPONSE_SCHEMA_VERSION if enabled else None),
    )
    return replace(config, generation_config=retained + metadata)


def run_baseline(
    baseline_id: str,
    scenario: dict[str, Any],
    adapter: ModelAdapter,
    config: ExperimentConfig,
    repetition_id: str | None = None,
    structured_output: bool = False,
) -> RunRecord:
    """Create the permitted view before any baseline or adapter receives input."""
    baseline = get_baseline(baseline_id)
    visible = candidate_view(scenario, phase="discovery", condition=baseline.condition)
    prompt = baseline.build_prompt(visible)
    effective_config = with_structured_output_metadata(config, structured_output)
    if structured_output:
        response = adapter.generate(prompt, effective_config, response_schema=DISCOVERY_RESPONSE_JSON_SCHEMA)
    else:
        response = adapter.generate(prompt, effective_config)
    decision_ids = [item["id"] for item in visible["decisions"]]
    try:
        parsed = parse_discovery_response(response.text, decision_ids)
        status, error = "valid", None
    except OutputValidationError as exc:
        parsed, status, error = None, "invalid", str(exc)
    return RunRecord(
        baseline_id=baseline.baseline_id, scenario_id=visible["id"], condition=baseline.condition,
        prompt_version=baseline.prompt_version, experiment_config_version=effective_config.version,
        model_adapter=adapter.identifier, raw_model_response=response.text,
        parsed_candidate_response=parsed, validation_status=status, validation_error=error,
        experiment_config=effective_config.to_dict(),
        model_name=response.model_name or effective_config.model_name,
        model_version=response.model_version or effective_config.model_version,
        latency_ms=response.latency_ms, input_tokens=response.input_tokens,
        output_tokens=response.output_tokens, repetition_id=repetition_id,
    )
