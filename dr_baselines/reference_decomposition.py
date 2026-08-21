"""Frozen Reference Decomposition v0.1 scaffold."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any, Callable

from dr_bench import evaluate_discovery, load_scenarios

from .baselines import BASE_TASK_PROMPT
from .config import ExperimentConfig
from .dev_experiment import (
    DELIVERY_BACKOFF_SECONDS, DELIVERY_POLICY_VERSION, INTER_CALL_DELAY_SECONDS,
    LOCATION, MAX_DELIVERY_ATTEMPTS, MODEL_ID, PROJECT_ID, SDK_PACKAGE, SDK_VERSION,
    TRANSPORT_ATTEMPTS, TRANSPORT_TIMEOUT_MS, TRANSPORT_TIMEOUT_SECONDS,
    _dev_adapter_factory, run_delivery_attempts,
)
from .output import (
    DISCOVERY_RESPONSE_JSON_SCHEMA, DISCOVERY_RESPONSE_MIME_TYPE,
    DISCOVERY_RESPONSE_SCHEMA_VERSION, OutputValidationError,
    parse_discovery_response,
)
from .runner import with_structured_output_metadata
from .round_b import _condition_metrics


EXPERIMENT_VERSION = "reference-decomposition-v0.1"
MANIFEST_TYPE = "reference-decomposition-manifest-v0.1"
PROTOCOL_COMMIT = "cdbd640a1aae3bbd5499f63bb8902f53ee438919"
PROTOCOL_SHA256 = "dde869c46bdbaa7a18334c1d2658dd0e3d6bfb0373f6e506533901608efbde68"
PROTOCOL_PATH = Path("docs/REFERENCE_DECOMPOSITION_PROTOCOL_V0.1.md")
CONDITIONS = ("R0", "RE", "RA", "REA")
DEV_SCENARIOS = tuple(f"dev-{number:03d}" for number in range(1, 13))
TOTAL_SLOTS = 48
PLAN_FILENAME = "execution_plan.json"
MANIFEST_FILENAME = "experiment_manifest.json"
PROOF_FILENAME = "structural_view_proof.json"
CONTRASTS = (("R0", "RE"), ("R0", "RA"), ("RE", "REA"), ("RA", "REA"))
FORENSIC_ENDPOINT = {"scenario_id": "dev-002", "decision_id": "d3"}


class ReferenceDecompositionError(RuntimeError):
    pass


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _schema_sha(schema: dict[str, Any]) -> str:
    return _sha(json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def protocol_sha256() -> str:
    return _sha(PROTOCOL_PATH.read_bytes())


def _dev_scenarios() -> list[dict[str, Any]]:
    scenarios = load_scenarios("dev")
    if tuple(scenario["id"] for scenario in scenarios) != DEV_SCENARIOS:
        raise ReferenceDecompositionError("DEV-only scenario inventory/order mismatch")
    return scenarios


def build_views(scenario: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return build_view_bundle(scenario)["views"]


def build_view_bundle(scenario: dict[str, Any]) -> dict[str, Any]:
    """Build raw, normalized, and factorial views without exposing condition identity."""
    # Import through the frozen public API only after the DEV-only scenario is selected.
    from dr_bench import candidate_view
    raw_implicit = candidate_view(scenario, "discovery", "implicit")
    raw_structured = candidate_view(scenario, "discovery", "structured")
    if raw_implicit.get("discovery_condition") != "implicit" or raw_structured.get("discovery_condition") != "structured":
        raise ReferenceDecompositionError("raw discovery_condition source metadata mismatch")
    r0, rea = copy.deepcopy(raw_implicit), copy.deepcopy(raw_structured)
    del r0["discovery_condition"]; del rea["discovery_condition"]
    r0_decisions = r0["decisions"]
    rea_decisions = rea["decisions"]
    r0_ids, rea_ids = [item["id"] for item in r0_decisions], [item["id"] for item in rea_decisions]
    if len(r0_ids) != len(set(r0_ids)) or r0_ids != rea_ids:
        raise ReferenceDecompositionError("decision identity alignment failure")
    re_view, ra_view = copy.deepcopy(r0), copy.deepcopy(r0)
    structured = {item["id"]: item for item in rea_decisions}
    for decision in re_view["decisions"]:
        if "evidence_available" not in structured[decision["id"]]:
            raise ReferenceDecompositionError("structured decision lacks evidence_available")
        decision["evidence_available"] = copy.deepcopy(structured[decision["id"]]["evidence_available"])
    for decision in ra_view["decisions"]:
        if "assumptions" not in structured[decision["id"]]:
            raise ReferenceDecompositionError("structured decision lacks assumptions")
        decision["assumptions"] = copy.deepcopy(structured[decision["id"]]["assumptions"])
    views = {"R0": r0, "RE": re_view, "RA": ra_view, "REA": rea}
    return {"raw": {"implicit": raw_implicit, "structured": raw_structured}, "normalized": {"implicit": r0, "structured": rea}, "views": views}


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def diff_paths(left: Any, right: Any, path: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        result = []
        for key in sorted(set(left) | set(right)):
            child = path + "/" + _escape_pointer(str(key))
            if key not in left or key not in right:
                result.append(child)
            else:
                result.extend(diff_paths(left[key], right[key], child))
        return result
    if isinstance(left, list) and isinstance(right, list):
        result = []
        if len(left) != len(right):
            result.append(path)
        for index, (a, b) in enumerate(zip(left, right)):
            result.extend(diff_paths(a, b, path + f"/{index}"))
        return result
    return [] if left == right else [path or "/"]


def _allowed(paths: list[str], field: str, decision_count: int) -> bool:
    return paths == [f"/decisions/{index}/{field}" for index in range(decision_count)]


def prove_views(scenario: dict[str, Any], views: dict[str, dict[str, Any]], bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    bundle = bundle or build_view_bundle(scenario)
    raw, normalized = bundle["raw"], bundle["normalized"]
    count = len(views["R0"]["decisions"])
    comparisons = {
        "RE_minus_R0": (diff_paths(views["R0"], views["RE"]), "evidence_available"),
        "RA_minus_R0": (diff_paths(views["R0"], views["RA"]), "assumptions"),
        "REA_minus_RE": (diff_paths(views["RE"], views["REA"]), "assumptions"),
        "REA_minus_RA": (diff_paths(views["RA"], views["REA"]), "evidence_available"),
    }
    proof = {
        "scenario_id": scenario["id"],
        "raw_view_sha256": {name: _sha(_canonical_json(raw[name])) for name in ("implicit", "structured")},
        "normalized_view_sha256": {name: _sha(_canonical_json(normalized[name])) for name in ("implicit", "structured")},
        "view_sha256": {condition: _sha(_canonical_json(views[condition])) for condition in CONDITIONS},
        "normalization": {
            "raw_discovery_condition": {"implicit": raw["implicit"].get("discovery_condition"), "structured": raw["structured"].get("discovery_condition")},
            "implicit_removed_paths": diff_paths(raw["implicit"], normalized["implicit"]),
            "structured_removed_paths": diff_paths(raw["structured"], normalized["structured"]),
            "unexpected_paths": [],
            "discovery_condition_absent_from_all_final_views": all("discovery_condition" not in views[condition] for condition in CONDITIONS),
            "replacement_condition_fields_absent": all(not ({"condition_id", "reference_type", "decomposition_condition", "view_type", "structured_reference", "evidence_only", "assumptions_only"} & set(views[condition])) for condition in CONDITIONS),
        },
        "comparisons": {name: {"diff_paths": paths, "required_field": field, "pass": _allowed(paths, field, count)} for name, (paths, field) in comparisons.items()},
    }
    normalization = proof["normalization"]
    normalization["pass"] = normalization["raw_discovery_condition"] == {"implicit": "implicit", "structured": "structured"} and normalization["implicit_removed_paths"] == ["/discovery_condition"] and normalization["structured_removed_paths"] == ["/discovery_condition"] and normalization["discovery_condition_absent_from_all_final_views"] and normalization["replacement_condition_fields_absent"]
    proof["factorial_pass"] = all(item["pass"] for item in proof["comparisons"].values())
    proof["pass"] = normalization["pass"] and proof["factorial_pass"]
    return proof


def _scenario_order(index: int) -> tuple[str, ...]:
    rows = (("R0", "RE", "RA", "REA"), ("RE", "RA", "REA", "R0"), ("RA", "REA", "R0", "RE"), ("REA", "R0", "RE", "RA"))
    return rows[(index - 1) % 4]


def build_execution_plan() -> list[dict[str, Any]]:
    plan, global_index = [], 1
    for scenario_index, scenario_id in enumerate(DEV_SCENARIOS, 1):
        for position, condition in enumerate(_scenario_order(scenario_index), 1):
            plan.append({"global_execution_index": global_index, "scenario_id": scenario_id, "repetition_id": "1", "condition_id": condition, "temporal_position": position, "observation_kind": "final", "expected_output_contract": DISCOVERY_RESPONSE_SCHEMA_VERSION})
            global_index += 1
    validate_plan(plan)
    return plan


def validate_plan(plan: list[dict[str, Any]]) -> None:
    if len(plan) != TOTAL_SLOTS or [item.get("global_execution_index") for item in plan] != list(range(1, 49)):
        raise ReferenceDecompositionError("plan must contain exactly 48 contiguous slots")
    if Counter(item.get("condition_id") for item in plan) != Counter({condition: 12 for condition in CONDITIONS}):
        raise ReferenceDecompositionError("condition counts differ from 12 each")
    for index, scenario_id in enumerate(DEV_SCENARIOS, 1):
        selected = [item for item in plan if item.get("scenario_id") == scenario_id]
        if tuple(item["condition_id"] for item in selected) != _scenario_order(index) or [item["temporal_position"] for item in selected] != [1, 2, 3, 4]:
            raise ReferenceDecompositionError("plan differs from frozen Latin square")
    for condition in CONDITIONS:
        if Counter(item["temporal_position"] for item in plan if item["condition_id"] == condition) != Counter({1: 3, 2: 3, 3: 3, 4: 3}):
            raise ReferenceDecompositionError("temporal positions are not balanced 3/3/3/3")


def _config() -> ExperimentConfig:
    return with_structured_output_metadata(ExperimentConfig(version=EXPERIMENT_VERSION, model_name=MODEL_ID, repetitions=1, dataset_id="DR-Bench", dataset_version="0.1", scenario_ids=DEV_SCENARIOS, candidate_view_contract_version="0.1", generation_config=(("delivery_policy_version", DELIVERY_POLICY_VERSION),)), True)


def _prompt(view: dict[str, Any]) -> str:
    return BASE_TASK_PROMPT + "\n\nCANDIDATE-VISIBLE SCENARIO:\n" + json.dumps(view, sort_keys=True, separators=(",", ":"))


def prepare(output_dir: Path) -> dict[str, Any]:
    if output_dir.exists():
        raise ReferenceDecompositionError("output directory already exists")
    if protocol_sha256() != PROTOCOL_SHA256:
        raise ReferenceDecompositionError("protocol SHA mismatch")
    if _git("rev-parse", PROTOCOL_COMMIT + "^{commit}") != PROTOCOL_COMMIT:
        raise ReferenceDecompositionError("protocol commit unavailable")
    if _git("status", "--porcelain", "--untracked-files=no"):
        raise ReferenceDecompositionError("tracked worktree must be clean")
    scenarios = _dev_scenarios()
    proofs = []
    for scenario in scenarios:
        bundle = build_view_bundle(scenario)
        proof = prove_views(scenario, bundle["views"], bundle); proofs.append(proof)
    proof_pass = all(item["pass"] for item in proofs)
    plan = build_execution_plan(); plan_bytes = _canonical_json(plan); plan_sha = _sha(plan_bytes)
    config = _config()
    proof_payload = {"proof_version": "reference-view-identity-proof-v0.1", "ignored_diff_paths": [], "scenario_proofs": proofs, "normalization_pass_count": sum(item["normalization"]["pass"] for item in proofs), "factorial_pass_count": sum(item["factorial_pass"] for item in proofs), "all_pass": proof_pass}
    proof_bytes = _canonical_json(proof_payload)
    manifest = {
        "manifest_type": MANIFEST_TYPE, "experiment_version": EXPERIMENT_VERSION,
        "protocol_commit_sha": PROTOCOL_COMMIT, "protocol_sha256": PROTOCOL_SHA256,
        "implementation_commit_sha": _git("rev-parse", "HEAD"), "branch": _git("branch", "--show-current"), "created_at_utc": _utc_now(),
        "dev_scenario_ids": list(DEV_SCENARIOS), "conditions": {
            "R0": "exact implicit view", "RE": "implicit plus evidence_available only",
            "RA": "implicit plus assumptions only", "REA": "exact full structured decision-context view",
        },
        "planned_scientific_observations": 48, "repetitions": 1, "execution_plan_sha256": plan_sha,
        "structural_proof_sha256": _sha(proof_bytes),
        "normalization_rule": "remove exactly top-level /discovery_condition from raw implicit and structured views before condition construction",
        "position_counts": {condition: {str(position): sum(item["condition_id"] == condition and item["temporal_position"] == position for item in plan) for position in range(1, 5)} for condition in CONDITIONS},
        "base_task_prompt_sha256": _sha(BASE_TASK_PROMPT.encode()),
        "discovery_schema_version": DISCOVERY_RESPONSE_SCHEMA_VERSION,
        "discovery_schema_sha256": _schema_sha(DISCOVERY_RESPONSE_JSON_SCHEMA),
        "structured_output": {"enabled": True, "response_mime_type": DISCOVERY_RESPONSE_MIME_TYPE},
        "experiment_config": config.to_dict(), "provider": "Google Cloud Agent Platform / Vertex", "project_id": PROJECT_ID, "location": LOCATION, "model_id": MODEL_ID, "sdk_package": SDK_PACKAGE, "sdk_version": SDK_VERSION,
        "transport": {"sdk_attempts": TRANSPORT_ATTEMPTS, "max_delivery_attempts": MAX_DELIVERY_ATTEMPTS, "retryable_statuses": [408, 429, 500, 502, 503, 504], "backoff_seconds": list(DELIVERY_BACKOFF_SECONDS), "jitter": False, "timeout_ms": TRANSPORT_TIMEOUT_MS, "timeout_seconds": TRANSPORT_TIMEOUT_SECONDS, "inter_scientific_slot_delay_seconds": INTER_CALL_DELAY_SECONDS, "concurrency": 1, "first_model_response_wins": True},
        "analysis_contrasts": [f"{a}_to_{b}" for a, b in CONTRASTS], "contemporary_reference_effect_gate": "R0_to_REA", "factorial_interpretation_version": "reference-decomposition-patterns-v0.1", "forensic_endpoint": FORENSIC_ENDPOINT,
        "fresh_calls_required": True, "historical_response_reuse_authorized": False,
        "stage1_present": False, "multi_pass_present": False, "confirmation_authorized": False,
        "sealed_holdout_excluded": True, "dev_only_loader": "load_scenarios(dev)", "structural_view_proofs_passed": sum(item["pass"] for item in proofs), "normalization_proofs_passed": sum(item["normalization"]["pass"] for item in proofs), "factorial_proofs_passed": sum(item["factorial_pass"] for item in proofs), "ignored_diff_paths": [],
        "execute_eligible": proof_pass, "prepare_status": "PREPARED" if proof_pass else "PREPARE BLOCKED — REFERENCE VIEW IDENTITY FAILURE",
    }
    output_dir.mkdir()
    (output_dir / PLAN_FILENAME).write_bytes(plan_bytes)
    (output_dir / PROOF_FILENAME).write_bytes(proof_bytes)
    (output_dir / MANIFEST_FILENAME).write_bytes(_canonical_json(manifest))
    return manifest


def _validate_prepared(output_dir: Path, prohibit_existing_runs: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not (output_dir / MANIFEST_FILENAME).exists() or not (output_dir / PLAN_FILENAME).exists():
        raise ReferenceDecompositionError("compatible PREPARE artifacts required")
    manifest = json.loads((output_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")); plan_bytes = (output_dir / PLAN_FILENAME).read_bytes(); plan = json.loads(plan_bytes)
    if manifest.get("manifest_type") != MANIFEST_TYPE or manifest.get("experiment_version") != EXPERIMENT_VERSION or not manifest.get("execute_eligible"):
        raise ReferenceDecompositionError("compatible execute-eligible PREPARE manifest required")
    validate_plan(plan)
    if _sha(plan_bytes) != manifest.get("execution_plan_sha256") or manifest.get("implementation_commit_sha") != _git("rev-parse", "HEAD"):
        raise ReferenceDecompositionError("prepared plan/implementation identity mismatch")
    if prohibit_existing_runs and (output_dir / "runs.jsonl").exists():
        raise ReferenceDecompositionError("existing execution artifacts prohibit re-execution")
    return manifest, plan


def execute(output_dir: Path, adapter_factory: Callable[[], Any] = _dev_adapter_factory, sleep_fn: Callable[[float], None] = sleep) -> dict[str, Any]:
    manifest, plan = _validate_prepared(output_dir)
    scenarios = {scenario["id"]: scenario for scenario in _dev_scenarios()}
    adapter = adapter_factory(); runs_path = output_dir / "runs.jsonl"; lifecycle = output_dir / "delivery_attempts.jsonl"; evaluations_path = output_dir / "evaluations.jsonl"; config = _config()
    completed = valid = invalid = provider_failures = 0; interrupted = False
    try:
        for index, entry in enumerate(plan):
            views = build_views(scenarios[entry["scenario_id"]]); visible = views[entry["condition_id"]]; prompt = _prompt(visible)
            delivery = run_delivery_attempts(entry, lifecycle, lambda: adapter.generate(prompt, config, response_schema=DISCOVERY_RESPONSE_JSON_SCHEMA), sleep_fn)
            record = {**entry, "baseline_id": entry["condition_id"], "condition": entry["condition_id"], "prompt_version": EXPERIMENT_VERSION, "experiment_config_version": config.version, "model_adapter": adapter.identifier, "experiment_config": config.to_dict()}
            if delivery["result"] is None:
                provider_failures += 1; record.update({"raw_model_response": None, "parsed_candidate_response": None, "validation_status": "provider_error", "validation_error": None, "provider_error": delivery["error"], "delivery_attempts_used": delivery["attempts_used"]})
            else:
                response = delivery["result"]
                try:
                    parsed = parse_discovery_response(response.text, [decision["id"] for decision in visible["decisions"]]); status, error = "valid", None; valid += 1
                except OutputValidationError as exc:
                    parsed, status, error = None, "invalid", str(exc); invalid += 1
                record.update({"raw_model_response": response.text, "parsed_candidate_response": parsed, "validation_status": status, "validation_error": error, "provider_error": None, "delivery_attempts_used": delivery["attempts_used"], "model_name": response.model_name or MODEL_ID, "model_version": response.model_version, "latency_ms": response.latency_ms, "input_tokens": response.input_tokens, "output_tokens": response.output_tokens})
                if status == "valid":
                    evaluation = {"global_execution_index": entry["global_execution_index"], "scenario_id": entry["scenario_id"], "condition_id": entry["condition_id"], "repetition_id": "1", "evaluation": asdict(evaluate_discovery(scenarios[entry["scenario_id"]], parsed))}
                    with evaluations_path.open("a", encoding="utf-8", newline="\n") as stream: stream.write(json.dumps(evaluation, sort_keys=True, separators=(",", ":")) + "\n")
            with runs_path.open("a", encoding="utf-8", newline="\n") as stream: stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            completed += 1
            if index < len(plan) - 1: sleep_fn(INTER_CALL_DELAY_SECONDS)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        adapter.close()
    summary = {"experiment_version": EXPERIMENT_VERSION, "planned": 48, "completed": completed, "valid": valid, "invalid": invalid, "provider_failures": provider_failures, "experiment_status": "completed" if completed == 48 and not interrupted else "aborted", "abort_reason": "operator_interrupt" if interrupted else None, "analysis_authorized": completed == 48 and provider_failures == 0 and not interrupted}
    (output_dir / "summary.json").write_bytes(_canonical_json(summary))
    if interrupted: raise KeyboardInterrupt
    return summary


def _operational_errors(rows: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    errors = set()
    for row in rows:
        for field in ("materially_dependent", "still_justified"):
            if row["predicted_" + field] != row["true_" + field]:
                errors.add((row["scenario_id"], row["decision_id"], field))
    return errors


def _contrast(control: list[dict[str, Any]], treatment: list[dict[str, Any]]) -> dict[str, Any]:
    a, b = _operational_errors(control), _operational_errors(treatment)
    return {"operational_corrections": [list(x) for x in sorted(a - b)], "operational_regressions": [list(x) for x in sorted(b - a)], "strength_error_delta": sum(x["predicted_dependency_strength"] != x["true_dependency_strength"] for x in treatment) - sum(x["predicted_dependency_strength"] != x["true_dependency_strength"] for x in control)}


def classify_pattern(rows_by_condition: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    r0_errors, rea_errors = _operational_errors(rows_by_condition["R0"]), _operational_errors(rows_by_condition["REA"])
    target, rea_regressions = r0_errors - rea_errors, rea_errors - r0_errors
    if not target or rea_regressions:
        return {"pattern": "PATTERN E — NO CLEAN DECOMPOSITION", "reason": "CONTEMPORARY STRUCTURED-REFERENCE ADVANTAGE NOT REPRODUCED", "contemporary_advantage_units": [list(x) for x in sorted(target)], "contemporary_regressions": [list(x) for x in sorted(rea_regressions)]}
    reproduces, clean_none, diagnostics = {}, {}, {}
    for condition in ("RE", "RA"):
        errors = _operational_errors(rows_by_condition[condition])
        corrected = target - errors; regressions = errors - r0_errors
        reproduces[condition] = corrected == target and not regressions
        clean_none[condition] = not corrected and not regressions
        diagnostics[condition] = {"corrected_target_units": [list(x) for x in sorted(corrected)], "new_operational_regressions": [list(x) for x in sorted(regressions)]}
    if reproduces == {"RE": True, "RA": False}: pattern = "PATTERN A — EVIDENCE-LINK DOMINANT"
    elif reproduces == {"RE": False, "RA": True}: pattern = "PATTERN B — ASSUMPTION DOMINANT"
    elif reproduces == {"RE": False, "RA": False} and clean_none == {"RE": True, "RA": True}: pattern = "PATTERN C — INTERACTION"
    elif reproduces == {"RE": True, "RA": True}: pattern = "PATTERN D — REDUNDANT ROUTES"
    else: pattern = "PATTERN E — NO CLEAN DECOMPOSITION"
    return {"pattern": pattern, "reason": "fresh contemporary operational comparison", "single_factor_reproduction": reproduces, "single_factor_diagnostics": diagnostics, "contemporary_advantage_units": [list(x) for x in sorted(target)], "contemporary_regressions": []}


def analyze(output_dir: Path, analysis_dir: Path) -> dict[str, Any]:
    if analysis_dir.exists(): raise ReferenceDecompositionError("analysis directory already exists")
    manifest, plan = _validate_prepared(output_dir, prohibit_existing_runs=False)
    summary_path, runs_path = output_dir / "summary.json", output_dir / "runs.jsonl"
    if not summary_path.exists() or not runs_path.exists(): raise ReferenceDecompositionError("completed compatible execution artifacts required")
    summary = json.loads(summary_path.read_text(encoding="utf-8")); runs = [json.loads(line) for line in runs_path.read_text(encoding="utf-8").splitlines() if line]
    if summary.get("completed") != 48 or summary.get("valid") != 48 or summary.get("invalid") or summary.get("provider_failures") or len(runs) != 48:
        result = {"analysis_status": "INCOMPLETE / NON-CLASSIFIABLE", "factorial_pattern": None, "confirmation_authorized": False}
        analysis_dir.mkdir(); (analysis_dir / "reference_decomposition_analysis.json").write_bytes(_canonical_json(result)); return result
    expected_keys = {(entry["scenario_id"], entry["repetition_id"], entry["condition_id"]) for entry in plan}
    run_keys = {(run["scenario_id"], str(run["repetition_id"]), run["condition_id"]) for run in runs}
    if len(run_keys) != 48 or run_keys != expected_keys: raise ReferenceDecompositionError("missing or duplicate scientific slot")
    scenarios = {scenario["id"]: scenario for scenario in _dev_scenarios()}; ledger = []
    for run in runs:
        scenario = scenarios[run["scenario_id"]]; visible_ids = {item["id"] for item in scenario["candidate"]["decisions"]}; predictions = run["parsed_candidate_response"]["decisions"]
        ids = [item["decision_id"] for item in predictions]
        if len(ids) != len(set(ids)) or set(ids) != visible_ids: raise ReferenceDecompositionError("decision ledger identity mismatch")
        truth = {item["decision_id"]: item for item in scenario["private"]["decision_labels"]}
        for prediction in predictions:
            label = truth[prediction["decision_id"]]; ledger.append({"scenario_id": run["scenario_id"], "repetition_id": "1", "condition_id": run["condition_id"], "decision_id": prediction["decision_id"], "true_materially_dependent": label["materially_dependent"], "predicted_materially_dependent": prediction["materially_dependent"], "true_still_justified": label["still_justified"], "predicted_still_justified": prediction["still_justified"], "true_dependency_strength": label["dependency_strength"], "predicted_dependency_strength": prediction["dependency_strength"]})
    expected_rows = sum(len(scenario["candidate"]["decisions"]) for scenario in scenarios.values()) * 4
    if len(ledger) != expected_rows: raise ReferenceDecompositionError("decision ledger cardinality mismatch")
    by_condition = {condition: [row for row in ledger if row["condition_id"] == condition] for condition in CONDITIONS}
    contrasts = {f"{a}_to_{b}": _contrast(by_condition[a], by_condition[b]) for a, b in CONTRASTS + (("R0", "REA"),)}
    pattern = classify_pattern(by_condition)
    forensic = {condition: next(row for row in by_condition[condition] if row["scenario_id"] == "dev-002" and row["decision_id"] == "d3") for condition in CONDITIONS}
    result = {"analysis_status": "COMPLETE", "analysis_version": "reference-decomposition-analysis-v0.1", "per_condition": {condition: _condition_metrics(by_condition[condition]) for condition in CONDITIONS}, "contrasts": contrasts, "factorial_pattern": pattern, "forensic_endpoint": forensic, "confirmation_authorized": False, "historical_results_used": False}
    analysis_dir.mkdir()
    (analysis_dir / "reference_decomposition_analysis.json").write_bytes(_canonical_json(result))
    import csv
    with (analysis_dir / "decision_prediction_ledger.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(ledger[0]), lineterminator="\n"); writer.writeheader(); writer.writerows(ledger)
    (analysis_dir / "REFERENCE_DECOMPOSITION_REPORT.md").write_text("# Reference Decomposition Analysis\n\nDEV diagnostic reference decomposition only. No confirmation is authorized.\n\nPattern: **" + pattern["pattern"] + "**\n", encoding="utf-8", newline="\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reference Decomposition v0.1")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--analysis-dir", type=Path)
    actions = parser.add_mutually_exclusive_group(required=True); actions.add_argument("--prepare", action="store_true"); actions.add_argument("--execute", action="store_true"); actions.add_argument("--analyze", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.prepare: result = prepare(args.output_dir)
        elif args.execute: result = execute(args.output_dir)
        else:
            if args.analysis_dir is None: raise ReferenceDecompositionError("--analyze requires --analysis-dir")
            result = analyze(args.output_dir, args.analysis_dir)
        print(json.dumps(result, sort_keys=True)); return 0
    except (ReferenceDecompositionError, OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
