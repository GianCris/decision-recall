from __future__ import annotations

from copy import deepcopy
from typing import Any


PRIVATE_KEYS = {
    "private", "oracle", "decision_labels", "materially_dependent", "dependency_strength",
    "dependency_path", "still_justified", "must_recover", "must_not_touch",
    "expected_actions", "expected_final_world",
}


def candidate_view(scenario: dict[str, Any], phase: str = "discovery") -> dict[str, Any]:
    """Return an isolated candidate-visible copy for Discovery or Recovery."""
    if phase not in {"discovery", "recovery"}:
        raise ValueError("phase must be 'discovery' or 'recovery'")
    view = {
        "schema_version": scenario["schema_version"], "id": scenario["id"],
        "split": scenario["split"], "domain": scenario["domain"], "title": scenario["title"],
        "complexity": deepcopy(scenario["complexity"]), **deepcopy(scenario["candidate"]), "phase": phase,
    }
    if phase == "recovery":
        view["affected_decision_ids"] = [item["decision_id"] for item in scenario["private"]["decision_labels"] if item["materially_dependent"]]
    return view


def contains_private_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key in PRIVATE_KEYS or contains_private_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_private_key(item) for item in value)
    return False
