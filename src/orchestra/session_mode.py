"""Main-session mode helpers for Orchestra."""

from __future__ import annotations

from typing import TYPE_CHECKING

from orchestra.context import CONTRACT_VERSION, AppContext, AppError
from orchestra.state import (
    MAIN_SESSION_MODE_OFF,
    MAIN_SESSION_MODE_ON,
    MainSessionState,
)

if TYPE_CHECKING:
    pass

__all__ = [
    "default_main_session_mode",
    "get_main_session_state",
    "main_session_state_payload",
    "resolve_main_session_mode",
    "set_main_session_mode",
]


def _require_session_id(session_id: str) -> None:
    if not session_id.strip():
        raise AppError("session_id is required")


def set_main_session_mode(
    context: AppContext,
    session_id: str,
    mode: str,
) -> MainSessionState:
    return context.store.set_main_session_mode(session_id, mode)


def get_main_session_state(
    context: AppContext,
    session_id: str,
) -> MainSessionState | None:
    return context.store.get_main_session_state(session_id)


def default_main_session_mode(context: AppContext) -> str:
    return (
        MAIN_SESSION_MODE_ON
        if context.config.tools_enabled_by_default
        else MAIN_SESSION_MODE_OFF
    )


def resolve_main_session_mode(context: AppContext, session_id: str) -> str:
    state = get_main_session_state(context, session_id)
    if state is not None:
        return state.main_session_mode
    return default_main_session_mode(context)


def main_session_state_payload(
    context: AppContext,
    session_id: str,
) -> dict[str, object]:
    _require_session_id(session_id)
    state = get_main_session_state(context, session_id)
    return {
        "contract_version": CONTRACT_VERSION,
        "kind": "main_session_state",
        "ok": True,
        "session_id": session_id,
        "main_session_mode": resolve_main_session_mode(context, session_id),
        "explicit_main_session_mode": None if state is None else state.main_session_mode,
        "updated_at": None if state is None else state.updated_at,
    }
