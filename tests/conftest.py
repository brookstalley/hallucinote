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

    Example groups: "tests/unit/sync", "hallucinote_mcp/tests/unit",
    "songs/falling-walking", "root".

    Roots considered (first match wins, in order):
      1. `tests/` — the main suite
      2. `songs/<slug>/tests/` — per-song test trees (key includes the slug
         so each song gets its own xdist group, preserving parallelism as
         the song count grows)
      3. `hallucinote_mcp/tests/` — the MCP server's test tree
    """
    repo_root = Path(config.rootpath)
    candidate_roots = [
        ("tests", repo_root / "tests"),
        ("hallucinote_mcp/tests", repo_root / "hallucinote_mcp" / "tests"),
    ]
    songs_dir = repo_root / "songs"
    if songs_dir.is_dir():
        for song_path in sorted(songs_dir.iterdir()):
            song_tests = song_path / "tests"
            if song_tests.is_dir():
                candidate_roots.append((f"songs/{song_path.name}", song_tests))

    for item in items:
        if item.get_closest_marker("xdist_group"):
            continue  # Respect explicit marks
        group = "root"
        for prefix, root in candidate_roots:
            try:
                rel = item.path.relative_to(root)
            except ValueError:
                continue
            sub = "/".join(rel.parts[:-1])
            group = f"{prefix}/{sub}" if sub else prefix
            break
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

# Both profiles disable the per-example wall-clock deadline (default 200ms):
# under pytest-xdist the workers contend for CPU and an example that takes
# 2ms idle can blow 200ms under load — observed as a flaky DeadlineExceeded
# on test_sorted_breakpoints_are_always_accepted (2026-06-10). The deadline
# is a perf tripwire, not a property contract; the invariants are unchanged.

# CI profile: more examples
settings.register_profile(
    "ci",
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# Dev profile: fast feedback during development
settings.register_profile(
    "dev",
    max_examples=20,
    deadline=None,
)

# Default to dev; CI sets HYPOTHESIS_PROFILE=ci
settings.load_profile("dev")
