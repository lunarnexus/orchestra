# Tests and verification

Use for behavior changes, bug fixes, risky paths, or acceptance-critical work.

Risk tiers:
- P0: data, security, production path, migration, external side effect; strongest verification and AppSec gate.
- P1: user-visible or core behavior; focused tests, verifier, and reviewer.
- P2: normal internal feature; focused tests and relevant checks.
- P3: docs/config/small cleanup; lightweight verification.

Plan behavior and bug slices TDD-first when practical:
1. failing test or exact repro;
2. minimal green implementation;
3. safe refactor after green;
4. focused verify command.

Add verifier gates after acceptance-relevant code exists, reviewer gates after coherent steps or phases, and AppSec gates for changed trust boundaries or sensitive assets.
