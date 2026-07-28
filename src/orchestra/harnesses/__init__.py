"""Harness plugin registry."""

from __future__ import annotations

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
    return registry


def _load_pi_harness() -> Harness:
    from orchestra.harnesses.pi import PiHarness

    return PiHarness()


def _load_hermes_harness() -> Harness:
    from orchestra.harnesses.hermes import HermesHarness

    return HermesHarness()


def __getattr__(name: str) -> object:
    if name == "PiHarness":
        from orchestra.harnesses.pi import PiHarness

        return PiHarness
    if name == "HermesHarness":
        from orchestra.harnesses.hermes import HermesHarness

        return HermesHarness
    raise AttributeError(name)


if TYPE_CHECKING:
    from orchestra.harnesses.hermes import HermesHarness
    from orchestra.harnesses.pi import PiHarness


__all__ = [
    "Harness",
    "HarnessLoadError",
    "HarnessRegistry",
    "HermesHarness",
    "PiHarness",
    "WorkerProcess",
    "WorkerRequest",
    "WorkerResult",
    "register_builtin_harnesses",
]
