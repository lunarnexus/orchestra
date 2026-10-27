from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import yaml

from orchestra.admission import admit_run
from orchestra.artifacts import canonical_return_path
from orchestra.config import (
    AgentCatalog,
    AppConfig,
    ConcurrencyConfig,
    ModelLimitConfig,
    PromptConfig,
    RoleConfig,
)
from orchestra.context import AppContext, AppError, OrchestraPaths, queue_resource_limits
from orchestra.dispatch import start_run
from orchestra.jobs import JobQueue, Limits
from orchestra.logs import utc_now
from orchestra.state import (
    STATUS_DONE,
    RunRecord,
    RunUpdate,
    StateStore,
)
from orchestra.status import format_status, status_payload
from tests.helpers import extract_run_id, make_jobs, seed_run, wait_for_condition
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
        tool_additional_context_description=data["tool_additional_context_description"],
        tool_role_description=data["tool_role_description"],
        tool_task_label_description=data["tool_task_label_description"],
        main_session_ownership_guidance=data["main_session_ownership_guidance"],
        status_description=data["status_description"],
        status_action_description=data["status_action_description"],
        status_limit_description=data["status_limit_description"],
        status_run_id_description=data["status_run_id_description"],
        status_role_description=data["status_role_description"],
        status_setting_description=data["status_setting_description"],
        status_value_description=data["status_value_description"],
        host_help=data["host_help"],
        budget_exceeded_prompt=data["budget_exceeded_prompt"],
        return_hint_done=data["return_hint_done"],
        return_hint_incomplete=data["return_hint_incomplete"],
        return_hint_failed=data["return_hint_failed"],
        return_hint_builder_failed=data["return_hint_builder_failed"],
        return_hint_budget_exceeded=data["return_hint_budget_exceeded"],
        budget_trigger_label=data["budget_trigger_label"],
        soft_timeout_block_reason=data["soft_timeout_block_reason"],
        session_mode_off_message=data["session_mode_off_message"],
        session_mode_on_message=data["session_mode_on_message"],
        session_mode_orchestrate_message=data["session_mode_orchestrate_message"],
        dispatch_ack_instruction=data["dispatch_ack_instruction"],
    )


def test_model_limits_match_unprefixed_role_model_names() -> None:
    catalog = AgentCatalog(
        roles={},
        model_limits={"lmstudio/qwen3.6-27b": ModelLimitConfig(concurrency=1)},
    )
    expanded = queue_resource_limits(catalog)

    assert expanded["lmstudio/qwen3.6-27b"] == 1
    assert expanded["qwen3.6-27b"] == 1


@pytest.mark.parametrize(
    ("limits", "blocker_session", "expected_message"),
    [
        (
            Limits(global_limit=1, per_owner_limit=4),
            "manual:other-session",
            "global concurrency limit exceeded",
        ),
        (
            Limits(global_limit=4, per_owner_limit=1),
            "manual:test-session",
            "per-session concurrency limit exceeded",
        ),
        (
            Limits(global_limit=4, per_owner_limit=4, resource_limits={"lmstudio/qwen": 1}),
            "manual:test-session",
            "model concurrency limit exceeded: lmstudio/qwen active=1 limit=1",
        ),
    ],
)
def test_start_run_appends_dispatch_retry_guidance_for_concurrency_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limits: Limits,
    blocker_session: str,
    expected_message: str,
) -> None:
    store = StateStore(tmp_path / "state" / "orchestra.db")
    store.initialize()
    jobs = JobQueue(store.database_path)
    jobs.initialize(limits)
    config = AppConfig(
        default_timeout=30,
        prompts=load_root_prompt_config(),
        state_dir=tmp_path / "state",
        log_dir=tmp_path / "logs",
        concurrency=ConcurrencyConfig(
            global_limit=limits.global_limit,
            per_session_limit=limits.per_owner_limit,
        ),
    )
    context = AppContext(
        config=config,
        catalog=AgentCatalog(
            roles={
                "builder": RoleConfig(
                    harness="shell",
                    command=["echo"],
                    model="lmstudio/qwen",
                )
            },
            default_role="builder",
            model_limits={"lmstudio/qwen": ModelLimitConfig(concurrency=1)},
        ),
        store=store,
        jobs=jobs,
        registry=cast(Any, SimpleNamespace()),
        paths=OrchestraPaths(
            config_path=tmp_path / "config.yaml",
            catalog_path=tmp_path / "catalog.yaml",
        ),
    )
    monkeypatch.setattr("orchestra.harnesses.common.orchestra_can_dispatch", lambda: True)

    # Occupy the relevant limit with a real admitted run, exactly as a dispatch does.
    admit_run(
        jobs,
        store,
        RunRecord(
            run_id="run-1",
            orchestrator_session_id=blocker_session,
            harness="shell",
            role="builder",
            model="lmstudio/qwen",
            task_label="occupying run",
            log_path=tmp_path / "logs" / "run-1.jsonl",
            created_at=utc_now(),
        ),
    )
    store.update_run("run-1", RunUpdate(status="running"))

    session_active = 1 if blocker_session == "manual:test-session" else 0
    with pytest.raises(
        AppError,
        match=(
            rf"{expected_message}; dispatch was not accepted; wait for "
            rf"current subagents to return, then re-dispatch\. Do not "
            rf"poll while waiting\.\n"
            rf"orchestra_tools: on\nsession_id: manual:test-session\n"
            rf"active_runs: {session_active}/{limits.per_owner_limit}\n"
            rf"global_active_runs: 1/{limits.global_limit}"
        ),
    ):
        start_run(
            context,
            session_id="manual:test-session",
            role_name=None,
            goal="Do work.",
            additional_context="",
            boundaries="",
            acceptance_target="",
            return_format="",
            timeout_seconds=10,
            task_label="",
            batch_id=None,
        )


