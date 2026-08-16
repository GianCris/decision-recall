from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from google.genai import errors as genai_errors

from dr_bench import evaluate_discovery, load_scenario

from .baselines import get_baseline
from .config import ExperimentConfig
from .google_adapter import MODEL_ID, GeminiAuthenticationError, GeminiVertexAdapter
from .records import RunRecord
from .runner import run_baseline

PILOT_SCENARIOS = ("dev-005", "dev-002", "dev-006")
PILOT_BASELINES = ("B0", "B1", "B2")
PILOT_REPETITIONS = ("1",)
METRICS = (
    "dependency_precision", "dependency_recall", "dependency_f1",
    "dependency_strength_accuracy", "still_justified_accuracy",
)


@dataclass(frozen=True)
class PilotAttempt:
    scenario_id: str
    baseline_id: str
    repetition_id: str


def build_schedule(
    scenario_ids: tuple[str, ...] = PILOT_SCENARIOS,
    baseline_ids: tuple[str, ...] = PILOT_BASELINES,
    repetitions: tuple[str, ...] = PILOT_REPETITIONS,
) -> tuple[PilotAttempt, ...]:
    if scenario_ids != PILOT_SCENARIOS or baseline_ids != PILOT_BASELINES or repetitions != PILOT_REPETITIONS:
        raise ValueError("pilot matrix is frozen and cannot be changed or expanded")
    return tuple(PilotAttempt(scenario, baseline, repetition) for scenario in scenario_ids for baseline in baseline_ids for repetition in repetitions)


def pilot_config() -> ExperimentConfig:
    return ExperimentConfig(
        version="pilot-0.1", model_name=MODEL_ID, repetitions=1,
        dataset_id="DR-Bench", dataset_version="0.1", scenario_ids=PILOT_SCENARIOS,
        candidate_view_contract_version="0.1",
    )


