from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .paths import PathError, get
from .simulator import simulate_recovery


@dataclass(frozen=True)
class DiscoveryEvaluation:
    scenario_id: str
    dependency_precision: float
    dependency_recall: float
    dependency_f1: float
    false_positive_dependence: int
    false_negative_dependence: int
    dependency_strength_accuracy: float
    still_justified_accuracy: float
    multi_hop_recall: float | None


@dataclass(frozen=True)
class RecoveryEvaluation:
    scenario_id: str
    repair_correctness: float
    wrongful_rollback: int
    unnecessary_disruption: int
    recovered_value: float
    recovery_window_capture: float
    final_world_state_correctness: float


def _ratio(numerator: int, denominator: int, empty: float = 1.0) -> float:
    return numerator / denominator if denominator else empty


def evaluate_discovery(scenario: dict[str, Any], candidate: dict[str, Any]) -> DiscoveryEvaluation:
    truth = {item["decision_id"]: item for item in scenario["private"]["decision_labels"]}
    predictions = {item["decision_id"]: item for item in candidate.get("decisions", [])}
    actual_positive = {key for key, item in truth.items() if item["materially_dependent"]}
    predicted_positive = {key for key, item in predictions.items() if item.get("materially_dependent") is True}
    true_positive = len(actual_positive & predicted_positive)
    false_positive = len(predicted_positive - actual_positive)
    false_negative = len(actual_positive - predicted_positive)
    precision = _ratio(true_positive, true_positive + false_positive, 0.0)
    recall = _ratio(true_positive, true_positive + false_negative)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    strength_correct = sum(predictions.get(key, {}).get("dependency_strength") == item["dependency_strength"] for key, item in truth.items())
    justified_correct = sum(predictions.get(key, {}).get("still_justified") == item["still_justified"] for key, item in truth.items())
    multi_hop = {key for key in actual_positive if truth[key]["dependency_path"]["agent_hops"] > 1}
    multi_hop_recall = _ratio(len(multi_hop & predicted_positive), len(multi_hop)) if multi_hop else None
    return DiscoveryEvaluation(
        scenario["id"], precision, recall, f1, false_positive, false_negative,
        _ratio(strength_correct, len(truth)), _ratio(justified_correct, len(truth)), multi_hop_recall,
    )


def evaluate_recovery(scenario: dict[str, Any], candidate: dict[str, Any]) -> RecoveryEvaluation:
    action_ids = candidate.get("action_ids", [])
    at_step = candidate.get("at_step", 0)
    world = simulate_recovery(scenario, action_ids)
    private = scenario["private"]
    consequences = {item["id"]: item for item in scenario["candidate"]["consequences"]}
    labels = private["consequence_labels"]
    recovered = 0
    recovered_value = 0.0
    for target in labels["must_recover"]:
        item = consequences[target["id"]]
        try:
            repaired = get(world, item["path"]) == target["desired_value"]
        except PathError:
            repaired = False
        if repaired:
            recovered += 1
            recovered_value += item.get("value", 1.0)
    initial = scenario["candidate"]["world"]
    wrongful = 0
    for consequence_id in labels["must_not_touch"]:
        path = consequences[consequence_id]["path"]
        try:
            wrongful += get(world, path) != get(initial, path)
        except PathError:
            wrongful += 1
    expected_actions = set(private["recovery"]["expected_actions"])
    unnecessary = len(set(action_ids) - expected_actions) + wrongful
    actions = {item["id"]: item for item in scenario["candidate"]["recovery_actions"]}
    required_selected = expected_actions & set(action_ids)
    in_window = sum(at_step <= actions[action_id]["window_closes_at"] for action_id in required_selected)
    expected_world = private["recovery"]["expected_final_world"]
    final_correct = 0
    for path, value in expected_world.items():
        try:
            final_correct += get(world, path) == value
        except PathError:
            pass
    return RecoveryEvaluation(
        scenario["id"], _ratio(recovered, len(labels["must_recover"])), wrongful,
        unnecessary, recovered_value, _ratio(in_window, len(expected_actions)),
        _ratio(final_correct, len(expected_world)),
    )


def evaluate(scenario: dict[str, Any], candidate: dict[str, Any], phase: str = "discovery") -> DiscoveryEvaluation | RecoveryEvaluation:
    if phase == "discovery":
        return evaluate_discovery(scenario, candidate)
    if phase == "recovery":
        return evaluate_recovery(scenario, candidate)
    raise ValueError("phase must be 'discovery' or 'recovery'")
