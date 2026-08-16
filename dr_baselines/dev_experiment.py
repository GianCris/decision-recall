from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version as package_version
from itertools import combinations
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from google.genai import errors as genai_errors
from google.genai import types

from dr_bench import evaluate_discovery, load_scenario

from .baselines import BASE_TASK_PROMPT, get_baseline
from .config import ExperimentConfig
from .google_adapter import (
    LOCATION,
    MODEL_ID,
    PROJECT_ID,
    GeminiAuthenticationError,
    GeminiVertexAdapter,
)
from .output import (
    DISCOVERY_RESPONSE_JSON_SCHEMA,
    DISCOVERY_RESPONSE_MIME_TYPE,
    DISCOVERY_RESPONSE_SCHEMA_VERSION,
)
from .records import RunRecord
from .runner import run_baseline, with_structured_output_metadata

EXPERIMENT_VERSION = "dev-baselines-v0.2"
SDK_PACKAGE = "google-genai"
SDK_VERSION = "2.14.0"
DEV_SCENARIOS = tuple(f"dev-{number:03d}" for number in range(1, 13))
DEV_BASELINES = ("B0", "B1")
DEV_REPETITIONS = ("1", "2", "3")
TOTAL_CALLS = 72
PROMPT_SHA256 = hashlib.sha256(BASE_TASK_PROMPT.encode("utf-8")).hexdigest()
SCHEMA_SHA256 = hashlib.sha256(
    json.dumps(DISCOVERY_RESPONSE_JSON_SCHEMA, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
ORDER_RULE = "odd:1=B0_then_B1,2=B1_then_B0,3=B0_then_B1;even:1=B1_then_B0,2=B0_then_B1,3=B1_then_B0"
PLAN_FILENAME = "execution_plan.json"
MANIFEST_FILENAME = "experiment_manifest.json"
ATTEMPT_LIFECYCLE_FILENAME = "attempt_lifecycle.jsonl"
TRANSPORT_TIMEOUT_MS = 120_000
TRANSPORT_TIMEOUT_SECONDS = 120
TRANSPORT_ATTEMPTS = 1


class DevExperimentError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_commit_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _tracked_tree_clean() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    )
    return not result.stdout.strip()


def _validate_output_path(output_dir: Path) -> None:
    lowered = [part.lower().replace("-", "_") for part in output_dir.parts]
    if any("sealed_holdout" in part for part in lowered):
        raise DevExperimentError("sealed-holdout paths are forbidden")


def build_execution_plan() -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    index = 1
    for scenario_id in DEV_SCENARIOS:
        number = int(scenario_id.rsplit("-", 1)[1])
        for repetition_id in DEV_REPETITIONS:
            b0_first = (number % 2 == 1) == (repetition_id in {"1", "3"})
            order = ("B0", "B1") if b0_first else ("B1", "B0")
            pair_order = "B0_then_B1" if b0_first else "B1_then_B0"
            pair_id = f"{scenario_id}-rep-{repetition_id}"
            for within_pair, baseline_id in enumerate(order, 1):
                plan.append({
                    "global_call_index": index,
                    "pair_id": pair_id,
                    "scenario_id": scenario_id,
                    "repetition_id": repetition_id,
                    "baseline_id": baseline_id,
                    "condition": get_baseline(baseline_id).condition,
                    "pair_order": pair_order,
                    "order_within_pair": within_pair,
                    "native_structured_output": True,
                    "response_schema_version": DISCOVERY_RESPONSE_SCHEMA_VERSION,
                })
                index += 1
    validate_execution_plan(plan)
    return plan


def validate_execution_plan(plan: list[dict[str, Any]]) -> None:
    expected = build_execution_plan_unchecked()
    if plan != expected:
        raise DevExperimentError("execution plan differs from the frozen 72-call order")


def build_execution_plan_unchecked() -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    index = 1
    for scenario_id in DEV_SCENARIOS:
        number = int(scenario_id[-3:])
        for repetition_id in DEV_REPETITIONS:
            b0_first = (number % 2 == 1) == (repetition_id in {"1", "3"})
            order = ("B0", "B1") if b0_first else ("B1", "B0")
            pair_order = "B0_then_B1" if b0_first else "B1_then_B0"
            for position, baseline_id in enumerate(order, 1):
                plan.append({
                    "global_call_index": index,
                    "pair_id": f"{scenario_id}-rep-{repetition_id}",
                    "scenario_id": scenario_id,
                    "repetition_id": repetition_id,
                    "baseline_id": baseline_id,
                    "condition": get_baseline(baseline_id).condition,
                    "pair_order": pair_order,
                    "order_within_pair": position,
                    "native_structured_output": True,
                    "response_schema_version": DISCOVERY_RESPONSE_SCHEMA_VERSION,
                })
                index += 1
    return plan


def _manifest_design(git_sha: str, plan_sha: str) -> dict[str, Any]:
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "git_commit_sha": git_sha,
        "provider": "Google Cloud Agent Platform / Vertex",
        "project_id": PROJECT_ID,
        "location": LOCATION,
        "model_id": MODEL_ID,
        "sdk_package": SDK_PACKAGE,
        "sdk_version": SDK_VERSION,
        "api_version": "v1",
        "dev_scenario_allowlist": list(DEV_SCENARIOS),
        "baseline_allowlist": list(DEV_BASELINES),
        "repetitions": list(DEV_REPETITIONS),
        "total_planned_calls": TOTAL_CALLS,
        "prompt_sha256": PROMPT_SHA256,
        "response_schema_version": DISCOVERY_RESPONSE_SCHEMA_VERSION,
        "response_schema_sha256": SCHEMA_SHA256,
        "structured_output": {
            "native_structured_output": True,
            "response_mime_type": DISCOVERY_RESPONSE_MIME_TYPE,
        },
        "provider_default_generation": {
            key: "unset/provider-default"
            for key in (
                "temperature", "top_p", "top_k", "thinking_config", "seed",
                "penalties", "stop_sequences", "tools", "max_output_tokens",
            )
        },
        "retry_policy": {"automatic_retries": False, "max_attempts_per_plan_entry": 1},
        "transport": {
            "timeout_ms": TRANSPORT_TIMEOUT_MS,
            "timeout_seconds": TRANSPORT_TIMEOUT_SECONDS,
            "attempts": TRANSPORT_ATTEMPTS,
            "configuration_api": "google.genai.types.HttpOptions",
            "retry_configuration_api": "google.genai.types.HttpRetryOptions",
        },
        "failure_policy": {
            "invalid_response": "persist_and_continue_no_retry",
            "isolated_provider_error": "persist_and_continue_no_retry",
            "systemic_error": "persist_and_abort_no_retry",
        },
        "execution_plan_sha256": plan_sha,
        "paired_order_rule": ORDER_RULE,
        "first_position_counts": {"B0": 18, "B1": 18},
        "candidate_view_contract_version": "0.1",
        "dataset_id": "DR-Bench",
        "dataset_version": "0.1",
        "sealed_holdout_exclusion": "DEV runner permits only dev-001 through dev-012 and has no sealed-holdout dependency.",
    }


