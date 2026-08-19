from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any, Callable

from dr_bench import candidate_view, load_scenario

from .config import ExperimentConfig
from .dev_experiment import (
    DELIVERY_BACKOFF_SECONDS, DELIVERY_POLICY_VERSION, INTER_CALL_DELAY_SECONDS,
    LOCATION, MAX_DELIVERY_ATTEMPTS, MODEL_ID, PROJECT_ID, SDK_PACKAGE, SDK_VERSION,
    TRANSPORT_ATTEMPTS, TRANSPORT_TIMEOUT_MS, TRANSPORT_TIMEOUT_SECONDS,
    _append_jsonl, _dev_adapter_factory, run_delivery_attempts,
)
from .runner import with_structured_output_metadata
from .round_b import (
    ARTIFACT_ENVELOPE_VERSION, DECISION_SUPPORT_JSON_SCHEMA,
    DECISION_SUPPORT_SCHEMA_VERSION, NEUTRAL_GROUNDED_CONTEXT_JSON_SCHEMA,
    NEUTRAL_GROUNDED_CONTEXT_SCHEMA_VERSION, PROMPT_HASHES, PROJECTION_FIELDS,
    PROTOCOL_COMMIT, PROTOCOL_SHA256, PROTOCOL_VERSION, RoundBError,
    IntermediateValidationError, _canonical_json, _git_branch, _git_sha,
    _stage1_schema, _tracked_clean, build_artifact_envelope,
    build_stage1_projection, build_stage1_prompt, protocol_sha256, schema_sha256,
    validate_decision_support, validate_frozen_constants,
    validate_neutral_grounded_context,
)

SANITY_EXPERIMENT_VERSION = "round-b-stage1-interface-sanity-v0.2"
SANITY_MANIFEST_TYPE = "round-b-stage1-interface-sanity-manifest-v0.2"
FULL_SCREENING_MANIFEST_TYPE = "round-b-screening-manifest-v0.2"
SANITY_PLAN_FILENAME = "sanity_execution_plan.json"
SANITY_MANIFEST_FILENAME = "sanity_manifest.json"
SANITY_DELIVERY_FILENAME = "sanity_delivery_attempts.jsonl"
SANITY_SCENARIOS = ("dev-001", "dev-005", "dev-006")
SANITY_SCHEDULE = (
    ("dev-001", "RC0_GENERIC_STAGE1"),
    ("dev-001", "SHARED_RECONSTRUCTION_STAGE1"),
    ("dev-005", "SHARED_RECONSTRUCTION_STAGE1"),
    ("dev-005", "RC0_GENERIC_STAGE1"),
    ("dev-006", "RC0_GENERIC_STAGE1"),
    ("dev-006", "SHARED_RECONSTRUCTION_STAGE1"),
)


def _sanity_config() -> ExperimentConfig:
    return with_structured_output_metadata(ExperimentConfig(
        version=SANITY_EXPERIMENT_VERSION, model_name=MODEL_ID, repetitions=1,
        dataset_id="DR-Bench", dataset_version="0.1", scenario_ids=SANITY_SCENARIOS,
        candidate_view_contract_version="0.1",
        generation_config=(("delivery_policy_version", DELIVERY_POLICY_VERSION),),
    ), True)


def build_sanity_plan() -> list[dict[str, Any]]:
    plan = [{
        "global_sanity_index": index, "scenario_id": scenario_id,
        "repetition_id": "1", "stage_id": stage_id,
        "condition_id": "RC0" if stage_id == "RC0_GENERIC_STAGE1" else "SHARED_RECONSTRUCTION",
        "observation_kind": "intermediate", "protocol_version": PROTOCOL_VERSION,
    } for index, (scenario_id, stage_id) in enumerate(SANITY_SCHEDULE, 1)]
    validate_sanity_plan(plan)
    return plan


def validate_sanity_plan(plan: list[dict[str, Any]]) -> None:
    if len(plan) != 6 or [x.get("global_sanity_index") for x in plan] != list(range(1, 7)):
        raise RoundBError("sanity plan must contain six contiguous Stage-1 observations")
    if [(x.get("scenario_id"), x.get("stage_id")) for x in plan] != list(SANITY_SCHEDULE):
        raise RoundBError("sanity plan differs from the frozen six-call schedule")
    if any(x.get("observation_kind") != "intermediate" for x in plan):
        raise RoundBError("sanity cannot contain Stage-2 observations")
    if Counter(x["stage_id"] for x in plan) != Counter({"RC0_GENERIC_STAGE1": 3, "SHARED_RECONSTRUCTION_STAGE1": 3}):
        raise RoundBError("sanity must contain three observations per Stage-1 condition")


