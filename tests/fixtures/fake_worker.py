from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["success", "fail", "sleep", "metadata"])
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--output", default="worker ok")
    parser.add_argument("--stderr", default="")
    parser.add_argument("--marker")
    parser.add_argument("--session-id")
    parser.add_argument("--transcript-path")
    args = parser.parse_args()

    if args.marker:
        Path(args.marker).write_text("started\n", encoding="utf-8")

    if args.mode == "metadata":
        payload = {
            "session_id": args.session_id or "worker-session",
            "transcript_path": args.transcript_path or "transcript.md",
            "approval_needed": False,
        }
        print(json.dumps(payload))
        return 0

    if args.mode == "sleep":
        def _handle(_: int, __: object) -> None:
            print("terminated", flush=True)
            raise SystemExit(143)

        signal.signal(signal.SIGTERM, _handle)
        signal.signal(signal.SIGINT, _handle)
        time.sleep(args.sleep)

    if args.stderr:
        print(args.stderr, file=sys.stderr)
    print(args.output)
    return 1 if args.mode == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