def test_format_status_reports_capacity_notation_for_session_and_global_scopes(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "state" / "orchestra.db")
    store.initialize()
    jobs = JobQueue(store.database_path)
    jobs.initialize(
        Limits(global_limit=4, per_owner_limit=2, resource_limits={"lmstudio/qwen": 1})
    )
    context = AppContext(
        config=AppConfig(
            default_timeout=30,
            prompts=load_root_prompt_config(),
            state_dir=tmp_path / "state",
            log_dir=tmp_path / "logs",
            concurrency=ConcurrencyConfig(global_limit=4, per_session_limit=2),
        ),
        catalog=AgentCatalog(
            roles={
                "builder": RoleConfig(
                    harness="shell",
                    command=["echo"],
                    model="lmstudio/qwen",
                )
            },
            default_role="builder",
            model_limits={"lmstudio/qwen": ModelLimitConfig(concurrency=1)},
        ),
        store=store,
        jobs=jobs,
        registry=cast(Any, SimpleNamespace()),
        paths=OrchestraPaths(
            config_path=tmp_path / "config.yaml",
            catalog_path=tmp_path / "catalog.yaml",
        ),
    )
    admit_run(
        jobs,
        store,
        RunRecord(
            run_id="run-1",
            orchestrator_session_id="manual:test-session",
            harness="shell",
            role="builder",
            model="lmstudio/qwen",
            task_label="test task",
            log_path=tmp_path / "logs" / "run-1.jsonl",
            created_at=utc_now(),
        ),
    )
    store.update_run("run-1", RunUpdate(status="running"))

    assert format_status(context, "manual:test-session").splitlines()[:11] == [
        "orchestra_tools: on",
        "session_id: manual:test-session",
        "active_runs: 1/2",
        "global_active_runs: 1/4",
        "model_active_runs:",
        "- lmstudio/qwen: 1/1",
        "descendants_terminal: no",
        "session_report_available: no",
        "session_report_delivered: no",
        "active:",
        '- run-1 builder running task="test task"',
    ]
    assert format_status(context).splitlines()[:8] == [
        "orchestra_tools: on",
        "scope: global",
        "active_runs: 1/4",
        "global_active_runs: 1/4",
        "model_active_runs:",
        "- lmstudio/qwen: 1/1",
        "active:",
        '- run-1 builder running task="test task" owner=manual:test-session',
    ]


