from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from .golden_loop import run_golden_decision
from .presentation import build_decision_threads_presentation


def export_decision_threads_demo(output: Path) -> Path:
    """Export the frozen golden-loop result as the winner-slice read model."""

    result = run_golden_decision()
    presentation = build_decision_threads_presentation(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(presentation), indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Export Decision Threads presentation state")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("apps/decision-threads/public/demo-state.json"),
    )
    args = parser.parse_args()
    path = export_decision_threads_demo(args.output)
    print(json.dumps({"artifact": str(path)}))


if __name__ == "__main__":
    main()
