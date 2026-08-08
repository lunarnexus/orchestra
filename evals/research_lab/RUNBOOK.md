# Research Lab Runbook

## Experiment setup

Choose the configurations being compared before running cases. Keep the model and harness constant when comparing methodology. Keep the methodology constant when comparing models.

Run each selected scenario at least three times per configuration. Randomize configuration order where practical to reduce operator and time-order bias.

```bash
ROOT="$(pwd)/evals/research_lab/runs/$(date -u +%Y%m%dT%H%M%SZ)-experiment"
mkdir -p "$ROOT"
python3 -m evals.research_lab.cli list
```

Record configuration details in `$ROOT/experiment.md`:

- hypothesis;
- skill commit or file hash;
- methodology prompt;
- role catalog and enabled roles;
- harness and model;
- timeout and concurrency settings;
- date and current-data cutoff for live cases.

## Prepare a case

```bash
CASE_DIR=$(python3 -m evals.research_lab.cli prepare call-path \
  --run-root "$ROOT" --configuration micro-slices --trial 1)
cat "$CASE_DIR/task.md"
```

For fixture cases, read `source_scope` from `manifest.json` and provide this approved context:

```text
Workspace: <absolute source_scope>. Research only inside this fixture unless the task explicitly requests external documentation.
```

Fixture sources live under `evals/research_lab/fixtures/`, outside ignored run artifacts, so the root Codegraph watcher indexes them.

For live cases:

```text
This is a live research evaluation. Use current authoritative sources. Record retrieval dates and disclose inaccessible evidence.
```

Boundaries:

```text
Stay read-only. Do not inspect sibling scenarios, manifest.json, scorecard.json, or evaluator files. Do not modify the fixture. Return the smallest complete evidence-backed answer.
```

Do not show `manifest.json` or scorecards to the research system.

## Run end to end

Dispatch through the methodology under test using the normal host and Orchestra tools. This may mean direct orchestrator work, planner dispatch, researcher dispatch, or nested workers depending on the configuration.

Save the exact final answer:

```bash
cat > "$CASE_DIR/result.txt" <<'EOF'
<exact final answer>
EOF
```

For a final Orchestra worker, collect its trace:

```bash
python3 -m evals.research_lab.cli collect-trace "$CASE_DIR" \
  --run-id RUN_ID --state-dir "$(pwd)/state" --log-dir "$(pwd)/logs"
```

If several workers contributed, record all run IDs in `$CASE_DIR/run-ids.txt`. Preserve additional return artifacts under `$CASE_DIR/traces/` without rewriting them.

## Score the result

Open `manifest.json`, `result.txt`, and available traces only after the run ends. Fill `scorecard.json`.

Rating anchors:

- `1` — materially failed;
- `2` — major problems;
- `3` — usable with meaningful correction;
- `4` — strong and trustworthy with minor limitations;
- `5` — excellent for this scenario and cost.

Interpret dimensions independently. A correct answer can still score poorly on evidence or efficiency. A concise lookup that dispatches several agents should score poorly on escalation judgment and efficiency even if correct.

Then evaluate:

```bash
python3 -m evals.research_lab.cli evaluate "$CASE_DIR"
```

## Compare configurations

```bash
python3 -m evals.research_lab.cli report "$ROOT"
```

Review:

- performance by scenario level;
- `would_use` and `overkill` rates;
- mean duration;
- repeated failure themes;
- where added complexity materially improved evidence or correctness;
- where simple methods achieved equivalent quality.

Prefer paired comparisons on the same scenario and trial number. Keep qualitative notes: the purpose is to discover governing behaviors, not merely optimize a score.

## Suggested first experiment

Run these six scenarios across `direct`, `current`, `micro-slices`, and `adaptive`, three trials each:

- `symbol-lookup`
- `call-path`
- `code-test-conflict`
- `planning-knowledge-gaps`
- `broad-decomposition`
- `live-official-api`

This 72-run matrix is large. Start with one trial (24 runs) to remove broken configurations, then run two additional trials only for viable configurations.
