from __future__ import annotations

import argparse
import json
from pathlib import Path

from .eval_harness import CASES, Case, collect_trace, create_workspace, grade_case, suite_summary


def _filtered_cases(suite: str | None) -> dict[str, Case]:
    if suite is None:
        return dict(CASES)
    return {case_id: case for case_id, case in CASES.items() if case.suite == suite}


def main() -> int:
    parser = argparse.ArgumentParser(description="Researcher regression evaluation harness")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list")
    list_parser.add_argument("--suite", choices=sorted({case.suite for case in CASES.values()}))

    prepare = sub.add_parser("prepare")
    prepare.add_argument("case", choices=sorted(CASES))
    prepare.add_argument("--run-root", type=Path, required=True)

    trace = sub.add_parser("collect-trace")
    trace.add_argument("case_dir", type=Path)
    trace.add_argument("--run-id", required=True)
    trace.add_argument("--state-dir", type=Path, required=True)
    trace.add_argument("--log-dir", type=Path, required=True)

    grade = sub.add_parser("grade")
    grade.add_argument("case_dir", type=Path)

    report = sub.add_parser("report")
    report.add_argument("run_root", type=Path)

    args = parser.parse_args()
    if args.command == "list":
        for case_id, case in sorted(_filtered_cases(args.suite).items()):
            print(f"{case_id}\t{case.task}")
        return 0
    if args.command == "prepare":
        print(create_workspace(args.case, args.run_root.resolve()))
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
    if args.command == "grade":
        case_dir = args.case_dir.resolve()
        grade_result = grade_case(case_dir)
        (case_dir / "grade.json").write_text(json.dumps(grade_result, indent=2) + "\n")
        print(json.dumps(grade_result, indent=2))
        return 0
    summary = suite_summary(args.run_root.resolve())
    (args.run_root.resolve() / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
