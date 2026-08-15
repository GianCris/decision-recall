from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .paths import PathError, get


@dataclass(frozen=True)
class AssertionResult:
    path: str
    op: str
    passed: bool
    message: str


@dataclass(frozen=True)
class Evaluation:
    scenario_id: str
    passed: bool
    score: float
    assertions: tuple[AssertionResult, ...]


def _check(candidate: Any, assertion: dict[str, Any]) -> AssertionResult:
    path, op = assertion["path"], assertion["op"]
    try:
        actual = get(candidate, path)
        found = True
    except PathError:
        actual, found = None, False
    expected = assertion.get("value")
    if op == "exists":
        passed = found
    elif op == "absent":
        passed = not found
    elif not found:
        passed = False
    elif op == "equals":
        passed = actual == expected and type(actual) is type(expected)
    elif op == "not_equals":
        passed = actual != expected
    elif op == "contains":
        passed = isinstance(actual, (str, list, dict)) and expected in actual
    elif op == "set_equals":
        passed = isinstance(actual, list) and isinstance(expected, list) and set(actual) == set(expected)
    else:
        passed = False
    message = "passed" if passed else f"expected {op} {expected!r}; got {actual!r}"
    return AssertionResult(path, op, passed, message)


def evaluate(scenario: dict[str, Any], candidate: Any) -> Evaluation:
    results = tuple(_check(candidate, item) for item in scenario["oracle"]["assertions"])
    passed_count = sum(result.passed for result in results)
    score = passed_count / len(results) if results else 1.0
    return Evaluation(scenario["id"], score == 1.0, score, results)
