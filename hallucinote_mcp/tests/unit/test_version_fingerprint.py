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


def test_mismatch_refusal_carries_machine_code():
    """The refusal stamps a stable ``code`` so the server side can refine the
    remediation, and it survives the wire round-trip."""
    from hallucinote_mcp.client import _response_from_dict
    from hallucinote_mcp.wire import VERSION_MISMATCH_CODE

    drifted = BASE_VERSION + "+abcdef012345"
    resp = check_version_compat(drifted, __version__)
    assert resp.code == VERSION_MISMATCH_CODE
    # Serialized and reconstructed across the TCP boundary unchanged.
    assert resp.to_dict()["code"] == VERSION_MISMATCH_CODE
    assert _response_from_dict(resp.to_dict()).code == VERSION_MISMATCH_CODE


class TestStaleServerProcessHint:
    """The server side's third fact: its own on-disk source. A mismatch where
    the running process fingerprint != the on-disk fingerprint is a stale
    *server process*, not a stale Remote Script (MCP-8H4N)."""

    def test_running_version_differs_from_disk_diagnoses_stale_process(self):
        from hallucinote_mcp import stale_server_process_hint

        # The process "sent" an older fingerprint than the on-disk source now
        # computes — exactly the misdiagnosed case from the bug report.
        stale = BASE_VERSION + "+0000deadbeef"
        hint = stale_server_process_hint(running_version=stale)
        assert hint is not None
        assert "/mcp" in hint
        assert "stale" in hint.lower()
        # It must NOT send the user re-vendoring (the wrong fix here).
        assert "will NOT help" in hint

    def test_running_version_matches_disk_returns_none(self):
        from hallucinote_mcp import stale_server_process_hint

        # The live process IS current — no server-process diagnosis; the
        # generic re-vendor hint should stand.
        assert stale_server_process_hint(running_version=__version__) is None

    def test_unknown_fingerprint_does_not_assert_staleness(self, monkeypatch):
        import hallucinote_mcp
        from hallucinote_mcp import stale_server_process_hint

        monkeypatch.setattr(
            hallucinote_mcp, "_compute_content_fingerprint", lambda *a, **k: "unknown"
        )
        # An unreadable tree fingerprints "unknown" — treat as "cannot
        # diagnose," not "definitely stale."
        assert stale_server_process_hint(running_version=__version__) is None


def test_hash_path_into_is_stable_across_crlf_and_lf(tmp_path: Path):
    """The shared ``hash_path_into`` helper must produce the same hash
    for a file's content whether the on-disk bytes use CRLF or LF
    line endings. Without this, a Windows checkout (or any git config
    with autocrlf=true) produces a different ``__version__`` than a
    Unix checkout for SEMANTICALLY-IDENTICAL source. The handshake
    would then surface a "version mismatch" error for non-drift.

    This is the load-bearing property for W4-F.
    """
    from hallucinote_mcp import hash_path_into

    lf_path = tmp_path / "lf.py"
    crlf_path = tmp_path / "crlf.py"
    lf_path.write_bytes(b"def f():\n    return 1\n")
    crlf_path.write_bytes(b"def f():\r\n    return 1\r\n")

    h_lf = hashlib.sha256()
    hash_path_into(h_lf, lf_path, "same-rel-key")
    h_crlf = hashlib.sha256()
    hash_path_into(h_crlf, crlf_path, "same-rel-key")
    assert h_lf.hexdigest() == h_crlf.hexdigest(), (
        "CRLF and LF versions of the same source must hash identically"
    )


def test_hash_path_into_still_distinguishes_genuinely_different_content(tmp_path: Path):
    """Sanity: CRLF/LF normalization must not be so broad that it
    collapses genuinely different content into the same hash. A
    minimal byte-flip in non-newline content must still change the
    fingerprint contribution."""
    from hallucinote_mcp import hash_path_into

    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_bytes(b"def f():\n    return 1\n")
    b.write_bytes(b"def f():\n    return 2\n")

    h_a = hashlib.sha256()
    hash_path_into(h_a, a, "same-rel-key")
    h_b = hashlib.sha256()
    hash_path_into(h_b, b, "same-rel-key")
    assert h_a.hexdigest() != h_b.hexdigest()


def test_hash_path_into_preserves_binary_content_through_nul_sniff(tmp_path: Path):
    """When a fingerprint entry contains a NUL byte, the CRLF→LF
    normalization is skipped — a future ``_FINGERPRINT_PATHS`` entry
    pointing at a non-Python file (JSON manifest with literal CRLF,
    static ``.als`` skeleton, ``.so``) keeps every byte intact rather
    than having ``b"\\r\\n"`` substrings silently rewritten.

    Two binary blobs differing only in a CRLF→LF substitution must
    hash differently — the load-bearing property the NUL-sniff
    defends. (Python source files have no NUL bytes, so the existing
    CRLF/LF stability test continues to apply for them.)
    """
    from hallucinote_mcp import hash_path_into

    crlf_binary = tmp_path / "manifest.bin"
    lf_binary = tmp_path / "manifest2.bin"
    # Embed a NUL byte alongside a CRLF — without the sniff, the
    # replace would silently collapse the two files.
    crlf_binary.write_bytes(b"hdr\x00payload\r\nfooter")
    lf_binary.write_bytes(b"hdr\x00payload\nfooter")

    h_crlf = hashlib.sha256()
    hash_path_into(h_crlf, crlf_binary, "same-rel-key")
    h_lf = hashlib.sha256()
    hash_path_into(h_lf, lf_binary, "same-rel-key")
    assert h_crlf.hexdigest() != h_lf.hexdigest(), (
        "binary files (NUL byte present) must hash byte-for-byte; the "
        "CRLF→LF normalization must NOT fire on them"
    )


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


def test_handshake_fingerprint_value_is_unchanged_by_the_shared_hash_helper(tmp_path: Path):
    """A golden value over a fixed tree.

    The advisory vendored-content fingerprint hashes through the same helper as
    the handshake one, so the helper is now shared and could be "improved" from
    either side. Any such change would silently invalidate every vendored
    install in the field — a version mismatch for code that never drifted. This
    pins the produced value, CRLF normalization included.
    """
    from hallucinote_mcp import _compute_content_fingerprint

    root = tmp_path / "pkg"
    root.mkdir()
    (root / "wire.py").write_bytes(b"WIRE\r\nsecond line\n")
    (root / "schema.py").write_bytes(b"SCHEMA\n")
    (root / "dispatcher.py").write_bytes(b"DISPATCH\n")
    for sub in ("actions", "handlers", "remote_script"):
        (root / sub).mkdir()
        (root / sub / "__init__.py").write_bytes(f"# {sub}\n".encode())
    (root / "handlers" / "render.py").write_bytes(b"RENDER\n")

    assert _compute_content_fingerprint(root) == "ea03c173dcbc"
