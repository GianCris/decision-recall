from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib.metadata import version as package_version
from pathlib import Path
from time import perf_counter, sleep
from typing import Any, Callable

from dr_bench import candidate_view, evaluate_discovery, load_scenario

from .baselines import BASE_TASK_PROMPT
from .config import ExperimentConfig
from .dev_experiment import (
    DELIVERY_BACKOFF_SECONDS, DELIVERY_POLICY_VERSION, INTER_CALL_DELAY_SECONDS,
    MAX_DELIVERY_ATTEMPTS, MODEL_ID, PROJECT_ID, LOCATION, SDK_PACKAGE, SDK_VERSION,
    TRANSPORT_ATTEMPTS, TRANSPORT_TIMEOUT_MS, TRANSPORT_TIMEOUT_SECONDS,
    _append_jsonl, _dev_adapter_factory, run_delivery_attempts,
)
from .output import (
    DISCOVERY_RESPONSE_JSON_SCHEMA, DISCOVERY_RESPONSE_MIME_TYPE,
    DISCOVERY_RESPONSE_SCHEMA_VERSION, OutputValidationError, parse_discovery_response,
)
from .records import RunRecord
from .runner import with_structured_output_metadata

EXPERIMENT_VERSION = "mechanism-tournament-a1-v0.1"
PROTOCOL_PATH = Path("docs/MECHANISM_TOURNAMENT_V0.1.md")
DEV_SCENARIOS = tuple(f"dev-{number:03d}" for number in range(1, 13))
CONDITION_ORDER = ("M0", "R1", "M1", "M2", "M3")
TOTAL_SLOTS = 60
PLAN_FILENAME = "execution_plan.json"
MANIFEST_FILENAME = "experiment_manifest.json"
DELIVERY_FILENAME = "delivery_attempts.jsonl"
DELIMITER = "CANDIDATE-VISIBLE SCENARIO:\n"

M1_INSTRUCTION = """RELIANCE DISCRIMINATION:
For each decision, evaluate whether the changed premise was necessary to
support the decision at the time it was made. Consider the counterfactual in
which that premise had not been available while all other information that was
available at decision time remained unchanged.

Treat relevance, temporal proximity, participation in the decision process,
or ordinary support as insufficient by themselves to establish material
dependence."""

M2_INSTRUCTION = """DECISION SURVIVABILITY:
For each decision, evaluate the counterfactual in which the changed premise is
replaced by the updated knowledge while all other still-valid information
remains available.

Classify the decision as materially dependent only if, under that
counterfactual, its remaining support is no longer sufficient to justify the
same decision.

Do not treat the mere fact that changed information participated in the
original decision as sufficient reason to reopen it."""

ALTERNATIVE_SUPPORT_INSTRUCTION = """ALTERNATIVE SUPPORT CHECK:
Before concluding that the counterfactual decision lacks sufficient support,
explicitly search the candidate-visible information for an independent
remaining reason or evidence source that would be sufficient to justify the
same decision without relying on the changed premise."""


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


@dataclass(frozen=True)
class TournamentCondition:
    condition_id: str
    name: str
    candidate_view_mode: str
    probe_version: str
    instructions: tuple[str, ...] = ()
    base_prompt_version: str = "0.1"

    @property
    def task_instruction(self) -> str:
        return "\n\n".join((BASE_TASK_PROMPT, *self.instructions))

    @property
    def probe_instruction_sha256(self) -> str | None:
        return _sha_text("\n\n".join(self.instructions)) if self.instructions else None

    @property
    def effective_template_sha256(self) -> str:
        return _sha_text(self.task_instruction + "\n\n" + DELIMITER + "{candidate_json}")

    def build_prompt(self, visible: dict[str, Any]) -> str:
        if visible.get("phase") != "discovery" or visible.get("discovery_condition") != self.candidate_view_mode:
            raise ValueError(f"{self.condition_id} requires {self.candidate_view_mode!r} Discovery input")
        payload = json.dumps(visible, sort_keys=True, separators=(",", ":"))
        return self.task_instruction + "\n\n" + DELIMITER + payload


