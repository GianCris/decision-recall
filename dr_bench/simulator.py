from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from .paths import delete, get, set_value


class SimulationError(ValueError):
    pass


def _apply(world: dict[str, Any], effect: dict[str, Any]) -> None:
    operation, path = effect["operation"], effect["path"]
    if operation == "set":
        set_value(world, path, deepcopy(effect["value"]))
    elif operation == "delete":
        delete(world, path)
    elif operation == "append":
        target = get(world, path)
        if not isinstance(target, list):
            raise SimulationError(f"append target {path!r} is not a list")
        target.append(deepcopy(effect["value"]))
    else:
        raise SimulationError(f"unknown operation {operation!r}")


def simulate_recovery(scenario: dict[str, Any], action_ids: Iterable[str]) -> dict[str, Any]:
    """Apply selected public recovery actions, in candidate order, to a fresh world."""
    world = deepcopy(scenario["candidate"]["world"])
    actions = {item["id"]: item for item in scenario["candidate"]["recovery_actions"]}
    for action_id in action_ids:
        if action_id not in actions:
            raise SimulationError(f"unknown recovery action {action_id!r}")
        try:
            for effect in actions[action_id]["effects"]:
                _apply(world, effect)
        except ValueError as exc:
            if isinstance(exc, SimulationError):
                raise
            raise SimulationError(f"action {action_id!r}: {exc}") from exc
    return world


def simulate(scenario: dict[str, Any], action_ids: Iterable[str] = ()) -> dict[str, Any]:
    return simulate_recovery(scenario, action_ids)
