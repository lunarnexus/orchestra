"""Reserved nested-dispatch marker — the core-owned no-nesting policy.

An Orchestra subagent is launched with ``ORCHESTRA_DISPATCH_BUDGET=1`` so it can
never dispatch a further subagent. This is a single reserved marker, not a
configurable depth or budget: an absent, empty, or nonpositive integer permits
parent dispatch; positive or malformed values disable dispatch. The policy lives here
so the harness, the core submit entry point, and the thin host adapters all read
the same rule instead of re-implementing it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

# The reserved environment marker shared with the host adapters. A launched
# child always carries ``CHILD_DISPATCH_MARKER``; an unmarked parent leaves it
# unset (or it parses to ``PARENT_DISPATCH_VALUE``).
ORCHESTRA_DISPATCH_BUDGET_ENV = "ORCHESTRA_DISPATCH_BUDGET"
CHILD_DISPATCH_MARKER = "1"
PARENT_DISPATCH_VALUE = "0"


def orchestra_can_dispatch(env: Mapping[str, str] | None = None) -> bool:
    """True only for an unmarked parent; a marked or malformed child is False.

    Absent/empty means an unmarked parent. A reserved marker or any positive
    value means a marked child. A value that does not parse as an integer is
    treated fail-closed (no dispatch) so a tampered marker cannot reopen
    dispatching in a subagent.
    """
    raw = (env if env is not None else os.environ).get(ORCHESTRA_DISPATCH_BUDGET_ENV)
    if raw is None or not raw.strip():
        return True
    try:
        value = int(raw.strip())
    except ValueError:
        return False
    return value <= 0


def mark_child_dispatch_env(
    base: Mapping[str, str], role_env: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Return a child environment carrying the reserved nested-dispatch marker.

    The role environment is applied first and the reserved marker last, so a
    role's own ``env`` can never clear or raise the marker. The caller's
    environment is never mutated: the result is a fresh mapping.
    """
    child = dict(base)
    child.update(role_env or {})
    child[ORCHESTRA_DISPATCH_BUDGET_ENV] = CHILD_DISPATCH_MARKER
    return child
