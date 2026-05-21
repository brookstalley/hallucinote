"""FastMCP server construction + handle_tool_call routing."""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.server import (
    PRIMER,
    create_server,
    handle_tool_call,
    registered_tool_names,
)


def test_create_server_registers_ten_tools():
    server = create_server()
    names = registered_tool_names(server)
    assert sorted(names) == sorted(schema.TOOLS)


def test_primer_mentions_each_tool():
    for tool in schema.TOOLS:
        assert tool in PRIMER, f"PRIMER missing {tool}"


def test_handle_tool_call_help_works_without_remote():
    # After create_server, help actions are registered for every tool, so
    # action='help' should return ok without contacting the Remote Script.
    create_server()
    response = handle_tool_call("ableton_session", "help")
    assert response["ok"] is True
    assert response["result"]["tool"] == "ableton_session"


def test_handle_tool_call_unknown_action_returns_structured_error():
    create_server()
    response = handle_tool_call("ableton_session", "fly_to_the_moon")
    assert response["ok"] is False
    assert "valid_actions" in response
    assert "help" in response["valid_actions"]


def test_handle_tool_call_unknown_tool_returns_structured_error():
    response = handle_tool_call("ableton_imaginary", "help")
    assert response["ok"] is False
    assert "unknown tool" in response["error"]


def test_handle_tool_call_forwards_to_client_when_executor_needs_live(
    isolated_registry,
):
    """If validation passes but no actions are registered, the server-side
    dispatch returns a 'needs Live context' error. handle_tool_call should
    then forward to the Remote Script client. We patch ``client.send`` to
    verify the forwarding path without a real socket.
    """
    from hallucinote_mcp.schema import Action, LiveOp, ParamSpec
    from hallucinote_mcp.wire import Response

    isolated_registry.register(
        Action(
            tool="ableton_session",
            name="set_tempo",
            description="",
            params=(ParamSpec(name="value", type="float"),),
            declarative_op=LiveOp(
                kind="property_write", target="song", property="tempo"
            ),
        )
    )

    # No registered help means handle_tool_call would also fail for `help`,
    # so register them too.
    isolated_registry.register_help_actions()

    forwarded = Response(ok=True, result={"new_tempo": 132.0})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        response = handle_tool_call("ableton_session", "set_tempo", {"value": 132.0})
    assert send.call_count == 1
    forwarded_request = send.call_args.args[0]
    assert forwarded_request.tool == "ableton_session"
    assert forwarded_request.action == "set_tempo"
    assert forwarded_request.params == {"value": 132.0}
    # Default (no opt-in) — the bypass field stays False on the forwarded
    # request, preserving the strict-by-default contract.
    assert forwarded_request.allow_version_mismatch is False
    assert response == {"ok": True, "result": {"new_tempo": 132.0}}


def test_handle_tool_call_propagates_allow_version_mismatch_to_remote(
    isolated_registry,
):
    """When the caller opts into the bypass, the flag MUST ride through to
    the forwarded request — otherwise the Remote Script side never sees it
    and refuses on drift as before."""
    from hallucinote_mcp.schema import Action, LiveOp, ParamSpec
    from hallucinote_mcp.wire import Response

    isolated_registry.register(
        Action(
            tool="ableton_session",
            name="set_tempo",
            description="",
            params=(ParamSpec(name="value", type="float"),),
            declarative_op=LiveOp(
                kind="property_write", target="song", property="tempo"
            ),
        )
    )
    isolated_registry.register_help_actions()

    forwarded = Response(ok=True, result={"new_tempo": 132.0})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call(
            "ableton_session",
            "set_tempo",
            {"value": 132.0},
            allow_version_mismatch=True,
        )
    forwarded_request = send.call_args.args[0]
    assert forwarded_request.allow_version_mismatch is True


def test_handle_tool_call_translates_connection_error(isolated_registry):
    """When the Remote Script is unreachable, surface a teaching error rather
    than letting the LiveConnectionError bubble up to the MCP client.
    """
    from hallucinote_mcp.client import LiveConnectionError
    from hallucinote_mcp.schema import Action, LiveOp, ParamSpec

    isolated_registry.register(
        Action(
            tool="ableton_session",
            name="set_tempo",
            description="",
            params=(ParamSpec(name="value", type="float"),),
            declarative_op=LiveOp(
                kind="property_write", target="song", property="tempo"
            ),
        )
    )
    isolated_registry.register_help_actions()

    with patch(
        "hallucinote_mcp.server.client.send",
        side_effect=LiveConnectionError("Connection refused"),
    ):
        response = handle_tool_call("ableton_session", "set_tempo", {"value": 132.0})
    assert response["ok"] is False
    assert "Connection refused" in response["error"]
    assert "Control Surface" in (response.get("hint") or "")


# ---------------------------------------------------------------------------
# Wire-shape regression: every tool's inputSchema must expose action params
# as top-level kwargs (not nested under ``params``).
#
# Backstory: the original wrapper signature ``(action, params: dict | None)``
# combined with pydantic's silent ``extra='ignore'`` made the documented
# call form (``ableton_session(action='set_tempo', bpm=132.0)``) silently
# drop the ``bpm`` and fail with "missing required param" — every example
# string and resource guide in the codebase pointed at the broken shape.
# These tests pin the flat-kwargs surface against regression. (Wave 2 W2-1)
# ---------------------------------------------------------------------------


