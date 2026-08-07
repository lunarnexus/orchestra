from __future__ import annotations

import argparse
import json
from pathlib import Path

from .eval_harness import (
    CASES,
    collect_trace,
    create_workspace,
    grade_workspace,
    suite_summary,
    trace_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare and grade natural Orchestra verifier evaluations"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")

    prepare = sub.add_parser("prepare")
    prepare.add_argument("case", choices=sorted(CASES))
    prepare.add_argument("--run-root", type=Path, required=True)

    grade = sub.add_parser("grade")
    grade.add_argument("case_dir", type=Path)

    trace = sub.add_parser("collect-trace")
    trace.add_argument("case_dir", type=Path)
    trace.add_argument("--run-id", required=True)
    trace.add_argument("--state-dir", type=Path, required=True)
    trace.add_argument("--log-dir", type=Path, required=True)

    report = sub.add_parser("report")
    report.add_argument("run_root", type=Path)

    args = parser.parse_args()
    if args.command == "list":
        for case_id in sorted(CASES):
            print(case_id)
        return 0
    if args.command == "prepare":
        print(create_workspace(args.case, args.run_root.resolve()))
        return 0
    if args.command == "collect-trace":
        collect_trace(
            args.run_id,
            args.case_dir.resolve(),
            args.state_dir.resolve(),
            args.log_dir.resolve(),
        )
        print(args.case_dir.resolve() / "traces")
        return 0
    if args.command == "grade":
        case_dir = args.case_dir.resolve()
        result = grade_workspace(case_dir)
        config = json.loads((case_dir / "hidden" / "grade_config.json").read_text())
        process = trace_summary(
            case_dir / "traces" / "pi-session.jsonl",
            requires_command=config["requires_command"],
            requires_semantic=config["requires_semantic"],
            semantic_tool_available=config.get("semantic_tool_available", False),
        )
        result["process_pass"] = process["process_pass"]
        result["trace"] = process
        (case_dir / "grade.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    summary = suite_summary(args.run_root.resolve())
    (args.run_root.resolve() / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
