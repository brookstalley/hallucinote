"""Repo-root pytest configuration — container-friendly test selection.

Container / web sessions run on a CPU-only image with no Ableton. Two test
classes need special handling so the suite runs cleanly here:

- **Audio DSP** (``audio`` marker, auto-applied by path): the native stack
  (librosa / numba / scipy) intermittently segfaults mid-run on this image. We
  never develop the audio subsystem in a container, so it is **opt-out**: set
  ``HALLUCINOTE_SKIP_AUDIO=1`` (or ``-m "not audio"``) and the full non-audio
  suite runs. Local dev with the native stack runs everything by default.

- **Live Ableton** (``ableton`` marker, declared explicitly on a test): requires
  a running Live + remote script. There are none today — MCP-server tests use
  fakes, which is exactly how MCP features get built in-container. The marker is
  **opt-in** (default-skip): a future live-sequencer test tagged
  ``@pytest.mark.ableton`` auto-skips unless ``HALLUCINOTE_WITH_ABLETON=1``, so
  it never breaks a container/CI run by default.

Markers are registered in ``pyproject.toml`` ``[tool.pytest.ini_options]``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# `pythonpath` in pyproject front-inserts this checkout's source dirs into the
# PYTEST process — it does not reach a SUBPROCESS. Tests across the suite shell
# out to `sys.executable -m hallucinote...` (grep `sys.executable`), and those
# children resolve `hallucinote` through the editable-install `.pth`, which
# points at the PRIMARY checkout. From a git worktree that is a different tree:
# the CLI tests then exercise code the tree under test does not contain. It
# surfaced as six phantom `test_restamp_*` failures whose subject was correct
# here and simply absent from the primary checkout — a bare `pytest` was red
# while `PYTHONPATH=$PWD/src pytest` was green, and the red was about the wrong
# tree either way. Export the same dirs so a child tests what the parent
# imported. In the primary checkout these are the paths the `.pth` already
# targets, so it changes nothing there.
_REPO_ROOT = Path(__file__).resolve().parent
_SOURCE_DIRS = (_REPO_ROOT / "src", _REPO_ROOT / "hallucinote_mcp" / "src")


def _export_source_path_for_subprocesses() -> None:
    ours = [str(p) for p in _SOURCE_DIRS if p.is_dir()]
    existing = os.environ.get("PYTHONPATH", "")
    parts = [p for p in existing.split(os.pathsep) if p]
    # Front-insert, and don't duplicate on a re-import of this conftest.
    merged = ours + [p for p in parts if p not in ours]
    os.environ["PYTHONPATH"] = os.pathsep.join(merged)


_export_source_path_for_subprocesses()

# Test locations that load and exercise the native audio/DSP stack.
_AUDIO_PATH_FRAGMENTS = ("/tests/unit/audio/",)
_AUDIO_FILE_NAMES = ("test_handlers_analysis.py",)


def _is_audio_item(item: pytest.Item) -> bool:
    path = str(item.fspath).replace(os.sep, "/")
    if any(fragment in path for fragment in _AUDIO_PATH_FRAGMENTS):
        return True
    return any(path.endswith(name) for name in _AUDIO_FILE_NAMES)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    skip_audio = _env_truthy("HALLUCINOTE_SKIP_AUDIO")
    with_ableton = _env_truthy("HALLUCINOTE_WITH_ABLETON")

    audio_skip = pytest.mark.skip(
        reason="audio DSP tests skipped (HALLUCINOTE_SKIP_AUDIO set); "
        "native librosa/numba/scipy stack is unstable in containers"
    )
    ableton_skip = pytest.mark.skip(
        reason="requires a live Ableton/sequencer; "
        "set HALLUCINOTE_WITH_ABLETON=1 to run"
    )

    for item in items:
        if _is_audio_item(item):
            item.add_marker(pytest.mark.audio)
            if skip_audio:
                item.add_marker(audio_skip)
        # `ableton`-marked tests are opt-in: skipped unless explicitly enabled.
        if item.get_closest_marker("ableton") and not with_ableton:
            item.add_marker(ableton_skip)
