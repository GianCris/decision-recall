from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, Literal

from .validation import validate_scenario

Split = Literal["dev", "holdout"]


def load_scenarios(split: Split | None = None) -> list[dict[str, Any]]:
    splits = (split,) if split else ("dev", "holdout")
    scenarios: list[dict[str, Any]] = []
    chains = json.loads(files("dr_bench").joinpath("data", "interaction_chains.json").read_text(encoding="utf-8"))
    for name in splits:
        resource = files("dr_bench").joinpath("data", f"{name}.jsonl")
        for line in resource.read_text(encoding="utf-8").splitlines():
            if line.strip():
                scenario = json.loads(line)
                scenario["candidate"]["transmissions"] = chains[scenario["id"]]
                validate_scenario(scenario)
                scenarios.append(scenario)
    ids = [scenario["id"] for scenario in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("scenario ids must be unique")
    return scenarios


def load_scenario(scenario_id: str) -> dict[str, Any]:
    for scenario in load_scenarios():
        if scenario["id"] == scenario_id:
            return scenario
    raise KeyError(f"unknown scenario {scenario_id!r}")
