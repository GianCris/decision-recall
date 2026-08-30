"""Offline composition and analysis of the qualified Round B v0.2 recovered view."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from dr_bench import load_scenarios

from .round_b import FINAL_CONDITIONS, _condition_metrics, classify_contrast, validate_plan


ANALYSIS_VERSION = "round-b-v0.2-recovered-analysis-v0.1"
EXPECTED_ORIGINAL_IMPLEMENTATION = "167ecfa50c871c74d0aee4ed9abd9feab40fc923"
EXPECTED_RECOVERY_PROTOCOL_SHA = "bf3b76dbfc6635a7aff4c6f7acad55b75f59b205e816eed70fd989e017353652"
EXPECTED_ROUND_B_PROTOCOL_SHA = "eba2cd3d3c848ca43a0c26e1eb7c23e1c5be3af6a44a218a2018bb4019c1f335"
RECOVERED_SLOT = (11, "dev-002", "1", "RC0", "RC0_STAGE2")
CONTRASTS = (
    ("RB0_vs_RC0", "RB0", "RC0"),
    ("RC0_vs_RB1", "RC0", "RB1"),
    ("RB1_vs_RB2", "RB1", "RB2"),
    ("RB2_vs_RB3", "RB2", "RB3"),
    ("RB0_vs_RR1", "RB0", "RR1"),
)


class RecoveredAnalysisError(RuntimeError):
    pass


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def _source_hashes(directory: Path) -> dict[str, str]:
    return {path.name: _sha(path) for path in sorted(directory.iterdir()) if path.is_file()}


def _dev_truth() -> dict[str, dict[str, Any]]:
    scenarios = load_scenarios("dev")
    if {scenario["id"] for scenario in scenarios} != {f"dev-{n:03d}" for n in range(1, 13)}:
        raise RecoveredAnalysisError("DEV-only scenario inventory mismatch")
    return {scenario["id"]: scenario for scenario in scenarios}


def _slot_key(run: dict[str, Any]) -> tuple[str, str, str, str]:
    return (run["scenario_id"], str(run["repetition_id"]), run["condition_id"], run["stage_id"])


def _expected_final_slots(plan: list[dict[str, Any]]) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    validate_plan(plan)
    entries = [entry for entry in plan if entry["observation_kind"] == "final"]
    result = {_slot_key(entry): entry for entry in entries}
    if len(entries) != 72 or len(result) != 72:
        raise RecoveredAnalysisError("frozen final-slot plan is not uniquely 72 positions")
    return result


def _verify_sources(original: Path, recovery: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    summary = _json(original / "summary.json")
    manifest = _json(original / "experiment_manifest.json")
    recovery_summary = _json(recovery / "recovery_summary.json")
    recovery_manifest = _json(recovery / "recovery_manifest.json")
    runs = _jsonl(original / "runs.jsonl")
    evaluations = _jsonl(original / "evaluations.jsonl")
    if summary.get("final_runs_persisted") != 72 or len(runs) != 72:
        raise RecoveredAnalysisError("original final run count is not 72")
    if summary.get("final_valid_outputs") != 71 or summary.get("evaluations_persisted") != 71 or len(evaluations) != 71:
        raise RecoveredAnalysisError("original evaluable count is not 71")
    if summary.get("provider_failures") != 1 or summary.get("final_invalid_outputs") != 0 or summary.get("intermediate_failures") != 0:
        raise RecoveredAnalysisError("original failure accounting is incompatible")
    if summary.get("classification_status") != "INCOMPLETE / INFRASTRUCTURE":
        raise RecoveredAnalysisError("original historical status changed")
    if manifest.get("git_commit_sha") != EXPECTED_ORIGINAL_IMPLEMENTATION:
        raise RecoveredAnalysisError("original implementation identity mismatch")
    if recovery_summary.get("recovery_status") != "RECOVERED / VALID" or recovery_summary.get("valid_outputs") != 1 or recovery_summary.get("evaluations_persisted") != 1:
        raise RecoveredAnalysisError("recovery is not exactly one valid evaluated observation")
    if recovery_manifest.get("recovery_protocol_sha256") != EXPECTED_RECOVERY_PROTOCOL_SHA or recovery_manifest.get("original_round_b_protocol_sha256") != EXPECTED_ROUND_B_PROTOCOL_SHA:
        raise RecoveredAnalysisError("recovery protocol linkage mismatch")
    return summary, {"original": manifest, "recovery": recovery_manifest}, runs, evaluations


def compose_recovered_view(original: Path, recovery: Path) -> dict[str, Any]:
    summary, manifests, runs, evaluations = _verify_sources(original, recovery)
    plan = _json(original / "execution_plan.json")
    expected = _expected_final_slots(plan)
    original_valid = [run for run in runs if run.get("validation_status") == "valid"]
    original_failed = [run for run in runs if run.get("provider_error")]
    if len(original_valid) != 71 or len(original_failed) != 1:
        raise RecoveredAnalysisError("original valid/provider-failure partition mismatch")
    failed = original_failed[0]
    failed_identity = (failed["global_execution_index"], failed["scenario_id"], str(failed["repetition_id"]), failed["condition_id"], failed["stage_id"])
    if failed_identity != RECOVERED_SLOT or failed.get("parsed_candidate_response") is not None:
        raise RecoveredAnalysisError("original failed slot identity/content mismatch")
    recovered = _json(recovery / "recovery_run.json")
    recovered_eval = _json(recovery / "recovery_evaluation.json")
    recovered_identity = (recovered["original_global_execution_index"], recovered["scenario_id"], str(recovered["repetition_id"]), recovered["condition_id"], recovered["stage_id"])
    if recovered_identity != RECOVERED_SLOT or recovered.get("validation_status") != "valid" or recovered.get("provider_error") is not None:
        raise RecoveredAnalysisError("recovered observation identity/validity mismatch")
    if (recovered_eval["original_global_execution_index"], recovered_eval["scenario_id"], str(recovered_eval["repetition_id"]), recovered_eval["condition_id"]) != RECOVERED_SLOT[:4]:
        raise RecoveredAnalysisError("recovered evaluation identity mismatch")
    derived_recovered = {**recovered, "global_execution_index": recovered["original_global_execution_index"]}
    combined = original_valid + [derived_recovered]
    keys = [_slot_key(run) for run in combined]
    if len(combined) != 72 or len(set(keys)) != 72 or set(keys) != set(expected):
        raise RecoveredAnalysisError("recovered view has missing, duplicate, or unexpected final slots")
    counts = Counter(run["condition_id"] for run in combined)
    if counts != Counter({condition: 12 for condition in FINAL_CONDITIONS}):
        raise RecoveredAnalysisError("recovered condition counts are imbalanced")
    evaluation_keys = {(item["scenario_id"], str(item["repetition_id"]), item["condition_id"]) for item in evaluations}
    evaluation_keys.add((recovered_eval["scenario_id"], str(recovered_eval["repetition_id"]), recovered_eval["condition_id"]))
    if len(evaluation_keys) != 72:
        raise RecoveredAnalysisError("recovered evaluation coverage is not 72 unique slots")
    return {"summary": summary, "manifests": manifests, "plan": plan, "runs": combined, "original_evaluation_count": len(evaluations), "condition_counts": dict(counts)}


def _ledger(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scenarios = _dev_truth()
    rows: list[dict[str, Any]] = []
    for run in sorted(runs, key=lambda item: item["global_execution_index"]):
        scenario = scenarios[run["scenario_id"]]
        truth = {label["decision_id"]: label for label in scenario["private"]["decision_labels"]}
        visible_decision_ids = {decision["id"] for decision in scenario["candidate"]["decisions"]}
        predictions = run["parsed_candidate_response"]["decisions"]
        predicted_ids = [prediction["decision_id"] for prediction in predictions]
        if set(truth) != visible_decision_ids or len(predicted_ids) != len(set(predicted_ids)) or set(predicted_ids) != visible_decision_ids:
            raise RecoveredAnalysisError(f"decision coverage mismatch: {run['scenario_id']} {run['condition_id']}")
        for prediction in predictions:
            label = truth[prediction["decision_id"]]
            rows.append({
                "scenario_id": run["scenario_id"], "repetition_id": str(run["repetition_id"]),
                "condition_id": run["condition_id"], "stage_id": run["stage_id"],
                "global_execution_index": run["global_execution_index"], "decision_id": prediction["decision_id"],
                "infrastructure_recovered": bool(run.get("infrastructure_recovered", False)),
                "true_materially_dependent": label["materially_dependent"],
                "predicted_materially_dependent": prediction["materially_dependent"],
                "true_still_justified": label["still_justified"],
                "predicted_still_justified": prediction["still_justified"],
                "true_dependency_strength": label["dependency_strength"],
                "predicted_dependency_strength": prediction["dependency_strength"],
            })
    expected_rows = sum(len(scenario["private"]["decision_labels"]) for scenario in scenarios.values()) * len(FINAL_CONDITIONS)
    if len(rows) != expected_rows:
        raise RecoveredAnalysisError("decision ledger cardinality mismatch")
    return rows


def _confusion(row: dict[str, Any]) -> str:
    truth, prediction = row["true_materially_dependent"], row["predicted_materially_dependent"]
    return "TP" if truth and prediction else "FN" if truth else "FP" if prediction else "TN"


def _sensitivity(ledger: list[dict[str, Any]], comparisons: dict[str, Any]) -> dict[str, Any]:
    recovered_rows = [row for row in ledger if row["infrastructure_recovered"]]
    confusion = Counter(_confusion(row) for row in recovered_rows)
    direct = {
        "TP": confusion["TP"], "TN": confusion["TN"], "FP": confusion["FP"], "FN": confusion["FN"],
        "still_justified_errors": sum(row["true_still_justified"] != row["predicted_still_justified"] for row in recovered_rows),
        "dependency_strength_errors": sum(row["true_dependency_strength"] != row["predicted_dependency_strength"] for row in recovered_rows),
        "unique_binary_failure_units": sorted({f"{row['scenario_id']}/{row['decision_id']}" for row in recovered_rows if row["true_materially_dependent"] != row["predicted_materially_dependent"]}),
    }
    affected = {}
    for name, control, candidate in CONTRASTS:
        if "RC0" not in (control, candidate):
            continue
        control_rows = [row for row in ledger if row["condition_id"] == control]
        candidate_rows = [row for row in ledger if row["condition_id"] == candidate]
        reduced_control = [row for row in control_rows if row["scenario_id"] != "dev-002"]
        reduced_candidate = [row for row in candidate_rows if row["scenario_id"] != "dev-002"]
        leave_slot_status = classify_contrast(reduced_control, reduced_candidate, True)["status"]
        affected[name] = {
            "final_status": comparisons[name]["status"],
            "leave_recovered_scenario_gate_status_for_sensitivity_only": leave_slot_status,
            "pivotal": leave_slot_status != comparisons[name]["status"],
            "recovered_scenario_improved_units": [unit for unit in comparisons[name]["improved_units"] if unit["scenario_id"] == "dev-002"],
            "recovered_scenario_regressed_units": [unit for unit in comparisons[name]["regressed_units"] if unit["scenario_id"] == "dev-002"],
            "recovered_scenario_new_material_false_negative_units": [unit for unit in comparisons[name]["new_material_false_negative_units"] if unit["scenario_id"] == "dev-002"],
            "note": "This is not a classification of the original 71-observation view.",
        }
    return {
        "original_view_status": "PARTIAL / NON-CLASSIFIABLE",
        "recovered_slot": {"original_global_execution_index": 11, "scenario_id": "dev-002", "repetition_id": "1", "condition_id": "RC0", "stage_id": "RC0_STAGE2"},
        "affected_contrasts": affected,
        "direct_metric_error_contribution": direct,
        "recovered_prediction_rows": len(recovered_rows),
    }


def analyze_recovered(original: Path, recovery: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise RecoveredAnalysisError("analysis output directory already exists")
    original_before, recovery_before = _source_hashes(original), _source_hashes(recovery)
    view = compose_recovered_view(original, recovery)
    ledger = _ledger(view["runs"])
    by_condition = {condition: [row for row in ledger if row["condition_id"] == condition] for condition in FINAL_CONDITIONS}
    metrics = {condition: _condition_metrics(by_condition[condition]) for condition in FINAL_CONDITIONS}
    comparisons = {name: classify_contrast(by_condition[control], by_condition[candidate], True) for name, control, candidate in CONTRASTS}
    sensitivity = _sensitivity(ledger, comparisons)
    classifications = {candidate: comparisons[name]["status"] for name, _, candidate in CONTRASTS}
    manifest = {
        "analysis_version": ANALYSIS_VERSION, "analysis_implementation_sha": _git_head(),
        "original_experiment_directory": original.name, "original_experiment_version": view["manifests"]["original"]["experiment_version"],
        "original_execution_plan_sha256": view["manifests"]["original"]["execution_plan_sha256"],
        "original_implementation_sha": EXPECTED_ORIGINAL_IMPLEMENTATION,
        "recovery_experiment_directory": recovery.name, "recovery_experiment_version": view["manifests"]["recovery"]["experiment_version"],
        "recovery_implementation_sha": view["manifests"]["recovery"]["recovery_implementation_git_sha"],
        "recovery_protocol_sha256": EXPECTED_RECOVERY_PROTOCOL_SHA,
        "round_b_protocol_sha256": EXPECTED_ROUND_B_PROTOCOL_SHA,
        "original_experiment_status": "INCOMPLETE / INFRASTRUCTURE",
        "contains_infrastructure_recovered_observation": True, "out_of_original_order_recovery_count": 1,
        "recovered_observation_count": 1, "original_global_execution_index": 11,
        "recovered_scenario_id": "dev-002", "recovered_condition_id": "RC0", "recovered_stage_id": "RC0_STAGE2",
        "original_valid_evaluable_observations": 71, "total_evaluable_final_observations": 72,
        "unique_final_slot_count": 72, "missing_final_slots": 0, "duplicate_final_slots": 0,
        "condition_counts": view["condition_counts"], "decision_ledger_rows": len(ledger),
        "claim_boundary": "Round B DEV screening only; qualified recovered view, not uninterrupted execution or generalization evidence.",
    }
    analysis = {
        "analysis_version": ANALYSIS_VERSION, "screening_complete": True,
        "per_condition": metrics, "precommitted_comparisons": comparisons,
        "screening_classifications": classifications, "confirmation_authorized": False,
        "claim_boundary": manifest["claim_boundary"],
    }
    output.mkdir()
    (output / "recovered_screening_manifest.json").write_bytes(_canonical_json(manifest))
    (output / "recovered_analysis.json").write_bytes(_canonical_json(analysis))
    (output / "recovery_sensitivity.json").write_bytes(_canonical_json(sensitivity))
    with (output / "recovered_decision_prediction_ledger.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(ledger[0]), lineterminator="\n"); writer.writeheader(); writer.writerows(ledger)
    report = [
        "# Recovered Round B v0.2 Screening Report", "",
        "DEV screening only. This qualified view contains one infrastructure-recovered, out-of-original-order observation and is not equivalent to an uninterrupted run or evidence of generalization.", "",
        "## Integrity", "", "The immutable original remains `INCOMPLETE / INFRASTRUCTURE`. The recovered view contains 71 original evaluable final observations plus one valid recovery, with 72 unique final slots and no missing or duplicate slots.", "",
        "## Per-condition core metrics", "", "| Condition | TP | TN | FP | FN | Precision | Recall | F1 | Still-justified errors | Strength errors |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for condition in FINAL_CONDITIONS:
        value = metrics[condition]; report.append(f"| {condition} | {value['TP']} | {value['TN']} | {value['FP']} | {value['FN']} | {value['precision']:.6f} | {value['recall']:.6f} | {value['f1']:.6f} | {value['still_justified_errors']} | {value['dependency_strength_errors']} |")
    report.extend(["", "## Frozen contrasts", "", "| Contrast | Status | Improved units | Regressed units | New material false negatives |", "|---|---|---:|---:|---:|"])
    for name, _, _ in CONTRASTS:
        value = comparisons[name]; report.append(f"| {name.replace('_vs_', ' → ')} | {value['status']} | {len(value['improved_units'])} | {len(value['regressed_units'])} | {len(value['new_material_false_negative_units'])} |")
    report.extend(["", "## Recovery sensitivity", "", f"Recovered slot: `dev-002 / RC0 / RC0_STAGE2 / original index 11`. Direct contribution: `{json.dumps(sensitivity['direct_metric_error_contribution'], sort_keys=True)}`."])
    for name, value in sensitivity["affected_contrasts"].items():
        report.append(f"- {name}: final `{value['final_status']}`; pivotal `{str(value['pivotal']).lower()}`. The leave-slot value is sensitivity-only, not a classification of the partial original view.")
    report.extend(["", "## Claim boundary", "", "These results apply only to the frozen DEV screening contrasts. They do not establish generalization, architectural necessity, production readiness, or transport reliability. No confirmation experiment is authorized by this analysis.", ""])
    (output / "RECOVERED_ROUND_B_REPORT.md").write_text("\n".join(report), encoding="utf-8", newline="\n")
    if _source_hashes(original) != original_before or _source_hashes(recovery) != recovery_before:
        raise RecoveredAnalysisError("source experiment artifacts changed during analysis")
    return {"manifest": manifest, "analysis": analysis, "sensitivity": sensitivity}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Round B v0.2 recovered screening analysis")
    parser.add_argument("--original-dir", type=Path, required=True)
    parser.add_argument("--recovery-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = analyze_recovered(args.original_dir, args.recovery_dir, args.output_dir)
        print(json.dumps({"status": "COMPLETE", "observations": result["manifest"]["total_evaluable_final_observations"]}, sort_keys=True))
        return 0
    except (RecoveredAnalysisError, OSError, ValueError, KeyError) as exc:
        print(str(exc), file=__import__("sys").stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