CONDITIONS = {
    item.condition_id: item for item in (
        TournamentCondition("M0", "Fresh Implicit Control", "implicit", "none"),
        TournamentCondition("R1", "Fresh Structured-Provenance Reference", "structured", "none"),
        TournamentCondition("M1", "Reliance Discrimination Probe", "implicit", "m1-v0.1", (M1_INSTRUCTION,)),
        TournamentCondition("M2", "Decision Survivability Probe", "implicit", "m2-v0.1", (M2_INSTRUCTION,)),
        TournamentCondition("M3", "Alternative-Support Ablation", "implicit", "m3-v0.1", (M2_INSTRUCTION, ALTERNATIVE_SUPPORT_INSTRUCTION)),
    )
}


class TournamentError(RuntimeError):
    pass


def protocol_sha256() -> str:
    return hashlib.sha256(PROTOCOL_PATH.read_bytes()).hexdigest()


def build_execution_plan() -> list[dict[str, Any]]:
    plan = []
    global_index = 1
    for scenario_index, scenario_id in enumerate(DEV_SCENARIOS, 1):
        offset = (scenario_index - 1) % len(CONDITION_ORDER)
        order = CONDITION_ORDER[offset:] + CONDITION_ORDER[:offset]
        for position, condition_id in enumerate(order, 1):
            condition = CONDITIONS[condition_id]
            scenario = load_scenario(scenario_id)
            visible = candidate_view(scenario, phase="discovery", condition=condition.candidate_view_mode)
            prompt = condition.build_prompt(visible)
            plan.append({
                "global_scientific_slot_index": global_index,
                "scenario_id": scenario_id, "scenario_index": scenario_index,
                "condition_id": condition_id, "condition_position": position,
                "candidate_view_mode": condition.candidate_view_mode, "repetition": 1,
                "effective_prompt_sha256": _sha_text(prompt),
                "effective_prompt_template_sha256": condition.effective_template_sha256,
                "probe_instruction_sha256": condition.probe_instruction_sha256,
                "instruction_sha256s": [_sha_text(value) for value in condition.instructions],
                "protocol_sha256": protocol_sha256(),
                "base_prompt_sha256": _sha_text(BASE_TASK_PROMPT),
            })
            global_index += 1
    validate_plan(plan)
    return plan


def validate_plan(plan: list[dict[str, Any]]) -> None:
    if len(plan) != TOTAL_SLOTS:
        raise TournamentError("A1 plan must contain exactly 60 scientific slots")
    for index, entry in enumerate(plan, 1):
        if entry.get("global_scientific_slot_index") != index:
            raise TournamentError("A1 slot indexes are not contiguous")
        if entry.get("scenario_id") not in DEV_SCENARIOS or entry.get("condition_id") not in CONDITIONS:
            raise TournamentError("A1 plan contains an unauthorized scenario or condition")
        if entry.get("repetition") != 1:
            raise TournamentError("A1 repetition must be exactly 1")
    if Counter(item["scenario_id"] for item in plan) != Counter({value: 5 for value in DEV_SCENARIOS}):
        raise TournamentError("each DEV scenario must occur exactly five times")
    if Counter(item["condition_id"] for item in plan) != Counter({value: 12 for value in CONDITION_ORDER}):
        raise TournamentError("each A1 condition must occur exactly twelve times")
    for scenario_index, scenario_id in enumerate(DEV_SCENARIOS, 1):
        selected = [item["condition_id"] for item in plan if item["scenario_id"] == scenario_id]
        offset = (scenario_index - 1) % 5
        if selected != list(CONDITION_ORDER[offset:] + CONDITION_ORDER[:offset]):
            raise TournamentError("A1 plan differs from the frozen cyclic order")


def condition_position_counts(plan: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    return {
        condition: {str(position): sum(item["condition_id"] == condition and item["condition_position"] == position for item in plan) for position in range(1, 6)}
        for condition in CONDITION_ORDER
    }


def _git_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def _git_branch() -> str:
    return subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def _tracked_clean() -> bool:
    return not subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], check=True, capture_output=True, text=True).stdout.strip()


