"""
Root conftest.py — test parallelization via pytest-xdist.

Auto-groups tests by directory so same-directory tests run serially on one
worker (preserving fixture/state isolation) while different directories
run in parallel across workers.

To run sequentially: pytest -n0
To run with specific worker count: pytest -n4
"""
from __future__ import annotations

from pathlib import Path

import pytest


def pytest_collection_modifyitems(config, items):
    """Auto-assign xdist_group marks by test directory.

    Tests in the same directory run serially on one worker (deterministic order).
    Different directories run in parallel across workers.

    Example groups: "unit/eval", "unit/web", "integration", "root".
    """
    tests_root = Path(config.rootpath) / "tests"
    for item in items:
        if item.get_closest_marker("xdist_group"):
            continue  # Respect explicit marks
        try:
            rel = item.path.relative_to(tests_root)
            group = "/".join(rel.parts[:-1]) or "root"
        except ValueError:
            group = "root"
        item.add_marker(pytest.mark.xdist_group(group))


def pytest_report_header(config):
    """Print a notice when tests run in parallel via pytest-xdist."""
    worker_count = getattr(config, "workerinput", None)
    if worker_count is not None:
        return []  # Worker process — don't print
    num_workers = getattr(config.option, "numprocesses", None)
    if num_workers and num_workers != 0:
        return [
            "NOTE: Running with pytest-xdist (parallel). Use '-n0' for sequential execution.",
        ]
    return []


# =============================================================================
# Property-based testing with Hypothesis
# =============================================================================
#
# Enabled in Wave M-4 for envelope-breakpoint validation (the first place in
# the codebase with a clear domain + named invariants that benefits from
# generative testing). See `hallucinote_mcp/tests/unit/test_envelope_properties.py`.
#
# Docs: https://hypothesis.readthedocs.io/

from hypothesis import settings, HealthCheck

# CI profile: more examples, stricter deadlines
settings.register_profile(
    "ci",
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow],
)

# Dev profile: fast feedback during development
settings.register_profile(
    "dev",
    max_examples=20,
)

# Default to dev; CI sets HYPOTHESIS_PROFILE=ci
settings.load_profile("dev")
