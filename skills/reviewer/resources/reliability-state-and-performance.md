# Reliability, State, and Performance

Map state ownership, lifecycle, invariants, legal transitions, and competing operations.

Check relevant behavior:

- duplicate delivery, retry, and idempotency
- cancellation, timeout, shutdown, and resource cleanup
- transaction and partial-completion behavior
- lock scope and external I/O while locked
- stale cache or duplicated source-of-truth risk
- error propagation and silent failure
- deterministic coverage of material races, ordering, recovery, or retries

A concurrency concern needs a plausible interleaving and affected invariant. A reliability concern needs a realistic failure path. Do not report generic possibilities.

For performance claims, require an approved user-visible metric, representative workload, repeatable baseline, and evidence that the changed code addresses the measured bottleneck. Compare like-for-like measurements and account for variance and resource tradeoffs.

Do not recommend caching, concurrency, batching, or asynchronous complexity without measured need at the project's current scale. Do not trade correctness, clarity, or maintainability for micro-performance.
