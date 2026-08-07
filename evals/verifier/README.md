# Verifier Evals

Behavioral evaluations for Orchestra's `verifier` role. Cases run through the normal Orchestra dispatch path and grade the verdict, evidence handoff, read-only policy, and available process trace.

## Design

- Each case is a fresh git repository containing a baseline and visible candidate diff.
- Hidden configuration records the expected verdict and initial workspace state outside the worker workspace.
- The worker must return `pass`, `fail`, or `blocked` without changing project source.
- Outcome, process, scope, policy, and handoff are reported separately.
- Process remains unknown when a supported trace is unavailable.

## Coverage

- complete acceptance pass
- incorrect behavior
- missing regression protection
- ambiguous acceptance target
- unavailable mandatory verifier
- distrust of builder success claims
- semantic change-impact analysis
- pre-existing versus introduced failures
- scope creep detection

## Commands

```bash
python3 -m evals.verifier.cli list
python3 -m evals.verifier.cli prepare acceptance-pass --run-root /tmp/verifier-trial
python3 -m evals.verifier.cli collect-trace /tmp/verifier-trial/acceptance-pass \
  --run-id RUN_ID --state-dir state --log-dir logs
python3 -m evals.verifier.cli grade /tmp/verifier-trial/acceptance-pass
python3 -m evals.verifier.cli report /tmp/verifier-trial
```

Read [`RUNBOOK.md`](RUNBOOK.md) before running trials. Run each case at least three times per model and skill revision.
