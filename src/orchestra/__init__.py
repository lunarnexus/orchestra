"""Orchestra package."""

from __future__ import annotations

from importlib import import_module

__all__ = ["__version__"]

try:
    __version__ = str(import_module("orchestra._version").__version__)
except (ImportError, AttributeError):
    __version__ = "0+unknown"
