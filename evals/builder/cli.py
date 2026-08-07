from __future__ import annotations

import argparse
import json
from pathlib import Path

from .eval_harness import (
    CASES,
    EXPECTED_RESOURCES,
    TDD_TRACE_CASES,
    collect_trace,
    create_workspace,
    grade_resource_loading,
    grade_workspace,
    suite_summary,
    trace_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare and grade natural Orchestra builder evaluations"
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
        case_dir = create_workspace(args.case, args.run_root.resolve())
        print(case_dir)
        return 0
    if args.command == "grade":
        case_dir = args.case_dir.resolve()
        grade_result = grade_workspace(case_dir)
        trace_result = trace_summary(case_dir / "traces" / "pi-session.jsonl")
        expected_resources = EXPECTED_RESOURCES.get(case_dir.name, ())
        resource_grade: dict[str, object] | None
        if expected_resources and not trace_result["available"]:
            resource_grade = None
        else:
            resource_grade = grade_resource_loading(
                trace_result["tools"], expected_resources
            )
        resource_loading_pass = (
            None if resource_grade is None else bool(resource_grade["pass"])
        )
        grade_result["trace"] = {
            "available": trace_result["available"],
            "saw_test_before_write": trace_result["saw_test_before_write"],
            "tool_count": len(trace_result["tools"]),
        }
        case_id = case_dir.name
        if case_id in TDD_TRACE_CASES and not trace_result["available"]:
            core_method_pass: bool | None = None
        elif case_id in TDD_TRACE_CASES:
            core_method_pass = bool(trace_result["saw_test_before_write"])
        else:
            core_method_pass = True
        grade_result["expected_resources"] = expected_resources
        grade_result["resource_loading_pass"] = resource_loading_pass
        grade_result["resource_loading"] = resource_grade
        grade_result["core_method_pass"] = core_method_pass
        process_results = (resource_loading_pass, core_method_pass)
        grade_result["complete_pass"] = (
            None
            if any(result is None for result in process_results)
            else grade_result["passed"] and all(process_results)
        )
        (case_dir / "grade.json").write_text(json.dumps(grade_result, indent=2) + "\n")
        print(json.dumps(grade_result, indent=2))
        return 0 if grade_result["complete_pass"] is True else 1
    if args.command == "collect-trace":
        collect_trace(
            args.run_id,
            args.case_dir.resolve(),
            args.state_dir.resolve(),
            args.log_dir.resolve(),
        )
        print(args.case_dir.resolve() / "traces")
        return 0
    summary = suite_summary(args.run_root.resolve())
    (args.run_root.resolve() / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
