from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


BASE_TASK_PROMPT = """You are evaluating prior organizational decisions after a knowledge change.

Given the candidate-visible scenario, identify which decisions materially depended on the changed knowledge. Distinguish independent decisions and merely supporting or non-material relationships from material and critical dependence. Separately determine whether each decision remains sufficiently justified under the updated knowledge.

Return only one JSON object with this exact shape:
{"decisions":[{"decision_id":"<id>","materially_dependent":<boolean>,"dependency_strength":"independent|supporting|material|critical","still_justified":<boolean>}]}

Return exactly one entry for every decision ID in the scenario. Do not add or omit fields. Do not include commentary or markdown."""


REEVALUATION_INSTRUCTION = """REEVALUATION PROCEDURE:
For each potentially affected decision, explicitly ask whether it would still be sufficiently justified under the updated knowledge. A changed premise must not automatically imply rollback. Classify dependence as independent, supporting/non-material, material, or critical, and determine still-justified status separately."""


@dataclass(frozen=True)
class Baseline:
    baseline_id: str
    condition: str
    prompt_version: str = "0.1"
    reevaluation_instruction: str | None = None

    @property
    def task_instruction(self) -> str:
        if self.reevaluation_instruction is None:
            return BASE_TASK_PROMPT
        return BASE_TASK_PROMPT + "\n\n" + self.reevaluation_instruction

    def build_prompt(self, candidate_input: dict[str, Any]) -> str:
        if candidate_input.get("phase") != "discovery":
            raise ValueError("baseline requires a Discovery view")
        if candidate_input.get("discovery_condition") != self.condition:
            raise ValueError(f"{self.baseline_id} requires {self.condition!r} Discovery input")
        return self.task_instruction + "\n\nCANDIDATE-VISIBLE SCENARIO:\n" + json.dumps(candidate_input, sort_keys=True, separators=(",", ":"))


B0 = Baseline("B0", "implicit")
B1 = Baseline("B1", "structured")
B2 = Baseline("B2", "structured", reevaluation_instruction=REEVALUATION_INSTRUCTION)
BASELINES = {item.baseline_id: item for item in (B0, B1, B2)}


def get_baseline(baseline_id: str) -> Baseline:
    try:
        return BASELINES[baseline_id]
    except KeyError as exc:
        raise KeyError(f"unknown baseline {baseline_id!r}") from exc
