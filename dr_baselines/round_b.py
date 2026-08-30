from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, sleep
from typing import Any, Callable

from dr_bench import candidate_view, evaluate_discovery, load_scenario

from .baselines import BASE_TASK_PROMPT
from .config import ExperimentConfig
from .dev_experiment import (
    DELIVERY_BACKOFF_SECONDS, DELIVERY_POLICY_VERSION, INTER_CALL_DELAY_SECONDS,
    LOCATION, MAX_DELIVERY_ATTEMPTS, MODEL_ID, PROJECT_ID, SDK_PACKAGE, SDK_VERSION,
    TRANSPORT_ATTEMPTS, TRANSPORT_TIMEOUT_MS, TRANSPORT_TIMEOUT_SECONDS,
    _append_jsonl, _dev_adapter_factory, run_delivery_attempts,
)
from .output import (
    DISCOVERY_RESPONSE_JSON_SCHEMA, DISCOVERY_RESPONSE_MIME_TYPE,
    DISCOVERY_RESPONSE_SCHEMA_VERSION, OutputValidationError, parse_discovery_response,
)
from .runner import with_structured_output_metadata


EXPERIMENT_VERSION = "round-b-screening-v0.2"
PROTOCOL_VERSION = "round-b-protocol-v0.2"
PROTOCOL_COMMIT = "bfa262a8b7cd4ee30f17e3445e39c14b7f9ad916"
PROTOCOL_SHA256 = "eba2cd3d3c848ca43a0c26e1eb7c23e1c5be3af6a44a218a2018bb4019c1f335"
PROTOCOL_PATH = Path("docs/ROUND_B_PROTOCOL_V0.2.md")
DEV_SCENARIOS = tuple(f"dev-{number:03d}" for number in range(1, 13))
FINAL_CONDITIONS = ("RB0", "RC0", "RR1", "RB1", "RB2", "RB3")
INTERMEDIATE_STAGES = ("RC0_GENERIC_STAGE1", "SHARED_RECONSTRUCTION_STAGE1")
TOTAL_CONCEPTUAL_CALLS = 96
TOTAL_FINAL_OUTPUTS = 72
PLAN_FILENAME = "execution_plan.json"
MANIFEST_FILENAME = "experiment_manifest.json"
DELIVERY_FILENAME = "delivery_attempts.jsonl"

RC0_STAGE1_NEUTRAL_GROUNDED_CONTEXT_INSTRUCTION = """NEUTRAL GROUNDED CONTEXT:
Using only the provided Stage1VisibleProjection, produce the required
NeutralGroundedContextPayload.

Select candidate-visible textual elements and return each selected complete
source string together with its exact JSON Pointer source_path.

Include at least one knowledge_before statement, the change statement, and at
least one decision statement. If transmissions is non-empty, include at least
one transmission content string, using the exact source-path classes required
by the frozen schema.

Do not paraphrase, summarize, shorten, rewrite, interpret, or add text.
source_text must exactly equal the complete string resolved by source_path.

Do not construct or encode change-to-prior-knowledge mappings,
knowledge/evidence-to-decision mappings, decision-specific evidence groups,
provenance, reliance, materiality, dependency strength, necessity,
sufficiency, survivability, justification, reopening, or alternative support.

Do not rank, score, weight, label relevance, or assign confidence to grounded
items.

Return only the fields required by the frozen NeutralGroundedContextPayload
schema."""

RECONSTRUCTION_STAGE1_INSTRUCTION = """DECISION SUPPORT RECONSTRUCTION:
Using only the provided Stage1VisibleProjection, produce the required
DecisionSupportRecord.

For change_alignment, identify zero or more visible knowledge_before IDs that
are plausible candidates for the prior knowledge revised by the visible
change.

For every visible decision, identify zero or more visible knowledge_before IDs
that are plausible candidates for having been informationally connected to
that decision.

Where visible transmissions provide a traceable basis for a candidate
connection, include their IDs in basis_trace_refs. basis_trace_refs may be
empty.

Return only the candidate references required by the frozen
DecisionSupportRecord schema.

Do not judge or encode whether any candidate connection is necessary,
sufficient, supporting, material, critical, decisive, essential, justified,
surviving, or grounds for reopening.

Do not identify or encode alternative support.

Do not rank, score, weight, or assign confidence to candidate references.

Do not add rationale, explanation, reasoning text, or other unrestricted
free-text fields."""

SURVIVABILITY_STAGE2_INSTRUCTION = """DECISION SURVIVABILITY:
For each decision, evaluate the counterfactual in which the changed premise is
replaced by the updated knowledge while all other still-valid information
remains available.

Classify the decision as materially dependent only if, under that
counterfactual, its remaining support is no longer sufficient to justify the
same decision.

Do not treat the mere fact that changed information participated in the
original decision as sufficient reason to reopen it."""

ALTERNATIVE_SUPPORT_STAGE2_INSTRUCTION = """ALTERNATIVE SUPPORT CHECK:
Before concluding that the counterfactual decision lacks sufficient support,
explicitly search the candidate-visible information for an independent
remaining reason or evidence source that would be sufficient to justify the
same decision without relying on the changed premise."""

PROMPT_HASHES = {
    "rc0_stage1": "e0915fb6ea21d3f6e5dc163e5e10514ab1588d954f599fdb783929c0c4c25f48",
    "reconstruction_stage1": "b691855c1d3e6240daa45b5174e66c7a18286b9c943abe034dff7b33540cd716",
    "survivability_stage2": "18c946ff305a079cc1de83baf8e01a192717fa21942bd06530573d1ec6666c2f",
    "alternative_support_stage2": "ffe28d4ba2459442f04fdac8dc0406dff8c64f093f176ee719946274170eab9e",
}

PROJECTION_FIELDS = (
    "scenario_id", "brief", "agents", "knowledge_before", "change", "transmissions",
    "decisions", "world", "consequences", "recovery_actions",
)

ARTIFACT_ENVELOPE_VERSION = "artifact-envelope-v0.2"
NEUTRAL_GROUNDED_CONTEXT_SCHEMA_VERSION = "neutral-grounded-context-payload-v0.2"
DECISION_SUPPORT_SCHEMA_VERSION = "decision-support-payload-v0.2"

