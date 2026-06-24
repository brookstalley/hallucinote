"""MCP-7F2K — the server-side / Live-side boundary that keeps server-internal
changes out of the version fingerprint.

The version handshake fingerprints the code that is *vendored into Live AND
executed in Live*. ``runs_server_side=True`` actions execute only in the MCP
server process, so their code lives in ``hallucinote_mcp.server_side`` and is
deliberately kept out of ``_FINGERPRINT_PATHS``. That exclusion is only *safe*
if a server-side change cannot transitively reach Live-side behavior — which is
exactly what these tests enforce:

  1. The boundary matches the declared flag (server_side handlers ⇔ runs_server_side).
  2. No Live-side code (handlers/, remote_script/) imports from server_side, and
     the only fingerprinted reference is the one registration trigger in
     actions/__init__.py.
  3. The fingerprint walk hashes no file under server_side — so editing it cannot
     flip the handshake (the whole point of MCP-7F2K).

A regression in any of these silently re-introduces the over-trigger (or, worse,
lets a server-side change masquerade as wire-compatible while altering Live).
"""
from __future__ import annotations

from pathlib import Path

import hallucinote_mcp
import hallucinote_mcp.actions  # noqa: F401 — boot the registry side-effect
from hallucinote_mcp import schema
from hallucinote_mcp import _FINGERPRINT_PATHS

PKG_ROOT = Path(hallucinote_mcp.__file__).parent
SERVER_SIDE_PREFIX = "hallucinote_mcp.server_side"


def _py_files(*subdirs: str) -> list[Path]:
    files: list[Path] = []
    for sub in subdirs:
        base = PKG_ROOT / sub
        if base.is_dir():
            files.extend(
                p for p in base.rglob("*.py") if "__pycache__" not in p.parts
            )
    return files


def _fingerprinted_files() -> set[Path]:
    """Replicate the _compute_content_fingerprint file walk (the set of files
    whose bytes are hashed into the version), so we can assert what is in it."""
    out: set[Path] = set()
    for entry in _FINGERPRINT_PATHS:
        target = PKG_ROOT / entry
        if target.is_file():
            out.add(target)
        elif target.is_dir():
            for p in target.rglob("*"):
                if not p.is_file():
                    continue
                if p.name.endswith(".pyc") or "__pycache__" in p.parts:
                    continue
                out.add(p)
    return out


# ---------------------------------------------------------------------------
# 1. The boundary matches the declared flag.
# ---------------------------------------------------------------------------


def test_server_side_package_exists_with_relocated_analysis():
    pkg = PKG_ROOT / "server_side"
    assert pkg.is_dir(), "server_side package must exist (MCP-7F2K relocation)"
    assert (pkg / "analysis.py").is_file()
    assert (pkg / "analysis_actions.py").is_file()
    # And it must NOT have been left behind under handlers/ or actions/.
    assert not (PKG_ROOT / "handlers" / "analysis.py").exists()
    assert not (PKG_ROOT / "actions" / "analysis.py").exists()


def test_runs_server_side_actions_have_handlers_in_server_side():
    server_side_actions = [
        a for a in schema._REGISTRY.values() if getattr(a, "runs_server_side", False)
    ]
    assert server_side_actions, "expected at least the ableton_analysis actions"
    for a in server_side_actions:
        mod = a.handler.__module__
        assert mod.startswith(SERVER_SIDE_PREFIX), (
            f"{a.tool}/{a.name} is runs_server_side but its handler lives in "
            f"{mod} — server-side handlers must live in server_side so they stay "
            f"out of the fingerprint"
        )


def test_handlers_in_server_side_are_declared_server_side():
    """The converse: anything wired from a server_side handler module must carry
    the flag, or it would be dispatched to Live (where its code isn't meant to run)."""
    for a in schema._REGISTRY.values():
        handler = getattr(a, "handler", None)
        if handler is None:
            continue
        if handler.__module__.startswith(SERVER_SIDE_PREFIX):
            assert a.runs_server_side is True, (
                f"{a.tool}/{a.name} handler is in server_side but is not "
                f"runs_server_side=True"
            )


# ---------------------------------------------------------------------------
# 2. No Live-side code depends on server_side.
# ---------------------------------------------------------------------------


def test_no_live_side_module_imports_server_side():
    """handlers/ and remote_script/ run inside Live; they must never import
    server_side, so a server-side change provably cannot alter Live behavior."""
    offenders = [
        str(p.relative_to(PKG_ROOT))
        for p in _py_files("handlers", "remote_script")
        if "server_side" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"Live-side modules must not reference server_side: {offenders}"
    )


def test_only_actions_init_triggers_server_side_registration():
    """The sole fingerprinted reference to server_side is the registration
    trigger in actions/__init__.py (importing the package registers its
    actions). Anything else would couple the wire surface to server internals."""
    referencing = {
        str(p.relative_to(PKG_ROOT))
        for p in _py_files("actions")
        if "server_side" in p.read_text(encoding="utf-8")
    }
    assert referencing == {"actions/__init__.py"}, referencing


# ---------------------------------------------------------------------------
# 3. The fingerprint excludes server_side.
# ---------------------------------------------------------------------------


def test_server_side_not_in_fingerprint_paths():
    assert "server_side" not in _FINGERPRINT_PATHS
    # And no listed entry is a parent that would pull server_side in.
    for entry in _FINGERPRINT_PATHS:
        assert not (PKG_ROOT / entry / "server_side").exists(), (
            f"_FINGERPRINT_PATHS entry {entry!r} contains server_side — the "
            f"exclusion only works while server_side is a top-level sibling"
        )


def test_fingerprint_walk_hashes_no_server_side_file():
    """The behavioral guarantee of MCP-7F2K: no server_side byte enters the hash,
    so editing server_side cannot flip the version and force a re-vendor."""
    hashed = _fingerprinted_files()
    assert hashed, "sanity: the fingerprint should hash some files"
    leaked = [str(p.relative_to(PKG_ROOT)) for p in hashed if "server_side" in p.parts]
    assert not leaked, f"server_side files must not be fingerprinted: {leaked}"
