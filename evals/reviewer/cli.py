from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from evals.reviewer.eval_harness import (
    CASES,
    collect_trace,
    create_workspace,
    grade_workspace,
    suite_summary,
    trace_summary,
)


def parse_run_id(output: str) -> str:
    match = re.search(r"^run_id:\s*(\S+)", output, re.MULTILINE)
    if not match:
        raise ValueError(f"run id missing from output: {output}")
    return match.group(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reviewer skill behavioral evaluation harness")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")

    prepare = sub.add_parser("prepare")
    prepare.add_argument("case", choices=sorted(CASES))
    prepare.add_argument("--run-root", type=Path, required=True)

    grade = sub.add_parser("grade")
    grade.add_argument("case_dir", type=Path)

    collect = sub.add_parser("collect-trace")
    collect.add_argument("case_dir", type=Path)
    collect.add_argument("--run-id", required=True)
    collect.add_argument("--state-dir", type=Path, required=True)
    collect.add_argument("--log-dir", type=Path, required=True)

    report = sub.add_parser("report")
    report.add_argument("run_root", type=Path)

    args = parser.parse_args()
    if args.command == "list":
        print("\n".join(sorted(CASES)))
        return
    if args.command == "prepare":
        print(create_workspace(args.case, args.run_root))
        return
    if args.command == "collect-trace":
        collect_trace(args.run_id, args.case_dir, args.state_dir, args.log_dir)
        return
    if args.command == "grade":
        result = grade_workspace(args.case_dir)
        config = json.loads((args.case_dir / "hidden" / "grade_config.json").read_text())
        process = trace_summary(
            args.case_dir / "traces" / "pi-session.jsonl",
            expected_resources=tuple(config["expected_resources"]),
            requires_semantic=config["requires_semantic"],
            semantic_tool_available=config.get("semantic_tool_available", False),
            requires_diff=config.get("requires_diff", True),
        )
        result.update(process_pass=process["process_pass"], trace=process)
        (args.case_dir / "grade.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        return
    summary = suite_summary(args.run_root)
    (args.run_root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