NEUTRAL_GROUNDED_CONTEXT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["grounded_items"],
    "properties": {
        "grounded_items": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["source_path", "source_text"], "properties": {
                "source_path": {"type": "string", "minLength": 1}, "source_text": {"type": "string", "minLength": 1}
            }}},
    },
}

DECISION_SUPPORT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["change_alignment", "decision_connections"],
    "properties": {
        "change_alignment": {
            "type": "object", "additionalProperties": False,
            "required": ["change_ref", "candidate_prior_knowledge_refs"],
            "properties": {"change_ref": {"type": "string"}, "candidate_prior_knowledge_refs": {"type": "array", "items": {"type": "string"}}},
        },
        "decision_connections": {
            "type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["decision_id", "candidate_knowledge_refs", "basis_trace_refs"],
                "properties": {
                    "decision_id": {"type": "string"},
                    "candidate_knowledge_refs": {"type": "array", "items": {"type": "string"}},
                    "basis_trace_refs": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


class RoundBError(RuntimeError):
    pass


class IntermediateValidationError(ValueError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def protocol_sha256() -> str:
    return hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest()


def schema_sha256(schema: dict[str, Any]) -> str:
    return hashlib.sha256(_compact_json(schema).encode("utf-8")).hexdigest()


def build_artifact_envelope(scenario_id: str, stage_id: str, canonical_bytes: bytes) -> dict[str, str]:
    return {
        "artifact_schema_version": ARTIFACT_ENVELOPE_VERSION,
        "scenario_id": scenario_id,
        "stage_id": stage_id,
        "artifact_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
    }


def verify_artifact_envelope(envelope: dict[str, str], canonical_bytes: bytes) -> None:
    if hashlib.sha256(canonical_bytes).hexdigest() != envelope.get("artifact_sha256"):
        raise RoundBError("canonical Stage-1 payload does not match its out-of-band envelope")


def validate_frozen_constants() -> None:
    blocks = {
        "rc0_stage1": RC0_STAGE1_NEUTRAL_GROUNDED_CONTEXT_INSTRUCTION,
        "reconstruction_stage1": RECONSTRUCTION_STAGE1_INSTRUCTION,
        "survivability_stage2": SURVIVABILITY_STAGE2_INSTRUCTION,
        "alternative_support_stage2": ALTERNATIVE_SUPPORT_STAGE2_INSTRUCTION,
    }
    if protocol_sha256() != PROTOCOL_SHA256:
        raise RoundBError("Round B protocol SHA-256 differs from the frozen value")
    if {key: _sha_text(value) for key, value in blocks.items()} != PROMPT_HASHES:
        raise RoundBError("Round B literal prompt block differs from the frozen value")


def build_stage1_projection(implicit_view: dict[str, Any]) -> dict[str, Any]:
    if implicit_view.get("phase") != "discovery" or implicit_view.get("discovery_condition") != "implicit":
        raise RoundBError("Stage 1 requires the frozen implicit Discovery view")
    source_keys = {
        "scenario_id": "id", "brief": "brief", "agents": "agents",
        "knowledge_before": "knowledge_before", "change": "change",
        "transmissions": "transmissions", "decisions": "decisions", "world": "world",
        "consequences": "consequences", "recovery_actions": "recovery_actions",
    }
    return json.loads(json.dumps({key: implicit_view[value] for key, value in source_keys.items()}))


def projection_bytes(projection: dict[str, Any]) -> bytes:
    if tuple(projection) != PROJECTION_FIELDS:
        raise RoundBError("Stage1VisibleProjection fields differ from the frozen contract")
    return _canonical_json(projection)


def _require_exact_keys(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise IntermediateValidationError("SCHEMA_INVALID", f"{label} has an invalid field set")
    return value


def _unique_strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise IntermediateValidationError("SCHEMA_INVALID", f"{label} must be a string array")
    if len(value) != len(set(value)):
        raise IntermediateValidationError("SCHEMA_INVALID", f"{label} contains duplicates")
    return sorted(value)


def _resolve_json_pointer(projection: dict[str, Any], pointer: str) -> str:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise IntermediateValidationError("SEMANTIC_REFERENCE_INVALID", "source_path is not a frozen RFC 6901 pointer")
    current: Any = projection
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if "~" in raw.replace("~0", "").replace("~1", ""):
            raise IntermediateValidationError("SEMANTIC_REFERENCE_INVALID", "source_path contains invalid escape")
        if isinstance(current, dict):
            if token not in current:
                raise IntermediateValidationError("SEMANTIC_REFERENCE_INVALID", "source_path does not resolve")
            current = current[token]
        elif isinstance(current, list):
            if token == "-" or not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise IntermediateValidationError("SEMANTIC_REFERENCE_INVALID", "source_path has invalid array index")
            index = int(token)
            if index >= len(current):
                raise IntermediateValidationError("SEMANTIC_REFERENCE_INVALID", "source_path does not resolve")
            current = current[index]
        else:
            raise IntermediateValidationError("SEMANTIC_REFERENCE_INVALID", "source_path traverses a terminal value")
    if not isinstance(current, str):
        raise IntermediateValidationError("SEMANTIC_REFERENCE_INVALID", "source_path must resolve to a terminal string")
    return current


def validate_neutral_grounded_context(raw_text: str, projection: dict[str, Any]) -> tuple[dict[str, Any], bytes, str]:
    try:
        value = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise IntermediateValidationError("SCHEMA_INVALID", str(exc)) from exc
    if isinstance(value, dict) and set(value) & {
        "change_to_knowledge", "change_alignment", "knowledge_to_decision",
        "decision_connections", "decision_support", "provenance", "reliance",
        "materially_dependent", "dependency_strength", "necessity", "sufficiency",
        "survivability", "still_justified", "should_reopen", "must_reopen",
        "alternative_support", "alternative_support_candidates", "confidence",
        "probability", "ranking", "private_dependency_path", "oracle_labels",
    }:
        raise IntermediateValidationError("FORBIDDEN_SEMANTIC_CONTENT", "RC0 payload contains prohibited specialized semantics")
    _require_exact_keys(value, {"grounded_items"}, "NeutralGroundedContextPayload")
    items = value["grounded_items"]
    if not isinstance(items, list):
        raise IntermediateValidationError("SCHEMA_INVALID", "grounded_items must be an array")
    canonical_items = []
    for item in items:
        item = _require_exact_keys(item, {"source_path", "source_text"}, "grounded_item")
        if not isinstance(item["source_path"], str) or not isinstance(item["source_text"], str) or not item["source_path"] or not item["source_text"]:
            raise IntermediateValidationError("SCHEMA_INVALID", "grounded item values must be non-empty strings")
        resolved = _resolve_json_pointer(projection, item["source_path"])
        if resolved != item["source_text"]:
            raise IntermediateValidationError("SEMANTIC_REFERENCE_INVALID", "source_text does not exactly equal resolved source string")
        canonical_items.append({"source_path": item["source_path"], "source_text": item["source_text"]})
    paths = [item["source_path"] for item in canonical_items]
    if len(paths) != len(set(paths)):
        raise IntermediateValidationError("SCHEMA_INVALID", "grounded_items contains duplicate source_path values")
    import re
    coverage = {
        "knowledge_before": any(re.fullmatch(r"/knowledge_before/(0|[1-9][0-9]*)/statement", path) for path in paths),
        "change": "/change/statement" in paths,
        "decisions": any(re.fullmatch(r"/decisions/(0|[1-9][0-9]*)/statement", path) for path in paths),
        "transmissions": not projection["transmissions"] or any(re.fullmatch(r"/transmissions/(0|[1-9][0-9]*)/content", path) for path in paths),
    }
    if not all(coverage.values()):
        missing = ", ".join(key for key, present in coverage.items() if not present)
        raise IntermediateValidationError("SEMANTIC_COVERAGE_INVALID", f"missing mandatory semantic coverage: {missing}")
    canonical = {"grounded_items": sorted(canonical_items, key=lambda item: item["source_path"])}
    encoded = _canonical_json(canonical)
    return canonical, encoded, hashlib.sha256(encoded).hexdigest()


def validate_decision_support(raw_text: str, projection: dict[str, Any]) -> tuple[dict[str, Any], bytes, str]:
    try:
        value = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise IntermediateValidationError("SCHEMA_INVALID", str(exc)) from exc
    _require_exact_keys(value, {"change_alignment", "decision_connections"}, "DecisionSupportPayload")
    alignment = _require_exact_keys(value["change_alignment"], {"change_ref", "candidate_prior_knowledge_refs"}, "change_alignment")
    if alignment["change_ref"] != projection["change"]["id"]:
        raise IntermediateValidationError("SEMANTIC_REFERENCE_INVALID", "change_ref does not equal visible change.id")
    knowledge_ids = {item["id"] for item in projection["knowledge_before"]}
    trace_ids = {item["id"] for item in projection["transmissions"]}
    decision_ids = {item["id"] for item in projection["decisions"]}
    prior = _unique_strings(alignment["candidate_prior_knowledge_refs"], "candidate_prior_knowledge_refs")
    if not set(prior) <= knowledge_ids:
        raise IntermediateValidationError("SEMANTIC_REFERENCE_INVALID", "unknown prior knowledge reference")
    connections = value["decision_connections"]
    if not isinstance(connections, list):
        raise IntermediateValidationError("SCHEMA_INVALID", "decision_connections must be an array")
    canonical_connections = []
    for item in connections:
        item = _require_exact_keys(item, {"decision_id", "candidate_knowledge_refs", "basis_trace_refs"}, "decision_connection")
        knowledge = _unique_strings(item["candidate_knowledge_refs"], "candidate_knowledge_refs")
        traces = _unique_strings(item["basis_trace_refs"], "basis_trace_refs")
        if item["decision_id"] not in decision_ids or not set(knowledge) <= knowledge_ids or not set(traces) <= trace_ids:
            raise IntermediateValidationError("SEMANTIC_REFERENCE_INVALID", "unknown or wrong-namespace support reference")
        canonical_connections.append({"decision_id": item["decision_id"], "candidate_knowledge_refs": knowledge, "basis_trace_refs": traces})
    if len(canonical_connections) != len(decision_ids) or {item["decision_id"] for item in canonical_connections} != decision_ids:
        raise IntermediateValidationError("SCHEMA_INVALID", "decision connections must cover every decision exactly once")
    canonical = {
        "change_alignment": {"change_ref": alignment["change_ref"], "candidate_prior_knowledge_refs": prior},
        "decision_connections": sorted(canonical_connections, key=lambda item: item["decision_id"]),
    }
    encoded = _canonical_json(canonical)
    return canonical, encoded, hashlib.sha256(encoded).hexdigest()


def build_stage1_prompt(stage_id: str, projection: dict[str, Any]) -> str:
    instruction = RC0_STAGE1_NEUTRAL_GROUNDED_CONTEXT_INSTRUCTION if stage_id == "RC0_GENERIC_STAGE1" else RECONSTRUCTION_STAGE1_INSTRUCTION
    if stage_id not in INTERMEDIATE_STAGES:
        raise RoundBError("unknown Stage-1 operation")
    return instruction + "\n\nSTAGE1VISIBLEPROJECTION:\n" + projection_bytes(projection).decode("utf-8").rstrip("\n")


def stage2_instruction(condition_id: str) -> str:
    if condition_id in {"RB0", "RC0", "RR1", "RB1"}:
        return BASE_TASK_PROMPT
    if condition_id == "RB2":
        return BASE_TASK_PROMPT + "\n\n" + SURVIVABILITY_STAGE2_INSTRUCTION
    if condition_id == "RB3":
        return BASE_TASK_PROMPT + "\n\n" + SURVIVABILITY_STAGE2_INSTRUCTION + "\n\n" + ALTERNATIVE_SUPPORT_STAGE2_INSTRUCTION
    raise RoundBError("unknown final condition")


def build_stage2_prompt(condition_id: str, visible: dict[str, Any], artifact_bytes: bytes | None = None) -> str:
    prompt = stage2_instruction(condition_id) + "\n\nCANDIDATE-VISIBLE SCENARIO:\n" + _compact_json(visible)
    if condition_id in {"RC0", "RB1", "RB2", "RB3"}:
        if artifact_bytes is None:
            raise RoundBError("dependent Stage 2 requires a canonical artifact")
        prompt += "\n\nCANONICAL STAGE-1 ARTIFACT:\n" + artifact_bytes.decode("utf-8").rstrip("\n")
    elif artifact_bytes is not None:
        raise RoundBError("independent final condition cannot receive a Stage-1 artifact")
    return prompt


STAGE_SPECS = {
    "RB0_FINAL": ("RB0", "implicit", None, True, "discovery-response-v0.1"),
    "RR1_FINAL": ("RR1", "structured", None, True, "discovery-response-v0.1"),
    "RC0_GENERIC_STAGE1": ("RC0", "implicit", None, False, NEUTRAL_GROUNDED_CONTEXT_SCHEMA_VERSION),
    "RC0_STAGE2": ("RC0", "implicit", "RC0_GENERIC_STAGE1", True, "discovery-response-v0.1"),
    "SHARED_RECONSTRUCTION_STAGE1": ("SHARED_RECONSTRUCTION", "implicit", None, False, DECISION_SUPPORT_SCHEMA_VERSION),
    "RB1_STAGE2": ("RB1", "implicit", "SHARED_RECONSTRUCTION_STAGE1", True, "discovery-response-v0.1"),
    "RB2_STAGE2": ("RB2", "implicit", "SHARED_RECONSTRUCTION_STAGE1", True, "discovery-response-v0.1"),
    "RB3_STAGE2": ("RB3", "implicit", "SHARED_RECONSTRUCTION_STAGE1", True, "discovery-response-v0.1"),
}


def _scenario_stage_order(index: int) -> list[str]:
    # Both producers run first; a six-way Latin rotation then places every final
    # condition exactly twice in every final position across twelve scenarios.
    producers = ["RC0_GENERIC_STAGE1", "SHARED_RECONSTRUCTION_STAGE1"]
    if index % 2 == 0:
        producers.reverse()
    finals = ["RB0_FINAL", "RC0_STAGE2", "RR1_FINAL", "RB1_STAGE2", "RB2_STAGE2", "RB3_STAGE2"]
    offset = (index - 1) % len(finals)
    return producers + finals[offset:] + finals[:offset]


def build_execution_plan() -> list[dict[str, Any]]:
    plan = []
    global_index = 1
    for scenario_index, scenario_id in enumerate(DEV_SCENARIOS, 1):
        for within, stage_id in enumerate(_scenario_stage_order(scenario_index), 1):
            condition_id, mode, dependency, final, contract = STAGE_SPECS[stage_id]
            plan.append({
                "global_execution_index": global_index, "scenario_id": scenario_id,
                "repetition_id": "1", "stage_id": stage_id, "condition_id": condition_id,
                "candidate_view_mode": mode, "dependency_artifact_required": dependency,
                "dependency_producing_stage": dependency, "within_scenario_order": within,
                "observation_kind": "final" if final else "intermediate",
                "expected_output_contract": contract, "protocol_version": PROTOCOL_VERSION,
            })
            global_index += 1
    validate_plan(plan)
    return plan


def validate_plan(plan: list[dict[str, Any]]) -> None:
    if len(plan) != TOTAL_CONCEPTUAL_CALLS or [item.get("global_execution_index") for item in plan] != list(range(1, 97)):
        raise RoundBError("Round B plan must contain exactly 96 contiguous conceptual calls")
    if any(item.get("scenario_id") not in DEV_SCENARIOS or item.get("repetition_id") != "1" or item.get("stage_id") not in STAGE_SPECS for item in plan):
        raise RoundBError("Round B plan contains an unauthorized scenario, repetition, or stage")
    if sum(item["observation_kind"] == "final" for item in plan) != TOTAL_FINAL_OUTPUTS:
        raise RoundBError("Round B plan must contain exactly 72 final outputs")
    for scenario_index, scenario_id in enumerate(DEV_SCENARIOS, 1):
        selected = [item for item in plan if item["scenario_id"] == scenario_id]
        if [item["stage_id"] for item in selected] != _scenario_stage_order(scenario_index):
            raise RoundBError("Round B plan differs from the frozen balanced order")
        positions = {item["stage_id"]: item["within_scenario_order"] for item in selected}
        for item in selected:
            dependency = item["dependency_producing_stage"]
            if dependency and positions[dependency] >= item["within_scenario_order"]:
                raise RoundBError("dependent Stage 2 precedes its Stage-1 producer")
    if Counter(item["stage_id"] for item in plan) != Counter({stage: 12 for stage in STAGE_SPECS}):
        raise RoundBError("every Round B stage must occur exactly twelve times")


def final_position_counts(plan: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    return {condition: {str(position): sum(x["condition_id"] == condition and x["observation_kind"] == "final" and x["within_scenario_order"] == position for x in plan) for position in range(1, 9)} for condition in FINAL_CONDITIONS}


def _git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def _git_branch() -> str:
    return subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def _tracked_clean() -> bool:
    return not subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], check=True, capture_output=True, text=True).stdout.strip()


def _config() -> ExperimentConfig:
    return with_structured_output_metadata(ExperimentConfig(
        version=EXPERIMENT_VERSION, model_name=MODEL_ID, repetitions=1,
        dataset_id="DR-Bench", dataset_version="0.1", scenario_ids=DEV_SCENARIOS,
        candidate_view_contract_version="0.1",
        generation_config=(("delivery_policy_version", DELIVERY_POLICY_VERSION),),
    ), True)


def _manifest(git_sha: str, branch: str, plan_sha: str, created_at: str) -> dict[str, Any]:
    projection_definition = {"top_level_fields": list(PROJECTION_FIELDS), "source": "frozen implicit candidate view", "scenario_id_source": "id"}
    return {
        "manifest_type": "round-b-screening-manifest-v0.2",
        "experiment_version": EXPERIMENT_VERSION, "protocol_version": PROTOCOL_VERSION,
        "round_b_protocol_sha256": protocol_sha256(), "source_protocol_commit": PROTOCOL_COMMIT,
        "git_commit_sha": git_sha, "branch": branch, "created_at_utc": created_at,
        "provider": "Google Cloud Agent Platform / Vertex", "project_id": PROJECT_ID,
        "location": LOCATION, "model_id": MODEL_ID, "sdk_package": SDK_PACKAGE, "sdk_version": SDK_VERSION,
        "transport": {"timeout_ms": TRANSPORT_TIMEOUT_MS, "timeout_seconds": TRANSPORT_TIMEOUT_SECONDS, "sdk_attempts": TRANSPORT_ATTEMPTS, "max_delivery_attempts": MAX_DELIVERY_ATTEMPTS, "backoff_seconds": list(DELIVERY_BACKOFF_SECONDS), "inter_scientific_slot_delay_seconds": INTER_CALL_DELAY_SECONDS, "jitter": False, "concurrency": 1, "first_model_response_wins": True, "delivery_policy_version": DELIVERY_POLICY_VERSION},
        "dev_scenario_allowlist": list(DEV_SCENARIOS), "screening_repetitions": 1,
        "final_conditions": list(FINAL_CONDITIONS), "intermediate_stages": list(INTERMEDIATE_STAGES),
        "stage1_visible_projection": projection_definition,
        "stage1_visible_projection_definition_sha256": hashlib.sha256(_canonical_json(projection_definition)).hexdigest(),
        "artifact_envelope_version": ARTIFACT_ENVELOPE_VERSION,
        "neutral_grounded_context_schema_version": NEUTRAL_GROUNDED_CONTEXT_SCHEMA_VERSION,
        "neutral_grounded_context_schema_sha256": schema_sha256(NEUTRAL_GROUNDED_CONTEXT_JSON_SCHEMA),
        "decision_support_schema_version": DECISION_SUPPORT_SCHEMA_VERSION,
        "decision_support_schema_sha256": schema_sha256(DECISION_SUPPORT_JSON_SCHEMA),
        "prompt_versions": {"rc0_stage1": "rc0-stage1-neutral-grounded-context-v0.2", "reconstruction_stage1": "reconstruction-stage1-v0.1", "survivability_stage2": "survivability-stage2-v0.1", "alternative_support_stage2": "alternative-support-stage2-v0.1"},
        "prompt_hashes": PROMPT_HASHES,
        "base_prompt_sha256": _sha_text(BASE_TASK_PROMPT),
        "discovery_schema_version": DISCOVERY_RESPONSE_SCHEMA_VERSION,
        "discovery_schema_sha256": schema_sha256(DISCOVERY_RESPONSE_JSON_SCHEMA),
        "structured_output": {"enabled": True, "response_mime_type": DISCOVERY_RESPONSE_MIME_TYPE},
        "execution_plan_sha256": plan_sha, "conceptual_model_calls": TOTAL_CONCEPTUAL_CALLS,
        "possible_final_outputs": TOTAL_FINAL_OUTPUTS,
        "final_position_counts": final_position_counts(build_execution_plan()),
        "screening_only": True, "confirmation_authorized": False,
        "sealed_holdout_exclusion": "hard allowlist dev-001 through dev-012; no dataset path option",
    }


def prepare(output_dir: Path) -> dict[str, Any]:
    if output_dir.exists():
        raise RoundBError("output directory already exists")
    validate_frozen_constants()
    if not _tracked_clean():
        raise RoundBError("tracked worktree is not clean")
    plan_bytes = _canonical_json(build_execution_plan())
    manifest = _manifest(_git_sha(), _git_branch(), hashlib.sha256(plan_bytes).hexdigest(), datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    output_dir.mkdir(parents=True)
    (output_dir / PLAN_FILENAME).write_bytes(plan_bytes)
    (output_dir / MANIFEST_FILENAME).write_bytes(_canonical_json(manifest))
    return manifest


def _load_prepared(output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not output_dir.is_dir():
        raise RoundBError("prepared directory does not exist")
    if (output_dir / "sanity_manifest.json").exists():
        raise RoundBError("Stage-1 sanity manifest cannot be used for full screening")
    if any((output_dir / name).exists() for name in (DELIVERY_FILENAME, "stage1_raw.jsonl", "stage1_artifacts.jsonl", "terminal_states.jsonl", "runs.jsonl", "evaluations.jsonl", "summary.json")):
        raise RoundBError("prepared directory already contains execution artifacts; resume is not authorized")
    plan_bytes = (output_dir / PLAN_FILENAME).read_bytes()
    plan = json.loads(plan_bytes)
    manifest = json.loads((output_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    validate_plan(plan)
    plan_sha = hashlib.sha256(plan_bytes).hexdigest()
    expected = _manifest(_git_sha(), _git_branch(), plan_sha, manifest.get("created_at_utc"))
    validate_frozen_constants()
    if manifest != expected or not _tracked_clean():
        raise RoundBError("prepared plan/manifest/protocol/config/Git identity mismatch")
    return plan, manifest


def _stage1_schema(stage_id: str) -> dict[str, Any]:
    return NEUTRAL_GROUNDED_CONTEXT_JSON_SCHEMA if stage_id == "RC0_GENERIC_STAGE1" else DECISION_SUPPORT_JSON_SCHEMA


def _provider_error(entry: dict[str, Any], error: Exception | None, attempts: int, latency_ms: float) -> dict[str, Any]:
    return {**entry, "validation_status": "provider_error", "provider_error": f"{type(error).__name__}: {error}", "delivery_attempts_used": attempts, "latency_ms": latency_ms, "input_tokens": None, "output_tokens": None, "raw_model_response": "", "parsed_candidate_response": None}


def execute(output_dir: Path, adapter_factory: Callable[[], Any] = _dev_adapter_factory, sleep_fn: Callable[[float], None] = sleep) -> dict[str, Any]:
    plan, manifest = _load_prepared(output_dir)
    adapter = adapter_factory()
    artifacts: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}
    failed_dependencies: set[tuple[str, str]] = set()
    runs: list[dict[str, Any]] = []
    terminal: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []
    provider_failures = intermediate_failures = blocked = 0
    aborted = False
    interrupted = None
    try:
        for entry in plan:
            dependency = entry["dependency_artifact_required"]
            key = (entry["scenario_id"], dependency) if dependency else None
            if key and key in failed_dependencies:
                state = {**entry, "terminal_state": "downstream_blocked", "upstream_failure_stage": dependency, "model_call_executed": False}
                _append_jsonl(output_dir / "terminal_states.jsonl", state)
                terminal.append(state); blocked += 1
                continue
            stage = "planned"
            attempts = 0
            try:
                if entry["global_execution_index"] > 1:
                    stage = "inter_slot_pacing"; sleep_fn(INTER_CALL_DELAY_SECONDS)
                scenario = load_scenario(entry["scenario_id"])
                public = {k: v for k, v in scenario.items() if k != "private"}
                implicit = candidate_view(public, "discovery", "implicit")
                projection = build_stage1_projection(implicit)
                prompt = ""
                result = None
                started = perf_counter()

                def invoke() -> Any:
                    nonlocal prompt
                    if entry["observation_kind"] == "intermediate":
                        prompt = build_stage1_prompt(entry["stage_id"], projection)
                        return adapter.generate(prompt, _config(), response_schema=_stage1_schema(entry["stage_id"]))
                    mode = entry["candidate_view_mode"]
                    visible = candidate_view(public, "discovery", mode)
                    artifact = artifacts[key][0] if key else None
                    if key:
                        verify_artifact_envelope(artifacts[key][1], artifact)
                    prompt = build_stage2_prompt(entry["condition_id"], visible, artifact)
                    return adapter.generate(prompt, _config(), response_schema=DISCOVERY_RESPONSE_JSON_SCHEMA)

                def set_stage(value: str) -> None:
                    nonlocal stage
                    stage = value

                delivery = run_delivery_attempts(entry, output_dir / DELIVERY_FILENAME, invoke, sleep_fn, stage_callback=set_stage)
                attempts = delivery["attempts_used"]
                response = delivery["result"]
                if response is None:
                    provider_failures += 1
                    state = _provider_error(entry, delivery["last_error"], attempts, (perf_counter() - started) * 1000)
                    _append_jsonl(output_dir / "terminal_states.jsonl", state); terminal.append(state)
                    if entry["observation_kind"] == "intermediate":
                        failed_dependencies.add((entry["scenario_id"], entry["stage_id"]))
                    else:
                        state.update({"baseline_id": entry["condition_id"], "condition": entry["candidate_view_mode"], "prompt_version": PROTOCOL_VERSION, "experiment_config_version": EXPERIMENT_VERSION, "model_adapter": adapter.identifier, "model_name": MODEL_ID, "model_version": None, "validation_error": None, "artifact_sha256": artifacts[key][1]["artifact_sha256"] if key else None, "experiment_config": _config().to_dict()})
                        _append_jsonl(output_dir / "runs.jsonl", state); runs.append(state)
                    continue
                raw = {**entry, "raw_stage1_response": response.text, "model_name": response.model_name or MODEL_ID, "model_version": response.model_version, "latency_ms": response.latency_ms, "input_tokens": response.input_tokens, "output_tokens": response.output_tokens, "delivery_attempts_used": attempts}
                if entry["observation_kind"] == "intermediate":
                    _append_jsonl(output_dir / "stage1_raw.jsonl", raw)
                    try:
                        canonical, encoded, artifact_sha = (validate_neutral_grounded_context(response.text, projection) if entry["stage_id"] == "RC0_GENERIC_STAGE1" else validate_decision_support(response.text, projection))
                    except IntermediateValidationError as exc:
                        intermediate_failures += 1
                        failed_dependencies.add((entry["scenario_id"], entry["stage_id"]))
                        state = {**entry, "terminal_state": "intermediate_invalid", "failure_category": exc.category, "validation_error": str(exc), "model_call_executed": True, "delivery_attempts_used": attempts}
                        _append_jsonl(output_dir / "terminal_states.jsonl", state); terminal.append(state)
                    else:
                        envelope = build_artifact_envelope(entry["scenario_id"], entry["stage_id"], encoded)
                        artifact_value = {**entry, "canonical_payload": canonical, "canonical_bytes_utf8": encoded.decode("utf-8"), "artifact_envelope": envelope, "artifact_sha256": artifact_sha, "model_call_executed": True}
                        _append_jsonl(output_dir / "stage1_artifacts.jsonl", artifact_value)
                        artifacts[(entry["scenario_id"], entry["stage_id"])] = (encoded, envelope)
                        state = {**entry, "terminal_state": "intermediate_valid", "artifact_sha256": artifact_sha, "model_call_executed": True}
                        _append_jsonl(output_dir / "terminal_states.jsonl", state); terminal.append(state)
                else:
                    try:
                        parsed = parse_discovery_response(response.text, [item["id"] for item in implicit["decisions"]])
                        validation_status, validation_error = "valid", None
                    except OutputValidationError as exc:
                        parsed, validation_status, validation_error = None, "invalid", str(exc)
                    run = {**entry, "baseline_id": entry["condition_id"], "condition": entry["candidate_view_mode"], "prompt_version": PROTOCOL_VERSION, "experiment_config_version": EXPERIMENT_VERSION, "raw_model_response": response.text, "parsed_candidate_response": parsed, "validation_status": validation_status, "validation_error": validation_error, "provider_error": None, "model_adapter": adapter.identifier, "model_name": response.model_name or MODEL_ID, "model_version": response.model_version, "latency_ms": response.latency_ms, "input_tokens": response.input_tokens, "output_tokens": response.output_tokens, "delivery_attempts_used": attempts, "artifact_sha256": artifacts[key][1]["artifact_sha256"] if key else None, "experiment_config": _config().to_dict()}
                    _append_jsonl(output_dir / "runs.jsonl", run); runs.append(run)
                    if validation_status == "valid":
                        evaluation = {"global_execution_index": entry["global_execution_index"], "scenario_id": entry["scenario_id"], "condition_id": entry["condition_id"], "repetition_id": "1", "evaluation": asdict(evaluate_discovery(scenario, parsed))}
                        _append_jsonl(output_dir / "evaluations.jsonl", evaluation); evaluations.append(evaluation)
                    state = {**entry, "terminal_state": "final_" + validation_status, "model_call_executed": True}
                    _append_jsonl(output_dir / "terminal_states.jsonl", state); terminal.append(state)
            except KeyboardInterrupt:
                aborted = True
                interrupted = {**entry, "terminal_state": "operator_interrupt", "lifecycle_stage": stage, "delivery_attempt_number": attempts}
                _append_jsonl(output_dir / "terminal_states.jsonl", interrupted)
                break
    finally:
        if hasattr(adapter, "close"): adapter.close()
    final_runs_persisted = len(runs)
    final_valid_outputs = sum(x["validation_status"] == "valid" for x in runs)
    final_invalid_outputs = sum(x["validation_status"] == "invalid" for x in runs)
    evaluations_persisted = len(evaluations)
    infrastructure_complete = not aborted and len(terminal) == 96 and provider_failures == 0
    scientific_outputs_complete = (
        final_runs_persisted == 72
        and final_valid_outputs == 72
        and final_invalid_outputs == 0
        and evaluations_persisted == 72
        and intermediate_failures == 0
        and provider_failures == 0
        and not aborted
    )
    if infrastructure_complete and scientific_outputs_complete:
        classification_status = None
    elif infrastructure_complete and intermediate_failures:
        classification_status = "FAIL / DO NOT ADVANCE"
    elif infrastructure_complete and final_invalid_outputs:
        classification_status = "INCOMPLETE / MODEL OUTPUT"
    else:
        classification_status = "INCOMPLETE / INFRASTRUCTURE"
    summary = {
        "experiment_version": EXPERIMENT_VERSION, "experiment_status": "aborted" if aborted else "completed",
        "conceptual_slots_planned": 96, "conceptual_slots_terminal": len(terminal),
        "model_calls_with_response": sum(x.get("validation_status") != "provider_error" for x in runs) + len(artifacts) + intermediate_failures,
        "final_outputs_possible": 72, "final_runs_persisted": final_runs_persisted,
        "final_valid_outputs": final_valid_outputs, "final_invalid_outputs": final_invalid_outputs,
        "evaluations_persisted": evaluations_persisted,
        "provider_failures": provider_failures, "intermediate_failures": intermediate_failures,
        "downstream_blocked": blocked,
        "infrastructure_complete": infrastructure_complete,
        "scientific_outputs_complete": scientific_outputs_complete,
        "screening_complete": infrastructure_complete and scientific_outputs_complete,
        "classification_status": classification_status,
        "abort_reason": "operator_interrupt" if aborted else None, "interrupted_position": interrupted,
        "input_tokens": sum((x.get("input_tokens") or 0) for x in runs), "output_tokens": sum((x.get("output_tokens") or 0) for x in runs), "latency_ms": sum((x.get("latency_ms") or 0) for x in runs),
        "claim_boundary": "Round B DEV screening only; not generalization evidence",
    }
    (output_dir / "summary.json").write_bytes(_canonical_json(summary))
    return summary


def _condition_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(x["true_materially_dependent"] and x["predicted_materially_dependent"] for x in rows)
    tn = sum(not x["true_materially_dependent"] and not x["predicted_materially_dependent"] for x in rows)
    fp = sum(not x["true_materially_dependent"] and x["predicted_materially_dependent"] for x in rows)
    fn = sum(x["true_materially_dependent"] and not x["predicted_materially_dependent"] for x in rows)
    precision = tp / (tp + fp) if tp + fp else 0.0; recall = tp / (tp + fn) if tp + fn else 1.0
    return {"TP": tp, "TN": tn, "FP": fp, "FN": fn, "precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0, "unique_binary_failures": len({(x["scenario_id"], x["decision_id"]) for x in rows if x["true_materially_dependent"] != x["predicted_materially_dependent"]}), "still_justified_errors": sum(x["true_still_justified"] != x["predicted_still_justified"] for x in rows), "dependency_strength_errors": sum(x["true_dependency_strength"] != x["predicted_dependency_strength"] for x in rows), "material_false_negatives": fn}


def classify_contrast(
    control_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]], complete: bool,
    incomplete_status: str = "INCOMPLETE / INFRASTRUCTURE",
) -> dict[str, Any]:
    if not complete: return {"status": incomplete_status, "improved_units": [], "regressed_units": []}
    control = {(x["scenario_id"], x["decision_id"]): x for x in control_rows}; candidate = {(x["scenario_id"], x["decision_id"]): x for x in candidate_rows}
    if set(control) != set(candidate): return {"status": incomplete_status, "improved_units": [], "regressed_units": []}
    improved, regressed = defaultdict(list), defaultdict(list)
    for key in sorted(control):
        for field in ("materially_dependent", "still_justified"):
            truth = control[key]["true_" + field]; a = control[key]["predicted_" + field] == truth; b = candidate[key]["predicted_" + field] == truth
            if not a and b: improved[key].append(field)
            if a and not b: regressed[key].append(field)
    values = lambda x: [{"scenario_id": k[0], "decision_id": k[1], "fields": v} for k, v in x.items()]
    new_fn = [k for k in regressed if control[k]["true_materially_dependent"] and not candidate[k]["predicted_materially_dependent"]]
    if improved and not regressed: status = "PROMISING"
    elif improved and len(regressed) == 1: status = "AMBIGUOUS / NEEDS CONFIRMATION"
    elif len(new_fn) > 1 and not improved: status = "FAIL / SAFETY REGRESSION"
    else: status = "FAIL / DO NOT ADVANCE"
    return {"status": status, "improved_units": values(improved), "regressed_units": values(regressed), "new_material_false_negative_units": [{"scenario_id": k[0], "decision_id": k[1]} for k in new_fn]}


def analyze(output_dir: Path, analysis_dir: Path) -> dict[str, Any]:
    if analysis_dir.exists(): raise RoundBError("analysis directory already exists")
    plan_bytes = (output_dir / PLAN_FILENAME).read_bytes(); plan = json.loads(plan_bytes)
    manifest = json.loads((output_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")); validate_plan(plan)
    if hashlib.sha256(plan_bytes).hexdigest() != manifest["execution_plan_sha256"]: raise RoundBError("analysis plan hash mismatch")
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    runs_path = output_dir / "runs.jsonl"; runs = [json.loads(x) for x in runs_path.read_text(encoding="utf-8").splitlines() if x] if runs_path.exists() else []
    ledger = []
    for run in runs:
        if run["validation_status"] != "valid": continue
        truth = {x["decision_id"]: x for x in load_scenario(run["scenario_id"])["private"]["decision_labels"]}
        for prediction in run["parsed_candidate_response"]["decisions"]:
            label = truth[prediction["decision_id"]]
            ledger.append({"scenario_id": run["scenario_id"], "decision_id": prediction["decision_id"], "condition_id": run["condition_id"], "repetition_id": "1", "true_materially_dependent": label["materially_dependent"], "predicted_materially_dependent": prediction["materially_dependent"], "true_still_justified": label["still_justified"], "predicted_still_justified": prediction["still_justified"], "true_dependency_strength": label["dependency_strength"], "predicted_dependency_strength": prediction["dependency_strength"]})
    by_condition = {c: [x for x in ledger if x["condition_id"] == c] for c in FINAL_CONDITIONS}
    complete = bool(summary.get("screening_complete"))
    if summary.get("intermediate_failures", 0):
        incomplete_status = "UNAVAILABLE / INTERMEDIATE FAILURE"
    elif summary.get("final_invalid_outputs", 0):
        incomplete_status = "INCOMPLETE / MODEL OUTPUT"
    else:
        incomplete_status = "INCOMPLETE / INFRASTRUCTURE"
    comparisons = {"RB0_vs_RC0": classify_contrast(by_condition["RB0"], by_condition["RC0"], complete, incomplete_status), "RB0_vs_RR1": classify_contrast(by_condition["RB0"], by_condition["RR1"], complete, incomplete_status), "RC0_vs_RB1": classify_contrast(by_condition["RC0"], by_condition["RB1"], complete, incomplete_status), "RB1_vs_RB2": classify_contrast(by_condition["RB1"], by_condition["RB2"], complete, incomplete_status), "RB2_vs_RB3": classify_contrast(by_condition["RB2"], by_condition["RB3"], complete, incomplete_status)}
    artifacts_path = output_dir / "stage1_artifacts.jsonl"; artifacts = [json.loads(x) for x in artifacts_path.read_text(encoding="utf-8").splitlines() if x] if artifacts_path.exists() else []
    raw_path = output_dir / "stage1_raw.jsonl"; stage1_raw = [json.loads(x) for x in raw_path.read_text(encoding="utf-8").splitlines() if x] if raw_path.exists() else []
    stage_cost = defaultdict(lambda: {"model_calls": 0, "delivery_attempts": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0.0})
    for run in runs:
        cost = stage_cost[run["condition_id"]]; cost["model_calls"] += 1; cost["delivery_attempts"] += run.get("delivery_attempts_used", 0); cost["input_tokens"] += run.get("input_tokens") or 0; cost["output_tokens"] += run.get("output_tokens") or 0; cost["latency_ms"] += run.get("latency_ms") or 0
    for raw in stage1_raw:
        cost = stage_cost[raw["stage_id"]]; cost["model_calls"] += 1; cost["delivery_attempts"] += raw.get("delivery_attempts_used", 0); cost["input_tokens"] += raw.get("input_tokens") or 0; cost["output_tokens"] += raw.get("output_tokens") or 0; cost["latency_ms"] += raw.get("latency_ms") or 0
    def add_cost(*values: dict[str, Any]) -> dict[str, Any]:
        return {field: sum(value.get(field, 0) for value in values) for field in ("model_calls", "delivery_attempts", "input_tokens", "output_tokens", "latency_ms")}
    standalone = {
        "RB0": dict(stage_cost["RB0"]), "RR1": dict(stage_cost["RR1"]),
        "RC0": add_cost(stage_cost["RC0_GENERIC_STAGE1"], stage_cost["RC0"]),
        "RB1": add_cost(stage_cost["SHARED_RECONSTRUCTION_STAGE1"], stage_cost["RB1"]),
        "RB2": add_cost(stage_cost["SHARED_RECONSTRUCTION_STAGE1"], stage_cost["RB2"]),
        "RB3": add_cost(stage_cost["SHARED_RECONSTRUCTION_STAGE1"], stage_cost["RB3"]),
    }
    analysis = {"analysis_version": "round-b-screening-analysis-v0.1", "screening_complete": complete, "classification_status": summary.get("classification_status"), "infrastructure_complete": summary.get("infrastructure_complete", False), "final_runs_persisted": summary.get("final_runs_persisted", 0), "final_valid_outputs": summary.get("final_valid_outputs", 0), "final_invalid_outputs": summary.get("final_invalid_outputs", 0), "evaluations_persisted": summary.get("evaluations_persisted", 0), "intermediate_failures": summary.get("intermediate_failures", 0), "primary_unit": "scenario_id + decision_id", "per_condition": {c: _condition_metrics(by_condition[c]) for c in FINAL_CONDITIONS}, "precommitted_comparisons": comparisons, "cost_accounting": {"tournament_amortized_by_stage": dict(stage_cost), "standalone_pipeline": standalone}, "intermediate_artifact_count": len(artifacts), "stage1_excluded_from_discovery_denominators": True, "rc0_claim_boundary": "RC0 does not match specialized semantic work; RB1 > RC0 cannot prove relationship structure alone caused a gain", "confirmation_authorized": False, "claim_boundary": "DEV screening only; PROMISING DEVELOPMENT EVIDENCE at most"}
    analysis_dir.mkdir()
    fields = list(ledger[0]) if ledger else ["scenario_id", "decision_id", "condition_id"]
    with (analysis_dir / "decision_prediction_ledger.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n"); writer.writeheader(); writer.writerows(ledger)
    (analysis_dir / "round_b_analysis.json").write_bytes(_canonical_json(analysis))
    (analysis_dir / "ROUND_B_REPORT.md").write_text("# Round B Screening Analysis\n\nDEV screening only; not generalization evidence. RC0 is a pass-count-matched generic control and does not match specialized semantic work.\n", encoding="utf-8", newline="\n")
    return analysis


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen Decision Recall Round B v0.2 screening scaffold")
    parser.add_argument("--output-dir", type=Path, required=True)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--prepare", action="store_true"); actions.add_argument("--execute", action="store_true"); actions.add_argument("--analyze", action="store_true")
    parser.add_argument("--analysis-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.prepare: print(json.dumps(prepare(args.output_dir), sort_keys=True)); return 0
        if args.execute: print(json.dumps(execute(args.output_dir), sort_keys=True)); return 0
        if args.analyze:
            if args.analysis_dir is None: raise RoundBError("--analyze requires --analysis-dir")
            print(json.dumps(analyze(args.output_dir, args.analysis_dir), sort_keys=True)); return 0
        print("Refusing without explicit --prepare, --execute, or --analyze.", file=sys.stderr); return 2
    except (RoundBError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"Round B scaffold refused: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
