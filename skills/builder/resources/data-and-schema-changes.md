# Data and Schema Changes

Before editing, identify existing data, readers and writers, compatibility window, and failure recovery.

- Prefer additive, backward-compatible transitions.
- Confirm approved upgrade, rollback, and partial-failure behavior; return a blocker if any required behavior is undecided.
- Keep migrations deterministic, restartable, and safe for the expected data volume.
- Preserve data unless deletion is explicitly approved.
- Coordinate schema, validation, serialization, and callers.
- Test old-to-new migration, new reads/writes, invalid data, and rollback where supported.
- Return deployment ordering and residual compatibility risk.
