from __future__ import annotations

import json
import subprocess
from pathlib import Path

from orchestra.harnesses.base import WorkerProcess
from orchestra.state import STATUS_DONE
from orchestra.supervision import _result_from_completed_worker


def test_successful_pi_worker_result_reads_accounting_from_worker_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agent_dir = tmp_path / "agent"
    session_dir = agent_dir / "sessions" / "--repo--"
    session_dir.mkdir(parents=True)
    transcript = session_dir / "2026-09-02T17-37-34-057Z_orchestra-worker-run-1.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "session", "id": "orchestra-worker-run-1"}),
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "usage": {
                                "input": 10,
                                "output": 4,
                                "reasoning": 3,
                                "cacheRead": 2,
                                "cacheWrite": 1,
                                "cost": {"total": 0.25},
                            }
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "usage": {
                                "input": 5,
                                "output": 6,
                                "reasoning": 7,
                                "cacheRead": 0,
                                "cacheWrite": 4,
                                "cost": {"total": 0.5},
                            }
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_dir))

    process = subprocess.CompletedProcess(args=["pi"], returncode=0)
    worker = WorkerProcess(
        process=process,  # type: ignore[arg-type]
        command=["pi"],
        prompt="prompt",
        worker_session_id="orchestra-worker-run-1",
    )

    result = _result_from_completed_worker(worker, "done", "")

    assert result.status == STATUS_DONE
    assert result.input_tokens == 15
    assert result.output_tokens == 10
    assert result.reasoning_tokens == 10
    assert result.cache_read_tokens == 2
    assert result.cache_write_tokens == 5
    assert result.cost_usd == 0.75
