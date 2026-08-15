from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .catalog import load_scenario, load_scenarios
from .evaluator import evaluate
from .views import candidate_view


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dr-bench")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="list bundled scenarios")
    listing.add_argument("--split", choices=("dev", "holdout"))
    show = commands.add_parser("show", help="print candidate-visible scenario input")
    show.add_argument("scenario_id")
    show.add_argument("--phase", choices=("discovery", "recovery"), default="discovery")
    run = commands.add_parser("evaluate", help="evaluate a candidate JSON file")
    run.add_argument("scenario_id")
    run.add_argument("candidate", type=Path)
    run.add_argument("--phase", choices=("discovery", "recovery"), default="discovery")
    args = parser.parse_args(argv)
    if args.command == "list":
        for scenario in load_scenarios(args.split):
            print(f"{scenario['id']}\t{scenario['split']}\t{scenario['title']}")
        return 0
    scenario = load_scenario(args.scenario_id)
    if args.command == "show":
        print(json.dumps(candidate_view(scenario, args.phase), indent=2))
        return 0
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    result = evaluate(scenario, candidate, args.phase)
    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
