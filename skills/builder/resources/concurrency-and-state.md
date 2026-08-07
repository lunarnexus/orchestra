# Concurrency and State

Map state ownership, lifecycle, and competing operations before editing.

- Confirm approved invariants and legal state transitions; return a blocker if the implementation depends on an unresolved decision.
- Make retries idempotent or explicitly detect duplicates.
- Use project synchronization and transaction patterns; do not invent ad hoc locking.
- Handle cancellation, timeout, cleanup, and partial completion.
- Avoid holding locks across external I/O.
- Test the material race, retry, ordering, or recovery path deterministically when possible.
- Document any concurrency behavior that cannot be exercised locally.
