"""Tests for the analysis-pipeline loaded-vs-disk version probe.

The probe exists to make a stale MCP subprocess obvious: it hashes the
``hallucinote.audio`` source so the signature moves automatically with any
code change, and compares the import-frozen signature against disk.
"""
from __future__ import annotations

from pathlib import Path

from hallucinote.audio import codeversion


def test_hash_dir_is_deterministic(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.py").write_text("y = 2\n")

    assert codeversion._hash_dir(tmp_path) == codeversion._hash_dir(tmp_path)


def test_hash_dir_changes_with_content(tmp_path: Path):
    module = tmp_path / "a.py"
    module.write_text("x = 1\n")
    before = codeversion._hash_dir(tmp_path)

    module.write_text("x = 2\n")
    after = codeversion._hash_dir(tmp_path)

    assert before != after


def test_hash_dir_changes_with_rename(tmp_path: Path):
    """A renamed module is a code change — the name is folded into the digest."""
    (tmp_path / "a.py").write_text("x = 1\n")
    before = codeversion._hash_dir(tmp_path)

    (tmp_path / "a.py").rename(tmp_path / "b.py")
    after = codeversion._hash_dir(tmp_path)

    assert before != after


def test_hash_dir_ignores_non_py_files(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\n")
    before = codeversion._hash_dir(tmp_path)

    (tmp_path / "notes.txt").write_text("ignore me\n")
    (tmp_path / "a.cpython-312.pyc").write_bytes(b"\x00\x01")
    after = codeversion._hash_dir(tmp_path)

    assert before == after


def test_read_py_returns_marker_for_missing_file(tmp_path: Path):
    """An unreadable file folds into the digest deterministically, never raises."""
    assert codeversion._read_py(tmp_path / "gone.py") == codeversion._UNREADABLE


def test_loaded_signature_is_frozen(monkeypatch, tmp_path: Path):
    """loaded_signature() is captured at import — it must not follow a later
    change to the package dir, or it could not detect staleness."""
    frozen = codeversion.loaded_signature()

    # Even if the package dir resolver is repointed, the loaded signature
    # stays put (it was computed once, at import).
    monkeypatch.setattr(codeversion, "_package_dir", lambda: tmp_path)
    assert codeversion.loaded_signature() == frozen


def test_disk_signature_follows_package_dir(monkeypatch, tmp_path: Path):
    """disk_signature() recomputes from the current source on each call."""
    (tmp_path / "a.py").write_text("x = 1\n")
    monkeypatch.setattr(codeversion, "_package_dir", lambda: tmp_path)

    assert codeversion.disk_signature() == codeversion._hash_dir(tmp_path)


def test_not_stale_when_source_unchanged():
    """The realistic invariant: an un-edited tree is not stale (loaded == disk)."""
    assert codeversion.is_stale() is False
    assert codeversion.loaded_signature() == codeversion.disk_signature()


def test_is_stale_when_disk_differs_from_loaded(monkeypatch):
    """When on-disk source no longer matches the loaded (frozen) signature,
    the probe reports stale — the cue to respawn the MCP server."""
    monkeypatch.setattr(codeversion, "disk_signature", lambda: "deadbeef0000")
    assert codeversion.loaded_signature() != "deadbeef0000"
    assert codeversion.is_stale() is True


def test_signature_is_short_hex():
    sig = codeversion.loaded_signature()
    assert len(sig) == 12
    assert all(c in "0123456789abcdef" for c in sig)
