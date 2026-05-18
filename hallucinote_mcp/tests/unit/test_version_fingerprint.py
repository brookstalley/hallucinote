"""Content-fingerprint version mechanism (Wave-2 W2-G / W2-5).

Mechanism: ``hallucinote_mcp.__version__`` is built at import time from
``BASE_VERSION + "+" + content_hash``, where content_hash covers the
files that define the wire shape. Source drift between the MCP server
side and the Remote Script side (the W2-5 root cause behind chunks
A/B/C/D's stale-handler debugging) now invalidates the fingerprint;
the version handshake then catches it.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

import hallucinote_mcp
from hallucinote_mcp import BASE_VERSION, __version__
from hallucinote_mcp.wire import check_version_compat


def test_version_has_base_plus_fingerprint():
    """The package __version__ is base + content fingerprint."""
    assert __version__.startswith(BASE_VERSION + "+"), (
        f"Expected version to start with '{BASE_VERSION}+', got {__version__!r}"
    )
    fingerprint = __version__.split("+", 1)[1]
    # 12 hex chars (first 12 of sha256).
    assert len(fingerprint) == 12
    int(fingerprint, 16)  # raises if not hex


def test_fingerprint_is_deterministic_within_a_process():
    """Re-computing should yield the same hash for the same source tree."""
    from hallucinote_mcp import _compute_content_fingerprint
    first = _compute_content_fingerprint()
    second = _compute_content_fingerprint()
    assert first == second


def test_fingerprint_changes_when_source_changes(tmp_path: Path):
    """Building a parallel package tree with a modified handler file
    yields a different fingerprint — the mechanism's load-bearing
    property for drift detection.
    """
    pkg_root = Path(hallucinote_mcp.__file__).parent

    # Copy the real package tree into tmp_path, then mutate one file.
    import shutil
    shutil.copytree(pkg_root, tmp_path / "hallucinote_mcp")
    target_file = tmp_path / "hallucinote_mcp" / "handlers" / "track.py"
    # Drop a uniqueness-only comment at the end — preserves runtime
    # behavior but the fingerprint should differ.
    target_file.write_text(target_file.read_text() + "\n# drift-detection-test\n")

    # Load the modified package into a fresh module namespace.
    spec = importlib.util.spec_from_file_location(
        "_drift_test", tmp_path / "hallucinote_mcp" / "__init__.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_drift_test"] = mod
    try:
        spec.loader.exec_module(mod)
        assert mod.__version__ != __version__, (
            "fingerprint should differ when a handler file changes; got "
            f"{mod.__version__!r} == {__version__!r}"
        )
    finally:
        sys.modules.pop("_drift_test", None)


def test_check_version_compat_detects_fingerprint_drift():
    """A request whose fingerprint differs from local must trigger the
    mismatch error path (not silent acceptance).
    """
    # Same base, different fingerprint.
    drifted = BASE_VERSION + "+abcdef012345"
    resp = check_version_compat(drifted, __version__)
    assert resp is not None
    assert resp.ok is False
    assert "version mismatch" in (resp.error or "").lower()
    # Both versions named in the error.
    assert drifted in (resp.error or "")
    assert __version__ in (resp.error or "")
    # Hint points at the install skill.
    assert "ableton-install-mcp" in (resp.hint or "")


def test_check_version_compat_passes_when_fingerprints_match():
    """Same fingerprint = no error."""
    resp = check_version_compat(__version__, __version__)
    assert resp is None


def test_compute_fingerprint_handles_missing_paths_gracefully(tmp_path: Path, monkeypatch):
    """A partial install (e.g., handlers/ missing) should still return a
    fingerprint — degraded but non-empty — so the handshake gets a
    comparable value rather than raising at import time.
    """
    pkg_root = Path(hallucinote_mcp.__file__).parent

    # Mimic the same hash discipline locally without changing the
    # production tree: a sibling that omits the handlers directory.
    import shutil
    shutil.copytree(pkg_root, tmp_path / "hallucinote_mcp")
    shutil.rmtree(tmp_path / "hallucinote_mcp" / "handlers")

    spec = importlib.util.spec_from_file_location(
        "_partial_test", tmp_path / "hallucinote_mcp" / "__init__.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_partial_test"] = mod
    try:
        spec.loader.exec_module(mod)
        # Successful import + a valid version string.
        assert mod.__version__.startswith(BASE_VERSION + "+")
        # And it differs from the complete-tree fingerprint.
        assert mod.__version__ != __version__
    finally:
        sys.modules.pop("_partial_test", None)
