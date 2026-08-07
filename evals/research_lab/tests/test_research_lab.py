from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.research_lab.lab import (
    DIMENSIONS,
    SCENARIOS,
    collect_trace,
    create_case,
    evaluate_case,
    report_run,
)


def test_scenario_catalog_covers_complexity_and_live_cases() -> None:
    levels = {scenario.level for scenario in SCENARIOS.values()}
    assert levels == {"lookup", "focused", "planning", "adaptive"}
    assert sum(scenario.live for scenario in SCENARIOS.values()) >= 3
    assert sum(not scenario.live for scenario in SCENARIOS.values()) >= 8


def test_create_case_references_indexed_fixture_and_creates_scorecard(tmp_path: Path) -> None:
    case_dir = create_case("call-path", tmp_path, configuration="micro-slices", trial=2)

    assert not (case_dir / "workspace").exists()
    assert (case_dir / "task.md").read_text().strip()
    manifest = json.loads((case_dir / "manifest.json").read_text())
    source_scope = Path(manifest["source_scope"])
    assert source_scope == Path(__file__).parents[1] / "fixtures" / "call-path"
    assert (source_scope / "service.py").exists()
    assert manifest["configuration"] == "micro-slices"
    assert manifest["trial"] == 2
    scorecard = json.loads((case_dir / "scorecard.json").read_text())
    assert set(scorecard["ratings"]) == set(DIMENSIONS)
    assert all(value is None for value in scorecard["ratings"].values())


def test_create_case_rejects_existing_case(tmp_path: Path) -> None:
    create_case("symbol-lookup", tmp_path, configuration="baseline", trial=1)
    with pytest.raises(FileExistsError):
        create_case("symbol-lookup", tmp_path, configuration="baseline", trial=1)


def test_evaluate_case_combines_human_ratings_and_observations(tmp_path: Path) -> None:
    case_dir = create_case("symbol-lookup", tmp_path, configuration="baseline", trial=1)
    (case_dir / "result.txt").write_text(
        "Answer: parse_limit returns the default for None. Evidence: config.py:1-4\n"
    )
    scorecard = json.loads((case_dir / "scorecard.json").read_text())
    scorecard["ratings"] = {dimension: 4 for dimension in DIMENSIONS}
    scorecard["would_use"] = True
    (case_dir / "scorecard.json").write_text(json.dumps(scorecard))

    evaluation = evaluate_case(case_dir)

    assert evaluation["mean_rating"] == 4.0
    assert evaluation["would_use"] is True
    assert evaluation["observations"]["result_present"] is True
    assert evaluation["observations"]["source_reference_count"] >= 1


def test_evaluate_case_rejects_invalid_ratings(tmp_path: Path) -> None:
    case_dir = create_case("symbol-lookup", tmp_path, configuration="baseline", trial=1)
    scorecard = json.loads((case_dir / "scorecard.json").read_text())
    scorecard["ratings"][DIMENSIONS[0]] = 6
    (case_dir / "scorecard.json").write_text(json.dumps(scorecard))

    with pytest.raises(ValueError, match="1 through 5"):
        evaluate_case(case_dir)


def test_collect_trace_copies_available_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_dir = create_case("symbol-lookup", tmp_path / "runs", configuration="baseline", trial=1)
    state_dir = tmp_path / "state"
    log_dir = tmp_path / "logs"
    (state_dir / "return-artifacts").mkdir(parents=True)
    log_dir.mkdir()
    (state_dir / "return-artifacts" / "abc.md").write_text("full result")
    (log_dir / "abc.jsonl").write_text('{"event":"run.created"}\n')
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(tmp_path / "no-sessions"))

    copied = collect_trace("abc", case_dir, state_dir, log_dir)

    assert sorted(copied) == ["orchestra.jsonl", "result-artifact.md"]


def test_report_groups_results_by_configuration(tmp_path: Path) -> None:
    for configuration, rating in [("direct", 3), ("micro", 5)]:
        case_dir = create_case(
            "symbol-lookup", tmp_path, configuration=configuration, trial=1
        )
        (case_dir / "result.txt").write_text("Answer with config.py:1 evidence")
        scorecard = json.loads((case_dir / "scorecard.json").read_text())
        scorecard["ratings"] = {dimension: rating for dimension in DIMENSIONS}
        scorecard["would_use"] = rating >= 4
        (case_dir / "scorecard.json").write_text(json.dumps(scorecard))
        (case_dir / "evaluation.json").write_text(json.dumps(evaluate_case(case_dir)))

    report = report_run(tmp_path)

    assert report["configurations"]["direct"]["mean_rating"] == 3.0
    assert report["configurations"]["micro"]["mean_rating"] == 5.0
