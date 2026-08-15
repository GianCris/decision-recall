from __future__ import annotations

import json
from typing import Any


class OutputValidationError(ValueError):
    pass


STRENGTHS = {"independent", "supporting", "material", "critical"}
RESPONSE_KEYS = {"decision_id", "materially_dependent", "dependency_strength", "still_justified"}


def parse_discovery_response(raw: str, expected_decision_ids: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OutputValidationError(f"response is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict) or set(value) != {"decisions"} or not isinstance(value["decisions"], list):
        raise OutputValidationError("response must be exactly an object containing a decisions array")
    predictions = value["decisions"]
    ids: list[str] = []
    for index, prediction in enumerate(predictions):
        if not isinstance(prediction, dict) or set(prediction) != RESPONSE_KEYS:
            raise OutputValidationError(f"decisions[{index}] has an invalid field set")
        if not isinstance(prediction["decision_id"], str):
            raise OutputValidationError(f"decisions[{index}].decision_id must be a string")
        if type(prediction["materially_dependent"]) is not bool or type(prediction["still_justified"]) is not bool:
            raise OutputValidationError(f"decisions[{index}] boolean fields must be booleans")
        if prediction["dependency_strength"] not in STRENGTHS:
            raise OutputValidationError(f"decisions[{index}] has an invalid dependency_strength")
        if prediction["materially_dependent"] != (prediction["dependency_strength"] in {"material", "critical"}):
            raise OutputValidationError(f"decisions[{index}] material flag conflicts with strength")
        ids.append(prediction["decision_id"])
    if len(ids) != len(set(ids)):
        raise OutputValidationError("response contains duplicate decision IDs")
    if set(ids) != set(expected_decision_ids) or len(ids) != len(expected_decision_ids):
        raise OutputValidationError("response decision IDs must exactly match the candidate-visible scenario")
    return value
