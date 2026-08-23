"""Harness plugin registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from orchestra.harnesses.base import (
    Harness,
    HarnessLoadError,
    HarnessRegistry,
    WorkerProcess,
    WorkerRequest,
    WorkerResult,
)


def register_builtin_harnesses(registry: HarnessRegistry) -> HarnessRegistry:
    registry.register_loader("pi", _load_pi_harness)
    registry.register_loader("hermes", _load_hermes_harness)
    registry.register_loader("opencode", _load_opencode_harness)
    return registry


def register_catalog_harnesses(registry: HarnessRegistry, names: set[str]) -> HarnessRegistry:
    for name in names:
        if registry.contains(name):
            continue
        registry.register_loader(name, _catalog_subprocess_loader(name))
    return registry


def _catalog_subprocess_loader(name: str) -> Callable[[], Harness]:
    def loader() -> Harness:
        return _load_subprocess_harness(name)

    return loader


def _load_pi_harness() -> Harness:
    from orchestra.harnesses.pi import PiHarness

    return PiHarness()


def _load_hermes_harness() -> Harness:
    from orchestra.harnesses.hermes import HermesHarness

    return HermesHarness()


def _load_opencode_harness() -> Harness:
    from orchestra.harnesses.opencode import OpenCodeHarness

    return OpenCodeHarness()


def _load_subprocess_harness(name: str) -> Harness:
    from orchestra.harnesses.subprocess import SubprocessHarness

    return SubprocessHarness(name=name)


def __getattr__(name: str) -> object:
    if name == "PiHarness":
        from orchestra.harnesses.pi import PiHarness

        return PiHarness
    if name == "HermesHarness":
        from orchestra.harnesses.hermes import HermesHarness

        return HermesHarness
    if name == "OpenCodeHarness":
        from orchestra.harnesses.opencode import OpenCodeHarness

        return OpenCodeHarness
    raise AttributeError(name)


if TYPE_CHECKING:
    from orchestra.harnesses.hermes import HermesHarness
    from orchestra.harnesses.opencode import OpenCodeHarness
    from orchestra.harnesses.pi import PiHarness


__all__ = [
    "Harness",
    "HarnessLoadError",
    "HarnessRegistry",
    "HermesHarness",
    "OpenCodeHarness",
    "PiHarness",
    "WorkerProcess",
    "WorkerRequest",
    "WorkerResult",
    "register_builtin_harnesses",
    "register_catalog_harnesses",
]
