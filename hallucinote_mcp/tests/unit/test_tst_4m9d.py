"""TST-4M9D regression: the FastMCP single-tool lookup is centralized.

The three end-to-end FastMCP routing tests in ``test_server.py`` used to reach
into ``mcp._tool_manager._tools[name]`` directly — private FastMCP internals
that drift across versions. ``get_registered_tool`` (defined in
``test_server.py``, symmetric with the production ``registered_tool_names``
helper) centralizes that version-coupling in ONE place and prefers the tool
manager's public ``get_tool(name)`` accessor. These tests pin the helper's
contract so a future FastMCP bump only has to update one function.
"""
from __future__ import annotations

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.server import create_server

# pytest's default (prepend) import mode puts the test dir on sys.path, so the
# sibling module is importable by its bare name. Centralizing the helper there
# keeps it next to the three routing tests that consume it.
from test_server import get_registered_tool


def test_get_registered_tool_returns_a_runnable_tool():
    mcp = create_server()
    tool = get_registered_tool(mcp, "ableton_session")
    # FastMCP's Tool object is what the routing tests call .run() on.
    assert tool is not None
    assert getattr(tool, "name", None) == "ableton_session"
    assert callable(getattr(tool, "run", None))


def test_get_registered_tool_covers_every_registered_tool():
    mcp = create_server()
    for name in schema.TOOLS:
        tool = get_registered_tool(mcp, name)
        assert getattr(tool, "name", None) == name


def test_get_registered_tool_prefers_public_get_tool_accessor():
    """When the manager exposes the public ``get_tool`` method, the helper
    routes through it rather than the private ``_tools`` dict — so a version
    that keeps ``get_tool`` but renames the store still works."""

    class _Tool:
        name = "ableton_session"

        def run(self, *_a, **_k):  # pragma: no cover - never invoked here
            return None

    sentinel = _Tool()
    calls: list[str] = []

    class _PublicOnlyManager:
        def get_tool(self, name):
            calls.append(name)
            return sentinel if name == "ableton_session" else None

    class _FakeMcp:
        _tool_manager = _PublicOnlyManager()

    got = get_registered_tool(_FakeMcp(), "ableton_session")
    assert got is sentinel
    assert calls == ["ableton_session"]


def test_get_registered_tool_falls_back_to_private_store():
    """If a future FastMCP drops ``get_tool`` (or it returns None), the helper
    still resolves via the ``_tools`` dict — the version-drift resilience the
    centralization buys."""

    class _FakeManager:
        _tools = {"ableton_session": object()}

    class _FakeMcp:
        _tool_manager = _FakeManager()

    got = get_registered_tool(_FakeMcp(), "ableton_session")
    assert got is _FakeMcp._tool_manager._tools["ableton_session"]


def test_get_registered_tool_raises_on_unknown_tool():
    mcp = create_server()
    with pytest.raises(RuntimeError, match="Could not fetch tool"):
        get_registered_tool(mcp, "ableton_does_not_exist")
