"""Test helpers for downstream callers.

The shared schema registry is global state — every test that wants a clean
slate has to save it, clear it, do its work, restore it. ``isolated_actions``
captures that pattern as a single context manager so callers don't reinvent
the save/clear/sys.modules-pop/re-import dance.

Lives in the package (not in ``tests/``) so cross-package tests in the parent
repo can ``from hallucinote_mcp.testing import isolated_actions`` without
reaching across `tests/` boundaries.
"""
from __future__ import annotations

import contextlib
import sys
from typing import Iterator

from . import schema


@contextlib.contextmanager
def isolated_actions() -> Iterator[None]:
    """Yield a clean schema registry with actions freshly re-imported.

    Pattern:
      - Save the current registry contents.
      - Clear the registry.
      - Pop any cached ``hallucinote_mcp.actions.*`` modules so the next
        import re-executes the ``register(...)`` side effects.
      - Re-import the actions package (registers everything).
      - Register help actions for any tool without one.
      - Yield. On exit: restore the saved registry.
    """
    saved = dict(schema._REGISTRY)
    try:
        schema._REGISTRY.clear()
        for mod_name in list(sys.modules):
            if mod_name.startswith("hallucinote_mcp.actions"):
                sys.modules.pop(mod_name)
        import hallucinote_mcp.actions  # noqa: F401 — registration side-effect
        schema.register_help_actions()
        yield
    finally:
        schema._REGISTRY.clear()
        schema._REGISTRY.update(saved)


__all__ = ["isolated_actions"]
