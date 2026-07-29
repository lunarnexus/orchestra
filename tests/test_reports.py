from __future__ import annotations

from pathlib import Path

from orchestra.app import consume_pending_session_report, load_context
from orchestra.state import STATUS_DONE, StateStore
from tests.helpers import extract_run_id, wait_for_condition
from tests.types import RuntimeFilesFactory


def test_consolidated_report_includes_all_unreported_terminal_runs(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker ok"],
    )

    from tests.helpers import run_cli

    first = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:report",
        "--goal",
        "first goal",
    )
    second = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:report",
        "--goal",
        "second goal",
    )

    store = StateStore(db_path)
    first_id = extract_run_id(first.stdout)
    second_id = extract_run_id(second.stdout)
    assert wait_for_condition(lambda: store.get_run(first_id).status == STATUS_DONE, timeout=5)
    assert wait_for_condition(lambda: store.get_run(second_id).status == STATUS_DONE, timeout=5)

    context = load_context(config_path=config_path, catalog_path=catalog_path)
    report = consume_pending_session_report(context, "manual:report")
    assert report is not None
    assert report.startswith("[orchestra: 2 workers returned]\n\n")
    assert f"[orchestra: Worker {first_id} success]" in report
    assert f"[orchestra: Worker {second_id} success]" in report
    assert "Request: first goal" in report
    assert "Request: second goal" in report
    assert "Result: worker ok" in report
    assert "Log:" in report

    second_report = consume_pending_session_report(context, "manual:report")
    assert second_report is None
