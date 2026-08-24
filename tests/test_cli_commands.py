from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import yaml

from orchestra.app import (
    AppConfig,
    AppContext,
    AppError,
    OrchestraPaths,
    _debug_transcript_section,
    _expanded_model_limits,
    format_orchestrator_return,
    format_status,
    start_run,
)
from orchestra.config import (
    AgentCatalog,
    ConcurrencyConfig,
    ModelLimitConfig,
    PromptConfig,
    RoleConfig,
)
from orchestra.harnesses.common import ORCHESTRA_DISPATCH_BUDGET_ENV
from orchestra.state import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_RUNNING,
    ConcurrencyLimitError,
    RunRecord,
    RunUpdate,
    StateStore,
)
from tests.helpers import extract_run_id, wait_for_condition
from tests.types import RuntimeFilesFactory

ROOT_PROMPTS = Path(__file__).resolve().parents[1] / "prompts.yaml"


def write_root_prompts(path: Path) -> None:
    path.write_text(ROOT_PROMPTS.read_text(encoding="utf-8"), encoding="utf-8")


def load_root_prompt_config() -> PromptConfig:
    data = yaml.safe_load(ROOT_PROMPTS.read_text(encoding="utf-8"))
    return PromptConfig(
        default_return_format=data["default_return_format"],
        tool_description=data["tool_description"],
        tool_prompt_snippet=data["tool_prompt_snippet"],
        tool_prompt_guidelines=tuple(data["tool_prompt_guidelines"]),
        tool_goal_description=data["tool_goal_description"],
        tool_role_description=data["tool_role_description"],
        tool_task_label_description=data["tool_task_label_description"],
        status_description=data["status_description"],
        status_action_description=data["status_action_description"],
        status_limit_description=data["status_limit_description"],
        status_run_id_description=data["status_run_id_description"],
        status_role_description=data["status_role_description"],
        status_setting_description=data["status_setting_description"],
        status_value_description=data["status_value_description"],
        host_help=data["host_help"],
        budget_exceeded_prompt=data["budget_exceeded_prompt"],
    )


def test_model_limits_match_unprefixed_role_model_names() -> None:
    expanded = _expanded_model_limits(
        {"lmstudio/qwen3.6-27b": ModelLimitConfig(concurrency=1)}
    )

    assert expanded["lmstudio/qwen3.6-27b"] == 1
    assert expanded["qwen3.6-27b"] == 1


@pytest.mark.parametrize(
    ("failure_message",),
    [
        ("global concurrency limit exceeded",),
        ("per-session concurrency limit exceeded",),
        ("model concurrency limit exceeded: lmstudio/qwen active=1 limit=1",),
    ],
)
def test_start_run_appends_dispatch_retry_guidance_for_concurrency_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_message: str,
) -> None:
    def reserve_run(*args: object, **kwargs: object) -> None:
        raise ConcurrencyLimitError(failure_message)

    store = cast(
        Any,
        SimpleNamespace(
            list_active_runs=lambda session_id=None: [
                RunRecord(
                    run_id="run-1",
                    orchestrator_session_id="manual:test-session",
                    harness="shell",
                    role="builder",
                    task_label="test task",
                    log_path=Path("/tmp/run-1.jsonl"),
                    created_at="2026-08-07T00:00:00Z",
                    status="running",
                    model="lmstudio/qwen",
                )
            ],
            reserve_run=reserve_run,
            get_main_session_state=lambda session_id=None: None,
        ),
    )
    context = AppContext(
        config=AppConfig(
            default_timeout=30,
            prompts=load_root_prompt_config(),
            state_dir=tmp_path / "state",
            log_dir=tmp_path / "logs",
            concurrency=ConcurrencyConfig(global_limit=1, per_session_limit=1),
        ),
        catalog=AgentCatalog(
            roles={"builder": RoleConfig(harness="shell", command=["echo"] )},
            default_role="builder",
            model_limits={"lmstudio/qwen": ModelLimitConfig(concurrency=1)},
        ),
        store=store,
        registry=cast(Any, SimpleNamespace()),
        paths=OrchestraPaths(
            config_path=tmp_path / "config.yaml",
            catalog_path=tmp_path / "catalog.yaml",
        ),
    )
    monkeypatch.setattr("orchestra.app.orchestra_can_dispatch", lambda: True)

    with pytest.raises(
        AppError,
        match=(
            rf"{failure_message}; dispatch was not accepted; wait for current subagents to return, "
            rf"then re-dispatch\. Do not poll while waiting\.\n"
            rf"session_id: manual:test-session\nactive_runs: 1/1\n"
            rf"global_active_runs: 1/1"
        ),
    ):
        start_run(
            context,
            session_id="manual:test-session",
            role_name=None,
            goal="Do work.",
            approved_context="",
            boundaries="",
            acceptance_target="",
            return_format="",
            timeout_seconds=10,
            task_label="",
            batch_id=None,
        )


def test_debug_transcript_section_inlines_pi_fallback_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker_session_id = "orchestra-worker-abc123"
    transcript = tmp_path / "sessions" / "2026" / f"run_{worker_session_id}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"message":"tool trace"}\n', encoding="utf-8")
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(tmp_path / "sessions"))
    record = RunRecord(
        run_id="abc123",
        orchestrator_session_id="manual:test-session",
        harness="pi",
        role="builder",
        task_label="debug-test",
        log_path=tmp_path / "abc123.jsonl",
        created_at="2026-08-07T00:00:00Z",
        status=STATUS_DONE,
        worker_session_id=worker_session_id,
    )

    section = _debug_transcript_section(record)

    assert "transcript_path: discovered by Pi fallback search" in section
    assert str(transcript) in section
    assert '{"message":"tool trace"}' in section