def _manifest(git_sha: str, branch: str, plan_sha: str, created_at: str) -> dict[str, Any]:
    return {
        "experiment_version": EXPERIMENT_VERSION, "created_at_utc": created_at,
        "git_commit_sha": git_sha, "branch": branch,
        "mechanism_tournament_protocol_sha256": protocol_sha256(),
        "dataset_id": "DR-Bench", "dataset_version": "0.1",
        "dev_scenario_allowlist": list(DEV_SCENARIOS), "condition_ids": list(CONDITION_ORDER),
        "conditions": {
            key: {
                "name": value.name, "candidate_view_mode": value.candidate_view_mode,
                "base_prompt_version": value.base_prompt_version, "probe_version": value.probe_version,
                "probe_instruction_sha256": value.probe_instruction_sha256,
                "effective_prompt_template_sha256": value.effective_template_sha256,
            } for key, value in CONDITIONS.items()
        },
        "base_prompt_sha256": _sha_text(BASE_TASK_PROMPT),
        "M1_instruction_sha256": _sha_text(M1_INSTRUCTION),
        "M2_instruction_sha256": _sha_text(M2_INSTRUCTION),
        "alternative_support_instruction_sha256": _sha_text(ALTERNATIVE_SUPPORT_INSTRUCTION),
        "response_schema_version": DISCOVERY_RESPONSE_SCHEMA_VERSION,
        "response_schema_sha256": hashlib.sha256(json.dumps(DISCOVERY_RESPONSE_JSON_SCHEMA, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "provider": "Google Cloud Agent Platform / Vertex", "project_id": PROJECT_ID,
        "model_id": MODEL_ID, "location": LOCATION, "sdk_package": SDK_PACKAGE,
        "sdk_version": SDK_VERSION, "generation_policy": "provider defaults; no generation parameters set",
        "structured_output": {"enabled": True, "response_mime_type": DISCOVERY_RESPONSE_MIME_TYPE},
        "transport": {
            "timeout_ms": TRANSPORT_TIMEOUT_MS, "timeout_seconds": TRANSPORT_TIMEOUT_SECONDS,
            "sdk_attempts": TRANSPORT_ATTEMPTS, "max_delivery_attempts": MAX_DELIVERY_ATTEMPTS,
            "backoff_seconds": list(DELIVERY_BACKOFF_SECONDS), "jitter": False,
            "first_model_response_wins": True, "inter_scientific_slot_delay_seconds": INTER_CALL_DELAY_SECONDS,
            "concurrency": 1, "delivery_policy_version": DELIVERY_POLICY_VERSION,
        },
        "execution_plan_sha256": plan_sha, "scientific_slots_planned": TOTAL_SLOTS,
        "repetitions": [1], "condition_position_counts": condition_position_counts(build_execution_plan()),
        "classification_completeness_policy": "60 processed + 60 responses + 60 valid/evaluable + zero delivery failures + no abort",
        "sealed_holdout_exclusion": "DEV-only allowlist dev-001 through dev-012; no generic dataset path",
        "historical_response_reuse": False,
    }


def prepare(output_dir: Path) -> dict[str, Any]:
    if output_dir.exists():
        raise TournamentError("output directory already exists")
    if not _tracked_clean():
        raise TournamentError("tracked source files contain uncommitted changes")
    plan = build_execution_plan()
    plan_bytes = _canonical_json(plan)
    manifest = _manifest(_git_sha(), _git_branch(), hashlib.sha256(plan_bytes).hexdigest(), datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    output_dir.mkdir(parents=True)
    (output_dir / PLAN_FILENAME).write_bytes(plan_bytes)
    (output_dir / MANIFEST_FILENAME).write_bytes(_canonical_json(manifest))
    return manifest


def _load_prepared(output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not output_dir.is_dir():
        raise TournamentError("prepared directory does not exist")
    if any((output_dir / name).exists() for name in (DELIVERY_FILENAME, "runs.jsonl", "evaluations.jsonl", "summary.json")):
        raise TournamentError("prepared directory already contains execution artifacts")
    plan_bytes = (output_dir / PLAN_FILENAME).read_bytes()
    plan = json.loads(plan_bytes)
    manifest = json.loads((output_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    validate_plan(plan)
    plan_sha = hashlib.sha256(plan_bytes).hexdigest()
    expected = _manifest(_git_sha(), _git_branch(), plan_sha, manifest.get("created_at_utc"))
    if manifest != expected or manifest["execution_plan_sha256"] != plan_sha or not _tracked_clean():
        raise TournamentError("prepared manifest/plan/config/Git identity does not match executable state")
    return plan, manifest


def _config() -> ExperimentConfig:
    return with_structured_output_metadata(ExperimentConfig(
        version=EXPERIMENT_VERSION, model_name=MODEL_ID, repetitions=1,
        dataset_id="DR-Bench", dataset_version="0.1", scenario_ids=DEV_SCENARIOS,
        candidate_view_contract_version="0.1",
        generation_config=(("delivery_policy_version", DELIVERY_POLICY_VERSION),),
    ), True)


def run_condition(condition_id: str, scenario: dict[str, Any], adapter: Any) -> tuple[RunRecord, str]:
    condition = CONDITIONS[condition_id]
    public_scenario = {key: value for key, value in scenario.items() if key != "private"}
    visible = candidate_view(public_scenario, phase="discovery", condition=condition.candidate_view_mode)
    prompt = condition.build_prompt(visible)
    config = _config()
    response = adapter.generate(prompt, config, response_schema=DISCOVERY_RESPONSE_JSON_SCHEMA)
    decision_ids = [item["id"] for item in visible["decisions"]]
    try:
        parsed = parse_discovery_response(response.text, decision_ids)
        status, error = "valid", None
    except OutputValidationError as exc:
        parsed, status, error = None, "invalid", str(exc)
    return RunRecord(
        baseline_id=condition_id, scenario_id=visible["id"], condition=condition.candidate_view_mode,
        prompt_version=condition.probe_version, experiment_config_version=EXPERIMENT_VERSION,
        model_adapter=adapter.identifier, raw_model_response=response.text,
        parsed_candidate_response=parsed, validation_status=status, validation_error=error,
        experiment_config=config.to_dict(), model_name=response.model_name or MODEL_ID,
        model_version=response.model_version, latency_ms=response.latency_ms,
        input_tokens=response.input_tokens, output_tokens=response.output_tokens, repetition_id="1",
    ), prompt


def execute(output_dir: Path, adapter_factory: Callable[[], Any] = _dev_adapter_factory, sleep_fn: Callable[[float], None] = sleep) -> dict[str, Any]:
    plan, manifest = _load_prepared(output_dir)
    adapter = adapter_factory()
    runs: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []
    aborted = False
    interrupted: dict[str, Any] | None = None
    try:
        for entry in plan:
            stage = "planned"
            attempt_number = 0
            try:
                if entry["global_scientific_slot_index"] > 1:
                    stage = "inter_slot_pacing"
                    sleep_fn(INTER_CALL_DELAY_SECONDS)
                scenario = load_scenario(entry["scenario_id"])
                record = None
                prompt = ""
                last_error: Exception | None = None
                failure_classification = None
                failure_status = None
                started = perf_counter()
                def invoke() -> RunRecord:
                    nonlocal prompt
                    value, prompt = run_condition(entry["condition_id"], scenario, adapter)
                    return value

                def set_stage(value: str) -> None:
                    nonlocal stage
                    stage = value

                delivery = run_delivery_attempts(
                    entry, output_dir / DELIVERY_FILENAME, invoke, sleep_fn,
                    stage_callback=set_stage,
                )
                record = delivery["result"]
                attempt_number = delivery["attempts_used"]
                last_error = delivery["last_error"]
                failure_classification = delivery["failure_classification"]
                failure_status = delivery["http_status_code"]
                if record is None:
                    record = RunRecord(entry["condition_id"], entry["scenario_id"], entry["candidate_view_mode"], CONDITIONS[entry["condition_id"]].probe_version, EXPERIMENT_VERSION, adapter.identifier, "", None, "provider_error", provider_error=f"{type(last_error).__name__}: {last_error}", experiment_config=_config().to_dict(), model_name=MODEL_ID, latency_ms=(perf_counter() - started) * 1000, repetition_id="1")
                if prompt and _sha_text(prompt) != entry["effective_prompt_sha256"]:
                    raise TournamentError("runtime effective prompt differs from frozen slot hash")
                run_value = {
                    **asdict(record), **entry, "git_commit_sha": manifest["git_commit_sha"],
                    "protocol_sha256": manifest["mechanism_tournament_protocol_sha256"],
                    "plan_sha256": manifest["execution_plan_sha256"],
                    "final_effective_prompt_sha256": _sha_text(prompt) if prompt else None,
                    "response_schema_sha256": manifest["response_schema_sha256"],
                    "response_present": record.validation_status != "provider_error",
                    "delivery_attempts_used": attempt_number,
                    "terminal_delivery_state": "provider_delivery_failed" if record.validation_status == "provider_error" else "model_response_obtained",
                    "terminal_failure_classification": failure_classification if record.validation_status == "provider_error" else None,
                }
                stage = "run_record_persisting"
                _append_jsonl(output_dir / "runs.jsonl", run_value)
                runs.append(run_value)
                if record.validation_status == "valid":
                    stage = "evaluation_persisting"
                    evaluation = asdict(evaluate_discovery(scenario, record.parsed_candidate_response))
                    value = {"global_scientific_slot_index": entry["global_scientific_slot_index"], "scenario_id": entry["scenario_id"], "condition_id": entry["condition_id"], "repetition": 1, "evaluation": evaluation}
                    _append_jsonl(output_dir / "evaluations.jsonl", value)
                    evaluations.append(value)
            except KeyboardInterrupt:
                aborted = True
                interrupted = {**entry, "abort_reason": "operator_interrupt", "lifecycle_stage": stage, "delivery_attempt_number": attempt_number}
                _append_jsonl(output_dir / DELIVERY_FILENAME, {**interrupted, "event": "experiment_interrupted"})
                break
    finally:
        if hasattr(adapter, "close"):
            adapter.close()
    summary = {
        "experiment_version": EXPERIMENT_VERSION,
        "experiment_status": "aborted" if aborted else "completed",
        "scientific_slots_planned": TOTAL_SLOTS, "scientific_slots_processed": len(runs),
        "model_responses": sum(run["response_present"] for run in runs),
        "valid_responses": sum(run["validation_status"] == "valid" for run in runs),
        "invalid_responses": sum(run["validation_status"] == "invalid" for run in runs),
        "provider_delivery_failures": sum(run["validation_status"] == "provider_error" for run in runs),
        "classification_eligible": not aborted and len(runs) == 60 and len(evaluations) == 60,
        "classification_status": None if not aborted and len(evaluations) == 60 else "A1_CLASSIFICATION_INCOMPLETE",
        "abort_reason": "operator_interrupt" if aborted else None, "interrupted_position": interrupted,
        "model_call_count": sum(run["delivery_attempts_used"] for run in runs) + (attempt_number if aborted and (not runs or interrupted and interrupted["global_scientific_slot_index"] > len(runs)) else 0),
        "input_tokens": sum(run["input_tokens"] or 0 for run in runs),
        "output_tokens": sum(run["output_tokens"] or 0 for run in runs),
        "latency_ms": sum(run["latency_ms"] or 0 for run in runs),
        "condition_position_counts": manifest["condition_position_counts"],
    }
    (output_dir / "summary.json").write_bytes(_canonical_json(summary))
    return summary


def analyze(output_dir: Path, analysis_dir: Path) -> dict[str, Any]:
    if analysis_dir.exists():
        raise TournamentError("analysis directory already exists")
    plan = json.loads((output_dir / PLAN_FILENAME).read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    runs = [json.loads(line) for line in (output_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines() if line]
    validate_plan(plan)
    if hashlib.sha256((output_dir / PLAN_FILENAME).read_bytes()).hexdigest() != manifest.get("execution_plan_sha256"):
        raise TournamentError("analysis source plan hash mismatch")
    complete = bool(summary.get("classification_eligible")) and len(runs) == TOTAL_SLOTS
    ledger: list[dict[str, Any]] = []
    for run in sorted(runs, key=lambda item: item["global_scientific_slot_index"]):
        if run["validation_status"] != "valid":
            continue
        scenario = load_scenario(run["scenario_id"])
        truth = {item["decision_id"]: item for item in scenario["private"]["decision_labels"]}
        for prediction in sorted(run["parsed_candidate_response"]["decisions"], key=lambda item: item["decision_id"]):
            label = truth[prediction["decision_id"]]
            ledger.append({
                "scenario_id": run["scenario_id"], "decision_id": prediction["decision_id"],
                "condition_id": run["condition_id"], "repetition": run["repetition"],
                "true_materially_dependent": label["materially_dependent"],
                "predicted_materially_dependent": prediction["materially_dependent"],
                "true_still_justified": label["still_justified"],
                "predicted_still_justified": prediction["still_justified"],
                "true_dependency_strength": label["dependency_strength"],
                "predicted_dependency_strength": prediction["dependency_strength"],
            })
    per_condition = {}
    for condition_id in CONDITION_ORDER:
        selected = [row for row in ledger if row["condition_id"] == condition_id]
        tp = sum(row["true_materially_dependent"] and row["predicted_materially_dependent"] for row in selected)
        tn = sum(not row["true_materially_dependent"] and not row["predicted_materially_dependent"] for row in selected)
        fp = sum(not row["true_materially_dependent"] and row["predicted_materially_dependent"] for row in selected)
        fn = sum(row["true_materially_dependent"] and not row["predicted_materially_dependent"] for row in selected)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        per_condition[condition_id] = {
            "decision_observations": len(selected), "TP": tp, "TN": tn, "FP": fp, "FN": fn,
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "still_justified_errors": sum(row["true_still_justified"] != row["predicted_still_justified"] for row in selected),
            "dependency_strength_errors": sum(row["true_dependency_strength"] != row["predicted_dependency_strength"] for row in selected),
            "unique_binary_failures": len({(row["scenario_id"], row["decision_id"]) for row in selected if row["true_materially_dependent"] != row["predicted_materially_dependent"]}),
        }
    m0 = [row for row in ledger if row["condition_id"] == "M0"]
    classifications = {condition_id: classify_probe(m0, [row for row in ledger if row["condition_id"] == condition_id], complete) for condition_id in ("M1", "M2", "M3")}
    disagreements = []
    m0_by_key = {(row["scenario_id"], row["decision_id"]): row for row in m0}
    for condition_id in ("R1", "M1", "M2", "M3"):
        for row in [value for value in ledger if value["condition_id"] == condition_id]:
            control = m0_by_key.get((row["scenario_id"], row["decision_id"]))
            if control:
                for field in ("materially_dependent", "dependency_strength", "still_justified"):
                    if control[f"predicted_{field}"] != row[f"predicted_{field}"]:
                        disagreements.append({"scenario_id": row["scenario_id"], "decision_id": row["decision_id"], "condition_id": condition_id, "field": field, "M0_prediction": control[f"predicted_{field}"], "condition_prediction": row[f"predicted_{field}"]})
    analysis = {
        "analysis_version": "mechanism-tournament-a1-analysis-v0.1",
        "classification_eligible": complete,
        "classification_status": None if complete else "A1_CLASSIFICATION_INCOMPLETE",
        "execution_completeness": summary,
        "per_condition": per_condition, "probe_classifications": classifications,
        "decision_observations": len(ledger), "unique_scenario_decision_units": len({(row["scenario_id"], row["decision_id"]) for row in ledger}),
        "model_call_count": summary.get("model_call_count"), "condition_position_counts": manifest["condition_position_counts"],
        "claim_boundary": "A1 development screening; descriptive, not generalization evidence",
    }
    analysis_dir.mkdir()
    fields = list(ledger[0]) if ledger else ["scenario_id", "decision_id", "condition_id"]
    with (analysis_dir / "decision_prediction_ledger.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(ledger)
    (analysis_dir / "m0_condition_disagreements.json").write_bytes(_canonical_json(disagreements))
    (analysis_dir / "a1_analysis.json").write_bytes(_canonical_json(analysis))
    (analysis_dir / "A1_REPORT.md").write_text(
        "# Mechanism Tournament A1 Analysis\n\nDevelopment screening only; not generalization evidence.\n\n"
        f"Classification eligible: `{complete}`. Decision observations and unique scenario-decision units are reported separately.\n",
        encoding="utf-8", newline="\n",
    )
    return analysis


def classify_probe(m0_rows: list[dict[str, Any]], probe_rows: list[dict[str, Any]], complete: bool = True) -> dict[str, Any]:
    if not complete:
        return {"status": "A1_CLASSIFICATION_INCOMPLETE", "improved_units": [], "regressed_units": [], "material_false_negatives": []}
    m0 = {(row["scenario_id"], row["decision_id"]): row for row in m0_rows}
    probe = {(row["scenario_id"], row["decision_id"]): row for row in probe_rows}
    if set(m0) != set(probe):
        raise TournamentError("M0 and probe decision units differ")
    operational = ("materially_dependent", "still_justified")
    improved: dict[tuple[str, str], list[str]] = defaultdict(list)
    regressed: dict[tuple[str, str], list[str]] = defaultdict(list)
    material_fns = []
    opportunities = set()
    for key in sorted(m0):
        for field in operational:
            truth = m0[key][f"true_{field}"]
            m0_correct = m0[key][f"predicted_{field}"] == truth
            probe_correct = probe[key][f"predicted_{field}"] == truth
            if not m0_correct:
                opportunities.add(key)
            if not m0_correct and probe_correct:
                improved[key].append(field)
            if m0_correct and not probe_correct:
                regressed[key].append(field)
        if m0[key]["true_materially_dependent"] and not probe[key]["predicted_materially_dependent"] and m0[key]["predicted_materially_dependent"]:
            material_fns.append({"scenario_id": key[0], "decision_id": key[1]})
    improved_values = [{"scenario_id": key[0], "decision_id": key[1], "fields": fields} for key, fields in improved.items()]
    regressed_values = [{"scenario_id": key[0], "decision_id": key[1], "fields": fields} for key, fields in regressed.items()]
    if improved and not regressed:
        status = "PROMISING"
    elif improved and len(regressed) == 1:
        status = "AMBIGUOUS / NEEDS CONFIRMATION"
    elif not opportunities and not regressed:
        status = "AMBIGUOUS / INSUFFICIENT CONTEMPORARY SIGNAL"
    elif material_fns:
        status = "FAIL / SAFETY REGRESSION"
    else:
        status = "FAIL / DO NOT ADVANCE"
    return {"status": status, "improved_units": improved_values, "regressed_units": regressed_values, "material_false_negatives": material_fns, "contemporary_M0_opportunity_units": len(opportunities)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen Decision Recall Mechanism Tournament A1 scaffold")
    parser.add_argument("--output-dir", type=Path, required=True)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--prepare", action="store_true")
    actions.add_argument("--execute", action="store_true")
    actions.add_argument("--analyze", action="store_true")
    parser.add_argument("--analysis-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.prepare:
            print(json.dumps(prepare(args.output_dir), sort_keys=True))
            return 0
        if args.execute:
            print(json.dumps(execute(args.output_dir), sort_keys=True))
            return 0
        if args.analyze:
            if args.analysis_dir is None:
                raise TournamentError("--analyze requires --analysis-dir")
            print(json.dumps(analyze(args.output_dir, args.analysis_dir), sort_keys=True))
            return 0
        print("Refusing without explicit --prepare or --execute.", file=sys.stderr)
        return 2
    except (TournamentError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"A1 scaffold refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
