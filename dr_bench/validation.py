from __future__ import annotations

from typing import Any

from .paths import PathError, get, parts
from .simulator import SimulationError, simulate


class ScenarioValidationError(ValueError):
    pass


OPS = {"equals", "not_equals", "contains", "set_equals", "exists", "absent"}


def validate_scenario(scenario: dict[str, Any]) -> None:
    errors: list[str] = []
    required = {"schema_version", "id", "split", "title", "world", "events", "task", "oracle"}
    missing = sorted(required - scenario.keys())
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
    if scenario.get("schema_version") != "0.1":
        errors.append("schema_version must be '0.1'")
    if scenario.get("split") not in {"dev", "holdout"}:
        errors.append("split must be 'dev' or 'holdout'")
    if not isinstance(scenario.get("world"), dict):
        errors.append("world must be an object")
    events = scenario.get("events")
    if not isinstance(events, list):
        errors.append("events must be an array")
    else:
        sequences = [event.get("seq") for event in events if isinstance(event, dict)]
        if len(sequences) != len(events) or sequences != sorted(set(sequences)):
            errors.append("event seq values must be unique and strictly increasing")
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            if event.get("operation") not in {"set", "delete", "append"}:
                errors.append(f"events[{index}] has invalid operation")
            try:
                parts(event.get("path", "invalid"))
            except PathError as exc:
                errors.append(f"events[{index}]: {exc}")
            if event.get("operation") in {"set", "append"} and "value" not in event:
                errors.append(f"events[{index}] requires value")
    task = scenario.get("task")
    if not isinstance(task, dict) or not isinstance(task.get("prompt"), str):
        errors.append("task.prompt must be a string")
    oracle = scenario.get("oracle")
    if not isinstance(oracle, dict) or not isinstance(oracle.get("assertions"), list):
        errors.append("oracle.assertions must be an array")
    else:
        for index, assertion in enumerate(oracle["assertions"]):
            if assertion.get("op") not in OPS:
                errors.append(f"oracle.assertions[{index}] has invalid op")
            try:
                parts(assertion.get("path", "invalid"))
            except PathError as exc:
                errors.append(f"oracle.assertions[{index}]: {exc}")
            if assertion.get("op") not in {"exists", "absent"} and "value" not in assertion:
                errors.append(f"oracle.assertions[{index}] requires value")
    if not errors:
        try:
            final_world = simulate(scenario)
            expected = oracle.get("final_world", {})
            for path, value in expected.items():
                if get(final_world, path) != value:
                    errors.append(f"oracle.final_world mismatch at {path}")
        except (SimulationError, PathError) as exc:
            errors.append(str(exc))
    if errors:
        raise ScenarioValidationError(f"{scenario.get('id', '<unknown>')}: " + "; ".join(errors))
