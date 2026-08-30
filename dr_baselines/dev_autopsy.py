from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from dr_bench import evaluate_discovery, load_scenario

SOURCE_DIR = Path("dev-baseline-output-v4")
OUTPUT_DIR = Path("dev_failure_autopsy_v0.1")
SOURCE_VERSION = "dev-baselines-v0.4"
SOURCE_GIT_SHA = "2df8152a221543e93d609868ebd760f79545a3de"
PLAN_SHA = "b04496c00c3e5bc991e41b591254b73d222d430edfc30159b3deb0a4de2e40b7"
PROMPT_SHA = "2ed1e0280d3108aa9f7458bc7a21d4cf9f82ad2e6c4795d2ac516fffdb5557b1"
SCHEMA_VERSION = "discovery-response-v0.1"
SCHEMA_SHA = "c1da8e87a79950b25c57bfdd411a44c6482ec15cbadeca69b6019e7fbda52ce5"
BASELINES = ("B0", "B1")
STRENGTHS = ("independent", "supporting", "material", "critical")
META_FIELDS = ("agent_hops", "semantic_distance", "information_transformation", "boundary", "hard_negative_tags")


class AutopsyIntegrityError(RuntimeError):
    pass


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def validate_source(source_dir: Path = SOURCE_DIR) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if source_dir != SOURCE_DIR:
        raise AutopsyIntegrityError(f"source must be exactly {SOURCE_DIR}")
    required = ("experiment_manifest.json", "summary.json", "execution_plan.json", "runs.jsonl", "evaluations.jsonl")
    if not source_dir.is_dir() or any(not (source_dir / name).is_file() for name in required):
        raise AutopsyIntegrityError("official v0.4 source directory is missing or incomplete")
    manifest = _read_json(source_dir / "experiment_manifest.json")
    summary = _read_json(source_dir / "summary.json")
    expected_manifest = {
        "experiment_version": SOURCE_VERSION,
        "git_commit_sha": SOURCE_GIT_SHA,
        "execution_plan_sha256": PLAN_SHA,
        "prompt_sha256": PROMPT_SHA,
        "response_schema_version": SCHEMA_VERSION,
        "response_schema_sha256": SCHEMA_SHA,
    }
    for field, expected in expected_manifest.items():
        if manifest.get(field) != expected:
            raise AutopsyIntegrityError(f"source manifest {field} is not the frozen value")
    expected_summary = {
        "experiment_version": SOURCE_VERSION,
        "experiment_status": "completed",
        "official_result_eligible": True,
        "scientific_slots_planned": 72,
        "scientific_slots_processed": 72,
        "scientific_slots_with_model_response": 72,
        "provider_delivery_failed_slots": 0,
        "invalid_runs": 0,
    }
    for field, expected in expected_summary.items():
        if summary.get(field) != expected:
            raise AutopsyIntegrityError(f"source summary {field} is not {expected!r}")
    plan_bytes = (source_dir / "execution_plan.json").read_bytes()
    if hashlib.sha256(plan_bytes).hexdigest() != PLAN_SHA:
        raise AutopsyIntegrityError("execution plan bytes do not match the frozen SHA")
    plan = _read_json(source_dir / "execution_plan.json")
    runs = _read_jsonl(source_dir / "runs.jsonl")
    evaluations = _read_jsonl(source_dir / "evaluations.jsonl")
    if len(plan) != 72 or len(runs) != 72 or len(evaluations) != 72:
        raise AutopsyIntegrityError("official source does not contain exactly 72 plan, run, and evaluation records")
    if any(run.get("validation_status") != "valid" for run in runs):
        raise AutopsyIntegrityError("official source contains a non-valid RunRecord")
    plan_keys = {(p["global_call_index"], p["scenario_id"], p["repetition_id"], p["baseline_id"]) for p in plan}
    run_keys = {(r["global_call_index"], r["scenario_id"], r["repetition_id"], r["baseline_id"]) for r in runs}
    evaluation_keys = {(e["global_call_index"], e["scenario_id"], e["repetition_id"], e["baseline_id"]) for e in evaluations}
    if plan_keys != run_keys or plan_keys != evaluation_keys:
        raise AutopsyIntegrityError("plan, RunRecord, and evaluation slot identities differ")
    evaluations_by_key = {
        (item["global_call_index"], item["scenario_id"], item["repetition_id"], item["baseline_id"]): item["evaluation"]
        for item in evaluations
    }
    for run in runs:
        key = (run["global_call_index"], run["scenario_id"], run["repetition_id"], run["baseline_id"])
        scenario = load_scenario(run["scenario_id"])
        recomputed = asdict(evaluate_discovery(scenario, run["parsed_candidate_response"]))
        if evaluations_by_key[key] != recomputed:
            raise AutopsyIntegrityError(f"persisted evaluation differs from frozen evaluator for call {run['global_call_index']}")
    return manifest, summary, runs, evaluations


