"""Application context and loading helpers for Orchestra."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orchestra.config import (
    AgentCatalog,
    AppConfig,
    load_agent_catalog,
    load_app_config,
    resolve_agent_catalog_path,
    resolve_config_path,
    resolve_prompts_path,
)
from orchestra.harnesses import (
    HarnessRegistry,
    register_builtin_harnesses,
    register_catalog_harnesses,
)
from orchestra.jobs import JobQueue, Limits, PolicyError
from orchestra.state import StateStore

CONTRACT_VERSION = 1


class AppError(ValueError):
    """Raised for user-facing application errors."""


@dataclass(frozen=True)
class OrchestraPaths:
    config_path: Path
    catalog_path: Path


@dataclass(frozen=True)
class AppContext:
    config: AppConfig
    catalog: AgentCatalog
    store: StateStore
    registry: HarnessRegistry
    paths: OrchestraPaths
    jobs: JobQueue


__all__ = [
    "AppContext",
    "AppError",
    "CONTRACT_VERSION",
    "OrchestraPaths",
    "create_default_registry",
    "load_context",
    "queue_resource_limits",
]


def create_default_registry() -> HarnessRegistry:
    return register_builtin_harnesses(HarnessRegistry())


def _catalog_harness_names(catalog: AgentCatalog) -> set[str]:
    names = {config.harness for config in catalog.harness_configs.values() if config.harness}
    names.update(role.harness for role in catalog.roles.values() if role.harness)
    return names


def queue_resource_limits(catalog: AgentCatalog) -> dict[str, int]:
    """Map configured model limits to queue resource keys.

    Roles may name a model with or without its provider prefix, so both spellings
    share one configured budget.
    """
    limits: dict[str, int] = {}
    for model, limit in catalog.model_limits.items():
        limits[model] = limit.concurrency
        if "/" in model:
            limits.setdefault(model.rsplit("/", 1)[1], limit.concurrency)
    return limits


def load_context(
    *,
    config_path: str | Path | None = None,
    catalog_path: str | Path | None = None,
    registry: HarnessRegistry | None = None,
) -> AppContext:
    config_file = resolve_config_path(config_path)
    prompts_file = resolve_prompts_path(config_path)
    catalog_file = (
        Path(catalog_path)
        if catalog_path is not None
        else resolve_agent_catalog_path(config_path)
    )
    config = load_app_config(config_file, prompts_path=prompts_file)
    catalog = load_agent_catalog(catalog_file)
    resolved_registry = registry or create_default_registry()
    register_catalog_harnesses(resolved_registry, _catalog_harness_names(catalog))
    store = StateStore(config.state_dir / "orchestra.db")
    store.initialize()
    jobs = JobQueue(config.state_dir / "orchestra.db")
    if not jobs.schema_initialized():
        active = store.list_active_runs()
        if active:
            raise AppError(
                f"{len(active)} run(s) are already active in {config.state_dir / 'orchestra.db'} "
                "but the durable job queue has not been created yet. Orchestra does not adopt "
                "runs started by an older version; let them finish or stop them, then run "
                "'orchestra doctor' before dispatching again."
            )
    limits = Limits(
        global_limit=config.concurrency.global_limit,
        per_owner_limit=config.concurrency.per_session_limit,
        resource_limits=queue_resource_limits(catalog),
    )
    try:
        jobs.initialize(limits)
    except PolicyError:
        # config.yaml owns concurrency, so a changed setting converges the queue
        # policy instead of failing the command. Competing writers still lose the
        # optimistic revision check inside configure_limits.
        jobs.configure_limits(limits, expected_revision=jobs.get_limits().revision)
    return AppContext(
        config=config,
        catalog=catalog,
        store=store,
        registry=resolved_registry,
        paths=OrchestraPaths(config_path=config_file, catalog_path=catalog_file),
        jobs=jobs,
    )
