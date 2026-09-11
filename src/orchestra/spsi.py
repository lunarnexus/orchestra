"""System-prompt-skill-injection payload helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html import escape
from pathlib import Path

from orchestra.config import ORCHESTRATOR_ROLE_NAME, RoleConfig
from orchestra.context import CONTRACT_VERSION, AppContext
from orchestra.harnesses.common import SKILL_FILENAME, SKILL_LIBRARY_DIR
from orchestra.session_mode import resolve_main_session_mode
from orchestra.state import StateError

SPSI_NAME = "orchestra.spsi.role-skills"
WORKER_SESSION_PREFIX = "orchestra-worker-"


@dataclass(frozen=True)
class SpsiPayload:
    session_id: str
    enabled: bool
    name: str = SPSI_NAME
    role: str | None = None
    skills: tuple[str, ...] = ()
    revision: str | None = None
    content: str | None = None
    contract_version: int = CONTRACT_VERSION
    kind: str = "spsi_payload"
    ok: bool = True

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "contract_version": self.contract_version,
            "kind": self.kind,
            "ok": self.ok,
            "session_id": self.session_id,
            "enabled": self.enabled,
            "name": self.name,
        }
        if self.role is not None:
            payload["role"] = self.role
        if self.skills:
            payload["skills"] = list(self.skills)
        if self.revision is not None:
            payload["revision"] = self.revision
        if self.content is not None:
            payload["content"] = self.content
        return payload


def spsi_payload(context: AppContext, session_id: str) -> SpsiPayload:
    role_name, role, gate_session_id = _role_for_session(context, session_id)
    enabled = resolve_main_session_mode(context, gate_session_id) != "off"
    if not enabled or role is None or not role.skills:
        return SpsiPayload(session_id=session_id, enabled=False)

    skill_sections = _skill_sections(role.skills, _skill_roots(context))
    if not skill_sections:
        return SpsiPayload(session_id=session_id, enabled=False)

    revision_source = "\n\n".join(skill_sections)
    revision = "sha256:" + hashlib.sha256(revision_source.encode("utf-8")).hexdigest()
    skills_attr = ",".join(role.skills)
    content = (
        f'<orchestra_spsi name="{escape(SPSI_NAME, quote=True)}" '
        f'revision="{escape(revision, quote=True)}" '
        f'role="{escape(role_name, quote=True)}" '
        f'skills="{escape(skills_attr, quote=True)}">\n'
        f"{revision_source}\n"
        "</orchestra_spsi>"
    )
    return SpsiPayload(
        session_id=session_id,
        enabled=True,
        role=role_name,
        skills=role.skills,
        revision=revision,
        content=content,
    )


def _role_for_session(
    context: AppContext,
    session_id: str,
) -> tuple[str, RoleConfig | None, str]:
    run_id = _worker_run_id(session_id)
    if run_id is None:
        return (
            ORCHESTRATOR_ROLE_NAME,
            context.catalog.roles.get(ORCHESTRATOR_ROLE_NAME),
            session_id,
        )
    try:
        record = context.store.get_run(run_id)
    except StateError:
        return ("", None, session_id)
    return (record.role, context.catalog.roles.get(record.role), record.orchestrator_session_id)


def _worker_run_id(session_id: str) -> str | None:
    bare_session_id = session_id.split(":", 1)[1] if ":" in session_id else session_id
    if not bare_session_id.startswith(WORKER_SESSION_PREFIX):
        return None
    run_id = bare_session_id[len(WORKER_SESSION_PREFIX) :].strip()
    return run_id or None


def _skill_roots(context: AppContext) -> tuple[Path, ...]:
    roots = (
        Path.cwd() / SKILL_LIBRARY_DIR,
        context.paths.catalog_path.resolve().parent / SKILL_LIBRARY_DIR,
    )
    return tuple(dict.fromkeys(root.resolve() for root in roots))


def _skill_sections(skill_names: tuple[str, ...], skill_roots: tuple[Path, ...]) -> list[str]:
    sections: list[str] = []
    for skill_name in skill_names:
        skill_path = _find_project_skill(skill_name, skill_roots)
        if skill_path is not None:
            sections.append(
                f'<orchestra_spsi_skill name="{escape(skill_name, quote=True)}">\n'
                f"Skill directory: {skill_path.parent.resolve()}\n"
                "Resolve relative resource paths against this directory.\n\n"
                f"{skill_path.read_text(encoding='utf-8').strip()}\n"
                "</orchestra_spsi_skill>"
            )
    return sections


def _find_project_skill(skill_name: str, skill_roots: tuple[Path, ...]) -> Path | None:
    for skills_root in skill_roots:
        candidate = skills_root / skill_name / SKILL_FILENAME
        if candidate.is_file():
            return candidate
        if not skills_root.is_dir():
            continue
        for nested_candidate in skills_root.rglob(SKILL_FILENAME):
            if nested_candidate.parent.name == skill_name:
                return nested_candidate
    return None
