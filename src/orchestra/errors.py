"""Shared machine-readable error envelope for Orchestra transports.

One core-owned envelope (D-RETURN-018) is reused by CLI JSON failures and by
core-generated subagent error metadata in consolidated session reports.
"""

from __future__ import annotations

from orchestra.context import CONTRACT_VERSION

__all__ = ["error_envelope"]


def error_envelope(
    message: str,
    operation: str,
    run_id: str | None = None,
) -> dict[str, object]:
    """Build the shared error envelope for ``operation``.

    ``run_id`` is included only when it carries a value.
    """

    error: dict[str, object] = {"message": message, "operation": operation}
    if run_id:
        error["run_id"] = run_id
    return {
        "contract_version": CONTRACT_VERSION,
        "kind": "error",
        "ok": False,
        "error": error,
    }