def test_orchestrator_return_includes_worker_roles(tmp_path: Path) -> None:
    first = RunRecord(
        run_id="34f3a4324432",
        orchestrator_session_id="manual:test-session",
        harness="pi",
        role="appsec",
        task_label="appsec-eval:t3",
        log_path=tmp_path / "34f3a4324432.jsonl",
        created_at="2026-08-07T00:00:00Z",
        status=STATUS_DONE,
        result_summary="Mode: appsec Verdict: fail",
    )
    second = RunRecord(
        run_id="2bfb63e7db3a",
        orchestrator_session_id="manual:test-session",
        harness="pi",
        role="planner",
        task_label="planner-eval:t1",
        log_path=tmp_path / "2bfb63e7db3a.jsonl",
        created_at="2026-08-07T00:00:00Z",
        status=STATUS_FAILED,
        error_text="worker failed",
    )

    report = format_orchestrator_return([first, second])

    assert "[orchestra: 2 subagents returned]" in report
    assert "[orchestra: appsec 34f3a4324432 success]" in report
    assert "[orchestra: planner 2bfb63e7db3a fail]" in report


def test_status_reports_session_lineage_details_for_active_run(
    tmp_path: Path,
) -> None:
    prompts = load_root_prompt_config()
    store = StateStore(tmp_path / "orchestra.db")
    store.initialize()
    context = AppContext(
        config=AppConfig(
            state_dir=tmp_path / "state",
            log_dir=tmp_path / "logs",
            default_timeout=30,
            concurrency=ConcurrencyConfig(global_limit=4, per_session_limit=2),
            prompts=prompts,
        ),
        catalog=AgentCatalog(
            roles={"worker": RoleConfig(harness="pi", command=["pi", "-p", "{prompt}"])},
        ),
        store=store,
        registry=cast(Any, SimpleNamespace()),
        paths=OrchestraPaths(
            config_path=tmp_path / "config.yaml",
            catalog_path=tmp_path / "catalog.yaml",
        ),
    )
    store.create_run(
        RunRecord(
            run_id="active001",
            orchestrator_session_id="manual:lineage",
            harness="pi",
            role="worker",
            task_label="active",
            log_path=tmp_path / "logs" / "active001.jsonl",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    store.update_run("active001", RunUpdate(status=STATUS_RUNNING, process_id=1234))

    output = format_status(context, "manual:lineage")

    assert "active_runs: 1/2" in output
    assert "global_active_runs: 1/4" in output
    assert "descendants_terminal: no" in output
    assert "session_report_available: no" in output
    assert "session_report_delivered: no" in output


def test_status_reports_pending_session_report_details(
    tmp_path: Path,
) -> None:
    prompts = load_root_prompt_config()
    store = StateStore(tmp_path / "orchestra.db")
    store.initialize()
    context = AppContext(
        config=AppConfig(
            state_dir=tmp_path / "state",
            log_dir=tmp_path / "logs",
            default_timeout=30,
            concurrency=ConcurrencyConfig(global_limit=4, per_session_limit=2),
            prompts=prompts,
        ),
        catalog=AgentCatalog(
            roles={"worker": RoleConfig(harness="pi", command=["pi", "-p", "{prompt}"])},
        ),
        store=store,
        registry=cast(Any, SimpleNamespace()),
        paths=OrchestraPaths(
            config_path=tmp_path / "config.yaml",
            catalog_path=tmp_path / "catalog.yaml",
        ),
    )
    store.create_run(
        RunRecord(
            run_id="pending001",
            orchestrator_session_id="manual:lineage",
            harness="pi",
            role="worker",
            task_label="pending report",
            log_path=tmp_path / "logs" / "pending001.jsonl",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    store.update_run("pending001", RunUpdate(status=STATUS_RUNNING, process_id=1234))
    store.update_run("pending001", RunUpdate(status=STATUS_DONE, result_summary="done"))

    output = format_status(context, "manual:lineage")

    assert "active_runs: 0/2" in output
    assert "descendants_terminal: yes" in output
    assert "session_report_available: yes" in output
    assert "session_report_delivered: no" in output


def test_status_reports_delivered_session_report_details(
    tmp_path: Path,
) -> None:
    prompts = load_root_prompt_config()
    store = StateStore(tmp_path / "orchestra.db")
    store.initialize()
    context = AppContext(
        config=AppConfig(
            state_dir=tmp_path / "state",
            log_dir=tmp_path / "logs",
            default_timeout=30,
            concurrency=ConcurrencyConfig(global_limit=4, per_session_limit=2),
            prompts=prompts,
        ),
        catalog=AgentCatalog(
            roles={"worker": RoleConfig(harness="pi", command=["pi", "-p", "{prompt}"])},
        ),
        store=store,
        registry=cast(Any, SimpleNamespace()),
        paths=OrchestraPaths(
            config_path=tmp_path / "config.yaml",
            catalog_path=tmp_path / "catalog.yaml",
        ),
    )
    store.create_run(
        RunRecord(
            run_id="delivered01",
            orchestrator_session_id="manual:lineage",
            harness="pi",
            role="worker",
            task_label="delivered report",
            log_path=tmp_path / "logs" / "delivered01.jsonl",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    store.update_run("delivered01", RunUpdate(status=STATUS_RUNNING, process_id=1234))
    store.update_run("delivered01", RunUpdate(status=STATUS_DONE, result_summary="done"))
    store.mark_report_runs_delivered("manual:lineage", ["delivered01"])

    output = format_status(context, "manual:lineage")

    assert "descendants_terminal: yes" in output
    assert "session_report_available: no" in output
    assert "session_report_delivered: yes" in output


def test_do_output_exposes_effective_timeout_seconds(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker done"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:test-session",
            "--goal",
            "Summarize repository status.",
            "--timeout",
            "17",
        ]
    )
    do_output = capsys.readouterr().out

    assert exit_code == 0
    assert "timeout_seconds: 17" in do_output
    assert "dispatch: queued for supervision" in do_output


def test_do_status_history_flow(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker done"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:test-session",
            "--goal",
            "Summarize repository status.",
        ]
    )
    do_output = capsys.readouterr().out

    assert exit_code == 0
    assert "dispatch: queued for supervision" in do_output
    run_id = extract_run_id(do_output)

    assert wait_for_condition(
        lambda: StateStore(db_path).get_run(run_id).status == STATUS_DONE,
        timeout=5,
    )

    history_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "history",
            "--session-id",
            "manual:test-session",
        ]
    )
    history_output = capsys.readouterr().out

    assert history_exit == 0
    assert "history_count: 1" in history_output
    assert "worker done" in history_output


def test_do_rejects_over_model_limit(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, "-c", "import time; time.sleep(2); print('done')"],
    )
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["model_limits"] = {"lmstudio/qwen": {"concurrency": 1}}
    catalog["roles"]["worker"]["model"] = "lmstudio/qwen"
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")

    from orchestra.cli import main

    first_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:model-limit-a",
            "--goal",
            "hold model slot",
        ]
    )
    first_output = capsys.readouterr().out
    run_id = extract_run_id(first_output)
    store = StateStore(db_path)
    assert wait_for_condition(lambda: bool(store.list_active_runs()))

    second_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:model-limit-b",
            "--goal",
            "should fail fast",
        ]
    )
    second_output = capsys.readouterr().out

    assert first_exit == 0
    assert second_exit == 1
    assert "model concurrency limit exceeded: lmstudio/qwen" in second_output
    assert "active=1 limit=1" in second_output
    assert store.get_run(run_id).model == "lmstudio/qwen"


