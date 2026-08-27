from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


PROJECTION_VERSION = "PC2_JUDGE_SAFE_GEMINI_PROJECTION_V1"
EXPECTED_TARGETS = (
    ("historical_support:apex_delivery_instability", "historical_role"),
    ("beacon_reactivation_delay", "fact"),
)
EXPECTED_NORMAL_SURFACE = frozenset(
    {
        ("apex_delivery_instability", "fact"),
        ("beacon_reactivation_delay", "fact"),
        ("historical_support:apex_delivery_instability", "historical_role"),
    }
)


class ProjectionExportError(RuntimeError):
    pass


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectionExportError(f"cannot read valid JSON from {path}") from exc
    if not isinstance(value, dict):
        raise ProjectionExportError(f"expected a JSON object in {path}")
    return value


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectionExportError(f"{label} must be a non-empty string")
    return value


def build_projection(*, manifest_path: Path, raw_path: Path) -> dict[str, Any]:
    manifest = _json_object(manifest_path)
    expected_sha = _required_string(
        manifest.get("credentialed_artifact", {}).get("sha256"),
        "manifest credentialed artifact SHA-256",
    ).upper()
    raw_bytes = raw_path.read_bytes()
    actual_sha = sha256(raw_bytes).hexdigest().upper()
    if actual_sha != expected_sha:
        raise ProjectionExportError(
            f"raw artifact SHA-256 mismatch: expected {expected_sha}, got {actual_sha}"
        )

    raw = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(raw, dict):
        raise ProjectionExportError("raw artifact must be a JSON object")
    model = _required_string(raw.get("model"), "raw model")
    probe_version = _required_string(raw.get("probe_version"), "raw probe version")
    if model != manifest.get("model") or probe_version != manifest.get("producer_probe_version"):
        raise ProjectionExportError("raw model/probe identity does not match the release manifest")

    attempts = raw.get("attempts")
    if not isinstance(attempts, list):
        raise ProjectionExportError("raw attempts must be an array")
    normal = [item for item in attempts if isinstance(item, dict) and item.get("scenario") == "normal"]
    if len(normal) != 3 or any(
        item.get("semantic_pass") is not True
        or item.get("final_model_response_received") is not True
        for item in normal
    ):
        raise ProjectionExportError("expected exactly three successful normal credentialed executions")

    projected_runs: list[dict[tuple[str, str], dict[str, Any]]] = []
    for attempt in normal:
        raw_candidates = attempt.get("request", {}).get("raw_structured_output", {}).get("candidates")
        normalized = attempt.get("normalized_candidates")
        if not isinstance(raw_candidates, list) or not isinstance(normalized, list):
            raise ProjectionExportError("normal execution candidate evidence is incomplete")
        normalized_by_key = {
            (item.get("semantic_key"), item.get("kind")): item
            for item in normalized
            if isinstance(item, dict)
        }
        raw_by_key = {
            (item.get("semantic_key"), item.get("kind")): item
            for item in raw_candidates
            if isinstance(item, dict)
        }
        if frozenset(raw_by_key) != EXPECTED_NORMAL_SURFACE or frozenset(normalized_by_key) != EXPECTED_NORMAL_SURFACE:
            raise ProjectionExportError("normal execution does not match the frozen bounded semantic surface")

        run: dict[tuple[str, str], dict[str, Any]] = {}
        for key in EXPECTED_TARGETS:
            raw_candidate = raw_by_key[key]
            normalized_candidate = normalized_by_key[key]
            exact_quote = _required_string(raw_candidate.get("quote"), f"candidate quote {key}")
            if raw_candidate.get("source_id") != normalized_candidate.get("source_id"):
                raise ProjectionExportError(f"candidate source identity mismatch for {key}")
            if sha256(exact_quote.encode("utf-8")).hexdigest() != normalized_candidate.get("exact_quote_hash"):
                raise ProjectionExportError(f"candidate exact quote hash mismatch for {key}")
            if normalized_candidate.get("boundary_accepted") is not True:
                raise ProjectionExportError(f"candidate was not boundary accepted for {key}")
            run[key] = {
                "kind": key[1],
                "semantic_key": key[0],
                "source_id": _required_string(raw_candidate.get("source_id"), f"candidate source {key}"),
                "exact_quote": exact_quote,
                "boundary_accepted": True,
            }
        projected_runs.append(run)

    if any(run != projected_runs[0] for run in projected_runs[1:]):
        raise ProjectionExportError("normal credentialed executions disagree on judge-visible evidence")

    candidates = [projected_runs[0][key] for key in EXPECTED_TARGETS]
    return {
        "projection_version": PROJECTION_VERSION,
        "evidence_class": "release_proven_not_live_hero_request",
        "model": model,
        "producer_head_sha": _required_string(manifest.get("producer_head_sha"), "producer HEAD SHA"),
        "producer_probe_version": probe_version,
        "raw_artifact_sha256": expected_sha,
        "source_excerpts": [
            {"source_id": item["source_id"], "exact_quote": item["exact_quote"]}
            for item in candidates
        ],
        "candidates": candidates,
    }


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the judge-safe PC2 Gemini release projection.")
    parser.add_argument("--manifest", type=Path, default=Path("artifacts/pc2-credentialed-release-evidence.json"))
    parser.add_argument("--raw", type=Path, default=Path("artifacts/pc2-gemini-live-probe.json"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("apps/decision-threads/src/pc2-judge-safe-gemini-projection.json"),
    )
    args = parser.parse_args()
    projection = build_projection(manifest_path=args.manifest, raw_path=args.raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(projection))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
