"""Version parity — the guard against the version drift that accumulated
pre-1.5.0.

Before 1.5.0 the product version lived in four hand-maintained places that had
silently diverged — root `pyproject.toml` (0.9.0), `hallucinote_mcp/pyproject.toml`
(0.9.0), `.claude-plugin/plugin.json` (0.9.8), and `src/hallucinote/__init__.py`
(0.1.0) — with nothing to catch it (plus an abandoned 1.x git-tag/CHANGELOG track
on top). Root cause: a duplicated value with no single source of truth and no
drift check. See CHANGELOG [1.5.0].

Root `pyproject.toml [project].version` is now the CANONICAL product version. The
three places that must carry a literal copy of it — the MCP package's pyproject,
the plugin manifest Claude Code's marketplace reads, and the engine package's
`__version__` — are locked to it here. A future bump that misses one FAILS CI
instead of shipping drift.

(These read the SOURCE FILES directly, not installed metadata, so the test is
correct in any checkout regardless of editable-install state.)

The MCP server's `hallucinote_mcp.BASE_VERSION` is deliberately NOT part of this
parity: it is a wire-protocol epoch paired with a content fingerprint, decoupled
from the product version on purpose. `installed_remote_script_version` compares
the full `BASE_VERSION+fingerprint` string between the running server and Live's
vendored Remote Script, so bumping BASE_VERSION every release would flag every
Live install as drifted and force a needless re-vendor — even when the wire shape
is unchanged. This test only asserts that decoupling is intact (it stays valid
semver, free to differ from the product version).
"""
from __future__ import annotations

import json
from pathlib import Path

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # pragma: no cover - py3.10 fallback
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]


def _toml_version(rel_path: str) -> str:
    with (REPO_ROOT / rel_path).open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def _pyproject_version() -> str:
    """The canonical product version (root pyproject [project].version)."""
    return _toml_version("pyproject.toml")


def test_mcp_package_version_matches_pyproject():
    canonical = _pyproject_version()
    mcp = _toml_version("hallucinote_mcp/pyproject.toml")
    assert mcp == canonical, (
        f"hallucinote_mcp/pyproject.toml version {mcp!r} != root pyproject "
        f"{canonical!r} — bump both together (root pyproject is canonical)."
    )


def test_plugin_manifest_version_matches_pyproject():
    canonical = _pyproject_version()
    manifest = json.loads(
        (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == canonical, (
        f".claude-plugin/plugin.json version {manifest['version']!r} != pyproject "
        f"{canonical!r} — bump both together (pyproject is the canonical source)."
    )


def test_engine_dunder_version_matches_pyproject():
    import hallucinote

    canonical = _pyproject_version()
    assert hallucinote.__version__ == canonical, (
        f"hallucinote.__version__ {hallucinote.__version__!r} != pyproject "
        f"{canonical!r} — bump src/hallucinote/__init__.py to match."
    )


def test_mcp_base_version_is_decoupled_but_valid_semver():
    """BASE_VERSION is the wire-protocol epoch, intentionally independent of the
    product version (see module docstring) — so this asserts only that it stays a
    sane dotted X.Y.Z, NOT that it equals the product version."""
    from hallucinote_mcp import BASE_VERSION

    parts = BASE_VERSION.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), (
        f"hallucinote_mcp.BASE_VERSION {BASE_VERSION!r} is not X.Y.Z semver"
    )