def test_do_uses_role_nested_dispatch_depth_for_worker_env(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [
            python_executable,
            "-c",
            "import os; print(os.environ.get('ORCHESTRA_DISPATCH_BUDGET', 'missing'))",
        ],
    )
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["roles"]["worker"]["nested_dispatch_depth"] = 2
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:nested-dispatch-depth-role",
            "--goal",
            "Print nested dispatch depth env.",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    run_id = extract_run_id(output)
    assert wait_for_condition(
        lambda: StateStore(db_path).get_run(run_id).status == STATUS_DONE,
        timeout=5,
    )
    assert StateStore(db_path).get_run(run_id).result_summary == "2"


def test_do_rejects_when_orchestra_dispatch_budget_is_exhausted(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "should not run"],
    )
    monkeypatch.setenv(ORCHESTRA_DISPATCH_BUDGET_ENV, "1")

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:worker-budget-exhausted",
            "--goal",
            "Should be rejected.",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "ORCHESTRA_DISPATCH_BUDGET dispatch budget exhausted" in output


def test_roles_lists_configured_worker_roles(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success"],
    )
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["default_role"] = "builder"
    catalog["roles"] = {"builder": {"harness_config": "pi"}}
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "roles",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Configured roles" in output
    assert "Default: builder" in output
    assert "  D  builder [pi]" in output
    assert "      harness: pi" in output


def test_status_reports_active_run(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "sleep", "--sleep", "2", "--output", "slept"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:test-session",
            "--goal",
            "Run a long worker.",
        ]
    )
    do_output = capsys.readouterr().out
    run_id = extract_run_id(do_output)

    assert exit_code == 0
    assert wait_for_condition(
        lambda: StateStore(db_path).get_run(run_id).status == "running",
        timeout=5,
    )

    status_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "status",
            "--session-id",
            "manual:test-session",
        ]
    )
    status_output = capsys.readouterr().out

    assert status_exit == 0
    assert "session_id: manual:test-session" in status_output
    assert "active_runs: 1" in status_output
    assert run_id in status_output


