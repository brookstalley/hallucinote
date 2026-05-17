"""FastMCP server construction + handle_tool_call routing."""
from __future__ import annotations

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
    assert response == {"ok": True, "result": {"new_tempo": 132.0}}


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