def test_status_module_exports_match_direct_imports(tmp_path: Path) -> None:
    prompts = load_root_prompt_config()
    store = StateStore(tmp_path / "orchestra.db")
    store.initialize()
    context = AppContext(
        config=(config := AppConfig(
            default_timeout=30,
            prompts=prompts,
            state_dir=tmp_path / "state",
            log_dir=tmp_path / "logs",
            concurrency=ConcurrencyConfig(global_limit=4, per_session_limit=2),
        )),
        catalog=AgentCatalog(
            roles={"worker": RoleConfig(harness="pi", command=["pi", "-p", "{prompt}"])},
        ),
        store=store,
        jobs=make_jobs(store, config),
        registry=cast(Any, SimpleNamespace()),
        paths=OrchestraPaths(
            config_path=tmp_path / "config.yaml",
            catalog_path=tmp_path / "catalog.yaml",
        ),
    )

    from orchestra import status as status_module

    assert status_module.format_status(context) == format_status(context)
    assert status_module.status_payload(context) == status_payload(context)


def test_roles_module_exports_match_direct_imports(tmp_path: Path) -> None:
    prompts = load_root_prompt_config()
    store = StateStore(tmp_path / "orchestra.db")
    store.initialize()
    context = AppContext(
        config=(config := AppConfig(
            default_timeout=30,
            prompts=prompts,
            state_dir=tmp_path / "state",
            log_dir=tmp_path / "logs",
            concurrency=ConcurrencyConfig(global_limit=4, per_session_limit=2),
        )),
        catalog=AgentCatalog(
            default_role="builder",
            roles={
                "builder": RoleConfig(harness="pi", command=["pi", "-p", "{prompt}"]),
                "reviewer": RoleConfig(
                    harness="pi",
                    command=["pi", "-p", "{prompt}"],
                    enabled=False,
                ),
            },
        ),
        store=store,
        jobs=make_jobs(store, config),
        registry=cast(Any, SimpleNamespace()),
        paths=OrchestraPaths(
            config_path=tmp_path / "config.yaml",
            catalog_path=tmp_path / "catalog.yaml",
        ),
    )

    from orchestra import roles as roles_module
    from orchestra.roles import (
        SelectedRole as module_selected_role,
    )
    from orchestra.roles import (
        format_roles as module_format_roles,
    )
    from orchestra.roles import (
        role_metadata as module_role_metadata,
    )
    from orchestra.roles import (
        set_role_setting as module_set_role_setting,
    )

    assert roles_module.SelectedRole is module_selected_role
    assert roles_module.format_roles(context) == module_format_roles(context)
    assert roles_module.role_metadata(context) == module_role_metadata(context)
    assert roles_module.set_role_setting is module_set_role_setting


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
            str(config_path.parent),
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
            str(config_path.parent),
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
            str(config_path.parent),
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