def test_format_status_reports_capacity_notation_for_session_and_global_scopes() -> None:
    active_run = RunRecord(
        run_id="run-1",
        orchestrator_session_id="manual:test-session",
        harness="shell",
        role="builder",
        task_label="test task",
        log_path=Path("/tmp/run-1.jsonl"),
        created_at="2026-08-07T00:00:00Z",
        status="running",
        model="lmstudio/qwen",
    )
    context = AppContext(
        config=AppConfig(
            default_timeout=30,
            prompts=load_root_prompt_config(),
            concurrency=ConcurrencyConfig(global_limit=4, per_session_limit=2),
        ),
        catalog=cast(
            Any,
            SimpleNamespace(model_limits={"lmstudio/qwen": ModelLimitConfig(concurrency=1)}),
        ),
        store=cast(
            Any,
            SimpleNamespace(
                list_active_runs=lambda session_id=None: [active_run],
                get_main_session_state=lambda session_id=None: None,
            ),
        ),
        registry=cast(Any, SimpleNamespace()),
        paths=OrchestraPaths(
            config_path=Path("/tmp/config.yaml"),
            catalog_path=Path("/tmp/catalog.yaml"),
        ),
    )

    assert format_status(context, "manual:test-session").splitlines()[:11] == [
        "session_id: manual:test-session",
        "active_runs: 1/2",
        "global_active_runs: 1/4",
        "main_session_mode: on",
        "model_active_runs:",
        "- lmstudio/qwen: 1/1",
        "descendants_terminal: no",
        "session_report_available: no",
        "session_report_delivered: no",
        "active:",
        '- run-1 builder running task="test task"',
    ]
    assert format_status(context).splitlines()[:8] == [
        "scope: global",
        "active_runs: 1/4",
        "global_active_runs: 1/4",
        "main_session_mode: on",
        "model_active_runs:",
        "- lmstudio/qwen: 1/1",
        "active:",
        '- run-1 builder running task="test task" owner=manual:test-session',
    ]


def test_status_without_session_id_reports_global_active_runs(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "sleep", "--sleep", "2", "--output", "slept"],
    )

    from orchestra.cli import main

    first_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:first",
            "--goal",
            "Run first worker.",
        ]
    )
    first_output = capsys.readouterr().out
    first_run_id = extract_run_id(first_output)

    second_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:second",
            "--goal",
            "Run second worker.",
        ]
    )
    second_output = capsys.readouterr().out
    second_run_id = extract_run_id(second_output)

    assert first_exit == 0
    assert second_exit == 0
    assert wait_for_condition(
        lambda: len(StateStore(db_path).list_active_runs()) == 2,
        timeout=5,
    )

    status_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "status",
        ]
    )
    status_output = capsys.readouterr().out

    assert status_exit == 0
    assert "scope: global" in status_output
    assert "global_active_runs: 2" in status_output
    assert "owner=manual:first" in status_output
    assert "owner=manual:second" in status_output
    assert first_run_id in status_output
    assert second_run_id in status_output


