"""Live-side action-registry bootstrap.

Regression test for a real bug: the Remote Script's Control Surface init
only called ``schema.register_help_actions()`` and never imported the
``actions`` package. Result: Live's in-process schema registry held only
``help`` stubs, so every forwarded tool call (``info``, ``set_tempo``,
etc.) returned ``unknown action 'X' on Y`` with ``valid_actions=['help']``.

The MCP server side and the Remote Script side run in different Python
processes — they don't share runtime state, so each side must trigger the
side-effect imports under ``hallucinote_mcp.actions`` to populate its own
registry. ``server.create_server`` does this for the MCP side; the
Control Surface module must do the same for the Live side.

We verify via AST rather than runtime import because
``_control_surface`` depends on ``_Framework`` (only available inside
Live's embedded Python). AST inspection catches the bug without needing
Live.
"""
from __future__ import annotations

import ast
from pathlib import Path


_CONTROL_SURFACE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "hallucinote_mcp"
    / "remote_script"
    / "_control_surface.py"
)


def _imports_actions_package(source: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # `from .. import actions [as _actions]`
            if node.module is None and node.level == 2:
                for alias in node.names:
                    if alias.name == "actions":
                        return True
            # `from ..actions import ...` would also count
            if node.module == "actions" and node.level == 2:
                return True
        elif isinstance(node, ast.Import):
            # `import hallucinote_mcp.actions`
            for alias in node.names:
                if alias.name in ("hallucinote_mcp.actions",):
                    return True
    return False


def test_control_surface_imports_actions_package():
    source = _CONTROL_SURFACE.read_text(encoding="utf-8")
    assert _imports_actions_package(source), (
        "_control_surface.py must import the actions package as a side "
        "effect so the Live-side schema registry is populated. Without "
        "it, every forwarded tool call returns 'unknown action ... "
        "valid_actions=[\"help\"]'."
    )