def _set_default_mode(config_path: Path, mode: str) -> None:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["mode"] = mode
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_status_prose_and_json_include_resolved_orchestra_tools(
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

    status_exit = main(["--config", str(config_path.parent), "status"])
    assert status_exit == 0
    assert capsys.readouterr().out.splitlines()[0] == "orchestra_tools: on"

    json_exit = main(
        ["--config", str(config_path.parent), "status", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert json_exit == 0
    assert payload["orchestra_tools"] == "on"
    assert "main_session_mode" not in payload

    session_exit = main(
        [
            "--config",
            str(config_path.parent),
            "status",
            "--session-id",
            "manual:mode-session",
        ]
    )
    assert session_exit == 0
    assert capsys.readouterr().out.splitlines()[0] == "orchestra_tools: on"


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
    _set_default_mode(config_path, "off")

    from orchestra.cli import main

    status_exit = main(["--config", str(config_path.parent), "status"])
    assert status_exit == 0
    assert capsys.readouterr().out.splitlines()[0] == "orchestra_tools: off"

    json_exit = main(
        ["--config", str(config_path.parent), "status", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert json_exit == 0
    assert payload["orchestra_tools"] == "off"


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
    _set_default_mode(config_path, "off")

    from orchestra.cli import main

    invalid_set_exit = main(
        [
            "--config",
            str(config_path.parent),
            "_session-mode",
            "set",
            "--session-id",
            "manual:mode-session",
            "--mode",
            "orchestrator",
        ]
    )
    invalid_set_output = capsys.readouterr().out
    assert invalid_set_exit == 1
    assert "error: invalid main session mode: orchestrator" in invalid_set_output

    set_json_exit = main(
        [
            "--config",
            str(config_path.parent),
            "_session-mode",
            "set",
            "--session-id",
            "manual:mode-session",
            "--mode",
            "off",
            "--json",
        ]
    )
    set_payload = json.loads(capsys.readouterr().out)

    assert set_json_exit == 0
    assert (
        set_payload["effect"]["display_text"]
        == "Orchestra tools hidden for this session. Run /orch on to enable them again."
    )
    assert set_payload["effect"]["mode"] == "off"
    assert set_payload["effect"]["tools_enabled"] is False
    assert "trigger_turn" not in set_payload["effect"]

    get_exit = main(
        [
            "--config",
            str(config_path.parent),
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
    assert payload["main_session_mode"] == "off"
    assert payload["explicit_main_session_mode"] == "off"

    other_get_exit = main(
        [
            "--config",
            str(config_path.parent),
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
            str(config_path.parent),
            "status",
            "--session-id",
            "manual:mode-session",
            "--json",
        ]
    )
    status_payload = json.loads(capsys.readouterr().out)

    assert status_json_exit == 0
    assert status_payload["orchestra_tools"] == "off"

    bare_status_exit = main(["--config", str(config_path.parent), "status"])
    assert bare_status_exit == 0
    assert capsys.readouterr().out.splitlines()[0] == "orchestra_tools: off"


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
            str(config_path.parent),
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
            str(config_path.parent),
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
            str(config_path.parent),
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
    instruction = load_root_prompt_config().dispatch_ack_instruction
    assert instruction
    assert output.strip() == f"orchestra dispatched: critic abc123\n{instruction}"


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


def test_internal_dispatch_ack_reports_concurrency_headroom(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, _catalog_path, db_path = runtime_files_factory(
        tmp_path,
        ["python", "-c", "print('noop')"],
    )
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["concurrency"] = {"global": 4, "per_session": 5}
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    store = StateStore(db_path)
    store.initialize()
    jobs = JobQueue(db_path)
    jobs.initialize(Limits(global_limit=4, per_owner_limit=5))
    seed_run(
        jobs,
        store,
        RunRecord(
            run_id="ack-run-1",
            orchestrator_session_id="manual:ack-session",
            harness="pi",
            role="builder",
            task_label="ack",
            log_path=tmp_path / "logs" / "ack-run-1.jsonl",
            created_at="2026-01-01T00:00:00Z",
            transcript_path=tmp_path / "transcripts" / "ack-run-1.jsonl",
        ),
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path.parent),
            "_dispatch-ack",
            "--run-id",
            "ack-run-1",
            "--role",
            "builder",
        ]
    )
    text_output = capsys.readouterr().out
    assert exit_code == 0
    assert "dispatch concurrency: 4/5 available" in text_output

    json_exit = main(
        [
            "--config",
            str(config_path.parent),
            "_dispatch-ack",
            "--run-id",
            "ack-run-1",
            "--role",
            "builder",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert json_exit == 0
    assert payload["concurrency_slots_remaining"] == 4
    assert payload["concurrency_limit"] == 5


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
            str(config_path.parent),
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
            str(config_path.parent),
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


def test_await_run_text_uses_same_budget_hint_as_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from orchestra.cli import main
    from orchestra.reports import SessionStatusDetails
    from orchestra.supervision import WORKER_BUDGET_EXCEEDED_BLOCKER

    record = RunRecord(
        run_id="budget-run",
        orchestrator_session_id="manual:demo",
        harness="pi",
        role="builder",
        task_label="build",
        log_path=Path("events.jsonl"),
        created_at="2026-01-01T00:00:00Z",
        status="incomplete",
        blocker_text=WORKER_BUDGET_EXCEEDED_BLOCKER,
    )
    prompts = load_root_prompt_config()
    details = SessionStatusDetails(True, True, False)
    monkeypatch.setattr(
        "orchestra.cli.load_context",
        lambda **_kwargs: SimpleNamespace(config=SimpleNamespace(prompts=prompts)),
    )
    monkeypatch.setattr(
        "orchestra.cli.await_run_terminal_status",
        lambda *_args, **_kwargs: (record, 0, details),
    )
    command = ["_await-run", "--session-id", "manual:demo", "--run-id", "budget-run"]

    assert main([*command, "--json"]) == 0
    json_hint = json.loads(capsys.readouterr().out)["next"]
    assert main(command) == 0
    assert f"next: {json_hint}" in capsys.readouterr().out
    assert json_hint == prompts.return_hint_budget_exceeded


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
                "mode": "on",
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
                    "verifier": {"harness_config": "pi", "enabled": "auto"},
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
            str(config_path.parent),
            "roles",
        ]
    )
    default_output = capsys.readouterr().out

    all_exit_code = main(
        [
            "--config",
            str(config_path.parent),
            "roles",
            "--all",
        ]
    )
    all_output = capsys.readouterr().out

    assert default_exit_code == 0
    assert "Configured roles" in default_output
    assert "Default: reviewer" not in default_output
    assert "  D  reviewer [hermes]" in default_output
    assert "  A  verifier [pi]" in default_output
    assert "      enabled: auto" in default_output
    assert "      dispatch: auto-only" in default_output
    assert "  ✗  worker [pi]" not in default_output

    assert all_exit_code == 0
    assert "Default: reviewer" not in all_output
    assert "  D  reviewer [hermes]" in all_output
    assert "  A  verifier [pi]" in all_output
    assert "      enabled: auto" in all_output
    assert "      dispatch: auto-only" in all_output
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
                "mode": "on",
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
            str(config_path.parent),
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
                "mode": "on",
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
            str(config_path.parent),
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


def test_roles_command_accepts_auto_enabled_value(
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
                "mode": "on",
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
            str(config_path.parent),
            "roles",
            "reviewer",
            "enabled",
            "auto",
        ]
    )
    output = capsys.readouterr().out
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "Updated role reviewer: enabled=auto" in output
    assert "  A  reviewer [pi]" in output
    assert "      enabled: auto" in output
    assert "      dispatch: auto-only" in output
    assert catalog["roles"]["reviewer"]["enabled"] == "auto"


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
                "mode": "on",
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
            str(config_path.parent),
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
                "mode": "on",
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
                str(config_path.parent),
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
                "mode": "on",
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
            "error: enabled must be one of true/yes/y/1/on, auto, or false/no/n/0/off; got 'maybe'",
        ),
        (
            ["reviewer", "enabled", "2"],
            "error: enabled must be one of true/yes/y/1/on, auto, or false/no/n/0/off; got '2'",
        ),
        (
            ["builder", "enabled", "auto"],
            "error: cannot make default role auto-only: builder",
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
                str(config_path.parent),
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
    assert "enabled   true/false/auto" in incomplete_usage_output
    assert "harness   selected harness config name" in incomplete_usage_output
    assert "profile   optional harness profile, when supported" in incomplete_usage_output
    assert "auto" in incomplete_usage_output

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
                "mode": "on",
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
                "roles": {
                    "worker": {"harness_config": "pi"},
                    "builder": {"harness_config": "pi", "pass_parent_context": True},
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
            str(config_path.parent),
            "_role-metadata",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    # Host adapters read opt-in and default role from core metadata instead of scanning YAML.
    assert payload == {
        "roles": ["builder", "worker"],
        "harnessConfigs": ["pi", "unused"],
        "passParentContext": ["builder"],
        "defaultRole": "worker",
    }


def test_removed_opencode_help_command_is_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from orchestra.cli import main

    with pytest.raises(SystemExit) as raised:
        main(["help-opencode"])

    captured = capsys.readouterr()
    assert raised.value.code != 0
    assert "OpenCode /orch commands:" not in captured.out


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
                "mode": "on",
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
            str(config_path.parent),
            "help-host",
        ]
    )
    help_output = capsys.readouterr().out

    tool_exit = main(
        [
            "--config",
            str(config_path.parent),
            "_tool-info",
        ]
    )
    tool_output = capsys.readouterr().out
    tool_info = json.loads(tool_output)

    assert help_exit == 0
    assert tool_exit == 0
    assert (
        "/orch on                           Enable Orchestra tools"
        in help_output
    )
    assert "/orch off                          Hide Orchestra tools for this session" in help_output
    assert "/orch roles" in help_output
    assert (
        "/orch config [KEY] [VALUE]         Show or update supported config values"
        in help_output
    )
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
    assert "Selectable roles" in tool_info["description"]
    assert "- worker" in tool_info["description"]
    assert "- reviewer (default)" in tool_info["description"]
    assert "model: gpt-5" not in tool_info["description"]
    configured_prompts = load_root_prompt_config()
    assert tool_info["roleDescription"] == configured_prompts.tool_role_description.format(
        roles="Selectable roles\n- worker\n- reviewer (default)"
    )
    assert "- worker" in tool_info["roleDescription"]
    assert "- reviewer (default)" in tool_info["roleDescription"]
    assert "critic" not in tool_info["description"]
    assert "critic" not in tool_info["roleDescription"]
    assert "Legend:" not in tool_info["description"]
    for key, value in (
        ("statusDescription", configured_prompts.status_description),
        ("statusActionDescription", configured_prompts.status_action_description),
        ("statusLimitDescription", configured_prompts.status_limit_description),
        ("statusRunIdDescription", configured_prompts.status_run_id_description),
        ("statusRoleDescription", configured_prompts.status_role_description),
        ("statusSettingDescription", configured_prompts.status_setting_description),
        ("statusValueDescription", configured_prompts.status_value_description),
        ("budgetTriggerLabel", configured_prompts.budget_trigger_label),
        ("softTimeoutBlockReason", configured_prompts.soft_timeout_block_reason),
    ):
        assert tool_info[key] == value
    assert tool_info["dispatchTimeoutError"] == (
        "timeout is not accepted by orch_dispatch; configured default_timeout applies."
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
        "mode": "on",
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
                    "orchestrator": {"skills": ["orchestrator", "planner"]},
                    "worker": {"harness_config": "pi"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path, catalog_path


def test_tool_info_exposes_default_and_resolved_session_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from orchestra.cli import main

    config_path, _catalog_path = _write_tool_info_fixture(tmp_path)
    base_args = ["--config", str(config_path.parent)]

    exit_code = main([*base_args, "_tool-info"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert "toolsEnabledByDefault" not in payload
    assert payload["mainSessionMode"] == "on"
    # Existing tool-info fields remain intact.
    for key in (
        "description",
        "promptSnippet",
        "statusDescription",
        "dispatchTimeoutError",
    ):
        assert key in payload

    invalid_set_exit = main(
        [*base_args, "_session-mode", "set", "--session-id", "pi:s1", "--mode", "orchestrator"]
    )
    invalid_output = capsys.readouterr().out
    assert invalid_set_exit == 1
    assert "error: invalid main session mode: orchestrator" in invalid_output

    set_exit = main(
        [*base_args, "_session-mode", "set", "--session-id", "pi:s1", "--mode", "on"]
    )
    capsys.readouterr()
    assert set_exit == 0

    exit_code = main([*base_args, "_tool-info", "--session-id", "pi:s1"])
    resolved = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert resolved["mainSessionMode"] == "on"
    assert "toolsEnabledByDefault" not in resolved

    spsi_set_exit = main(
        [*base_args, "_session-mode", "set", "--session-id", "pi:s1", "--mode", "orchestrate"]
    )
    capsys.readouterr()
    assert spsi_set_exit == 0

    spsi_exit = main([*base_args, "_spsi-payload", "--session-id", "pi:s1", "--json"])
    spsi = json.loads(capsys.readouterr().out)
    assert spsi_exit == 0
    assert spsi["kind"] == "spsi_payload"
    assert spsi["enabled"] is True
    assert spsi["name"] == "orchestra.spsi.role-skills"
    assert spsi["revision"].startswith("sha256:")
    assert "<orchestra_spsi" in spsi["content"]

    # Without a session id the config-resolved default still applies.
    exit_code = main([*base_args, "_tool-info"])
    fallback = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert fallback["mainSessionMode"] == "on"


def test_tool_info_reflects_off_default_mode(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from orchestra.cli import main

    config_path, catalog_path = _write_tool_info_fixture(tmp_path, {"mode": "off"})

    exit_code = main(
        ["--config", str(config_path.parent), "_tool-info"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert "toolsEnabledByDefault" not in payload
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
                "mode": "on",
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
            str(config_path.parent),
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
                "mode": "on",
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
                        "dispatch_hint": "Review only.",
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
            str(config_path.parent),
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
    assert record.result_output is None

    return_text = canonical_return_path(tmp_path / "state", run_id).read_text(encoding="utf-8")
    payload = json.loads(return_text.split("## stdout\n\n", 1)[1].strip())
    assert payload["argv"] == ["--model", "fallback-model"]
    assert payload["nested_dispatch_depth"] == "2"
    assert payload["role_env"] == "configured"
    assert "Role: reviewer" in payload["prompt"]
    assert "Role skills:" not in payload["prompt"]
    assert "Skill instructions are delivered through SPSI." not in payload["prompt"]
    assert f"Skill directory: {skill_dir}" not in payload["prompt"]
    assert "Resolve relative resource paths against this directory." not in payload["prompt"]
    assert "# Reviewer Skill" not in payload["prompt"]
    assert "Role instructions: Review only." in payload["prompt"]

    history_exit = main(
        [
            "--config",
            str(config_path.parent),
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
                "mode": "on",
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
            str(config_path.parent),
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


def test_do_parent_context_artifact_missing_file_errors(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, _, _ = runtime_files_factory(
        tmp_path,
        [python_executable, "-c", "print('done')"],
    )

    from orchestra.cli import main

    missing_path = str(tmp_path / "does-not-exist.md")
    exit_code = main(
        [
            "--config",
            str(config_path.parent),
            "do",
            "--session-id",
            "manual:parent-ctx-missing",
            "--goal",
            "Test missing artifact.",
            "--parent-context-artifact",
            missing_path,
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert f"parent context artifact file does not exist: {missing_path}" in output


def test_do_parent_context_artifact_is_copied_into_run_state(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, "-c", "print('done')"],
    )

    artifact_file = tmp_path / "parent-context.md"
    artifact_file.write_text("# Parent Context\nSome session data.", encoding="utf-8")

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path.parent),
            "do",
            "--session-id",
            "manual:parent-ctx-valid",
            "--goal",
            "Test valid artifact.",
            "--additional-context",
            "extra context here",
            "--parent-context-artifact",
            str(artifact_file),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    run_id = extract_run_id(output)
    request_file = tmp_path / "state" / "runs" / run_id / "request.json"
    payload = json.loads(request_file.read_text(encoding="utf-8"))

    # Core owns the run-scoped copy; the request carries that path, not the adapter temp file.
    run_scoped = tmp_path / "state" / "runs" / run_id / "parent-context.jsonl"
    assert payload["parent_context_artifact"] == str(run_scoped)
    assert run_scoped.read_text(encoding="utf-8") == "# Parent Context\nSome session data."
    assert run_scoped.stat().st_mode & 0o777 == 0o600
    # Existing additional context behavior unchanged.
    assert payload["additional_context"] == "extra context here"


def test_do_parent_context_artifact_stdin_written_to_run_state(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io

    config_path, _, _ = runtime_files_factory(
        tmp_path,
        [python_executable, "-c", "print('done')"],
    )

    stdin_content = '{"role": "user", "content": "live parent turn"}\n'
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_content))

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path.parent),
            "do",
            "--session-id",
            "manual:parent-ctx-stdin",
            "--goal",
            "Test stdin artifact.",
            "--additional-context",
            "extra context here",
            "--parent-context-artifact",
            "-",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    run_id = extract_run_id(output)
    request_file = tmp_path / "state" / "runs" / run_id / "request.json"
    payload = json.loads(request_file.read_text(encoding="utf-8"))

    # Core writes the only persistent snapshot to the run-scoped private artifact.
    run_scoped = tmp_path / "state" / "runs" / run_id / "parent-context.jsonl"
    assert payload["parent_context_artifact"] == str(run_scoped)
    assert run_scoped.read_text(encoding="utf-8") == stdin_content
    assert run_scoped.stat().st_mode & 0o777 == 0o600
    # The stdin content never enters the request payload or additional context.
    assert "live parent turn" not in request_file.read_text(encoding="utf-8")
    assert payload["additional_context"] == "extra context here"


def test_do_without_parent_context_artifact_defaults_to_none(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, _, _ = runtime_files_factory(
        tmp_path,
        [python_executable, "-c", "print('done')"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path.parent),
            "do",
            "--session-id",
            "manual:parent-ctx-absent",
            "--goal",
            "No parent context.",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    run_id = extract_run_id(output)
    request_file = tmp_path / "state" / "runs" / run_id / "request.json"
    payload = json.loads(request_file.read_text(encoding="utf-8"))

    assert payload["parent_context_artifact"] is None
    assert not (tmp_path / "state" / "runs" / run_id / "parent-context.jsonl").exists()
