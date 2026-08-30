from __future__ import annotations

import argparse
import sys

from dr_bench import load_scenario

from .config import ExperimentConfig
from .google_adapter import MODEL_ID, GeminiAuthenticationError, GeminiVertexAdapter
from .runner import run_baseline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicit one-call B0/dev-001 Gemini sanity check")
    parser.add_argument("--execute", action="store_true", help="make the single paid provider call")
    args = parser.parse_args(argv)
    if not args.execute:
        print("Refusing to call Gemini without explicit --execute.", file=sys.stderr)
        return 2
    config = ExperimentConfig(
        version="0.1",
        model_name=MODEL_ID,
        repetitions=1,
        dataset_id="DR-Bench",
        dataset_version="0.1",
        scenario_ids=("dev-001",),
        candidate_view_contract_version="0.1",
    )
    adapter = GeminiVertexAdapter()
    try:
        record = run_baseline("B0", load_scenario("dev-001"), adapter, config, repetition_id="1")
    except GeminiAuthenticationError as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        return 3
    finally:
        adapter.close()
    print(record.to_json())
    return 0 if record.validation_status == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
