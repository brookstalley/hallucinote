"""Tests for the hallucinote_mcp package.

Each test that registers actions in the shared schema must clean up after
itself or the registry leaks between tests. The ``isolated_registry`` fixture
saves and restores the registry around each test that opts in.
"""
from __future__ import annotations

import pytest

from hallucinote_mcp import schema


@pytest.fixture()
def isolated_registry():
    """Save the registry state, yield, restore. Use when a test calls
    ``schema.register(...)`` so leaks don't cross test boundaries.
    """
    saved = dict(schema._REGISTRY)
    try:
        schema._REGISTRY.clear()
        yield schema
    finally:
        schema._REGISTRY.clear()
        schema._REGISTRY.update(saved)
