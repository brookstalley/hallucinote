"""Tests for ``tools/stamp_evidence_sha.py`` — the Arc 5 / P4 helper that
re-stamps ``.prawduct/.test-evidence.json``'s ``git_sha`` from ``HEAD``
so the cumulative PR reviewer doesn't see stale SHA pointers.

The script lives outside ``tools/product-hook`` (which carries in-flight
v1.5 framework WIP) and is wired into the Stop hook.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
STAMP_PATH = REPO_ROOT / "tools" / "stamp_evidence_sha.py"


def _load_stamp_module():
    """Load ``tools/stamp_evidence_sha.py`` as a module by path — ``tools``
    isn't a package so a normal import doesn't resolve."""
    spec = importlib.util.spec_from_file_location(
        "stamp_evidence_sha", str(STAMP_PATH),
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stamp_evidence_sha"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_stamp_no_file_returns_missing(tmp_path, monkeypatch):
    """No evidence file on disk — script is a no-op, no error."""
    stamp = _load_stamp_module()
    monkeypatch.setattr(stamp, "_git_head_sha", lambda: "abc123")
    assert stamp.stamp(tmp_path / "nope.json") == "missing"


def test_stamp_unparseable_returns_unparseable(tmp_path, monkeypatch):
    """Garbled JSON — surface the diagnostic, don't crash the hook."""
    stamp = _load_stamp_module()
    monkeypatch.setattr(stamp, "_git_head_sha", lambda: "abc123")
    evidence = tmp_path / "ev.json"
    evidence.write_text("not json at all")
    assert stamp.stamp(evidence) == "unparseable"


def test_stamp_current_sha_returns_current_no_write(tmp_path, monkeypatch):
    """Idempotency: if SHA already matches HEAD, no rewrite happens."""
    stamp = _load_stamp_module()
    monkeypatch.setattr(stamp, "_git_head_sha", lambda: "abc123")
    evidence = tmp_path / "ev.json"
    payload = {"git_sha": "abc123", "passed": 1851, "command": "pytest"}
    evidence.write_text(json.dumps(payload))
    mtime_before = evidence.stat().st_mtime_ns

    assert stamp.stamp(evidence) == "current"

    # File must not have been rewritten.
    assert evidence.stat().st_mtime_ns == mtime_before
    # Contents intact.
    assert json.loads(evidence.read_text()) == payload


def test_stamp_stale_sha_gets_updated_other_fields_preserved(
    tmp_path, monkeypatch
):
    """Core behavior: rewrite ``git_sha``; preserve every other field
    untouched. This is the load-bearing invariant — losing any other
    field would break the validator-required schema."""
    stamp = _load_stamp_module()
    monkeypatch.setattr(stamp, "_git_head_sha", lambda: "new-head-sha")
    evidence = tmp_path / "ev.json"
    payload = {
        "git_sha": "old-stale-sha",
        "timestamp": "2026-05-21T12:00:00Z",
        "passed": 1851, "failed": 0, "skipped": 0, "total": 1851,
        "duration_seconds": 13.4,
        "command": "pytest -n auto --dist loadgroup",
        "chunk": "Arc 5 / P1",
    }
    evidence.write_text(json.dumps(payload))

    out = stamp.stamp(evidence)
    assert out.startswith("stamped:old-stale-sha->new-head-sha")

    updated = json.loads(evidence.read_text())
    assert updated["git_sha"] == "new-head-sha"
    # Every other field preserved verbatim.
    for k in ("timestamp", "passed", "failed", "skipped", "total",
              "duration_seconds", "command", "chunk"):
        assert updated[k] == payload[k]


def test_stamp_absent_git_sha_key_gets_added(tmp_path, monkeypatch):
    """A pre-v1.4 evidence file may have lacked ``git_sha`` entirely.
    Stamping should add it without complaint."""
    stamp = _load_stamp_module()
    monkeypatch.setattr(stamp, "_git_head_sha", lambda: "head-x")
    evidence = tmp_path / "ev.json"
    payload = {"passed": 100, "command": "pytest"}
    evidence.write_text(json.dumps(payload))

    out = stamp.stamp(evidence)
    assert out == "stamped:absent->head-x"

    updated = json.loads(evidence.read_text())
    assert updated["git_sha"] == "head-x"
    assert updated["passed"] == 100


def test_stamp_no_head_returns_no_head_without_writing(tmp_path, monkeypatch):
    """If git rev-parse fails (no repo, detached state, hooks running
    outside the worktree), surface the condition and leave the file
    alone — don't write a None SHA."""
    stamp = _load_stamp_module()
    monkeypatch.setattr(stamp, "_git_head_sha", lambda: None)
    evidence = tmp_path / "ev.json"
    payload = {"git_sha": "x", "passed": 1}
    evidence.write_text(json.dumps(payload))
    mtime_before = evidence.stat().st_mtime_ns

    assert stamp.stamp(evidence) == "no-head"
    assert evidence.stat().st_mtime_ns == mtime_before


def test_main_returns_zero_on_every_path(tmp_path, monkeypatch):
    """The hook is housekeeping — main() must exit 0 even on errors so
    a stale SHA never blocks session shutdown."""
    stamp = _load_stamp_module()
    monkeypatch.chdir(tmp_path)

    # No evidence file → exit 0
    assert stamp.main() == 0

    # Unparseable evidence → still 0
    (tmp_path / ".prawduct").mkdir()
    (tmp_path / ".prawduct" / ".test-evidence.json").write_text("garbage")
    assert stamp.main() == 0
