from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .catalog import load_scenario, load_scenarios
from .evaluator import evaluate
from .simulator import simulate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dr-bench")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="list bundled scenarios")
    listing.add_argument("--split", choices=("dev", "holdout"))
    show = commands.add_parser("show", help="print a scenario and its final world")
    show.add_argument("scenario_id")
    run = commands.add_parser("evaluate", help="evaluate a candidate JSON file")
    run.add_argument("scenario_id")
    run.add_argument("candidate", type=Path)
    args = parser.parse_args(argv)
    if args.command == "list":
        for scenario in load_scenarios(args.split):
            print(f"{scenario['id']}\t{scenario['split']}\t{scenario['title']}")
        return 0
    scenario = load_scenario(args.scenario_id)
    if args.command == "show":
        print(json.dumps({"scenario": scenario, "final_world": simulate(scenario)}, indent=2))
        return 0
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    result = evaluate(scenario, candidate)
    print(json.dumps(asdict(result), indent=2))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
