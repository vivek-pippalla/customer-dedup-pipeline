"""Smoke tests for the project foundation."""

import importlib


def test_package_modules_import() -> None:
    """The initial package modules are importable."""
    for module_name in ("dedup", "dedup.cli", "dedup.config"):
        assert importlib.import_module(module_name)
