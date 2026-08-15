from __future__ import annotations

from typing import Any

from .paths import PathError, get, parts
from .simulator import SimulationError, simulate_recovery


class ScenarioValidationError(ValueError):
    pass


STRENGTHS = {"independent", "supporting", "material", "critical"}
SEMANTIC = {"literal", "paraphrase", "semantic_transformation", "conceptual_consequence"}
TRANSFORMATIONS = {"copy", "summary", "compression", "inference"}
BOUNDARIES = {"shared", "partial_visibility", "department", "different_authority"}


def validate_scenario(scenario: dict[str, Any]) -> None:
    errors: list[str] = []
    required = {"schema_version", "id", "split", "domain", "title", "complexity", "candidate", "private"}
    missing = required - scenario.keys()
    if missing:
        errors.append("missing fields: " + ", ".join(sorted(missing)))
    if scenario.get("schema_version") != "0.1": errors.append("schema_version must be '0.1'")
    split = scenario.get("split")
    if split not in {"dev", "holdout"} or not str(scenario.get("id", "")).startswith(f"{split}-"): errors.append("id and split must agree")
    complexity = scenario.get("complexity", {})
    if complexity.get("agent_hops") not in {0, 1, 2, 4}: errors.append("invalid agent_hops")
    if complexity.get("semantic_distance") not in SEMANTIC: errors.append("invalid semantic_distance")
    if complexity.get("information_transformation") not in TRANSFORMATIONS: errors.append("invalid information_transformation")
    if complexity.get("boundary") not in BOUNDARIES: errors.append("invalid boundary")
    candidate, private = scenario.get("candidate", {}), scenario.get("private", {})
    agents = candidate.get("agents", []); agent_ids = {x.get("id") for x in agents if isinstance(x, dict)}
    if len(agents) < 2 or len(agent_ids) != len(agents): errors.append("at least two unique agents are required")
    knowledge = candidate.get("knowledge_before", []); knowledge_ids = {x.get("id") for x in knowledge if isinstance(x, dict)}
    decisions = candidate.get("decisions", []); decision_ids = {x.get("id") for x in decisions if isinstance(x, dict)}
    if not knowledge or len(knowledge_ids) != len(knowledge): errors.append("knowledge ids must be non-empty and unique")
    if not decisions or len(decision_ids) != len(decisions): errors.append("decision ids must be non-empty and unique")
    for decision in decisions:
        if decision.get("agent_id") not in agent_ids: errors.append(f"unknown decision agent: {decision.get('id')}")
        if not set(decision.get("evidence_available", [])) <= knowledge_ids: errors.append(f"unknown evidence: {decision.get('id')}")
    labels = private.get("decision_labels", []); label_ids = {x.get("decision_id") for x in labels if isinstance(x, dict)}
    if label_ids != decision_ids or len(labels) != len(decisions): errors.append("labels must cover every decision exactly once")
    for label in labels:
        strength = label.get("dependency_strength")
        if strength not in STRENGTHS: errors.append(f"invalid strength: {label.get('decision_id')}")
        if label.get("materially_dependent") != (strength in {"material", "critical"}): errors.append(f"inconsistent material label: {label.get('decision_id')}")
        path = label.get("dependency_path", {})
        if not isinstance(path.get("nodes"), list) or path.get("agent_hops") not in {0, 1, 2, 3, 4}: errors.append(f"invalid path: {label.get('decision_id')}")
        if not isinstance(label.get("downstream"), bool) or not isinstance(label.get("still_justified"), bool): errors.append(f"invalid flags: {label.get('decision_id')}")
    consequences = candidate.get("consequences", []); consequence_ids = {x.get("id") for x in consequences if isinstance(x, dict)}
    for item in consequences:
        try: parts(item.get("path", "invalid"))
        except PathError as exc: errors.append(str(exc))
    consequence_labels = private.get("consequence_labels", {})
    recover_ids = {x.get("id") for x in consequence_labels.get("must_recover", []) if isinstance(x, dict)}
    protected_ids = set(consequence_labels.get("must_not_touch", []))
    if not recover_ids or not protected_ids or recover_ids & protected_ids or not (recover_ids | protected_ids) <= consequence_ids: errors.append("invalid recovery/protected consequences")
    actions = candidate.get("recovery_actions", []); action_ids = {x.get("id") for x in actions if isinstance(x, dict)}
    for action in actions:
        if action.get("agent_id") not in agent_ids or action.get("cost", -1) < 0 or action.get("window_closes_at", -1) < 0: errors.append(f"invalid action: {action.get('id')}")
        if any(effect.get("operation") not in {"set", "delete", "append"} for effect in action.get("effects", [])): errors.append(f"invalid effect: {action.get('id')}")
    recovery = private.get("recovery", {})
    if not set(recovery.get("expected_actions", [])) <= action_ids: errors.append("expected_actions reference unknown actions")
    if not errors:
        try:
            world = simulate_recovery(scenario, recovery["expected_actions"])
            for path, value in recovery["expected_final_world"].items():
                if get(world, path) != value: errors.append(f"expected_final_world mismatch at {path}")
        except (KeyError, PathError, SimulationError) as exc: errors.append(str(exc))
    if errors: raise ScenarioValidationError(f"{scenario.get('id', '<unknown>')}: " + "; ".join(errors))