def _preflight_source(git_sha: str) -> None:
    if not _tracked_tree_clean():
        raise DevExperimentError("tracked source files contain uncommitted modifications")
    if PROMPT_SHA256 != "2ed1e0280d3108aa9f7458bc7a21d4cf9f82ad2e6c4795d2ac516fffdb5557b1":
        raise DevExperimentError("B0/B1 prompt hash differs from the frozen value")
    if DISCOVERY_RESPONSE_SCHEMA_VERSION != "discovery-response-v0.1":
        raise DevExperimentError("Discovery response schema version differs from the frozen value")
    if package_version(SDK_PACKAGE) != SDK_VERSION:
        raise DevExperimentError(f"{SDK_PACKAGE} must be exactly {SDK_VERSION}")
    if not git_sha or len(git_sha) != 40:
        raise DevExperimentError("unable to determine an exact Git commit SHA")


def prepare_experiment(output_dir: Path) -> dict[str, Any]:
    _validate_output_path(output_dir)
    if output_dir.exists():
        raise DevExperimentError("output directory already exists")
    git_sha = _git_commit_sha()
    _preflight_source(git_sha)
    plan = build_execution_plan()
    plan_bytes = _canonical_json(plan)
    plan_sha = _sha256(plan_bytes)
    manifest = {"created_at_utc": _utc_now(), **_manifest_design(git_sha, plan_sha)}
    output_dir.mkdir(parents=True)
    (output_dir / PLAN_FILENAME).write_bytes(plan_bytes)
    (output_dir / MANIFEST_FILENAME).write_bytes(_canonical_json(manifest))
    return manifest