def _manifest(git_sha: str, branch: str, plan_sha: str, created_at: str) -> dict[str, Any]:
    projection_definition = {"top_level_fields": list(PROJECTION_FIELDS), "source": "frozen implicit candidate view", "scenario_id_source": "id"}
    return {
        "manifest_type": SANITY_MANIFEST_TYPE,
        "experiment_version": SANITY_EXPERIMENT_VERSION,
        "full_screening_experiment_version": "round-b-screening-v0.2",
        "full_screening_manifest_type": FULL_SCREENING_MANIFEST_TYPE,
        "protocol_version": PROTOCOL_VERSION, "protocol_sha256": protocol_sha256(),
        "source_protocol_commit": PROTOCOL_COMMIT, "git_commit_sha": git_sha,
        "branch": branch, "created_at_utc": created_at,
        "scenario_ids": list(SANITY_SCENARIOS), "planned_observations": 6,
        "execution_plan_sha256": plan_sha,
        "stage1_visible_projection": projection_definition,
        "stage1_visible_projection_definition_sha256": hashlib.sha256(_canonical_json(projection_definition)).hexdigest(),
        "artifact_envelope_version": ARTIFACT_ENVELOPE_VERSION,
        "rc0_payload_version": NEUTRAL_GROUNDED_CONTEXT_SCHEMA_VERSION,
        "rc0_schema_sha256": schema_sha256(NEUTRAL_GROUNDED_CONTEXT_JSON_SCHEMA),
        "reconstruction_payload_version": DECISION_SUPPORT_SCHEMA_VERSION,
        "reconstruction_schema_sha256": schema_sha256(DECISION_SUPPORT_JSON_SCHEMA),
        "prompt_hashes": PROMPT_HASHES,
        "provider": "Google Cloud Agent Platform / Vertex", "project_id": PROJECT_ID,
        "location": LOCATION, "model_id": MODEL_ID, "sdk_package": SDK_PACKAGE,
        "sdk_version": SDK_VERSION,
        "transport": {"timeout_ms": TRANSPORT_TIMEOUT_MS, "timeout_seconds": TRANSPORT_TIMEOUT_SECONDS,
            "sdk_attempts": TRANSPORT_ATTEMPTS, "max_delivery_attempts": MAX_DELIVERY_ATTEMPTS,
            "backoff_seconds": list(DELIVERY_BACKOFF_SECONDS),
            "inter_scientific_slot_delay_seconds": INTER_CALL_DELAY_SECONDS,
            "jitter": False, "concurrency": 1, "first_model_response_wins": True,
            "delivery_policy_version": DELIVERY_POLICY_VERSION},
        "status_precedence": ["ABORTED", "FAIL / INTERFACE", "INCOMPLETE / INFRASTRUCTURE", "PASS"],
        "stage2_authorized": False, "discovery_evaluation_authorized": False,
        "artifact_reuse_authorized": False, "sealed_holdout_excluded": True,
    }


