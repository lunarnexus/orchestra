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
)
from orchestra.harnesses import (
    HarnessRegistry,
    register_builtin_harnesses,
    register_catalog_harnesses,
)
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


__all__ = [
    "AppContext",
    "AppError",
    "CONTRACT_VERSION",
    "OrchestraPaths",
    "create_default_registry",
    "load_context",
]


def create_default_registry() -> HarnessRegistry:
    return register_builtin_harnesses(HarnessRegistry())


def _catalog_harness_names(catalog: AgentCatalog) -> set[str]:
    names = {config.harness for config in catalog.harness_configs.values() if config.harness}
    names.update(role.harness for role in catalog.roles.values() if role.harness)
    return names


def load_context(
    *,
    config_path: str | Path | None = None,
    catalog_path: str | Path | None = None,
    registry: HarnessRegistry | None = None,
) -> AppContext:
    config_file = resolve_config_path(config_path)
    catalog_file = resolve_agent_catalog_path(catalog_path)
    config = load_app_config(config_file)
    catalog = load_agent_catalog(catalog_file)
    resolved_registry = registry or create_default_registry()
    register_catalog_harnesses(resolved_registry, _catalog_harness_names(catalog))
    store = StateStore(config.state_dir / "orchestra.db")
    store.initialize()
    return AppContext(
        config=config,
        catalog=catalog,
        store=store,
        registry=resolved_registry,
        paths=OrchestraPaths(config_path=config_file, catalog_path=catalog_file),
    )
