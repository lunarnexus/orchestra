from __future__ import annotations

import argparse
import json
from pathlib import Path

from .lab import SCENARIOS, collect_trace, create_case, evaluate_case, report_run


def main() -> int:
    parser = argparse.ArgumentParser(description="Run exploratory Orchestra research evaluations")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list")

    prepare = sub.add_parser("prepare")
    prepare.add_argument("scenario", choices=sorted(SCENARIOS))
    prepare.add_argument("--run-root", type=Path, required=True)
    prepare.add_argument("--configuration", required=True)
    prepare.add_argument("--trial", type=int, required=True)

    trace = sub.add_parser("collect-trace")
    trace.add_argument("case_dir", type=Path)
    trace.add_argument("--run-id", required=True)
    trace.add_argument("--state-dir", type=Path, required=True)
    trace.add_argument("--log-dir", type=Path, required=True)

    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("case_dir", type=Path)

    report = sub.add_parser("report")
    report.add_argument("run_root", type=Path)

    args = parser.parse_args()
    if args.command == "list":
        for scenario_id, scenario in sorted(SCENARIOS.items()):
            source = "live" if scenario.live else "fixture"
            print(f"{scenario_id}\t{scenario.level}\t{source}\t{scenario.purpose}")
        return 0
    if args.command == "prepare":
        case_dir = create_case(
            args.scenario,
            args.run_root,
            configuration=args.configuration,
            trial=args.trial,
        )
        print(case_dir)
        return 0
    if args.command == "collect-trace":
        copied = collect_trace(
            args.run_id,
            args.case_dir.resolve(),
            args.state_dir.resolve(),
            args.log_dir.resolve(),
        )
        print(json.dumps({"copied": copied}, indent=2))
        return 0
    if args.command == "evaluate":
        case_dir = args.case_dir.resolve()
        evaluation = evaluate_case(case_dir)
        (case_dir / "evaluation.json").write_text(json.dumps(evaluation, indent=2) + "\n")
        print(json.dumps(evaluation, indent=2))
        return 0
    result = report_run(args.run_root.resolve())
    (args.run_root.resolve() / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