def prepare_sanity(output_dir: Path) -> dict[str, Any]:
    if output_dir.exists():
        raise RoundBError("sanity output directory already exists")
    validate_frozen_constants()
    if not _tracked_clean():
        raise RoundBError("tracked worktree is not clean")
    plan_bytes = _canonical_json(build_sanity_plan())
    manifest = _manifest(_git_sha(), _git_branch(), hashlib.sha256(plan_bytes).hexdigest(), datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    output_dir.mkdir(parents=True)
    (output_dir / SANITY_PLAN_FILENAME).write_bytes(plan_bytes)
    (output_dir / SANITY_MANIFEST_FILENAME).write_bytes(_canonical_json(manifest))
    return manifest


def _load_prepared_sanity(output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not output_dir.is_dir():
        raise RoundBError("prepared sanity directory does not exist")
    if (output_dir / "experiment_manifest.json").exists():
        raise RoundBError("full-screening manifest cannot be used for sanity")
    if any((output_dir / name).exists() for name in (SANITY_DELIVERY_FILENAME, "stage1_raw.jsonl", "stage1_artifacts.jsonl", "terminal_states.jsonl", "summary.json")):
        raise RoundBError("sanity directory contains execution artifacts; resume is not authorized")
    plan_bytes = (output_dir / SANITY_PLAN_FILENAME).read_bytes()
    plan = json.loads(plan_bytes); validate_sanity_plan(plan)
    manifest = json.loads((output_dir / SANITY_MANIFEST_FILENAME).read_text(encoding="utf-8"))
    expected = _manifest(_git_sha(), _git_branch(), hashlib.sha256(plan_bytes).hexdigest(), manifest.get("created_at_utc"))
    validate_frozen_constants()
    if manifest != expected or manifest.get("manifest_type") != SANITY_MANIFEST_TYPE or not _tracked_clean():
        raise RoundBError("prepared sanity manifest/protocol/config/Git identity mismatch")
    return plan, manifest


def execute_sanity(output_dir: Path, adapter_factory: Callable[[], Any] = _dev_adapter_factory, sleep_fn: Callable[[float], None] = sleep) -> dict[str, Any]:
    plan, _ = _load_prepared_sanity(output_dir)
    adapter = adapter_factory(); terminal = []; invalid = provider_failures = responses = valid = 0
    aborted = False; interrupted = None; failure_categories: Counter[str] = Counter()
    try:
        for entry in plan:
            attempts = 0
            try:
                if entry["global_sanity_index"] > 1: sleep_fn(INTER_CALL_DELAY_SECONDS)
                scenario = load_scenario(entry["scenario_id"]); public = {k: v for k, v in scenario.items() if k != "private"}
                projection = build_stage1_projection(candidate_view(public, "discovery", "implicit"))
                prompt = build_stage1_prompt(entry["stage_id"], projection)
                delivery = run_delivery_attempts(entry, output_dir / SANITY_DELIVERY_FILENAME,
                    lambda: adapter.generate(prompt, _sanity_config(), response_schema=_stage1_schema(entry["stage_id"])),
                    sleep_fn)
                attempts = delivery["attempts_used"]; response = delivery["result"]
                if response is None:
                    provider_failures += 1
                    state = {**entry, "terminal_state": "provider_delivery_failure", "failure_category": "PROVIDER_DELIVERY_FAILURE",
                        "provider_error": f"{type(delivery['last_error']).__name__}: {delivery['last_error']}", "delivery_attempts_used": attempts}
                    _append_jsonl(output_dir / "terminal_states.jsonl", state); terminal.append(state); continue
                responses += 1
                _append_jsonl(output_dir / "stage1_raw.jsonl", {**entry, "raw_stage1_response": response.text,
                    "model_name": response.model_name or MODEL_ID, "model_version": response.model_version,
                    "latency_ms": response.latency_ms, "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens, "delivery_attempts_used": attempts})
                try:
                    canonical, encoded, digest = (validate_neutral_grounded_context(response.text, projection)
                        if entry["stage_id"] == "RC0_GENERIC_STAGE1" else validate_decision_support(response.text, projection))
                except IntermediateValidationError as exc:
                    invalid += 1; failure_categories[exc.category] += 1
                    state = {**entry, "terminal_state": "intermediate_invalid", "failure_category": exc.category,
                        "validation_error": str(exc), "delivery_attempts_used": attempts}
                else:
                    valid += 1; envelope = build_artifact_envelope(entry["scenario_id"], entry["stage_id"], encoded)
                    _append_jsonl(output_dir / "stage1_artifacts.jsonl", {**entry, "canonical_payload": canonical,
                        "canonical_bytes_utf8": encoded.decode("utf-8"), "artifact_envelope": envelope})
                    state = {**entry, "terminal_state": "intermediate_valid", "artifact_sha256": digest,
                        "delivery_attempts_used": attempts}
                _append_jsonl(output_dir / "terminal_states.jsonl", state); terminal.append(state)
            except KeyboardInterrupt:
                aborted = True; interrupted = {**entry, "terminal_state": "operator_interrupt", "delivery_attempts_used": attempts}
                _append_jsonl(output_dir / "terminal_states.jsonl", interrupted); break
    finally:
        if hasattr(adapter, "close"): adapter.close()
    if aborted: status = "ABORTED"
    elif invalid: status = "FAIL / INTERFACE"
    elif provider_failures: status = "INCOMPLETE / INFRASTRUCTURE"
    elif len(terminal) == responses == valid == 6: status = "PASS"
    else: status = "INCOMPLETE / INFRASTRUCTURE"
    summary = {"manifest_type": SANITY_MANIFEST_TYPE, "experiment_version": SANITY_EXPERIMENT_VERSION,
        "sanity_status": status, "planned_observations": 6, "terminal_observations": len(terminal),
        "model_responses": responses, "valid_payloads": valid, "model_mechanism_invalid_payloads": invalid,
        "provider_delivery_failures": provider_failures, "failure_categories": dict(sorted(failure_categories.items())),
        "aborted": aborted, "interrupted_position": interrupted, "stage2_calls": 0,
        "discovery_evaluations": 0, "pass_eligible": status == "PASS", "artifact_reuse_authorized": False}
    (output_dir / "summary.json").write_bytes(_canonical_json(summary)); return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen Round B v0.2 Stage-1 interface sanity")
    parser.add_argument("--output-dir", type=Path, required=True)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--prepare", action="store_true"); actions.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.prepare: print(json.dumps(prepare_sanity(args.output_dir), sort_keys=True)); return 0
        if args.execute: print(json.dumps(execute_sanity(args.output_dir), sort_keys=True)); return 0
        print("Refusing without explicit --prepare or --execute.", file=sys.stderr); return 2
    except (RoundBError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"Round B sanity refused: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
