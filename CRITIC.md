# Critic

## Resolved findings

- [x] `stop` now terminates the owned worker process / process group instead of only changing DB state.
- [x] worker timeout now terminates the owned worker and records a failed timeout state.
- [x] global and per-session concurrency limits are enforced atomically in SQLite run reservation.
- [x] consolidated session reporting now groups unreported terminal runs by session and includes log / artifact refs.
- [x] CLI `--session-id` is documented as local/manual mode only.
- [x] first trusted host adapter exists as a Pi extension using runtime session identity normalization.

## Remaining notes

- Pi print-mode host checks verify the adapter command path, but persistent-session auto-return behavior is still most meaningful in an actual long-lived Pi session.
- Later adapters such as Hermes, OpenCode, MCP wrappers, and ACP remain future work.