def _load_and_validate_prepared(output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any], bytes]:
    _validate_output_path(output_dir)
    if not output_dir.is_dir():
        raise DevExperimentError("prepared output directory does not exist")
    for forbidden in (ATTEMPT_LIFECYCLE_FILENAME, "runs.jsonl", "evaluations.jsonl", "summary.json"):
        if (output_dir / forbidden).exists():
            raise DevExperimentError("prepared directory already contains execution artifacts")
    plan_bytes = (output_dir / PLAN_FILENAME).read_bytes()
    manifest = json.loads((output_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    plan = json.loads(plan_bytes)
    validate_execution_plan(plan)
    plan_sha = _sha256(plan_bytes)
    if plan_sha != manifest.get("execution_plan_sha256"):
        raise DevExperimentError("execution plan hash does not match the frozen manifest")
    git_sha = _git_commit_sha()
    _preflight_source(git_sha)
    expected = _manifest_design(git_sha, plan_sha)
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise DevExperimentError(f"experiment manifest field {key!r} differs from executable configuration")
    return plan, manifest, plan_bytes


def _experiment_config() -> ExperimentConfig:
    return with_structured_output_metadata(
        ExperimentConfig(
            version=EXPERIMENT_VERSION,
            model_name=MODEL_ID,
            repetitions=3,
            dataset_id="DR-Bench",
            dataset_version="0.1",
            scenario_ids=DEV_SCENARIOS,
            candidate_view_contract_version="0.1",
        ),
        True,
    )


def _dev_http_options() -> types.HttpOptions:
    return types.HttpOptions(
        api_version="v1",
        timeout=TRANSPORT_TIMEOUT_MS,
        retry_options=types.HttpRetryOptions(attempts=TRANSPORT_ATTEMPTS),
    )


def _dev_adapter_factory() -> GeminiVertexAdapter:
    return GeminiVertexAdapter(http_options=_dev_http_options())


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _generation_metadata() -> dict[str, Any]:
    return {
        "native_structured_output": True,
        "response_mime_type": DISCOVERY_RESPONSE_MIME_TYPE,
        "thinking_config": None,
        "temperature": None,
        "top_p": None,
        "top_k": None,
        "max_output_tokens": None,
        "retries": "disabled",
    }


def _run_metadata(entry: dict[str, Any], manifest: dict[str, Any], started: str, completed: str) -> dict[str, Any]:
    return {
        "pair_id": entry["pair_id"],
        "global_call_index": entry["global_call_index"],
        "pair_order": entry["pair_order"],
        "order_within_pair": entry["order_within_pair"],
        "started_at_utc": started,
        "completed_at_utc": completed,
        "git_commit_sha": manifest["git_commit_sha"],
        "prompt_sha256": PROMPT_SHA256,
        "response_schema_version": DISCOVERY_RESPONSE_SCHEMA_VERSION,
        "response_schema_sha256": SCHEMA_SHA256,
        "execution_plan_sha256": manifest["execution_plan_sha256"],
        "sdk_package": SDK_PACKAGE,
        "sdk_version": SDK_VERSION,
        "candidate_view_contract_version": "0.1",
        "dataset_id": "DR-Bench",
        "dataset_version": "0.1",
        "provider_identifier": "Google Cloud Agent Platform / Vertex",
        "project_id": PROJECT_ID,
        "location": LOCATION,
        "requested_model_id": MODEL_ID,
        "generation": _generation_metadata(),
        "transport": {
            "timeout_ms": TRANSPORT_TIMEOUT_MS,
            "timeout_seconds": TRANSPORT_TIMEOUT_SECONDS,
            "attempts": TRANSPORT_ATTEMPTS,
        },
    }


def _provider_error_record(entry: dict[str, Any], adapter: Any, error: Exception, latency_ms: float) -> RunRecord:
    baseline = get_baseline(entry["baseline_id"])
    config = _experiment_config()
    return RunRecord(
        baseline_id=baseline.baseline_id,
        scenario_id=entry["scenario_id"],
        condition=baseline.condition,
        prompt_version=baseline.prompt_version,
        experiment_config_version=config.version,
        model_adapter=adapter.identifier,
        raw_model_response="",
        parsed_candidate_response=None,
        validation_status="provider_error",
        provider_error=f"{type(error).__name__}: {error}",
        experiment_config=config.to_dict(),
        model_name=MODEL_ID,
        latency_ms=latency_ms,
        repetition_id=entry["repetition_id"],
    )


def _is_systemic(error: Exception) -> bool:
    if isinstance(error, (GeminiAuthenticationError, ValueError)):
        return True
    return isinstance(error, genai_errors.ClientError) and error.code in {400, 401, 403, 404}


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _aggregate(entries: list[tuple[dict[str, Any], dict[str, Any]]], scenarios: dict[str, dict[str, Any]]) -> dict[str, Any]:
    evaluations = [item[1] for item in entries]
    macro_fields = (
        "dependency_precision", "dependency_recall", "dependency_f1",
        "dependency_strength_accuracy", "still_justified_accuracy",
    )
    macro = {key: _mean([evaluation[key] for evaluation in evaluations]) for key in macro_fields}
    multi_hop = [evaluation["multi_hop_recall"] for evaluation in evaluations if evaluation["multi_hop_recall"] is not None]
    macro["multi_hop_recall"] = _mean(multi_hop)
    fp = sum(item["false_positive_dependence"] for item in evaluations)
    fn = sum(item["false_negative_dependence"] for item in evaluations)
    positives = sum(
        sum(label["materially_dependent"] for label in scenarios[entry["scenario_id"]]["private"]["decision_labels"])
        for entry, _ in entries
    )
    tp = positives - fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {
        "macro": macro,
        "micro": {
            "dependency_precision": precision,
            "dependency_recall": recall,
            "dependency_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
        },
    }


def _agreement(run_values: list[dict[str, Any]]) -> float | None:
    predictions = [
        sorted(value["parsed_candidate_response"]["decisions"], key=lambda item: item["decision_id"])
        for value in run_values
        if value["validation_status"] == "valid"
    ]
    if len(predictions) < 2:
        return None
    pairs = list(combinations(predictions, 2))
    return sum(left == right for left, right in pairs) / len(pairs)


def _diagnostics(
    evaluated: list[tuple[dict[str, Any], dict[str, Any]]],
    runs: list[dict[str, Any]],
    scenarios: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    def grouped(axis: str, value_for: Callable[[dict[str, Any]], list[Any]]) -> dict[str, Any]:
        groups: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
        for entry, evaluation in evaluated:
            for value in value_for(scenarios[entry["scenario_id"]]):
                groups.setdefault(str(value), []).append((entry, evaluation))
        return {
            key: {
                "overall": {"evaluated_runs": len(value), **_aggregate(value, scenarios)},
                "per_baseline": {
                    baseline: {
                        "evaluated_runs": len(selected),
                        **(_aggregate(selected, scenarios) if selected else {"macro": {}, "micro": {}}),
                    }
                    for baseline in DEV_BASELINES
                    for selected in ([item for item in value if item[0]["baseline_id"] == baseline],)
                },
            }
            for key, value in sorted(groups.items())
        }

    confusion = {
        "supporting_predicted_material_or_critical": 0,
        "independent_predicted_material_or_critical": 0,
        "material_or_critical_predicted_non_material": 0,
    }
    for run in runs:
        if run["validation_status"] != "valid":
            continue
        truth = {item["decision_id"]: item for item in scenarios[run["scenario_id"]]["private"]["decision_labels"]}
        for prediction in run["parsed_candidate_response"]["decisions"]:
            actual = truth[prediction["decision_id"]]["dependency_strength"]
            predicted = prediction["dependency_strength"]
            if actual == "supporting" and predicted in {"material", "critical"}:
                confusion["supporting_predicted_material_or_critical"] += 1
            if actual == "independent" and predicted in {"material", "critical"}:
                confusion["independent_predicted_material_or_critical"] += 1
            if actual in {"material", "critical"} and predicted in {"independent", "supporting"}:
                confusion["material_or_critical_predicted_non_material"] += 1
    return {
        "claim_boundary": "descriptive DEV diagnostics only; complexity differences are not causal effects",
        "hard_negative_category": grouped("hard_negative", lambda scenario: scenario["private"]["hard_negative_types"]),
        "complexity": {
            axis: grouped(axis, lambda scenario, key=axis: [scenario["complexity"][key]])
            for axis in ("agent_hops", "semantic_distance", "information_transformation", "boundary")
        },
        "dependency_confusion": confusion,
    }


def build_summary(
    plan: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    evaluated: list[tuple[dict[str, Any], dict[str, Any]]],
    scenarios: dict[str, dict[str, Any]],
    abort_reason: str | None,
    provider_invocations_started: int | None = None,
    provider_invocations_completed: int | None = None,
    interrupted_position: dict[str, Any] | None = None,
) -> dict[str, Any]:
    completed = len(runs) == TOTAL_CALLS and abort_reason is None
    per_baseline: dict[str, Any] = {}
    for baseline_id in DEV_BASELINES:
        baseline_runs = [run for run in runs if run["baseline_id"] == baseline_id]
        baseline_evaluated = [(entry, evaluation) for entry, evaluation in evaluated if entry["baseline_id"] == baseline_id]
        aggregate = _aggregate(baseline_evaluated, scenarios) if baseline_evaluated else {"macro": {}, "micro": {}}
        per_baseline[baseline_id] = {
            "evaluated_run_count": len(baseline_evaluated),
            "valid_count": sum(run["validation_status"] == "valid" for run in baseline_runs),
            "invalid_count": sum(run["validation_status"] == "invalid" for run in baseline_runs),
            "provider_error_count": sum(run["validation_status"] == "provider_error" for run in baseline_runs),
            **aggregate,
            "usage": {
                "input_tokens": sum(run["input_tokens"] for run in baseline_runs if run["input_tokens"] is not None) or None,
                "output_tokens": sum(run["output_tokens"] for run in baseline_runs if run["output_tokens"] is not None) or None,
                "latency_ms_total": sum(run["latency_ms"] for run in baseline_runs if run["latency_ms"] is not None) or None,
                "latency_ms_mean": _mean([run["latency_ms"] for run in baseline_runs if run["latency_ms"] is not None]),
            },
        }
    by_repetition = {
        repetition: {
            baseline: _aggregate(
                [(entry, evaluation) for entry, evaluation in evaluated if entry["repetition_id"] == repetition and entry["baseline_id"] == baseline],
                scenarios,
            )
            for baseline in DEV_BASELINES
        }
        for repetition in DEV_REPETITIONS
    }
    per_scenario = {
        scenario_id: {
            baseline: {
                "run_results": [
                    {
                        "global_call_index": run["global_call_index"],
                        "repetition_id": run["repetition_id"],
                        "validation_status": run["validation_status"],
                    }
                    for run in runs
                    if run["scenario_id"] == scenario_id and run["baseline_id"] == baseline
                ],
                "evaluations": [
                    {
                        "global_call_index": entry["global_call_index"],
                        "repetition_id": entry["repetition_id"],
                        "evaluation": evaluation,
                    }
                    for entry, evaluation in evaluated
                    if entry["scenario_id"] == scenario_id and entry["baseline_id"] == baseline
                ],
                "prediction_agreement": _agreement([run for run in runs if run["scenario_id"] == scenario_id and run["baseline_id"] == baseline]),
            }
            for baseline in DEV_BASELINES
        }
        for scenario_id in DEV_SCENARIOS
    }
    metrics = (
        "dependency_precision", "dependency_recall", "dependency_f1",
        "dependency_strength_accuracy", "still_justified_accuracy", "multi_hop_recall",
    )
    b1_b0 = {}
    for kind, selected_metrics in (("macro", metrics), ("micro", metrics[:3])):
        b1_b0[kind] = {
            metric: per_baseline["B1"][kind].get(metric) - per_baseline["B0"][kind].get(metric)
            if per_baseline["B1"][kind].get(metric) is not None and per_baseline["B0"][kind].get(metric) is not None else None
            for metric in selected_metrics
        }
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "experiment_status": "completed" if completed else "aborted",
        "aggregate_status": "COMPLETE" if completed else "PARTIAL / ABORTED",
        "official_result_eligible": completed,
        "planned_calls": len(plan),
        "attempted_calls": provider_invocations_started if provider_invocations_started is not None else len(runs),
        "provider_invocations_started": provider_invocations_started if provider_invocations_started is not None else len(runs),
        "completed_provider_calls": provider_invocations_completed if provider_invocations_completed is not None else sum(run["validation_status"] != "provider_error" for run in runs),
        "persisted_run_records": len(runs),
        "persisted_evaluations": len(evaluated),
        "valid_runs": sum(run["validation_status"] == "valid" for run in runs),
        "invalid_runs": sum(run["validation_status"] == "invalid" for run in runs),
        "provider_error_runs": sum(run["validation_status"] == "provider_error" for run in runs),
        "abort_reason": abort_reason,
        "last_global_call_index_attempted": (
            interrupted_position["global_call_index"]
            if interrupted_position and interrupted_position["provider_invocation_started"]
            else (runs[-1]["global_call_index"] if runs else None)
        ),
        "interrupted_position": interrupted_position,
        "per_baseline": per_baseline,
        "by_repetition": by_repetition,
        "per_scenario": per_scenario,
        "descriptive_B1_minus_B0": b1_b0,
        "diagnostics": _diagnostics(evaluated, runs, scenarios),
    }


def execute_experiment(
    output_dir: Path,
    adapter_factory: Callable[[], Any] = _dev_adapter_factory,
) -> dict[str, Any]:
    plan, manifest, _ = _load_and_validate_prepared(output_dir)
    config = _experiment_config()
    scenarios = {scenario_id: load_scenario(scenario_id) for scenario_id in DEV_SCENARIOS}
    public_scenarios = {
        scenario_id: {key: value for key, value in scenario.items() if key != "private"}
        for scenario_id, scenario in scenarios.items()
    }
    runs: list[dict[str, Any]] = []
    evaluated: list[tuple[dict[str, Any], dict[str, Any]]] = []
    abort_reason: str | None = None
    provider_invocations_started = 0
    provider_invocations_completed = 0
    interrupted_position: dict[str, Any] | None = None
    lifecycle_path = output_dir / ATTEMPT_LIFECYCLE_FILENAME
    adapter = adapter_factory()
    try:
        for entry in plan:
            started_at = _utc_now()
            started = perf_counter()
            lifecycle_stage = "planned"
            try:
                _append_jsonl(lifecycle_path, {
                    **entry,
                    "event": "provider_invocation_started",
                    "timestamp_utc": started_at,
                })
                provider_invocations_started += 1
                lifecycle_stage = "provider_invocation_in_flight"
                try:
                    record = run_baseline(
                        entry["baseline_id"],
                        public_scenarios[entry["scenario_id"]],
                        adapter,
                        config,
                        repetition_id=entry["repetition_id"],
                        structured_output=True,
                    )
                except KeyboardInterrupt:
                    raise
                except Exception as error:
                    record = _provider_error_record(entry, adapter, error, (perf_counter() - started) * 1000)
                    systemic = _is_systemic(error)
                    _append_jsonl(lifecycle_path, {
                        **entry,
                        "event": "provider_invocation_failed",
                        "timestamp_utc": _utc_now(),
                        "error_type": type(error).__name__,
                    })
                else:
                    systemic = False
                    provider_invocations_completed += 1
                    lifecycle_stage = "provider_invocation_completed"
                    _append_jsonl(lifecycle_path, {
                        **entry,
                        "event": "provider_invocation_completed",
                        "timestamp_utc": _utc_now(),
                    })
                completed_at = _utc_now()
                run_value = {**asdict(record), **_run_metadata(entry, manifest, started_at, completed_at)}
                _append_jsonl(output_dir / "runs.jsonl", run_value)
                runs.append(run_value)
                lifecycle_stage = "run_record_persisted"
                _append_jsonl(lifecycle_path, {
                    **entry,
                    "event": "run_record_persisted",
                    "timestamp_utc": _utc_now(),
                })
                if record.validation_status == "valid" and record.parsed_candidate_response is not None:
                    evaluation = evaluate_discovery(scenarios[entry["scenario_id"]], record.parsed_candidate_response)
                    evaluation_value = asdict(evaluation)
                    _append_jsonl(output_dir / "evaluations.jsonl", {
                        "global_call_index": entry["global_call_index"],
                        "pair_id": entry["pair_id"],
                        "scenario_id": entry["scenario_id"],
                        "baseline_id": entry["baseline_id"],
                        "repetition_id": entry["repetition_id"],
                        "evaluation": evaluation_value,
                    })
                    evaluated.append((entry, evaluation_value))
                    lifecycle_stage = "evaluation_persisted"
                    _append_jsonl(lifecycle_path, {
                        **entry,
                        "event": "evaluation_persisted",
                        "timestamp_utc": _utc_now(),
                    })
                if systemic:
                    abort_reason = record.provider_error
                    break
            except KeyboardInterrupt:
                abort_reason = "operator_interrupt"
                interrupted_position = {
                    "global_call_index": entry["global_call_index"],
                    "scenario_id": entry["scenario_id"],
                    "repetition_id": entry["repetition_id"],
                    "baseline_id": entry["baseline_id"],
                    "condition": entry["condition"],
                    "pair_id": entry["pair_id"],
                    "pair_order": entry["pair_order"],
                    "order_within_pair": entry["order_within_pair"],
                    "timestamp_utc": _utc_now(),
                    "interruption_type": "KeyboardInterrupt",
                    "abort_reason": "operator_interrupt",
                    "lifecycle_stage": lifecycle_stage,
                    "provider_invocation_started": lifecycle_stage != "planned",
                }
                _append_jsonl(lifecycle_path, {**interrupted_position, "event": "experiment_interrupted"})
                break
    finally:
        if hasattr(adapter, "close"):
            adapter.close()
    summary = build_summary(
        plan,
        runs,
        evaluated,
        scenarios,
        abort_reason,
        provider_invocations_started,
        provider_invocations_completed,
        interrupted_position,
    )
    (output_dir / "summary.json").write_bytes(_canonical_json(summary))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen 72-call B0/B1 DEV baseline experiment")
    parser.add_argument("--output-dir", type=Path, required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--prepare", action="store_true", help="write and freeze the zero-call execution plan")
    action.add_argument("--execute", action="store_true", help="execute an existing prepared plan")
    args = parser.parse_args(argv)
    try:
        if args.prepare:
            manifest = prepare_experiment(args.output_dir)
            print(json.dumps(manifest, sort_keys=True))
            return 0
        if args.execute:
            summary = execute_experiment(args.output_dir)
            print(json.dumps(summary, sort_keys=True))
            return 3 if summary["experiment_status"] == "aborted" else 0
        print("Refusing to prepare or execute without an explicit action flag.", file=sys.stderr)
        return 2
    except (DevExperimentError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"DEV experiment refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