def test_every_tool_input_schema_includes_action_field():
    """Every tool's JSONSchema has an ``action`` property (required)."""
    mcp = create_server()
    tools = asyncio.run(mcp.list_tools())
    by_name = {t.name: t for t in tools}
    for tool_name in schema.TOOLS:
        spec = by_name[tool_name]
        props = spec.inputSchema.get("properties", {})
        assert "action" in props, f"{tool_name} missing 'action'"
        assert "action" in spec.inputSchema.get("required", []), (
            f"{tool_name}'s 'action' field is not required"
        )


def test_every_tool_input_schema_flattens_action_params():
    """Every action's params appear as top-level keys in the tool's JSONSchema.

    The previous ``(action, params)`` wrapper exposed only ``{action, params}``
    — Claude Code following the schema would nest action args inside
    ``params``, but every example string instructed top-level kwargs. This
    test fails on the old shape and passes on the flattened one.
    """
    mcp = create_server()
    tools = asyncio.run(mcp.list_tools())
    by_name = {t.name: t for t in tools}
    for tool_name in schema.TOOLS:
        props = by_name[tool_name].inputSchema.get("properties", {})
        # ``params`` envelope must NOT exist — that's the bug shape.
        assert "params" not in props, (
            f"{tool_name} still exposes a 'params' envelope; flat wrapper "
            f"should have replaced it. Found schema props: {sorted(props)}"
        )
        # Every action's param names should appear at the top level.
        for action in schema.actions_for(tool_name):
            if action.name == "help":
                continue
            for param in action.params:
                assert param.name in props, (
                    f"{tool_name}.{action.name}: param '{param.name}' is "
                    f"missing from the tool's top-level inputSchema. "
                    f"Available: {sorted(props)}"
                )


def test_tool_call_via_fastmcp_accepts_flat_kwargs():
    """End-to-end: the FastMCP wrapper accepts ``bpm=132.0`` at the top
    level — the documented call shape. Forwards to the Remote Script with
    the param correctly placed in the wire Request's ``params`` dict.
    """
    from hallucinote_mcp.wire import Response

    mcp = create_server()
    tools = asyncio.run(mcp.list_tools())
    by_name = {t.name: t for t in tools}
    tool = by_name["ableton_session"]
    mgr = mcp._tool_manager  # noqa: SLF001 — test introspection
    runner = mgr._tools[tool.name]  # noqa: SLF001

    forwarded = Response(ok=True, result={"tempo": 132.0})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        # Mimic what FastMCP gets from the MCP client: a raw arguments dict.
        asyncio.run(runner.run({"action": "set_tempo", "bpm": 132.0}))
    assert send.call_count == 1
    forwarded_req = send.call_args.args[0]
    assert forwarded_req.tool == "ableton_session"
    assert forwarded_req.action == "set_tempo"
    assert forwarded_req.params == {"bpm": 132.0}, (
        f"Expected bpm=132.0 in forwarded params; got {forwarded_req.params}. "
        "If params is empty, the wire wrapper is dropping top-level kwargs "
        "again — the regression these tests exist to catch."
    )


def test_tool_call_via_fastmcp_drops_unsupplied_optional_kwargs():
    """``seek`` has an optional ``beat`` param; when the client omits it the
    wrapper should NOT forward ``beat=None`` — the dispatcher would either
    misinterpret None as a value or surface a type error.
    """
    from hallucinote_mcp.wire import Response

    mcp = create_server()
    mgr = mcp._tool_manager  # noqa: SLF001
    runner = mgr._tools["ableton_session"]  # noqa: SLF001

    forwarded = Response(ok=True, result={"song_time": 16.0})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        asyncio.run(runner.run({"action": "seek", "bar": 5}))
    forwarded_req = send.call_args.args[0]
    assert forwarded_req.params == {"bar": 5}, (
        f"Optional kwarg leak: forwarded params={forwarded_req.params}; "
        "expected just {'bar': 5} with no implicit beat=None."
    )


def test_help_action_works_via_fastmcp_with_no_kwargs():
    """The most common discovery call — ``action='help'`` with no other args
    — must succeed end-to-end through the FastMCP wrapper.
    """
    mcp = create_server()
    mgr = mcp._tool_manager  # noqa: SLF001
    runner = mgr._tools["ableton_session"]  # noqa: SLF001

    # No client.send patching — help is dispatcher-resolved, no Live trip.
    result = asyncio.run(runner.run({"action": "help"}))
    # FastMCP wraps the result; the inner dict is on .structured_content
    # or returned directly depending on version. Drill in by string match.
    rendered = repr(result)
    assert "set_tempo" in rendered, f"help didn't render: {rendered[:300]}"


def test_register_tool_detects_param_type_conflicts(isolated_registry):
    """Two actions on the same tool with the same param name but different
    types must raise at registration — the flat schema can't represent two
    types under one field.
    """
    from hallucinote_mcp.schema import Action, LiveOp, ParamSpec
    from hallucinote_mcp.server import _collect_tool_params

    isolated_registry.register(
        Action(
            tool="ableton_session",
            name="a_int",
            description="",
            params=(ParamSpec(name="value", type="int"),),
            declarative_op=LiveOp(
                kind="property_write", target="song", property="x"
            ),
        )
    )
    isolated_registry.register(
        Action(
            tool="ableton_session",
            name="a_str",
            description="",
            params=(ParamSpec(name="value", type="str"),),
            declarative_op=LiveOp(
                kind="property_write", target="song", property="y"
            ),
        )
    )
    with pytest.raises(ValueError, match="type conflict"):
        _collect_tool_params("ableton_session")
