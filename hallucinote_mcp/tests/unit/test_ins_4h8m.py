"""INS-4H8M — fingerprint the ``HallucinoteAnalyzer.amxd`` for install drift.

Parity with the Remote Script's ``matches_mcp_server`` drift signal: the
binary M4L device gets a raw-byte content fingerprint captured implicitly at
install (it's derived from bytes, so install copies the source fingerprint into
place) and re-derivable on verify. The load-bearing regression:

    install -> tamper-with-file -> verify reports drift
    install -> verify clean     -> a no-op pass (matches True)

The fingerprint is a raw-byte sha256 — NOT the text-normalizing
``compute_version_for`` path the Remote Script uses — because the ``.amxd`` is a
binary container that CRLF→LF normalization would corrupt.
"""
from __future__ import annotations

import hashlib
import pathlib


from hallucinote_mcp import install_ops as ops
from hallucinote_mcp import install_paths as P
from hallucinote_mcp.cli.preflight import _build_report


# A fake ``.amxd`` whose bytes include a CRLF *and* a NUL — the exact content a
# naive text-normalizing hash would corrupt or refuse. Proves the fingerprint
# hashes raw bytes.
_FAKE_AMXD_BYTES = b"max-device\x00binary\r\npayload\xff\x00more"


def _src(tmp_path: pathlib.Path) -> pathlib.Path:
    src = tmp_path / "HallucinoteAnalyzer.amxd"
    src.write_bytes(_FAKE_AMXD_BYTES)
    return src


# --- helper: analyzer_fingerprint ------------------------------------------

def test_fingerprint_is_raw_byte_sha256_prefix(tmp_path):
    """The fingerprint is the first 12 hex chars of the file's raw-byte sha256."""
    src = _src(tmp_path)
    expected = hashlib.sha256(_FAKE_AMXD_BYTES).hexdigest()[:12]
    fp = P.analyzer_fingerprint(src)
    assert fp == expected
    assert len(fp) == 12
    int(fp, 16)  # raises if not hex


def test_fingerprint_does_not_normalize_line_endings(tmp_path):
    """Binary container: CRLF must NOT be folded to LF (would corrupt the device).

    A CRLF-normalizing hash would produce the same fingerprint for these two
    distinct byte sequences; a raw-byte hash must keep them different.
    """
    crlf = tmp_path / "crlf.amxd"
    lf = tmp_path / "lf.amxd"
    crlf.write_bytes(b"head\r\ntail")
    lf.write_bytes(b"head\ntail")
    assert P.analyzer_fingerprint(crlf) != P.analyzer_fingerprint(lf)


def test_fingerprint_none_when_absent(tmp_path):
    """A missing path returns None (tri-state: distinguish absent from a hash)."""
    assert P.analyzer_fingerprint(tmp_path / "nope.amxd") is None


def test_fingerprint_none_for_directory(tmp_path):
    """A directory is not a fingerprintable device → None, not a crash."""
    d = tmp_path / "adir"
    d.mkdir()
    assert P.analyzer_fingerprint(d) is None


# --- install -> verify clean (no-op) ---------------------------------------

def test_install_then_verify_clean_matches(tmp_path):
    """install -> verify clean: installed fingerprint == source fingerprint.

    This is the no-op pass — the install skill skips the copy + overwrite
    prompt entirely when these match (INS-4H8M).
    """
    src = _src(tmp_path)
    user_library = tmp_path / "UserLibrary"
    dst = P.analyzer_install_target(user_library)

    ops.install_analyzer(src, dst)

    source_fp = P.analyzer_fingerprint(src)
    installed_fp = P.installed_analyzer_fingerprint(user_library)
    assert installed_fp is not None
    assert installed_fp == source_fp  # byte-identical copy → identical fingerprint


# --- install -> tamper -> verify reports drift ------------------------------

def test_install_then_tamper_reports_drift(tmp_path):
    """install -> tamper-with-file -> the installed fingerprint diverges.

    A stale/modified device must be detectable (the whole point of INS-4H8M):
    the install skill prompts to overwrite only when this drift is present.
    """
    src = _src(tmp_path)
    user_library = tmp_path / "UserLibrary"
    dst = P.analyzer_install_target(user_library)

    ops.install_analyzer(src, dst)
    clean_fp = P.installed_analyzer_fingerprint(user_library)

    # Tamper with the installed device (simulating a Max-GUI edit / stale build).
    dst.write_bytes(_FAKE_AMXD_BYTES + b"\x00tampered")
    drifted_fp = P.installed_analyzer_fingerprint(user_library)

    assert drifted_fp is not None
    assert drifted_fp != clean_fp
    assert drifted_fp != P.analyzer_fingerprint(src)


def test_installed_fingerprint_none_when_not_installed(tmp_path):
    """No installed device → None (preflight reports installed:false, matches:null)."""
    assert P.installed_analyzer_fingerprint(tmp_path / "EmptyLibrary") is None


# --- preflight surfaces the analyzer block ---------------------------------

def test_preflight_carries_analyzer_block_with_matches_field():
    """Schema contract: preflight has an `analyzer` block, parity with `remote_script`.

    One candidate entry per User Library candidate, each with a `matches`
    tri-state; a top-level `source_fingerprint`. Shape-only — independent of
    whether the test host has an installed device.
    """
    report = _build_report()
    assert "analyzer" in report
    block = report["analyzer"]
    assert "source_fingerprint" in block
    assert "candidates" in block
    assert len(block["candidates"]) == len(report["user_library"]["candidates"])
    for entry in block["candidates"]:
        assert set(entry.keys()) == {
            "user_library",
            "target",
            "installed",
            "installed_fingerprint",
            "matches",
        }
        assert isinstance(entry["installed"], bool)
        assert entry["matches"] in (True, False, None)
        # Absent install → no fingerprint, no match.
        if not entry["installed"]:
            assert entry["installed_fingerprint"] is None
            assert entry["matches"] is None


def test_preflight_analyzer_matches_true_for_byte_identical_install(tmp_path, monkeypatch):
    """End-to-end through preflight: install the *bundled* source, then the
    candidate for that User Library reports `matches: true` — the signal the
    skill branches on to skip the redundant overwrite prompt.
    """
    user_library = tmp_path / "UserLibrary"
    # Point the (single) candidate at our temp User Library so the real preflight
    # walk sees our freshly-installed device.
    monkeypatch.setattr(P, "candidate_user_libraries", lambda: [user_library])

    src = P.analyzer_amxd_source_path()
    dst = P.analyzer_install_target(user_library)
    ops.install_analyzer(src, dst)

    report = _build_report()
    cands = report["analyzer"]["candidates"]
    assert len(cands) == 1
    entry = cands[0]
    assert entry["installed"] is True
    assert entry["matches"] is True
    assert entry["installed_fingerprint"] == report["analyzer"]["source_fingerprint"]

    # Tamper → the same candidate now reports drift.
    dst.write_bytes(dst.read_bytes() + b"\x00drift")
    drifted = _build_report()["analyzer"]["candidates"][0]
    assert drifted["installed"] is True
    assert drifted["matches"] is False
