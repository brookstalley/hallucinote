"""Regression: top-level stdlib imports across the Remote Script
load chain that Live's embedded Python doesn't ship.

Live 12.x's embedded Python lacks several C-extension stdlib modules
that the agent's host Python takes for granted. The most-traveled one
so far is ``_sqlite3`` (so ``import sqlite3`` raises
``ModuleNotFoundError`` inside Live). When such an import lands at
module load in any module reachable from
``hallucinote_mcp/actions/__init__.py``, the side-effect walk that
populates the Live-side schema registry aborts — and the Control
Surface fails to initialize without the user ever seeing a stack
trace in Live's UI (only `Log.txt` shows it).

The Arc 2 annotations handler shipped exactly this bug: an
``import sqlite3`` at line 32 was dead code (lazy type-string
annotations under ``from __future__ import annotations``) but blew
up Live's Control Surface load anyway. Live's verification was
explicitly deferred for that chunk (Arc 2 backlog item), so this
test plugs the gap structurally.

The walk uses AST inspection rather than runtime import because:

1. Several Remote Script modules depend on ``_Framework`` (only
   available inside Live's embedded Python), so a runtime import of
   the full chain would fail with the wrong error.
2. We want to catch the bug whether or not the host Python happens
   to have ``sqlite3`` available — the host Python's sqlite3 is the
   reason the bug is invisible at normal test time.

If Live's embedded Python loses other modules in future versions, add
them to ``_FORBIDDEN_TOP_LEVEL_STDLIB`` here. The set is intentionally
narrow — only modules we've confirmed missing.
"""
from __future__ import annotations

import ast
from pathlib import Path


_PACKAGE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "hallucinote_mcp"
)

# Modules that Live's embedded Python is known to ship without. Add to
# this set only after confirming a real Log.txt ModuleNotFoundError.
# Adding speculatively risks rejecting valid code; under-pruning risks
# letting a Control-Surface-breaking import slip through.
_FORBIDDEN_TOP_LEVEL_STDLIB: frozenset[str] = frozenset({
    "sqlite3",
    "_sqlite3",
})


def _top_level_imports(source: str) -> set[str]:
    """Return the set of top-level (module-load-time) imports in source.

    Imports nested inside function bodies, class bodies, try/except
    guards, or `if` blocks are NOT included — those are deferred to
    invocation time, which is exactly the pattern callers use to keep
    risky modules off the Remote Script load path.
    """
    tree = ast.parse(source)
    out: set[str] = set()
    for node in tree.body:  # body = top-level statements only
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                out.add(node.module.split(".")[0])
    return out


def _modules_in_remote_script_load_chain() -> list[Path]:
    """Every .py file reachable from a Live-side Control Surface load.

    The Remote Script's ``_control_surface.py`` does
    ``from .. import actions as _actions`` at module load — that walks
    ``actions/__init__.py``, which `from . import each_action`,
    which each `from ..handlers import counterpart_handler`. So
    everything under ``actions/`` and ``handlers/`` is in the chain,
    plus the small top-level modules these depend on (``schema``,
    ``wire``, ``dispatcher``, ``device_names``).
    """
    return [
        *sorted((_PACKAGE_ROOT / "actions").glob("*.py")),
        *sorted((_PACKAGE_ROOT / "handlers").glob("*.py")),
        # Top-level modules transitively imported by the actions chain
        # — bundle them in the same check.
        _PACKAGE_ROOT / "schema.py",
        _PACKAGE_ROOT / "wire.py",
        _PACKAGE_ROOT / "dispatcher.py",
        _PACKAGE_ROOT / "device_names.py",
    ]


def test_remote_script_load_chain_does_not_top_level_import_forbidden_stdlib():
    offenders: list[tuple[Path, set[str]]] = []
    for path in _modules_in_remote_script_load_chain():
        if not path.exists():
            continue
        source = path.read_text()
        imports = _top_level_imports(source)
        forbidden = imports & _FORBIDDEN_TOP_LEVEL_STDLIB
        if forbidden:
            offenders.append((path.relative_to(_PACKAGE_ROOT), forbidden))

    assert not offenders, (
        "Remote Script load chain top-level imports forbidden stdlib "
        "modules that Live's embedded Python doesn't ship — the Control "
        "Surface will fail to initialize:\n"
        + "\n".join(
            f"  {p}: {sorted(m)}" for p, m in offenders
        )
        + "\n\nMove the import inside the function that needs it, OR "
        "delete the import if it's dead (e.g. type hints under "
        "`from __future__ import annotations` are lazy strings and "
        "don't need the import at runtime)."
    )


def test_forbidden_set_is_not_empty():
    """Belt-and-suspenders: if a refactor accidentally empties
    `_FORBIDDEN_TOP_LEVEL_STDLIB`, the main test silently passes. Pin
    the floor here.
    """
    assert _FORBIDDEN_TOP_LEVEL_STDLIB, (
        "_FORBIDDEN_TOP_LEVEL_STDLIB must list at least one module known "
        "to be absent from Live's embedded Python. Removing all entries "
        "neutralizes the regression check."
    )