def _set_tools_enabled_by_default(config_path: Path, enabled: bool) -> None:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["tools_enabled_by_default"] = enabled
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_status_prose_and_json_include_resolved_main_session_mode(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success"],
    )

    from orchestra.cli import main

    status_exit = main(["--config", str(config_path), "status"])
    assert status_exit == 0
    assert "main_session_mode: on" in capsys.readouterr().out

    json_exit = main(
        ["--config", str(config_path), "status", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert json_exit == 0
    assert payload["main_session_mode"] == "on"

    session_exit = main(
        [
            "--config",
            str(config_path),
            "status",
            "--session-id",
            "manual:mode-session",
        ]
    )
    assert session_exit == 0
    assert "main_session_mode: on" in capsys.readouterr().out


def test_bare_status_reports_config_resolved_default_when_disabled(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success"],
    )
    _set_tools_enabled_by_default(config_path, False)

    from orchestra.cli import main

    status_exit = main(["--config", str(config_path), "status"])
    assert status_exit == 0
    assert "main_session_mode: off" in capsys.readouterr().out

    json_exit = main(
        ["--config", str(config_path), "status", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert json_exit == 0
    assert payload["main_session_mode"] == "off"


def test_session_mode_set_get_roundtrip_and_status_resolution(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success"],
    )
    _set_tools_enabled_by_default(config_path, False)

    from orchestra.cli import main

    set_exit = main(
        [
            "--config",
            str(config_path),
            "_session-mode",
            "set",
            "--session-id",
            "manual:mode-session",
            "--mode",
            "orchestrator",
        ]
    )
    assert set_exit == 0
    capsys.readouterr()

    get_exit = main(
        [
            "--config",
            str(config_path),
            "_session-mode",
            "get",
            "--session-id",
            "manual:mode-session",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert get_exit == 0
    assert payload["session_id"] == "manual:mode-session"
    assert payload["main_session_mode"] == "orchestrator"
    assert payload["explicit_main_session_mode"] == "orchestrator"

    other_get_exit = main(
        [
            "--config",
            str(config_path),
            "_session-mode",
            "get",
            "--session-id",
            "manual:other-session",
            "--json",
        ]
    )
    other_payload = json.loads(capsys.readouterr().out)

    assert other_get_exit == 0
    assert other_payload["main_session_mode"] == "off"
    assert other_payload["explicit_main_session_mode"] is None

    status_json_exit = main(
        [
            "--config",
            str(config_path),
            "status",
            "--session-id",
            "manual:mode-session",
            "--json",
        ]
    )
    status_payload = json.loads(capsys.readouterr().out)

    assert status_json_exit == 0
    assert status_payload["main_session_mode"] == "orchestrator"

    bare_status_exit = main(["--config", str(config_path), "status"])
    assert bare_status_exit == 0
    assert "main_session_mode: off" in capsys.readouterr().out


def test_session_mode_set_invalid_mode_errors_cleanly(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "_session-mode",
            "set",
            "--session-id",
            "manual:mode-session",
            "--mode",
            "maybe",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "invalid main session mode" in output
    assert "Traceback" not in output


def test_stop_command_enforces_ownership(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "stop",
            "--session-id",
            "manual:other",
            "--run-id",
            "missing",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "run not found" in captured.out


def test_doctor_command_checks_local_setup(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "doctor",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "dependency:PyYAML: ok" in captured.out
    assert "executable:orchestra:" in captured.out
    assert "config: ok" in captured.out
    assert "agent_catalog: ok" in captured.out
    assert "database: ok" in captured.out
    assert "roles:enabled: ok" in captured.out
    assert "harness:worker: ok" in captured.out
    assert "harness:any_usable: ok" in captured.out


def test_internal_command_echo_preserves_full_orch_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from orchestra.cli import main

    exit_code = main(["_command-echo", "do --role critic tell me a haiku"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "/orch do --role critic tell me a haiku"


def test_internal_dispatch_ack_includes_role(capsys: pytest.CaptureFixture[str]) -> None:
    from orchestra.cli import main

    exit_code = main(["_dispatch-ack", "--run-id", "abc123", "--role", "critic"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == (
        "orchestra dispatched: critic abc123\n"
        "subagent will auto-return when finished. Do not poll while waiting."
    )


def test_internal_progress_message_includes_role(capsys: pytest.CaptureFixture[str]) -> None:
    from orchestra.cli import main

    exit_code = main(
        [
            "_progress-message",
            "--completed",
            "1",
            "--total",
            "2",
            "--run-id",
            "abc123",
            "--status",
            "done",
            "--role",
            "critic",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "orchestra: critic abc123 returned done (1/2)"


def test_internal_dispatch_ack_json_contract(capsys: pytest.CaptureFixture[str]) -> None:
    from orchestra.cli import main

    exit_code = main(["_dispatch-ack", "--run-id", "abc123", "--role", "critic", "--json"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["contract_version"] == 1
    assert output["kind"] == "dispatch_ack"
    assert output["ok"] is True
    assert output["run_id"] == "abc123"
    assert output["role"] == "critic"


def test_internal_progress_message_json_contract(capsys: pytest.CaptureFixture[str]) -> None:
    from orchestra.cli import main

    exit_code = main(
        [
            "_progress-message",
            "--completed",
            "1",
            "--total",
            "2",
            "--run-id",
            "abc123",
            "--status",
            "done",
            "--role",
            "critic",
            "--json",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["contract_version"] == 1
    assert output["kind"] == "progress_message"
    assert output["ok"] is True
    assert output["run_id"] == "abc123"
    assert output["status"] == "done"
    assert output["role"] == "critic"


def test_internal_orchestrator_skill_renders_project_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    skill_dir = tmp_path / "skills" / "orchestrator"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text("# Test skill\n\nUse it.", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    from orchestra.cli import main

    exit_code = main(["_orchestrator-skill"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output == "Load this Orchestra main-session skill:\n\n# Test skill\n\nUse it.\n"


def test_internal_orchestrator_skill_errors_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    import orchestra.app as app
    from orchestra.cli import main

    monkeypatch.setattr(app, "_find_source_root", lambda source_root=None: None)

    exit_code = main(["_orchestrator-skill"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "error: orchestrator skill file not found; looked for:" in output
    assert "skills/orchestrator/SKILL.md" in output


def test_internal_await_run_outputs_role(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker done"],
    )

    from orchestra.cli import main

    dispatch_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:test-session",
            "--role",
            "worker",
            "--goal",
            "Finish a worker.",
        ]
    )
    dispatch_output = capsys.readouterr().out
    run_id = extract_run_id(dispatch_output)
    assert dispatch_exit == 0
    assert wait_for_condition(
        lambda: StateStore(db_path).get_run(run_id).status == STATUS_DONE,
        timeout=5,
    )

    wait_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "_await-run",
            "--session-id",
            "manual:test-session",
            "--run-id",
            run_id,
        ]
    )

    output = capsys.readouterr().out
    assert wait_exit == 0
    assert "status: done" in output
    assert "role: worker" in output
    assert "active_runs_remaining: 0" in output
    assert "descendants_terminal: yes" in output
    assert "session_report_available: yes" in output
    assert "session_report_delivered: no" in output


def test_roles_command_lists_enabled_roles_by_default_and_all_roles_with_flag(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 600,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    write_root_prompts(prompts_path)
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "reviewer",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                    "hermes": {"harness": "hermes", "command": ["hermes", "-z", "{prompt}"]},
                },
                "roles": {
                    "worker": {"harness_config": "pi", "enabled": False},
                    "reviewer": {"harness_config": "hermes"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    default_exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "roles",
        ]
    )
    default_output = capsys.readouterr().out

    all_exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "roles",
            "--all",
        ]
    )
    all_output = capsys.readouterr().out

    assert default_exit_code == 0
    assert "Configured roles" in default_output
    assert "Default: reviewer" in default_output
    assert "  D  reviewer [hermes]" in default_output
    assert "  ✗  worker [pi]" not in default_output

    assert all_exit_code == 0
    assert "Default: reviewer" in all_output
    assert "  D  reviewer [hermes]" in all_output
    assert "  ✗  worker [pi]" in all_output


@pytest.mark.parametrize("value", ["true", "yes", "y", "1", "on"])
def test_roles_command_accepts_common_true_enabled_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    value: str,
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 600,
            }
        ),
        encoding="utf-8",
    )
    write_root_prompts(prompts_path)
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "builder",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                },
                "roles": {
                    "builder": {"harness_config": "pi"},
                    "reviewer": {"harness_config": "pi", "enabled": False},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "roles",
            "reviewer",
            "enabled",
            value,
        ]
    )
    output = capsys.readouterr().out
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "Updated role reviewer: enabled=true" in output
    assert "  ✓  reviewer [pi]" in output
    assert catalog["roles"]["reviewer"]["enabled"] is True


@pytest.mark.parametrize("value", ["false", "no", "n", "0", "off"])
def test_roles_command_accepts_common_false_enabled_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    value: str,
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 600,
            }
        ),
        encoding="utf-8",
    )
    write_root_prompts(prompts_path)
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "builder",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                },
                "roles": {
                    "builder": {"harness_config": "pi"},
                    "reviewer": {"harness_config": "pi"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "roles",
            "reviewer",
            "enabled",
            value,
        ]
    )
    output = capsys.readouterr().out
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "Updated role reviewer: enabled=false" in output
    assert "  ✗  reviewer [pi]" in output
    assert catalog["roles"]["reviewer"]["enabled"] is False


def test_roles_command_rejects_disabling_default_role(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 600,
            }
        ),
        encoding="utf-8",
    )
    write_root_prompts(prompts_path)
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "builder",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                },
                "roles": {"builder": {"harness_config": "pi"}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "roles",
            "builder",
            "enabled",
            "off",
        ]
    )
    output = capsys.readouterr().out
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert "error: cannot disable default role: builder" in output
    assert "enabled" not in catalog["roles"]["builder"]


def test_roles_command_updates_role_routing_settings(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 600,
            }
        ),
        encoding="utf-8",
    )
    write_root_prompts(prompts_path)
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "worker",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                    "hermes": {"harness": "hermes", "command": ["hermes", "-z", "{prompt}"]},
                },
                "roles": {"worker": {"harness_config": "pi", "model": "old-model"}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    updates = [
        ("harness", "hermes", "harness_config", "hermes"),
        ("model", "new/model", "model", "new/model"),
        ("profile", "tori", "profile", "tori"),
        ("agent", "plan", "agent", "plan"),
    ]
    for setting, value, yaml_key, expected_value in updates:
        exit_code = main(
            [
                "--config",
                str(config_path),
                "--agent-catalog",
                str(catalog_path),
                "roles",
                "worker",
                setting,
                value,
            ]
        )
        output = capsys.readouterr().out

        assert exit_code == 0
        assert f"Updated role worker: {yaml_key}={expected_value}" in output

    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    assert catalog["roles"]["worker"]["harness_config"] == "hermes"
    assert catalog["roles"]["worker"]["model"] == "new/model"
    assert catalog["roles"]["worker"]["profile"] == "tori"
    assert catalog["roles"]["worker"]["agent"] == "plan"


def test_roles_command_rejects_invalid_role_mutations(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 600,
            }
        ),
        encoding="utf-8",
    )
    write_root_prompts(prompts_path)
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "builder",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                },
                "roles": {
                    "builder": {"harness_config": "pi"},
                    "reviewer": {"harness_config": "pi", "model": "old-model"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    cases = [
        (["missing", "enabled", "true"], "error: unknown role: missing"),
        (
            ["reviewer", "enabled", "maybe"],
            "error: enabled must be one of true/yes/y/1/on or false/no/n/0/off; got 'maybe'",
        ),
        (
            ["reviewer", "enabled", "2"],
            "error: enabled must be one of true/yes/y/1/on or false/no/n/0/off; got '2'",
        ),
        (["reviewer", "model", ""], "error: model must be a non-empty string"),
        (["reviewer", "harness", "missing"], "error: unknown harness config: missing"),
        (["reviewer", "harness", ""], "error: harness must be a non-empty string"),
        (["reviewer", "enabled"], "error: missing value for role setting"),
    ]
    incomplete_usage_output = ""
    for role_args, expected_error in cases:
        exit_code = main(
            [
                "--config",
                str(config_path),
                "--agent-catalog",
                str(catalog_path),
                "roles",
                *role_args,
            ]
        )
        output = capsys.readouterr().out

        assert exit_code == 1
        assert expected_error in output
        if role_args == ["reviewer", "enabled"]:
            incomplete_usage_output = output

    assert "/orch roles ROLE SETTING VALUE" in incomplete_usage_output
    assert "harness   selected harness config name" in incomplete_usage_output
    assert "profile   optional harness profile, when supported" in incomplete_usage_output

    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    assert catalog["roles"]["reviewer"]["model"] == "old-model"
    assert "enabled" not in catalog["roles"]["reviewer"]


def test_role_metadata_lists_unused_harness_configs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 600,
            }
        ),
        encoding="utf-8",
    )
    write_root_prompts(prompts_path)
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "worker",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                    "unused": {"harness": "hermes", "command": ["hermes", "-z", "{prompt}"]},
                },
                "roles": {"worker": {"harness_config": "pi"}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "_role-metadata",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload == {"roles": ["worker"], "harnessConfigs": ["pi", "unused"]}


def test_opencode_help_describes_supported_open_code_template_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from orchestra.cli import main

    exit_code = main(["help-opencode"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "OpenCode /orch commands:" in output
    assert "/orch do [--role ROLE] <request>" in output
    assert "/orch stop" not in output
    assert "/orch do --timeout" not in output


def test_host_help_and_tool_info_reflect_current_enabled_and_default_roles(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 600,
            }
        ),
        encoding="utf-8",
    )
    write_root_prompts(prompts_path)
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "reviewer",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                    "hermes": {"harness": "hermes", "command": ["hermes", "-z", "{prompt}"]},
                },
                "roles": {
                    "worker": {"harness_config": "pi"},
                    "reviewer": {"harness_config": "hermes", "model": "gpt-5"},
                    "critic": {"harness_config": "hermes", "enabled": False},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    help_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "help-host",
        ]
    )
    help_output = capsys.readouterr().out

    tool_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "_tool-info",
        ]
    )
    tool_output = capsys.readouterr().out
    tool_info = json.loads(tool_output)

    assert help_exit == 0
    assert tool_exit == 0
    assert (
        "/orch on                           Enable Orchestra tools or load the orchestrator skill"
        in help_output
    )
    assert "/orch off                          Hide Orchestra tools for this session" in help_output
    assert "/orch roles" in help_output
    assert "/orch roles ROLE SETTING VALUE" in help_output
    assert "Settings: harness, enabled, model, profile, agent" in help_output
    assert "VALUE for enabled: true, yes, y, 1, on | false, no, n, 0, off" in help_output
    assert "harness-config" not in help_output
    assert "Configured roles" not in help_output
    assert "Default: reviewer" not in help_output
    assert "  ✓  worker [pi]" not in help_output
    assert "  D  reviewer [hermes]" not in help_output
    assert "      model: gpt-5" not in help_output
    assert "  ✗  critic" not in help_output
    assert "  ✓  worker [pi]" in tool_info["description"]
    assert "  D  reviewer [hermes]" in tool_info["description"]
    assert "      model: gpt-5" in tool_info["description"]
    assert tool_info["roleDescription"].startswith("Optional subagent capability.")
    assert "enabled role that best matches" in tool_info["roleDescription"]
    assert "  ✓  worker [pi]" in tool_info["roleDescription"]
    assert "  D  reviewer [hermes]" in tool_info["roleDescription"]
    assert "  ✗  critic" not in tool_info["description"]
    assert "  ✗  critic" not in tool_info["roleDescription"]
    assert tool_info["statusDescription"].startswith(
        "Use orch_status only when the user explicitly asks"
    )
    assert "Do not poll" in tool_info["statusDescription"]
    assert "Completed subagent reports return automatically" in tool_info[
        "statusDescription"
    ]
    assert "help, doctor, roles, status, history, on, or stop" in tool_info[
        "statusActionDescription"
    ]
    assert "runId" in tool_info["statusActionDescription"]
    assert tool_info["statusLimitDescription"] == (
        "Optional positive history limit for action=history."
    )
    assert tool_info["statusRunIdDescription"] == "Required run id when action=stop."
    assert tool_info["statusRoleDescription"] == (
        "Reserved for compatibility; action=roles lists all configured roles."
    )
    assert tool_info["statusSettingDescription"] == (
        "Reserved for role updates; model-callable roles are read-only for now."
    )
    assert tool_info["statusValueDescription"] == (
        "Reserved for role updates; model-callable roles are read-only for now."
    )
    assert tool_info["dispatchTimeoutError"] == (
        "timeout is not accepted by orch_dispatch; configured default_timeout applies."
    )
    assert tool_info["budgetTriggerLabel"] == "Budget trigger"
    assert tool_info["softTimeoutBlockReason"] == (
        "Orchestra soft timeout reached; return budget handoff"
    )
    assert "timeoutDescription" not in tool_info


