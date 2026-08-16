from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from dr_bench.validation import derive_agent_hops, validate_scenario
from dr_bench.views import candidate_view, contains_private_key

SEALED_DATASET_ID = "decision-recall-sealed-final-holdout-v0.1"
ROOT = Path(__file__).resolve().parent / "v0.1"
MANIFEST_PATH = ROOT / "manifest.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_and_validate() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest["dataset_id"] != SEALED_DATASET_ID or manifest["holdout_version"] != "0.1":
        raise ValueError("sealed dataset identity mismatch")
    if len(manifest["scenarios"]) != 8:
        raise ValueError("sealed manifest must contain exactly eight scenarios")
    scenarios = []
    for entry in manifest["scenarios"]:
        path = ROOT / entry["artifact"]
        if sha256(path).lower() != entry["sha256"].lower():
            raise ValueError(f"hash mismatch: {entry['artifact']}")
        scenario = json.loads(path.read_text(encoding="utf-8"))
        validate_scenario(scenario)
        if scenario["id"] != entry["scenario_id"] or scenario["domain"] != entry["domain"]:
            raise ValueError(f"manifest identity mismatch: {entry['scenario_id']}")
        if scenario["complexity"] != entry["complexity"]:
            raise ValueError(f"complexity mismatch: {entry['scenario_id']}")
        if len(scenario["candidate"]["decisions"]) != entry["decision_count"]:
            raise ValueError(f"decision count mismatch: {entry['scenario_id']}")
        if derive_agent_hops(scenario["candidate"]["transmissions"]) != entry["complexity"]["agent_hops"]:
            raise ValueError(f"structural hop mismatch: {entry['scenario_id']}")
        for condition in ("implicit", "structured"):
            if contains_private_key(candidate_view(scenario, "discovery", condition)):
                raise ValueError(f"private data leak: {entry['scenario_id']} {condition}")
        scenarios.append(scenario)
    return manifest, scenarios


def structural_report() -> dict[str, Any]:
    manifest, scenarios = load_and_validate()
    return {
        "dataset_id": manifest["dataset_id"],
        "scenario_ids": [item["id"] for item in scenarios],
        "domains": [item["domain"] for item in scenarios],
        "decision_counts": [len(item["candidate"]["decisions"]) for item in scenarios],
        "dependency_strengths": dict(sorted(Counter(label["dependency_strength"] for scenario in scenarios for label in scenario["private"]["decision_labels"]).items())),
        "hard_negative_types": dict(sorted(Counter(kind for scenario in scenarios for kind in scenario["private"]["hard_negative_types"]).items())),
        "hashes": {entry["artifact"]: entry["sha256"].lower() for entry in manifest["scenarios"]},
    }


if __name__ == "__main__":
    print(json.dumps(structural_report(), indent=2, sort_keys=True))