def build_ledger(runs: list[dict[str, Any]], scenarios: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in sorted(runs, key=lambda value: value["global_call_index"]):
        scenario = scenarios[run["scenario_id"]]
        truth = {item["decision_id"]: item for item in scenario["private"]["decision_labels"]}
        predictions = run["parsed_candidate_response"]["decisions"]
        if {item["decision_id"] for item in predictions} != set(truth):
            raise AutopsyIntegrityError(f"decision IDs differ for call {run['global_call_index']}")
        for prediction in sorted(predictions, key=lambda value: value["decision_id"]):
            decision_id = prediction["decision_id"]
            label = truth[decision_id]
            true_dep = label["materially_dependent"]
            pred_dep = prediction["materially_dependent"]
            confusion = "TP" if true_dep and pred_dep else "FN" if true_dep else "FP" if pred_dep else "TN"
            rows.append({
                "scenario_id": run["scenario_id"], "repetition_id": run["repetition_id"],
                "baseline_id": run["baseline_id"], "decision_id": decision_id,
                "global_call_index": run["global_call_index"], "pair_id": run["pair_id"],
                "pair_order": run["pair_order"], "order_within_pair": run["order_within_pair"],
                "true_materially_dependent": true_dep,
                "true_dependency_strength": label["dependency_strength"],
                "true_still_justified": label["still_justified"],
                "predicted_materially_dependent": pred_dep,
                "predicted_dependency_strength": prediction["dependency_strength"],
                "predicted_still_justified": prediction["still_justified"],
                "materially_dependent_correct": true_dep == pred_dep,
                "dependency_strength_correct": label["dependency_strength"] == prediction["dependency_strength"],
                "still_justified_correct": label["still_justified"] == prediction["still_justified"],
                "binary_confusion_class": confusion,
                "strength_transition": f"{label['dependency_strength']} -> {prediction['dependency_strength']}",
                "agent_hops": scenario["complexity"].get("agent_hops"),
                "semantic_distance": scenario["complexity"].get("semantic_distance"),
                "information_transformation": scenario["complexity"].get("information_transformation"),
                "boundary": scenario["complexity"].get("boundary"),
                "hard_negative_tags": "|".join(sorted(scenario["private"].get("hard_negative_types", []))),
                "decision_negative_type": label.get("negative_type"),
                "downstream": label.get("downstream"),
                "dependency_path_agent_hops": label.get("dependency_path", {}).get("agent_hops"),
            })
    return rows


def _metric_summary(rows: list[dict[str, Any]], baseline: str) -> dict[str, Any]:
    selected = [row for row in rows if row["baseline_id"] == baseline]
    counts = Counter(row["binary_confusion_class"] for row in selected)
    tp, fp, fn = counts["TP"], counts["FP"], counts["FN"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {
        "TP": tp, "TN": counts["TN"], "FP": fp, "FN": fn,
        "precision": precision, "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "observation_level_binary_failures": fp + fn,
        "unique_scenario_decision_binary_failures": len({(r["scenario_id"], r["decision_id"]) for r in selected if not r["materially_dependent_correct"]}),
    }


def _unique_failures(rows: list[dict[str, Any]], correctness_field: str, dimension: str) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["scenario_id"], row["decision_id"], row["baseline_id"])].append(row)
    output = []
    prediction_field = {
        "binary": "predicted_materially_dependent",
        "strength": "predicted_dependency_strength",
        "still_justified": "predicted_still_justified",
    }[dimension]
    for (scenario_id, decision_id, baseline), values in sorted(groups.items()):
        failed = [value for value in values if not value[correctness_field]]
        if not failed:
            continue
        predictions = [value[prediction_field] for value in failed]
        structured_predictions = [(
            value["predicted_materially_dependent"], value["predicted_dependency_strength"],
            value["predicted_still_justified"],
        ) for value in failed]
        transitions = [value["strength_transition"] for value in failed]
        output.append({
            "error_dimension": dimension, "scenario_id": scenario_id, "decision_id": decision_id,
            "baseline_id": baseline, "repetitions_observed": len(values),
            "repetitions_failed": len(failed),
            "failed_repetition_ids": "|".join(sorted(str(value["repetition_id"]) for value in failed)),
            "failure_rate": len(failed) / len(values),
            "structured_prediction_consistent": len({str(value) for value in predictions}) == 1,
            "full_structured_prediction_consistent": len(set(structured_predictions)) == 1,
            "same_error_transition_repeated": len(set(transitions)) == 1,
            "predicted_values": "|".join(str(value) for value in predictions),
            "error_transitions": "|".join(transitions),
            **{field: failed[0][field] for field in META_FIELDS},
        })
    return output