def _write_tool_info_fixture(
    tmp_path: Path,
    config_extra: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_body: dict[str, object] = {
        "state_dir": str(tmp_path / "state"),
        "log_dir": str(tmp_path / "logs"),
        "default_timeout": 600,
    }
    if config_extra:
        config_body.update(config_extra)
    config_path.write_text(yaml.safe_dump(config_body), encoding="utf-8")
    write_root_prompts(prompts_path)
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "worker",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                },
                "roles": {
                    "worker": {"harness_config": "pi"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path, catalog_path


def test_tool_info_exposes_tools_default_and_resolved_session_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from orchestra.cli import main

    config_path, catalog_path = _write_tool_info_fixture(tmp_path)
    base_args = ["--config", str(config_path), "--agent-catalog", str(catalog_path)]

    exit_code = main([*base_args, "_tool-info"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["toolsEnabledByDefault"] is True
    assert payload["mainSessionMode"] == "on"
    # Existing tool-info fields remain intact.
    for key in (
        "description",
        "promptSnippet",
        "statusDescription",
        "dispatchTimeoutError",
    ):
        assert key in payload

    set_exit = main(
        [*base_args, "_session-mode", "set", "--session-id", "pi:s1", "--mode", "orchestrator"]
    )
    capsys.readouterr()
    assert set_exit == 0

    exit_code = main([*base_args, "_tool-info", "--session-id", "pi:s1"])
    resolved = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert resolved["mainSessionMode"] == "orchestrator"
    assert resolved["toolsEnabledByDefault"] is True

    # Without a session id the config-resolved default still applies.
    exit_code = main([*base_args, "_tool-info"])
    fallback = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert fallback["mainSessionMode"] == "on"


def test_tool_info_reflects_disabled_tools_default(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from orchestra.cli import main

    config_path, catalog_path = _write_tool_info_fixture(
        tmp_path, {"tools_enabled_by_default": False}
    )

    exit_code = main(
        ["--config", str(config_path), "--agent-catalog", str(catalog_path), "_tool-info"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["toolsEnabledByDefault"] is False
    assert payload["mainSessionMode"] == "off"


def test_disabled_role_is_rejected_without_fallback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 600,
            }
        ),
        encoding="utf-8",
    )
    write_root_prompts(prompts_path)
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "worker",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                    "hermes": {"harness": "hermes", "command": ["hermes", "-z", "{prompt}"]},
                },
                "roles": {
                    "worker": {"harness_config": "pi"},
                    "critic": {
                        "harness_config": "hermes",
                        "enabled": False,
                        "harness_fallback": [{"harness_config": "pi"}],
                    },
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:test-session",
            "--role",
            "critic",
            "--goal",
            "Do not run.",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "role is disabled: critic" in output


def test_requested_role_startup_fallback_preserves_requested_role_runtime_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    python_executable: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    skill_dir = tmp_path / "skills" / "reviewer"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text("# Reviewer Skill\n\nInspect only.", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 600,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    write_root_prompts(prompts_path)
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "builder",
                "harness_configs": {
                    "pi": {
                        "harness": "pi",
                        "command": [
                            python_executable,
                            "-c",
                            (
                                "import json, os, sys; "
                                "print(json.dumps({"
                                "'argv': sys.argv[1:-1], "
                                "'prompt': sys.argv[-1], "
                                "'nested_dispatch_depth': "
                                "os.environ.get('ORCHESTRA_DISPATCH_BUDGET'), "
                                "'role_env': os.environ.get('ROLE_ENV_TEST')"
                                "}))"
                            ),
                            "--model",
                            "{model}",
                            "{prompt}",
                        ],
                    },
                    "hermes": {
                        "harness": "hermes",
                        "command": ["missing-hermes-binary", "-z", "{prompt}"],
                    },
                },
                "roles": {
                    "builder": {
                        "harness_config": "pi",
                        "model": "builder-model",
                    },
                    "reviewer": {
                        "harness_config": "hermes",
                        "harness_fallback": [{"harness_config": "pi", "model": "fallback-model"}],
                        "model": "requested-model",
                        "prompt_addition": "Review only.",
                        "skills": ["reviewer"],
                        "nested_dispatch_depth": 2,
                        "env": {"ROLE_ENV_TEST": "configured"},
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:fallback-requested-role",
            "--role",
            "reviewer",
            "--goal",
            "Run the requested role with fallback.",
        ]
    )
    do_output = capsys.readouterr().out

    assert exit_code == 0
    run_id = extract_run_id(do_output)
    store = StateStore(tmp_path / "state" / "orchestra.db")
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_DONE, timeout=5)

    record = store.get_run(run_id)
    note = "fallback: reviewer used harness_config pi after hermes failed to start"
    assert record.role == "reviewer"
    assert record.harness == "pi"
    assert record.result_summary is not None
    assert note in record.result_summary
    assert not record.blocker_text
    assert record.result_artifact_path is not None

    artifact_text = record.result_artifact_path.read_text(encoding="utf-8")
    payload = json.loads(artifact_text.split("## stdout\n\n", 1)[1].strip())
    assert payload["argv"] == ["--model", "fallback-model"]
    assert payload["nested_dispatch_depth"] == "2"
    assert payload["role_env"] == "configured"
    assert "Role: reviewer" in payload["prompt"]
    assert "Role skill: reviewer" in payload["prompt"]
    assert f"Skill directory: {skill_dir}" in payload["prompt"]
    assert "Resolve relative resource paths against this directory." in payload["prompt"]
    assert "# Reviewer Skill" in payload["prompt"]
    assert "Role instructions: Review only." in payload["prompt"]

    history_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "history",
            "--session-id",
            "manual:fallback-requested-role",
        ]
    )
    history_output = capsys.readouterr().out

    assert history_exit == 0
    assert note in history_output
    assert "reviewer ::" in history_output


def test_do_without_role_uses_default_role(
    tmp_path: Path,
    python_executable: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 600,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    write_root_prompts(prompts_path)
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "reviewer",
                "harness_configs": {
                    "pi": {
                        "harness": "pi",
                        "command": [python_executable, "-c", "print('default reviewer ran')"],
                    },
                },
                "roles": {
                    "worker": {"harness_config": "pi"},
                    "reviewer": {"harness_config": "pi"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:default-role",
            "--goal",
            "Use the default role.",
        ]
    )
    do_output = capsys.readouterr().out

    assert exit_code == 0
    run_id = extract_run_id(do_output)
    store = StateStore(tmp_path / "state" / "orchestra.db")
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_DONE, timeout=5)

    record = store.get_run(run_id)
    assert record.role == "reviewer"
    assert record.harness == "pi"
    assert record.result_summary == "default reviewer ran"
