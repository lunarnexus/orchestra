"""CLI entrypoint for Orchestra."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from orchestra.config import (
    ConfigError,
    list_config_values,
    read_config_value,
    resolve_config_path,
    update_config_value,
)
from orchestra.context import AppError, load_context
from orchestra.dispatch import format_started_run, start_run, started_run_payload
from orchestra.host_commands import (
    dispatch_command_payload,
    session_mode_transition_payload,
    tool_info_payload,
)
from orchestra.host_text import (
    ROLE_USAGE,
    dispatch_ack_payload,
    format_command_echo,
    format_dispatch_ack,
    format_host_help,
    format_opencode_help,
    format_progress_notification,
    progress_notification_payload,
    render_orchestrator_skill_message,
)
from orchestra.init import (
    InitFileResult,
    doctor_checks_pass,
    format_doctor_checks,
    init_all,
    init_codex,
    init_hermes,
    init_opencode,
    init_pi,
    run_doctor,
)
from orchestra.reports import (
    await_run_terminal_status,
    await_session_report,
    await_session_report_payload,
    consume_pending_session_report,
    format_run_report,
    mark_session_report_delivered,
    release_session_report,
    session_report_payload,
)
from orchestra.roles import format_roles, role_metadata, set_role_setting
from orchestra.session_mode import (
    main_session_state_payload,
    set_main_session_mode,
)
from orchestra.state import StateError
from orchestra.status import (
    await_run_payload,
    format_debug_run,
    format_debug_session,
    format_history,
    format_status,
    status_payload,
)
from orchestra.supervision import run_supervisor_guarded, stop_run

INTERNAL_COMMANDS = frozenset(
    {
        "help-host",
        "help-opencode",
        "_run-supervisor",
        "_pending-report",
        "_await-session-report",
        "_await-run",
        "_mark-session-report-delivered",
        "_release-session-report",
        "_dispatch-command",
        "_dispatch-ack",
        "_progress-message",
        "_command-echo",
        "_session-mode",
        "_tool-info",
        "_role-metadata",
        "_orchestrator-skill",
    }
)


def build_parser(*, include_internal: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestra",
        description="Focused worker-agent orchestration.",
        epilog=(
            "Examples:\n"
            "  orchestra doctor\n"
            "  orchestra roles\n"
            "  orchestra config\n"
            "  orchestra do --session-id manual:demo --goal \"smoke test\"\n"
            "  orchestra history --session-id manual:demo"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="config file path",
    )
    parser.add_argument(
        "--agent-catalog",
        metavar="PATH",
        default=None,
        help="agent catalog file path",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>", title="commands")

    do_parser = subparsers.add_parser("do", help="dispatch a worker run")
    do_parser.add_argument(
        "--session-id",
        required=True,
        help=(
            "local/manual session id for CLI mode; runtime host adapters "
            "supply session ids from runtime context"
        ),
    )
    do_parser.add_argument("--role", default=None, help="worker role name")
    do_parser.add_argument("--goal", required=True, help="goal for the worker")
    do_parser.add_argument("--approved-context", default="", help="approved context for the worker")
    do_parser.add_argument("--boundaries", default="", help="out-of-scope boundaries")
    do_parser.add_argument("--acceptance-target", default="", help="acceptance target")
    do_parser.add_argument("--return-format", default="", help="explicit return format")
    do_parser.add_argument("--timeout", type=_positive_int, default=None, help="timeout in seconds")
    do_parser.add_argument("--task-label", default="", help="short task label")
    do_parser.add_argument("--batch-id", default=None, help="optional batch id")
    do_parser.add_argument("--json", action="store_true")
    do_parser.set_defaults(handler=_handle_do)

    status_parser = subparsers.add_parser("status", help="show active run status")
    status_parser.add_argument(
        "--session-id",
        default=None,
        help="local/manual session id for CLI mode",
    )
    status_parser.add_argument("--json", action="store_true")
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
    roles_parser.add_argument(
        "--all",
        action="store_true",
        help="include disabled roles and default role metadata",
    )
    roles_parser.add_argument("role", nargs="?", help="role to update")
    roles_parser.add_argument(
        "setting",
        nargs="?",
        choices=("harness", "enabled", "model", "profile", "agent"),
        help="role setting to update",
    )
    roles_parser.add_argument("value", nargs="?", help="new role setting value")
    roles_parser.set_defaults(handler=_handle_roles)

    config_parser = subparsers.add_parser("config", help="read or update config values")
    config_parser.add_argument("key", nargs="?", help="config key to read or update")
    config_parser.add_argument("value", nargs="?", help="new config value")
    config_parser.set_defaults(handler=_handle_config)

    if include_internal:
        help_parser = subparsers.add_parser("help-host", help=argparse.SUPPRESS)
        help_parser.set_defaults(handler=_handle_help_host)

        opencode_help_parser = subparsers.add_parser("help-opencode", help=argparse.SUPPRESS)
        opencode_help_parser.set_defaults(handler=_handle_help_opencode)

    history_parser = subparsers.add_parser("history", help="show prior run summaries")
    history_parser.add_argument(
        "--session-id",
        required=True,
        help="local/manual session id for CLI mode",
    )
    history_parser.add_argument("--limit", type=int, default=10, help="maximum number of runs")
    history_parser.set_defaults(handler=_handle_history)

    prune_parser = subparsers.add_parser("prune", help="prune old runtime state")
    prune_parser.add_argument(
        "--retention-days",
        type=_positive_int,
        default=None,
        help="override configured retention_days for this prune run",
    )
    prune_parser.add_argument(
        "--delete",
        action="store_true",
        help="delete old terminal runs, owned runtime files, and safe old orphan files",
    )
    prune_parser.add_argument(
        "--json",
        action="store_true",
        help="print the prune result as JSON",
    )
    prune_parser.set_defaults(handler=_handle_prune)

    debug_parser = subparsers.add_parser("debug", help="print run/session debug bundle")
    debug_target = debug_parser.add_mutually_exclusive_group(required=True)
    debug_target.add_argument("--run-id", help="run id to inspect")
    debug_target.add_argument("--session-id", help="session id to inspect")
    debug_parser.add_argument("--limit", type=int, default=20, help="maximum session runs")
    debug_parser.set_defaults(handler=_handle_debug)

    init_parser = subparsers.add_parser("init", help="initialize host integrations")
    init_subparsers = init_parser.add_subparsers(dest="init_target", metavar="TARGET")
    init_pi_parser = init_subparsers.add_parser("pi", help="install global Pi extension")
    init_pi_parser.add_argument("--force", action="store_true", help="overwrite existing files")
    init_pi_parser.add_argument(
        "--copy",
        action="store_true",
        help="copy config files instead of linking",
    )
    init_pi_parser.set_defaults(handler=_handle_init_pi)

    init_hermes_parser = init_subparsers.add_parser("hermes", help="install Hermes plugin")
    init_hermes_parser.add_argument(
        "--profile",
        default=None,
        help="optional Hermes profile override",
    )
    init_hermes_parser.add_argument("--force", action="store_true", help="force reinstall")
    init_hermes_parser.add_argument(
        "--copy",
        action="store_true",
        help="copy config files instead of linking",
    )
    init_hermes_parser.set_defaults(handler=_handle_init_hermes)

    init_opencode_parser = init_subparsers.add_parser(
        "opencode",
        help="install OpenCode plugin",
    )
    init_opencode_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing plugin file",
    )
    init_opencode_parser.add_argument(
        "--copy",
        action="store_true",
        help="copy plugin file from source checkout",
    )
    init_opencode_parser.set_defaults(handler=_handle_init_opencode)

    init_codex_parser = init_subparsers.add_parser(
        "codex",
        help="install Codex plugin scaffold",
    )
    init_codex_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing plugin source and marketplace entry",
    )
    init_codex_parser.add_argument(
        "--copy",
        action="store_true",
        help="copy plugin directory instead of linking",
    )
    init_codex_parser.set_defaults(handler=_handle_init_codex)

    init_all_parser = init_subparsers.add_parser(
        "all",
        help="initialize configured integrations",
    )
    init_all_parser.add_argument("--force", action="store_true", help="overwrite existing files")
    init_all_parser.add_argument(
        "--copy",
        action="store_true",
        help="copy config files instead of linking",
    )
    init_all_parser.set_defaults(handler=_handle_init_all)

    if include_internal:
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
        wait_parser.add_argument("--json", action="store_true")
        wait_parser.set_defaults(handler=_handle_await_session_report)

        mark_report_parser = subparsers.add_parser(
            "_mark-session-report-delivered",
            help=argparse.SUPPRESS,
        )
        mark_report_parser.add_argument("--session-id", required=True)
        mark_report_parser.add_argument("--run-id", action="append", required=True)
        mark_report_parser.set_defaults(handler=_handle_mark_session_report_delivered)

        release_report_parser = subparsers.add_parser(
            "_release-session-report",
            help=argparse.SUPPRESS,
        )
        release_report_parser.add_argument("--session-id", required=True)
        release_report_parser.add_argument("--run-id", action="append", required=True)
        release_report_parser.set_defaults(handler=_handle_release_session_report)

        wait_run_parser = subparsers.add_parser("_await-run", help=argparse.SUPPRESS)
        wait_run_parser.add_argument("--session-id", required=True)
        wait_run_parser.add_argument("--run-id", required=True)
        wait_run_parser.add_argument("--timeout", type=float, default=None)
        wait_run_parser.add_argument("--json", action="store_true")
        wait_run_parser.set_defaults(handler=_handle_await_run)

        dispatch_command_parser = subparsers.add_parser("_dispatch-command", help=argparse.SUPPRESS)
        dispatch_command_parser.add_argument("--session-id", required=True)
        dispatch_command_parser.add_argument("--goal", required=True)
        dispatch_command_parser.add_argument("--role", default=None)
        dispatch_command_parser.add_argument("--timeout", type=_positive_int, default=None)
        dispatch_command_parser.add_argument("--task-label", default=None)
        dispatch_command_parser.add_argument("--json", action="store_true")
        dispatch_command_parser.set_defaults(handler=_handle_dispatch_command)

        dispatch_ack_parser = subparsers.add_parser("_dispatch-ack", help=argparse.SUPPRESS)
        dispatch_ack_parser.add_argument("--run-id", required=True)
        dispatch_ack_parser.add_argument("--role", default=None)
        dispatch_ack_parser.add_argument("--json", action="store_true")
        dispatch_ack_parser.set_defaults(handler=_handle_dispatch_ack)

        progress_parser = subparsers.add_parser("_progress-message", help=argparse.SUPPRESS)
        progress_parser.add_argument("--completed", type=int, required=True)
        progress_parser.add_argument("--total", type=int, required=True)
        progress_parser.add_argument("--run-id", required=True)
        progress_parser.add_argument("--status", required=True)
        progress_parser.add_argument("--role", default=None)
        progress_parser.add_argument("--json", action="store_true")
        progress_parser.set_defaults(handler=_handle_progress_message)

        echo_parser = subparsers.add_parser("_command-echo", help=argparse.SUPPRESS)
        echo_parser.add_argument("raw_command")
        echo_parser.set_defaults(handler=_handle_command_echo)

        session_mode_parser = subparsers.add_parser(
            "_session-mode",
            help=argparse.SUPPRESS,
        )
        session_mode_subparsers = session_mode_parser.add_subparsers(
            dest="session_mode_action",
            metavar="ACTION",
            required=True,
        )
        session_mode_set_parser = session_mode_subparsers.add_parser("set")
        session_mode_set_parser.add_argument("--session-id", required=True)
        session_mode_set_parser.add_argument("--mode", required=True)
        session_mode_set_parser.add_argument("--json", action="store_true")
        session_mode_set_parser.set_defaults(handler=_handle_session_mode)

        session_mode_get_parser = session_mode_subparsers.add_parser("get")
        session_mode_get_parser.add_argument("--session-id", required=True)
        session_mode_get_parser.add_argument("--json", action="store_true")
        session_mode_get_parser.set_defaults(handler=_handle_session_mode)

        tool_info_parser = subparsers.add_parser("_tool-info", help=argparse.SUPPRESS)
        tool_info_parser.add_argument(
            "--session-id",
            default=None,
            help="optional session id for resolving main_session_mode",
        )
        tool_info_parser.set_defaults(handler=_handle_tool_info)

        role_metadata_parser = subparsers.add_parser("_role-metadata", help=argparse.SUPPRESS)
        role_metadata_parser.set_defaults(handler=_handle_role_metadata)

        orchestrator_skill_parser = subparsers.add_parser(
            "_orchestrator-skill",
            help=argparse.SUPPRESS,
        )
        orchestrator_skill_parser.set_defaults(handler=_handle_orchestrator_skill)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser(include_internal=_uses_internal_command(effective_argv))
    args = parser.parse_args(effective_argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    try:
        return int(handler(args))
    except (AppError, ConfigError, StateError) as exc:
        print(f"error: {exc}")
        return 1
    except KeyError as exc:
        detail = exc.args[0] if exc.args else str(exc)
        print(f"error: {detail}")
        return 1


def _uses_internal_command(argv: Sequence[str]) -> bool:
    return any(token in INTERNAL_COMMANDS for token in argv)


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


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
    if args.json:
        print(
            json.dumps(
                started_run_payload(started, prompts=context.config.prompts)
            )
        )
    else:
        print(format_started_run(started, prompts=context.config.prompts))
    return 0


def _handle_status(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    if args.json:
        print(json.dumps(status_payload(context, args.session_id)))
    else:
        print(format_status(context, args.session_id))
    return 0


def _handle_session_mode(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    if not args.session_id.strip():
        raise AppError("session_id is required")
    action = args.session_mode_action
    if action == "set":
        state = set_main_session_mode(context, args.session_id, args.mode)
        if getattr(args, "json", False):
            print(
                json.dumps(
                    session_mode_transition_payload(
                        context,
                        args.session_id,
                        state.main_session_mode,
                    ).to_payload()
                )
            )
        else:
            print(f"main_session_mode: {state.main_session_mode}")
        return 0
    payload = main_session_state_payload(context, args.session_id)
    if getattr(args, "json", False):
        print(json.dumps(payload))
    else:
        print(f"main_session_mode: {payload['main_session_mode']}")
    return 0


def _handle_stop(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    record = stop_run(context, args.session_id, args.run_id)
    print(format_run_report(record, prompts=context.config.prompts))
    return 0


def _handle_doctor(args: argparse.Namespace) -> int:
    checks = run_doctor(config_path=args.config, catalog_path=args.agent_catalog)
    print(format_doctor_checks(checks))
    return 0 if doctor_checks_pass(checks) else 1


def _handle_roles(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    role_update_args = (args.role, args.setting, args.value)
    if any(value is not None for value in role_update_args):
        if any(value is None for value in role_update_args):
            raise AppError(f"missing value for role setting\n\n{ROLE_USAGE}")
        print(set_role_setting(context, args.role, args.setting, args.value))
        return 0
    print(format_roles(context, include_disabled=args.all))
    return 0


def _handle_config(args: argparse.Namespace) -> int:
    config_path = resolve_config_path(args.config)
    if args.key is None:
        values = list_config_values(config_path)
        for key, value in values.items():
            print(f"{key}: {value}")
        return 0
    if args.value is None:
        print(read_config_value(config_path, args.key))
        return 0
    print(update_config_value(config_path, args.key, args.value))
    return 0


def _handle_help_host(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    print(format_host_help(context))
    return 0


def _handle_help_opencode(args: argparse.Namespace) -> int:
    del args
    print(format_opencode_help())
    return 0


def _handle_history(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    if args.limit < 1:
        raise AppError("limit must be a positive integer")
    print(format_history(context, args.session_id, args.limit))
    return 0


def _handle_prune(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    retention_days = args.retention_days or context.config.retention_days
    plan = context.store.plan_prune(
        retention_days,
        request_dir=context.config.state_dir / "requests",
        log_dir=context.config.log_dir,
    )
    result = None
    if args.delete:
        result = context.store.delete_prune_candidates(
            plan,
            allowed_roots=(context.config.state_dir, context.config.log_dir),
        )
    payload = {
        "kind": "prune",
        "ok": result is None or not result.failed_paths,
        "dry_run": not args.delete,
        "retention_days": plan.retention_days,
        "cutoff_at": plan.cutoff_at,
        "candidate_count": len(plan.candidates),
        "candidates": [
            {
                "run_id": candidate.run_id,
                "session_id": candidate.orchestrator_session_id,
                "role": candidate.role,
                "status": candidate.status,
                "created_at": candidate.created_at,
                "owned_paths": [str(path) for path in candidate.owned_paths],
            }
            for candidate in plan.candidates
        ],
        "orphan_candidate_count": len(plan.orphan_candidates),
        "orphan_candidates": [str(path) for path in plan.orphan_candidates],
        "deleted_run_ids": list(result.deleted_run_ids) if result else [],
        "deleted_session_ids": list(result.deleted_session_ids) if result else [],
        "deleted_paths": [str(path) for path in result.deleted_paths] if result else [],
        "skipped_paths": [str(path) for path in result.skipped_paths] if result else [],
        "failed_paths": [str(path) for path in result.failed_paths] if result else [],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if args.delete:
            print("prune: delete completed")
        else:
            print("prune: dry-run only; no deletion performed")
        print(f"retention_days: {plan.retention_days}")
        print(f"cutoff_at: {plan.cutoff_at}")
        print(f"candidate_count: {len(plan.candidates)}")
        for candidate in plan.candidates:
            print(
                f"- {candidate.run_id} {candidate.status} {candidate.role} "
                f"session={candidate.orchestrator_session_id} created_at={candidate.created_at}"
            )
            for path in candidate.owned_paths:
                print(f"  path: {path}")
        if plan.orphan_candidates:
            print("orphan_candidates:")
            for path in plan.orphan_candidates:
                print(f"- {path}")
        if result:
            print(f"deleted_runs: {len(result.deleted_run_ids)}")
            print(f"deleted_sessions: {len(result.deleted_session_ids)}")
            print(f"deleted_paths: {len(result.deleted_paths)}")
            if result.skipped_paths:
                print("skipped_paths:")
                for path in result.skipped_paths:
                    print(f"- {path}")
            if result.failed_paths:
                print("failed_paths:")
                for path in result.failed_paths:
                    print(f"- {path}")
    return 1 if result and result.failed_paths else 0


def _handle_debug(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    if args.run_id:
        print(format_debug_run(context, args.run_id))
    else:
        if args.limit < 1:
            raise AppError("limit must be a positive integer")
        print(format_debug_session(context, args.session_id, limit=args.limit))
    return 0


def _handle_init_pi(args: argparse.Namespace) -> int:
    result = init_pi(force=bool(args.force), copy=bool(args.copy))
    _print_init_files(result.files)
    print(f"verify: {result.verification_command}")
    return 0


def _handle_init_hermes(args: argparse.Namespace) -> int:
    result = init_hermes(profile=args.profile, force=bool(args.force), copy=bool(args.copy))
    _print_init_files(result.files)
    print(f"installed: {' '.join(result.command)}")
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    print(f"verify: {result.verification_command}")
    return 0


def _handle_init_opencode(args: argparse.Namespace) -> int:
    result = init_opencode(force=bool(args.force), copy=bool(args.copy))
    _print_init_files(result.files)
    print(f"verify: {result.verification_command}")
    return 0


def _handle_init_codex(args: argparse.Namespace) -> int:
    result = init_codex(
        force=bool(args.force),
        copy=bool(args.copy),
    )
    _print_init_files(result.files)
    _print_init_files([result.marketplace])
    print(f"installed: {' '.join(result.command)}")
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    return 0


def _handle_init_all(args: argparse.Namespace) -> int:
    result = init_all(
        force=bool(args.force),
        copy=bool(args.copy),
        catalog_path=args.agent_catalog,
    )
    if result.pi is not None:
        print("[pi]")
        _print_init_files(result.pi.files)
        print(f"verify: {result.pi.verification_command}")
    for hermes_result in result.hermes:
        print("[hermes]")
        _print_init_files(hermes_result.files)
        print(f"installed: {' '.join(hermes_result.command)}")
        if hermes_result.stdout:
            print(hermes_result.stdout)
        if hermes_result.stderr:
            print(hermes_result.stderr)
        print(f"verify: {hermes_result.verification_command}")
    if result.opencode is not None:
        print("[opencode]")
        _print_init_files(result.opencode.files)
        print(f"verify: {result.opencode.verification_command}")
    return 0


def _print_init_files(files: Sequence[InitFileResult]) -> None:
    for file_result in files:
        print(f"{file_result.action}:{file_result.mode}: {file_result.target}")


def _handle_dispatch_command(args: argparse.Namespace) -> int:
    payload = dispatch_command_payload(
        args.session_id,
        args.goal,
        role=args.role,
        timeout_seconds=args.timeout,
        task_label=args.task_label,
    )
    print(json.dumps(payload.to_payload()))
    return 0


def _handle_dispatch_ack(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps(dispatch_ack_payload(args.run_id, role=args.role)))
    else:
        print(format_dispatch_ack(args.run_id, role=args.role))
    return 0


def _handle_command_echo(args: argparse.Namespace) -> int:
    print(format_command_echo(args.raw_command))
    return 0


def _handle_tool_info(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    session_id = args.session_id
    info = tool_info_payload(context, session_id).to_payload()
    print(
        json.dumps(
            {
                "description": info["description"],
                "promptSnippet": info["prompt_snippet"],
                "promptGuidelines": info["prompt_guidelines"],
                "goalDescription": info["goal_description"],
                "roleDescription": info["role_description"],
                "taskLabelDescription": info["task_label_description"],
                "statusDescription": info["status_description"],
                "statusActionDescription": info["status_action_description"],
                "statusLimitDescription": info["status_limit_description"],
                "statusRunIdDescription": info["status_run_id_description"],
                "statusRoleDescription": info["status_role_description"],
                "statusSettingDescription": info["status_setting_description"],
                "statusValueDescription": info["status_value_description"],
                "dispatchTimeoutError": info["dispatch_timeout_error"],
                "budgetTriggerLabel": info["budget_trigger_label"],
                "softTimeoutBlockReason": info["soft_timeout_block_reason"],
                "toolsEnabledByDefault": info["tools_enabled_by_default"],
                "mainSessionMode": info["main_session_mode"],
            }
        )
    )
    return 0


def _handle_role_metadata(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    print(json.dumps(role_metadata(context)))
    return 0


def _handle_orchestrator_skill(args: argparse.Namespace) -> int:
    del args
    print(render_orchestrator_skill_message())
    return 0


def _handle_progress_message(args: argparse.Namespace) -> int:
    if args.json:
        print(
            json.dumps(
                progress_notification_payload(
                    completed_count=args.completed,
                    total_count=args.total,
                    run_id=args.run_id,
                    status=args.status,
                    role=args.role,
                )
            )
        )
    else:
        print(
            format_progress_notification(
                completed_count=args.completed,
                total_count=args.total,
                run_id=args.run_id,
                status=args.status,
                role=args.role,
            )
        )
    return 0


def _handle_run_supervisor(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    run_supervisor_guarded(context, run_id=args.run_id, request_file=args.request_file)
    return 0


def _handle_pending_report(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    report = consume_pending_session_report(context, args.session_id)
    if report:
        print(report)
    return 0


def _handle_await_session_report(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    if args.json:
        report = await_session_report_payload(
            context,
            args.session_id,
            run_id=args.run_id,
            timeout_seconds=args.timeout,
        )
        if report:
            print(json.dumps(session_report_payload(report)))
        return 0

    report_text = await_session_report(
        context,
        args.session_id,
        run_id=args.run_id,
        timeout_seconds=args.timeout,
    )
    if report_text:
        print(report_text)
    return 0


def _handle_mark_session_report_delivered(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    mark_session_report_delivered(context, args.session_id, list(args.run_id))
    return 0


def _handle_release_session_report(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    release_session_report(context, args.session_id, list(args.run_id))
    return 0


def _handle_await_run(args: argparse.Namespace) -> int:
    context = load_context(config_path=args.config, catalog_path=args.agent_catalog)
    record, active_remaining, details = await_run_terminal_status(
        context,
        args.session_id,
        run_id=args.run_id,
        timeout_seconds=args.timeout,
    )
    if args.json:
        print(
            json.dumps(
                await_run_payload(
                    record,
                    active_remaining=active_remaining,
                    details=details,
                    prompts=context.config.prompts,
                )
            )
        )
        return 0
    print(f"run_id: {record.run_id}")
    print(f"status: {record.status}")
    print(f"role: {record.role}")
    print(f"harness: {record.harness}")
    if record.result_summary:
        print(f"result: {record.result_summary}")
    if record.error_text:
        print(f"error: {record.error_text}")
    if record.blocker_text:
        print(f"blocker: {record.blocker_text}")
    if record.status == "incomplete":
        print(f"next: {context.config.prompts.return_hint_incomplete}")
    print(f"active_runs_remaining: {active_remaining}")
    print(f"descendants_terminal: {'yes' if details.descendants_terminal else 'no'}")
    print(f"session_report_available: {'yes' if details.session_report_available else 'no'}")
    print(f"session_report_delivered: {'yes' if details.session_report_delivered else 'no'}")
    return 0