def _strength_matrix(rows: list[dict[str, Any]], baseline: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts = Counter((row["true_dependency_strength"], row["predicted_dependency_strength"])
                     for row in rows if row["baseline_id"] == baseline)
    matrix = [{"true_strength": truth, **{predicted: counts[(truth, predicted)] for predicted in STRENGTHS}}
              for truth in STRENGTHS]
    transitions = {f"{truth} -> {predicted}": count for (truth, predicted), count in sorted(counts.items())}
    return matrix, transitions


def _disagreements(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        grouped[(row["scenario_id"], str(row["repetition_id"]), row["decision_id"])][row["baseline_id"]] = row
    output = []
    fields = (
        ("materially_dependent", "true_materially_dependent", "predicted_materially_dependent", "materially_dependent_correct"),
        ("dependency_strength", "true_dependency_strength", "predicted_dependency_strength", "dependency_strength_correct"),
        ("still_justified", "true_still_justified", "predicted_still_justified", "still_justified_correct"),
    )
    for key, pair in sorted(grouped.items()):
        if set(pair) != set(BASELINES):
            raise AutopsyIntegrityError(f"unmatched B0/B1 decision unit: {key}")
        b0, b1 = pair["B0"], pair["B1"]
        for field, truth_field, prediction_field, correct_field in fields:
            c0, c1 = b0[correct_field], b1[correct_field]
            category = "both_correct" if c0 and c1 else "B0_correct_B1_wrong" if c0 else "B0_wrong_B1_correct" if c1 else "both_wrong"
            output.append({
                "scenario_id": key[0], "repetition_id": key[1], "decision_id": key[2], "field": field,
                "truth": b0[truth_field], "B0_prediction": b0[prediction_field], "B1_prediction": b1[prediction_field],
                "predictions_disagree": b0[prediction_field] != b1[prediction_field], "correctness_category": category,
                "both_wrong_same_prediction": category == "both_wrong" and b0[prediction_field] == b1[prediction_field],
                "both_wrong_different_prediction": category == "both_wrong" and b0[prediction_field] != b1[prediction_field],
            })
    return output


def _controls(rows: list[dict[str, Any]], failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["scenario_id"], row["decision_id"], row["baseline_id"])].append(row)
    output: list[dict[str, Any]] = []
    correctness = {"binary": "materially_dependent_correct", "strength": "dependency_strength_correct"}
    for failure in failures:
        dimension = failure["error_dimension"]
        candidates = [values[0] for key, values in groups.items()
                      if key[2] == failure["baseline_id"] and all(value[correctness[dimension]] for value in values)]
        scopes: list[tuple[str, tuple[str, ...], list[dict[str, Any]]]] = []
        for field in META_FIELDS:
            matches = [row for row in candidates if row[field] == failure[field]]
            scopes.append((f"individual:{field}", (field,), matches))
        for tag in filter(None, str(failure["hard_negative_tags"]).split("|")):
            matches = [row for row in candidates if tag in str(row["hard_negative_tags"]).split("|")]
            scopes.append((f"individual:hard_negative_tag={tag}", ("hard_negative_tags",), matches))
        maximum: list[tuple[str, tuple[str, ...], list[dict[str, Any]]]] = []
        for size in range(len(META_FIELDS), 0, -1):
            for fields in combinations(META_FIELDS, size):
                matches = [row for row in candidates if all(row[field] == failure[field] for field in fields)]
                if matches:
                    maximum.append(("maximum_exact:" + "+".join(fields), fields, matches))
            if maximum:
                break
        scopes.extend(maximum)
        for scope, fields, matches in scopes:
            if not matches:
                output.append({
                    "failure_dimension": dimension, "failure_scenario_id": failure["scenario_id"],
                    "failure_decision_id": failure["decision_id"], "baseline_id": failure["baseline_id"],
                    "match_scope": scope, "matched_fields": "|".join(fields), "control_match_count": 0,
                    "control_scenario_id": "", "control_decision_id": "", "control_repetitions": "",
                })
            else:
                for control in sorted(matches, key=lambda row: (row["scenario_id"], row["decision_id"])):
                    output.append({
                        "failure_dimension": dimension, "failure_scenario_id": failure["scenario_id"],
                        "failure_decision_id": failure["decision_id"], "baseline_id": failure["baseline_id"],
                        "match_scope": scope, "matched_fields": "|".join(fields), "control_match_count": len(matches),
                        "control_scenario_id": control["scenario_id"], "control_decision_id": control["decision_id"],
                        "control_repetitions": len(groups[(control["scenario_id"], control["decision_id"], control["baseline_id"])]),
                    })
    return output


def _metadata_breakdowns(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "warning": "Metadata slices overlap and are descriptive; they are not independent or causal evidence.",
        "dimensions": {},
    }
    correctness = {
        "binary": "materially_dependent_correct", "strength": "dependency_strength_correct",
        "still_justified": "still_justified_correct",
    }
    for field in META_FIELDS + ("decision_negative_type", "downstream", "dependency_path_agent_hops"):
        result["dimensions"][field] = {}
        for baseline in BASELINES:
            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                if row["baseline_id"] == baseline:
                    groups[str(row[field])].append(row)
            result["dimensions"][field][baseline] = {
                value: {
                    dimension: {
                        "observation_count": len(values),
                        "observation_errors": sum(not item[correct_field] for item in values),
                        "observation_error_rate": sum(not item[correct_field] for item in values) / len(values),
                        "unique_scenario_decision_count": len({(item["scenario_id"], item["decision_id"]) for item in values}),
                        "unique_scenario_decision_errors": len({(item["scenario_id"], item["decision_id"]) for item in values if not item[correct_field]}),
                    }
                    for dimension, correct_field in correctness.items()
                }
                for value, values in sorted(groups.items())
            }
    return result


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str] | None = None) -> None:
    fieldnames = list(fields or (rows[0].keys() if rows else []))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def generate_autopsy(source_dir: Path = SOURCE_DIR, output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    manifest, source_summary, runs, _ = validate_source(source_dir)
    if output_dir.exists():
        raise AutopsyIntegrityError("derived output directory already exists")
    scenario_ids = sorted({run["scenario_id"] for run in runs})
    scenarios = {scenario_id: load_scenario(scenario_id) for scenario_id in scenario_ids}
    ledger = build_ledger(runs, scenarios)
    binary_failures = [row for row in ledger if not row["materially_dependent_correct"]]
    unique_binary = _unique_failures(ledger, "materially_dependent_correct", "binary")
    unique_strength = _unique_failures(ledger, "dependency_strength_correct", "strength")
    unique_still = _unique_failures(ledger, "still_justified_correct", "still_justified")
    binary_failure_baselines: dict[tuple[str, str], set[str]] = defaultdict(set)
    for failure in unique_binary:
        binary_failure_baselines[(failure["scenario_id"], failure["decision_id"])].add(failure["baseline_id"])
    for failure in unique_binary:
        baselines = binary_failure_baselines[(failure["scenario_id"], failure["decision_id"])]
        failure["baseline_failure_scope"] = "shared_B0_B1" if baselines == set(BASELINES) else f"{failure['baseline_id']}_only"
    strength_errors = [row for row in ledger if not row["dependency_strength_correct"]]
    still_errors = [row for row in ledger if not row["still_justified_correct"]]
    disagreements = _disagreements(ledger)
    reproducibility = sorted(unique_binary + unique_strength + unique_still,
                             key=lambda row: (row["error_dimension"], row["scenario_id"], row["decision_id"], row["baseline_id"]))
    controls = _controls(ledger, unique_binary + unique_strength)
    metadata = _metadata_breakdowns(ledger)
    strength: dict[str, Any] = {}
    still: dict[str, Any] = {}
    matrices: dict[str, list[dict[str, Any]]] = {}
    for baseline in BASELINES:
        selected = [row for row in ledger if row["baseline_id"] == baseline]
        matrix, transitions = _strength_matrix(ledger, baseline)
        matrices[baseline] = matrix
        strength[baseline] = {
            "accuracy": sum(row["dependency_strength_correct"] for row in selected) / len(selected),
            "observation_level_errors": sum(not row["dependency_strength_correct"] for row in selected),
            "unique_scenario_decision_errors": len({(row["scenario_id"], row["decision_id"]) for row in selected if not row["dependency_strength_correct"]}),
            "confusion_counts": transitions,
        }
        still[baseline] = {
            "accuracy": sum(row["still_justified_correct"] for row in selected) / len(selected),
            "observation_level_errors": sum(not row["still_justified_correct"] for row in selected),
            "unique_scenario_decision_errors": len({(row["scenario_id"], row["decision_id"]) for row in selected if not row["still_justified_correct"]}),
            "confusion_counts": dict(Counter(f"{row['true_still_justified']} -> {row['predicted_still_justified']}" for row in selected)),
        }
    disagreement_summary = {}
    for field in ("materially_dependent", "dependency_strength", "still_justified"):
        selected = [row for row in disagreements if row["field"] == field]
        categories = Counter(row["correctness_category"] for row in selected)
        disagreement_summary[field] = {
            "total_units": len(selected), "total_disagreements": sum(row["predictions_disagree"] for row in selected),
            "B0_wrong_B1_correct": categories["B0_wrong_B1_correct"],
            "B0_correct_B1_wrong": categories["B0_correct_B1_wrong"],
            "both_wrong": categories["both_wrong"], "both_correct": categories["both_correct"],
            "both_wrong_same_prediction": sum(row["both_wrong_same_prediction"] for row in selected),
            "both_wrong_different_prediction": sum(row["both_wrong_different_prediction"] for row in selected),
        }
    error_crosstab = Counter(
        (not row["materially_dependent_correct"], not row["dependency_strength_correct"], not row["still_justified_correct"])
        for row in ledger
    )
    summary = {
        "analysis_id": "DEV Failure Autopsy v0.1 — FORENSIC / DESCRIPTIVE ONLY",
        "source_integrity": {
            "source_directory": str(source_dir), "experiment_version": manifest["experiment_version"],
            "git_commit_sha": manifest["git_commit_sha"], "execution_plan_sha256": manifest["execution_plan_sha256"],
            "prompt_sha256": manifest["prompt_sha256"], "response_schema_version": manifest["response_schema_version"],
            "response_schema_sha256": manifest["response_schema_sha256"],
            "official_result_eligible": source_summary["official_result_eligible"],
        },
        "units": {
            "scientific_runs_analyzed": len(runs), "decision_level_observations_analyzed": len(ledger),
            "unique_scenario_decision_units": len({(row["scenario_id"], row["decision_id"]) for row in ledger}),
            "unique_baseline_scenario_decision_units": len({(row["baseline_id"], row["scenario_id"], row["decision_id"]) for row in ledger}),
            "repetitions": sorted({str(row["repetition_id"]) for row in ledger}),
        },
        "binary_results": {baseline: _metric_summary(ledger, baseline) for baseline in BASELINES},
        "strength_results": strength, "still_justified_results": still,
        "B0_B1_disagreements": disagreement_summary,
        "error_dimension_cooccurrence": {
            f"binary_error={binary_error},strength_error={strength_error},still_justified_error={still_error}": count
            for (binary_error, strength_error, still_error), count in sorted(error_crosstab.items())
        },
        "reproducibility": reproducibility,
        "metadata": {
            "artifact": "metadata_breakdowns.json",
            "warning": metadata["warning"],
        },
        "limitations": [
            "DEV contains only 12 scenarios.",
            "Repetitions are repeated observations, not independent scenarios.",
            "Metadata slices overlap.",
            "No hidden reasoning traces exist.",
            "This analysis is descriptive, not causal.",
            "B1 is a provenance-enabled baseline/reference, not an oracle.",
            "No sealed-holdout evidence was used.",
            "The source manifest does not provide separate content hashes for runs.jsonl or evaluations.jsonl; source integrity uses the frozen manifest/plan hashes plus complete slot and evaluator consistency checks.",
        ],
    }
    output_dir.mkdir(parents=False)
    _write_csv(output_dir / "decision_prediction_ledger.csv", ledger)
    _write_csv(output_dir / "binary_failures.csv", binary_failures, ledger[0].keys())
    _write_csv(output_dir / "unique_binary_failures.csv", unique_binary)
    _write_csv(output_dir / "strength_confusion_B0.csv", matrices["B0"])
    _write_csv(output_dir / "strength_confusion_B1.csv", matrices["B1"])
    _write_csv(output_dir / "strength_errors.csv", strength_errors, ledger[0].keys())
    _write_csv(output_dir / "still_justified_errors.csv", still_errors, ledger[0].keys())
    _write_csv(output_dir / "b0_b1_disagreements.csv", disagreements)
    _write_csv(output_dir / "repetition_reproducibility.csv", reproducibility)
    _write_csv(output_dir / "failure_success_controls.csv", controls)
    _write_json(output_dir / "metadata_breakdowns.json", metadata)
    _write_json(output_dir / "autopsy_summary.json", summary)
    report = [
        "# DEV Failure Autopsy v0.1", "", "FORENSIC / DESCRIPTIVE ONLY — not a causal analysis.", "",
        f"Source: `{source_dir}/` at `{SOURCE_GIT_SHA}`; 72 official scientific runs.",
        f"Decision-level observations: {len(ledger)}; unique scenario-decision units: {summary['units']['unique_scenario_decision_units']}.", "",
        "## Results", "",
    ]
    for baseline in BASELINES:
        binary = summary["binary_results"][baseline]
        report.append(f"- {baseline} binary: TP={binary['TP']}, TN={binary['TN']}, FP={binary['FP']}, FN={binary['FN']}, precision={binary['precision']:.6f}, recall={binary['recall']:.6f}, F1={binary['f1']:.6f}.")
        report.append(f"- {baseline} strength accuracy={strength[baseline]['accuracy']:.6f}; still-justified accuracy={still[baseline]['accuracy']:.6f}.")
    report.extend([
        "", "Observation-level failures retain every repetition. Unique failure rows collapse only scenario, decision, baseline, and error dimension and report failed/observed repetitions.",
        "", "Successful controls are all exact matches on each individual frozen metadata dimension and all ties at the largest exact metadata combination with at least one match. No distance, weighting, or nearest-neighbor rule is used.",
        "", "Metadata slices overlap. Structured predictions reveal no hidden model reasoning. B1 is not an oracle. No sealed-holdout evidence was used.", "",
    ])
    (output_dir / "AUTOPSY_REPORT.md").write_text("\n".join(report), encoding="utf-8", newline="\n")
    return summary


def main() -> int:
    summary = generate_autopsy()
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
