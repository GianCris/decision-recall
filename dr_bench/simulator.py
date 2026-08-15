from __future__ import annotations

from copy import deepcopy
from typing import Any

from .paths import delete, get, set_value


class SimulationError(ValueError):
    pass


def simulate(scenario: dict[str, Any], through: int | None = None) -> dict[str, Any]:
    """Apply scenario events in sequence order and return a new world object."""
    world = deepcopy(scenario["world"])
    events = scenario["events"] if through is None else scenario["events"][:through]
    previous = 0
    for event in events:
        seq = event["seq"]
        if seq <= previous:
            raise SimulationError("event sequence numbers must be strictly increasing")
        previous = seq
        operation = event["operation"]
        path = event["path"]
        try:
            if operation == "set":
                set_value(world, path, deepcopy(event["value"]))
            elif operation == "delete":
                delete(world, path)
            elif operation == "append":
                target = get(world, path)
                if not isinstance(target, list):
                    raise SimulationError(f"append target {path!r} is not a list")
                target.append(deepcopy(event["value"]))
            else:
                raise SimulationError(f"unknown operation {operation!r}")
        except (KeyError, ValueError) as exc:
            if isinstance(exc, SimulationError):
                raise
            raise SimulationError(f"event {event.get('id', seq)!r}: {exc}") from exc
    return world