class PilotStore:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        output_dir.mkdir(parents=True, exist_ok=False)
        self.runs_path = output_dir / "runs.jsonl"
        self.evaluations_path = output_dir / "evaluations.jsonl"
        self.summary_path = output_dir / "summary.json"

    @staticmethod
    def _append(path: Path, value: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")

    def append_run(self, record: RunRecord) -> None:
        self._append(self.runs_path, asdict(record))

    def append_evaluation(self, attempt: PilotAttempt, evaluation: Any) -> None:
        self._append(self.evaluations_path, {
            "baseline_id": attempt.baseline_id, "scenario_id": attempt.scenario_id,
            "repetition_id": attempt.repetition_id, "evaluation": asdict(evaluation),
        })

    def write_summary(self, summary: dict[str, Any]) -> None:
        self.summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _usage(records: list[RunRecord]) -> dict[str, Any]:
    def total(field: str) -> int | float | None:
        values = [getattr(record, field) for record in records if getattr(record, field) is not None]
        return sum(values) if values else None
    return {
        "input_tokens": total("input_tokens"), "output_tokens": total("output_tokens"),
        "latency_ms": total("latency_ms"),
    }


def _delta(right: dict[str, Any], left: dict[str, Any], metrics: tuple[str, ...]) -> dict[str, float | None]:
    return {metric: None if right.get(metric) is None or left.get(metric) is None else right[metric] - left[metric] for metric in metrics}


def build_summary(
    records: list[RunRecord],
    evaluations: dict[tuple[str, str, str], Any],
    scenarios: dict[str, dict[str, Any]],
    systemic_failure: str | None,
) -> dict[str, Any]:
    per_baseline: dict[str, Any] = {}
    per_scenario: dict[str, Any] = {scenario: {} for scenario in PILOT_SCENARIOS}
    for baseline_id in PILOT_BASELINES:
        baseline_runs = [record for record in records if record.baseline_id == baseline_id]
        baseline_evals = [evaluations[(baseline_id, scenario, "1")] for scenario in PILOT_SCENARIOS if (baseline_id, scenario, "1") in evaluations]
        complete = len(baseline_evals) == len(PILOT_SCENARIOS)
        macro = {metric: _mean([getattr(item, metric) for item in baseline_evals]) if complete else None for metric in METRICS}
        tp = fp = fn = 0
        for scenario_id in PILOT_SCENARIOS:
            evaluation = evaluations.get((baseline_id, scenario_id, "1"))
            record = next((item for item in baseline_runs if item.scenario_id == scenario_id), None)
            per_scenario[scenario_id][baseline_id] = {
                "repetition_id": "1", "validation_status": record.validation_status if record else "not_attempted",
                "evaluation": asdict(evaluation) if evaluation else None,
            }
            if evaluation:
                positives = sum(item["materially_dependent"] for item in scenarios[scenario_id]["private"]["decision_labels"])
                tp += positives - evaluation.false_negative_dependence
                fp += evaluation.false_positive_dependence
                fn += evaluation.false_negative_dependence
        micro = {"dependency_precision": None, "dependency_recall": None, "dependency_f1": None, "true_positive": tp, "false_positive": fp, "false_negative": fn}
        if complete:
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 1.0
            micro.update(dependency_precision=precision, dependency_recall=recall, dependency_f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0)
        per_baseline[baseline_id] = {
            "macro": macro, "micro": micro, "usage": _usage(baseline_runs),
            "evaluated_scenario_count": len(baseline_evals),
            "invalid_response_count": sum(item.validation_status == "invalid" for item in baseline_runs),
            "provider_error_count": sum(item.validation_status == "provider_error" for item in baseline_runs),
        }
    deltas = {
        "B1-B0": {"macro": _delta(per_baseline["B1"]["macro"], per_baseline["B0"]["macro"], METRICS), "micro": _delta(per_baseline["B1"]["micro"], per_baseline["B0"]["micro"], ("dependency_precision", "dependency_recall", "dependency_f1"))},
        "B2-B1": {"macro": _delta(per_baseline["B2"]["macro"], per_baseline["B1"]["macro"], METRICS), "micro": _delta(per_baseline["B2"]["micro"], per_baseline["B1"]["micro"], ("dependency_precision", "dependency_recall", "dependency_f1"))},
    }
    return {
        "protocol_version": "pilot-0.1", "status": "aborted" if systemic_failure else "completed",
        "systemic_failure": systemic_failure, "scheduled_call_count": 9,
        "attempted_call_count": len(records), "invalid_response_count": sum(item.validation_status == "invalid" for item in records),
        "usage": _usage(records), "per_baseline": per_baseline, "per_scenario": per_scenario,
        "descriptive_deltas": deltas,
    }


def _provider_error_record(attempt: PilotAttempt, adapter: Any, config: ExperimentConfig, error: Exception, latency_ms: float) -> RunRecord:
    baseline = get_baseline(attempt.baseline_id)
    return RunRecord(
        baseline_id=attempt.baseline_id, scenario_id=attempt.scenario_id, condition=baseline.condition,
        prompt_version=baseline.prompt_version, experiment_config_version=config.version,
        model_adapter=adapter.identifier, raw_model_response="", parsed_candidate_response=None,
        validation_status="provider_error", provider_error=f"{type(error).__name__}: {error}",
        experiment_config=config.to_dict(), model_name=MODEL_ID, latency_ms=latency_ms,
        repetition_id=attempt.repetition_id,
    )


def run_fixed_pilot(output_dir: Path, adapter_factory: Callable[[], Any] = GeminiVertexAdapter) -> dict[str, Any]:
    schedule = build_schedule()
    store = PilotStore(output_dir)
    config = pilot_config()
    scenarios = {scenario_id: load_scenario(scenario_id) for scenario_id in PILOT_SCENARIOS}
    records: list[RunRecord] = []
    evaluations: dict[tuple[str, str, str], Any] = {}
    systemic_failure: str | None = None
    adapter = adapter_factory()
    try:
        for attempt in schedule:
            started = perf_counter()
            try:
                record = run_baseline(attempt.baseline_id, scenarios[attempt.scenario_id], adapter, config, repetition_id=attempt.repetition_id)
            except Exception as exc:
                record = _provider_error_record(attempt, adapter, config, exc, (perf_counter() - started) * 1000)
                records.append(record); store.append_run(record)
                if isinstance(exc, (GeminiAuthenticationError, genai_errors.ClientError, ValueError)):
                    systemic_failure = record.provider_error
                    break
                continue
            records.append(record); store.append_run(record)
            if record.validation_status == "valid" and record.parsed_candidate_response is not None:
                evaluation = evaluate_discovery(scenarios[attempt.scenario_id], record.parsed_candidate_response)
                evaluations[(attempt.baseline_id, attempt.scenario_id, attempt.repetition_id)] = evaluation
                store.append_evaluation(attempt, evaluation)
    finally:
        if hasattr(adapter, "close"):
            adapter.close()
    summary = build_summary(records, evaluations, scenarios, systemic_failure)
    store.write_summary(summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fixed 3x3x1 baseline pilot")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="make exactly the fixed provider calls")
    args = parser.parse_args(argv)
    if not args.execute:
        print("Refusing to execute the baseline pilot without explicit --execute.", file=sys.stderr)
        return 2
    summary = run_fixed_pilot(args.output_dir)
    print(json.dumps(summary, sort_keys=True))
    return 3 if summary["status"] == "aborted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
