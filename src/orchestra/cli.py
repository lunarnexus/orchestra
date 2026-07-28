"""CLI entrypoint for Orchestra."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from orchestra.app import (
    AppError,
    await_run_terminal_status,
    await_session_report,
    consume_pending_session_report,
    format_command_echo,
    format_dispatch_ack,
    format_doctor_checks,
    format_history,
    format_host_help,
    format_progress_notification,
    format_roles,
    format_run_report,
    format_started_run,
    format_status,
    init_pi,
    load_context,
    run_doctor,
    run_supervisor,
    start_run,
    stop_run,
    tool_info,
)
from orchestra.config import ConfigError
from orchestra.state import StateError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestra",
        description=(
            "Agent-agnostic orchestration control plane for focused worker agents."
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "path to config.yaml; defaults to ORCHESTRA_CONFIG, then "
            "${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/config.yaml, then ./config.yaml"
        ),
    )
    parser.add_argument(
        "--agent-catalog",
        default=None,
        help=(
            "path to agent-catalog.yaml; defaults to ORCHESTRA_AGENT_CATALOG, then "
            "${PI_CODING_AGENT_DIR:-~/.pi/agent}/orchestra/agent-catalog.yaml, "
            "then ./agent-catalog.yaml"
        ),
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    do_parser = subparsers.add_parser("do", help="dispatch a worker run")
    do_parser.add_argument(
        "--session-id",
        required=True,
        help=(
            "local/manual session id for CLI mode; trusted host adapters "
            "supply session ids from runtime context"
        ),
    )
    do_parser.add_argument("--role", default="worker", help="worker role name")
    do_parser.add_argument("--goal", required=True, help="goal for the worker")
    do_parser.add_argument("--approved-context", default="", help="approved context for the worker")
    do_parser.add_argument("--boundaries", default="", help="out-of-scope boundaries")
    do_parser.add_argument("--acceptance-target", default="", help="acceptance target")
    do_parser.add_argument("--return-format", default="", help="explicit return format")
    do_parser.add_argument("--timeout", type=int, default=None, help="timeout in seconds")
    do_parser.add_argument("--task-label", default="", help="short task label")
    do_parser.add_argument("--batch-id", default=None, help="optional batch id")
    do_parser.set_defaults(handler=_handle_do)

    status_parser = subparsers.add_parser("status", help="show active run status")
    status_parser.add_argument(
        "--session-id",
        required=True,
        help="local/manual session id for CLI mode",
    )
    status_parser.set_defaults(handler=_handle_status)

    stop_parser = subparsers.add_parser("stop", help="stop a worker run")
    stop_parser.add_argument(
        "--session-id",
        required=True,
        help="local/manual session id for CLI mode",
    )
    stop_parser.add_argument("--run-id", required=True, help="run id to cancel")
    stop_parser.set_defaults(handler=_handle_stop)

    doctor_parser = subparsers.add_parser("doctor", help="check local setup")
    doctor_parser.set_defaults(handler=_handle_doctor)

    roles_parser = subparsers.add_parser("roles", help="list configured worker roles")
    roles_parser.set_defaults(handler=_handle_roles)

    help_parser = subparsers.add_parser("help-host", help="show host command help")
    help_parser.set_defaults(handler=_handle_help_host)

    history_parser = subparsers.add_parser("history", help="show prior run summaries")
    history_parser.add_argument(
        "--session-id",
        required=True,
        help="local/manual session id for CLI mode",
    )
    history_parser.add_argument("--limit", type=int, default=10, help="maximum number of runs")
    history_parser.set_defaults(handler=_handle_history)

    init_parser = subparsers.add_parser("init", help="initialize host integrations")
    init_subparsers = init_parser.add_subparsers(dest="init_target", metavar="TARGET")
    init_pi_parser = init_subparsers.add_parser("pi", help="install global Pi extension/config")
    init_pi_parser.add_argument("--force", action="store_true", help="overwrite existing files")
    init_pi_parser.set_defaults(handler=_handle_init_pi)

    supervisor_parser = subparsers.add_parser("_run-supervisor", help=argparse.SUPPRESS)
    supervisor_parser.add_argument("--run-id", required=True)
    supervisor_parser.add_argument("--request-file", required=True)
    supervisor_parser.set_defaults(handler=_handle_run_supervisor)

    pending_parser = subparsers.add_parser("_pending-report", help=argparse.SUPPRESS)
    pending_parser.add_argument("--session-id", required=True)
    pending_parser.set_defaults(handler=_handle_pending_report)

    wait_parser = subparsers.add_parser("_await-session-report", help=argparse.SUPPRESS)
    wait_parser.add_argument("--session-id", required=True)
    wait_parser.add_argument("--run-id", required=True)
    wait_parser.add_argument("--timeout", type=float, default=None)
    wait_parser.set_defaults(handler=_handle_await_session_report)

    wait_run_parser = subparsers.add_parser("_await-run", help=argparse.SUPPRESS)
    wait_run_parser.add_argument("--session-id", required=True)
    wait_run_parser.add_argument("--run-id", required=True)
    wait_run_parser.add_argument("--timeout", type=float, default=None)
    wait_run_parser.set_defaults(handler=_handle_await_run)

    dispatch_ack_parser = subparsers.add_parser("_dispatch-ack", help=argparse.SUPPRESS)
    dispatch_ack_parser.add_argument("--run-id", required=True)
    dispatch_ack_parser.set_defaults(handler=_handle_dispatch_ack)

    progress_parser = subparsers.add_parser("_progress-message", help=argparse.SUPPRESS)
    progress_parser.add_argument("--completed", type=int, required=True)
    progress_parser.add_argument("--total", type=int, required=True)
    progress_parser.add_argument("--run-id", required=True)
    progress_parser.add_argument("--status", required=True)
    progress_parser.set_defaults(handler=_handle_progress_message)

    echo_parser = subparsers.add_parser("_command-echo", help=argparse.SUPPRESS)
    echo_parser.add_argument("raw_command")
    echo_parser.set_defaults(handler=_handle_command_echo)

    tool_info_parser = subparsers.add_parser("_tool-info", help=argparse.SUPPRESS)
    tool_info_parser.set_defaults(handler=_handle_tool_info)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    try:
        return int(handler(args))
    except (AppError, ConfigError, StateError, KeyError) as exc:
        print(f"error: {exc}")
        return 1


def _handle_do(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    started = start_run(
        context,
        session_id=args.session_id,
        role_name=args.role,
        goal=args.goal,
        approved_context=args.approved_context,
        boundaries=args.boundaries,
        acceptance_target=args.acceptance_target,
        return_format=args.return_format,
        timeout_seconds=args.timeout,
        task_label=args.task_label,
        batch_id=args.batch_id,
    )
    print(format_started_run(started))
    return 0


def _handle_status(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    print(format_status(context, args.session_id))
    return 0


def _handle_stop(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    record = stop_run(context, args.session_id, args.run_id)
    print(format_run_report(record))
    return 0


def _handle_doctor(args: argparse.Namespace) -> int:
    checks = run_doctor(config_path=args.config, catalog_path=args.agent_catalog)
    print(format_doctor_checks(checks))
    return 0 if all(check.ok for check in checks) else 1


def _handle_roles(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    print(format_roles(context))
    return 0


def _handle_help_host(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    print(format_host_help(context))
    return 0


def _handle_history(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    if args.limit < 1:
        raise AppError("limit must be a positive integer")
    print(format_history(context, args.session_id, args.limit))
    return 0


def _handle_init_pi(args: argparse.Namespace) -> int:
    result = init_pi(force=bool(args.force))
    for file_result in result.files:
        print(f"{file_result.action}: {file_result.target}")
    print(f"verify: {result.verification_command}")
    return 0


def _handle_dispatch_ack(args: argparse.Namespace) -> int:
    print(format_dispatch_ack(args.run_id))
    return 0


def _handle_command_echo(args: argparse.Namespace) -> int:
    print(format_command_echo(args.raw_command))
    return 0


def _handle_tool_info(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    info = tool_info(context)
    print(
        json.dumps(
            {
                "description": info.description,
                "promptSnippet": info.prompt_snippet,
                "promptGuidelines": info.prompt_guidelines,
                "goalDescription": info.goal_description,
                "roleDescription": info.role_description,
                "timeoutDescription": info.timeout_description,
                "taskLabelDescription": info.task_label_description,
            }
        )
    )
    return 0


def _handle_progress_message(args: argparse.Namespace) -> int:
    print(
        format_progress_notification(
            completed_count=args.completed,
            total_count=args.total,
            run_id=args.run_id,
            status=args.status,
        )
    )
    return 0


def _handle_run_supervisor(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    run_supervisor(context, run_id=args.run_id, request_file=args.request_file)
    return 0


def _handle_pending_report(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    report = consume_pending_session_report(context, args.session_id)
    if report:
        print(report)
    return 0


def _handle_await_session_report(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    report = await_session_report(
        context,
        args.session_id,
        run_id=args.run_id,
        timeout_seconds=args.timeout,
    )
    if report:
        print(report)
    return 0


def _handle_await_run(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    record, active_remaining = await_run_terminal_status(
        context,
        args.session_id,
        run_id=args.run_id,
        timeout_seconds=args.timeout,
    )
    print(f"run_id: {record.run_id}")
    print(f"status: {record.status}")
    print(f"active_runs_remaining: {active_remaining}")
    return 0
