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
    assert "ableton-mcp-install" in (resp.hint or "")


def test_check_version_compat_passes_when_fingerprints_match():
    """Same fingerprint = no error."""
    resp = check_version_compat(__version__, __version__)
    assert resp is None


def test_hash_file_is_stable_across_crlf_and_lf(tmp_path: Path):
    """The internal ``_hash_file`` helper must produce the same hash
    for a file's content whether the on-disk bytes use CRLF or LF
    line endings. Without this, a Windows checkout (or any git config
    with autocrlf=true) produces a different ``__version__`` than a
    Unix checkout for SEMANTICALLY-IDENTICAL source. The handshake
    would then surface a "version mismatch" error for non-drift.

    This is the load-bearing property for W4-F.
    """
    from hallucinote_mcp import _hash_file

    lf_path = tmp_path / "lf.py"
    crlf_path = tmp_path / "crlf.py"
    lf_path.write_bytes(b"def f():\n    return 1\n")
    crlf_path.write_bytes(b"def f():\r\n    return 1\r\n")

    h_lf = hashlib.sha256()
    _hash_file(h_lf, lf_path, "same-rel-key")
    h_crlf = hashlib.sha256()
    _hash_file(h_crlf, crlf_path, "same-rel-key")
    assert h_lf.hexdigest() == h_crlf.hexdigest(), (
        "CRLF and LF versions of the same source must hash identically"
    )


def test_hash_file_still_distinguishes_genuinely_different_content(tmp_path: Path):
    """Sanity: CRLF/LF normalization must not be so broad that it
    collapses genuinely different content into the same hash. A
    minimal byte-flip in non-newline content must still change the
    fingerprint contribution."""
    from hallucinote_mcp import _hash_file

    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_bytes(b"def f():\n    return 1\n")
    b.write_bytes(b"def f():\n    return 2\n")

    h_a = hashlib.sha256()
    _hash_file(h_a, a, "same-rel-key")
    h_b = hashlib.sha256()
    _hash_file(h_b, b, "same-rel-key")
    assert h_a.hexdigest() != h_b.hexdigest()


def test_compute_fingerprint_returns_unknown_on_os_error(monkeypatch):
    """When walking the source tree raises ``OSError`` (the filesystem
    layer is unhappy for some reason — permission denied, I/O error,
    transient FUSE mount unmounting under us), the function must
    return the literal string ``"unknown"`` rather than raising. The
    handshake's "unknown" never matches any other fingerprint, so the
    version check still surfaces drift — but import time keeps working.

    Pinning ``"unknown"`` (rather than "ok, just return ''") is
    load-bearing: a callsite searching for that exact literal is the
    only deterministic way to detect this failure mode from outside.
    """
    from hallucinote_mcp import _compute_content_fingerprint

    real_rglob = Path.rglob

    def _raise_os_error(self, pattern):
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(Path, "rglob", _raise_os_error)
    try:
        assert _compute_content_fingerprint() == "unknown"
    finally:
        # monkeypatch will undo automatically, but be explicit for clarity.
        monkeypatch.setattr(Path, "rglob", real_rglob)


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
