"""FastMCP server — the 10 unified tools as MCP entry points.

Each ``@mcp.tool()`` is a thin wrapper that:
  1. Builds a ``wire.Request`` from its arguments.
  2. Runs the dispatcher locally for fast-fail validation (no Live needed).
  3. If validation passed and execution requires Live, forwards to the
     Remote Script over TCP via ``client.send``.
  4. Returns the structured response (success or teaching error) as a dict.

The action surface is empty in M-0 — only ``action='help'`` works on every
tool. Subsequent chunks populate the registry; this file does not change
when new actions land. That's the property we wanted from declarative-first
dispatch.
"""
from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import client, schema
from .dispatcher import dispatch
from .wire import Request


logger = logging.getLogger("hallucinote_mcp")


PRIMER = """\
hallucinote-mcp — 10 unified tools for Ableton Live, structured for
low-context-cost agent interaction.

Tools:
  ableton_session     — global state, master, transport, view, tempo, signature, snapshot
  ableton_track       — tracks: lifecycle, mixer state, sends
  ableton_return      — return tracks
  ableton_clip        — session + arrangement clips; quantize/groove
  ableton_note        — within-clip note operations (gap #4 blocked)
  ableton_device      — devices on tracks/returns
  ableton_automation  — envelopes (7 target families)
  ableton_arrangement — arrangement layout + cue points
  ableton_scene       — session-view scenes (rows of clip slots + tempo + signature)
  ableton_browser     — instruments, effects, plugins

Every tool: action='help' returns its full action menu.

Hard constraints:
  - 1-based indexing throughout (track_index >= 1).
  - Note operations REPLACE the clip's full note array — there is no
    note-level addressing until gap #4 lands. To preserve manual edits,
    pull first, mutate, push.
  - Cue point names round-trip as numeric IDs (gap #13). Names are
    write-only-DB-side; do not trust pulled names.
"""


def create_server(name: str = "hallucinote-mcp") -> FastMCP:
    """Construct the FastMCP server with all 10 tools registered.

    Side-effect-light — safe to call from tests. The actual ``serve()`` /
    ``run()`` loop is started by the CLI entry point.
    """
    # Importing the actions package registers every tool's actions on the
    # shared schema registry. Each chunk's module imports happen here so a
    # missing action is caught at server boot, not first call.
    from . import actions  # noqa: F401  (side-effect import)

    # Fill in help actions for any tool that didn't already register one.
    schema.register_help_actions()

    mcp = FastMCP(name=name, instructions=PRIMER)

    # Define the ten tool entry points. Each is a thin wrapper around the
    # shared dispatcher; the wrapper exists only so FastMCP can register a
    # name + docstring for the MCP client to see.
    _register_tool(mcp, "ableton_session", "Global state, master, transport, view, tempo, signature, snapshot.")
    _register_tool(mcp, "ableton_track", "Tracks: lifecycle, mixer state, sends.")
    _register_tool(mcp, "ableton_return", "Return tracks: lifecycle, mixer state.")
    _register_tool(mcp, "ableton_clip", "Session + arrangement clips; quantize/groove.")
    _register_tool(mcp, "ableton_note", "Within-clip note operations (gap #4 blocked).")
    _register_tool(mcp, "ableton_device", "Devices on tracks/returns: load, parameters, routing.")
    _register_tool(mcp, "ableton_automation", "Envelopes across seven target families.")
    _register_tool(mcp, "ableton_arrangement", "Arrangement layout, cue points, loop region.")
    _register_tool(mcp, "ableton_scene", "Session-view scenes: clip-slot rows + tempo + signature.")
    _register_tool(mcp, "ableton_browser", "Instruments, effects, plugins; search and fetch.")

    return mcp


def handle_tool_call(tool: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Process one tool invocation. Returns the wire response as a dict.

    Decomposed from the FastMCP decorator wrappers so tests can drive it
    without spinning up the full MCP server.

    Strategy:
      1. Server-side dispatch first (no Live context) — catches unknown
         actions, unknown params, type errors, etc. Help actions return
         immediately here.
      2. If server-side dispatch sets ``needs_remote`` on the response
         (validation passed but the executor needs Live), forward the
         original request to the Remote Script over TCP.
      3. Otherwise (validation error or help result) return directly
         without touching the wire.
    """
    request = Request(tool=tool, action=action, params=params or {})

    server_response = dispatch(request, context=None)

    if not server_response.needs_remote:
        return server_response.to_dict()

    # Forward to the Remote Script.
    try:
        remote_response = client.send(request)
    except client.LiveConnectionError as exc:
        from .wire import error as wire_error

        logger.warning(
            "live connection failed for %s(%r): %s", tool, action, exc
        )
        return wire_error(
            str(exc),
            hint=(
                "Open Ableton Live, then in Preferences → Link, Tempo & MIDI "
                "select 'Hallucinote' as a Control Surface. Re-run the call."
            ),
        ).to_dict()

    return remote_response.to_dict()


def _register_tool(mcp: FastMCP, tool_name: str, summary: str) -> None:
    """Register one of the ten unified tools on the FastMCP instance.

    The wrapper signature is ``(action: str, params: dict | None = None)`` —
    deliberately minimal, since the per-action schema is discoverable via
    ``action='help'`` and the dispatcher does the validation.
    """

    def wrapper(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return handle_tool_call(tool_name, action, params)

    wrapper.__name__ = tool_name
    wrapper.__doc__ = (
        f"{summary}\n\n"
        f"All operations dispatch on `action` (string). Use "
        f"`{tool_name}(action='help')` to see the full action menu with "
        f"required/optional params, examples, and tips."
    )

    mcp.tool(name=tool_name, description=wrapper.__doc__)(wrapper)


def registered_tool_names(mcp: FastMCP) -> list[str]:
    """Return the names of all tools registered on the FastMCP instance.

    FastMCP's internal storage shape varies across versions; this helper is
    only used by tests to assert "we registered the ten we expected" without
    coupling to private API.
    """
    # FastMCP exposes a tool manager whose internal store has changed over
    # versions; try a few attribute names before giving up.
    for attr in ("_tool_manager", "tool_manager"):
        manager = getattr(mcp, attr, None)
        if manager is None:
            continue
        for store_attr in ("_tools", "tools"):
            store = getattr(manager, store_attr, None)
            if isinstance(store, dict):
                return sorted(store.keys())
    raise RuntimeError(
        "Could not introspect FastMCP tool registry — FastMCP API may have changed"
    )


__all__ = [
    "PRIMER",
    "create_server",
    "handle_tool_call",
    "registered_tool_names",
]
