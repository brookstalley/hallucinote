"""MCP resources — 11 URIs covering session reads, browser trees,
reference lookups, and agent-facing guides.

Resources differ from tools structurally:
  - **Tools** are imperative; the agent decides to call them.
  - **Resources** are addressable content; the MCP client (or the agent)
    reads them by URI without consuming a per-tool turn.

Wave M-6 ships 11 resources:

Live-backed (delegate to existing handlers via the server's
``handle_tool_call`` so they reuse the forward-to-Remote-Script path):
  - ``ableton://session/snapshot``
  - ``ableton://browser/instruments``
  - ``ableton://browser/effects``
  - ``ableton://browser/drums``
  - ``ableton://plugins/installed``

Static reference (shipped as JSON in the package data dir):
  - ``ableton://reference/scales``
  - ``ableton://reference/device-params``

Static guides (shipped as markdown in the package data dir):
  - ``ableton://guides/getting-started``
  - ``ableton://guides/conventions``
  - ``ableton://guides/error-recovery``
  - ``ableton://guides/gaps``

Arc 5 / P3 introduces the first **templated** resource for the
DB-side surface (per W11-A's ``hallucinote://song/<slug>/...``
hierarchy in ``project-state.yaml``). Templates are addressed via
``{slug}`` placeholders and live in a separate ``RESOURCE_TEMPLATE_URIS``
tuple, mirrored by ``registered_resource_template_uris`` on the
server module:
  - ``hallucinote://song/{slug}/annotations``

The registration happens in ``register_resources(mcp)`` called by
``server.create_server``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# Resource directory ships with the package; resolve relative to this file.
_RESOURCES_DIR = Path(__file__).resolve().parent
_GUIDES_DIR = _RESOURCES_DIR / "guides"
_REFERENCE_DIR = _RESOURCES_DIR / "reference"


# The full URI list — canonical M-6 surface. Locked by test
# (`test_resource_uri_list_matches_design`).
RESOURCE_URIS: tuple[str, ...] = (
    "ableton://session/snapshot",
    "ableton://browser/instruments",
    "ableton://browser/effects",
    "ableton://browser/drums",
    "ableton://plugins/installed",
    "ableton://reference/scales",
    "ableton://reference/device-params",
    "ableton://guides/getting-started",
    "ableton://guides/conventions",
    "ableton://guides/error-recovery",
    "ableton://guides/gaps",
)


# Templated URI list — addressed with ``{slug}`` placeholders so a single
# registration covers every song. First Arc 5 / P3 surface; future
# hallucinote:// per-song resources land here. Locked by
# `test_resource_template_uri_list_matches_design`.
RESOURCE_TEMPLATE_URIS: tuple[str, ...] = (
    "hallucinote://song/{slug}/annotations",
)


# ---------------------------------------------------------------------------
# Static loaders (no Live needed; read from package data dir)
# ---------------------------------------------------------------------------


def _read_guide(name: str) -> str:
    path = _GUIDES_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def _read_reference_json(name: str) -> str:
    """Return the reference JSON file contents as a string. Validated as
    parseable JSON at read time so a malformed file fails loud rather
    than shipping bad payload to the agent.
    """
    path = _REFERENCE_DIR / f"{name}.json"
    raw = path.read_text(encoding="utf-8")
    json.loads(raw)  # validation; discards
    return raw


# ---------------------------------------------------------------------------
# Live-backed loaders (delegate to handle_tool_call so the forward-to-
# Remote-Script path is reused)
# ---------------------------------------------------------------------------


def _session_snapshot() -> str:
    """Compose a session snapshot from three existing actions:
    ableton_session(info) + ableton_track(list) + ableton_return(list).

    The composition happens here (resource layer) rather than as a new
    `ableton_session(action='snapshot')` action because resources can
    fan-out into multiple handler calls without burning per-call agent
    turns. Note: the M-1 stubbed snapshot/revert actions are about
    save-point semantics (LiveContext §14.6 open question), not this
    state-snapshot read.
    """
    from ..server import handle_tool_call

    parts: dict[str, Any] = {}
    parts["session"] = handle_tool_call("ableton_session", "info", {})
    parts["tracks"] = handle_tool_call("ableton_track", "list", {})
    parts["returns"] = handle_tool_call("ableton_return", "list", {})
    return json.dumps(parts, indent=2)


def _browser_tree(root: str) -> str:
    """Read a browser tree via the existing ableton_browser action."""
    from ..server import handle_tool_call

    return json.dumps(
        handle_tool_call(
            "ableton_browser", "tree", {"root": root, "depth": 3},
        ),
        indent=2,
    )


def _plugins_installed() -> str:
    """Flat plugin list via ableton_browser(plugins_list)."""
    from ..server import handle_tool_call

    return json.dumps(
        handle_tool_call("ableton_browser", "plugins_list", {}),
        indent=2,
    )


# ---------------------------------------------------------------------------
# DB-backed templated resources (W11-A: ``hallucinote://song/<slug>/...``)
# ---------------------------------------------------------------------------


def _song_annotations(slug: str) -> str:
    """Composer-intent annotations for ``<slug>``, as JSON.

    Cheap-context companion to ``ableton_annotation(action='list',
    song_slug=...)`` — same Q.get_annotations_for_song read, surfaced
    as a templated resource so an LLM agent can fetch annotations
    without burning a tool-call turn before composing.

    Delegates to ``ableton_annotation.list_handler`` (whose ``_context``
    parameter is unused per its dispatcher-shape contract). Unknown slug
    surfaces the same teaching error the tool path raises, so failure
    modes are consistent across surfaces.
    """
    from ..handlers import ableton_annotation as ah

    result = ah.list_handler(None, song_slug=slug)  # type: ignore[arg-type]
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_resources(mcp: Any) -> None:
    """Wire all 11 resources onto a FastMCP instance.

    Called once at server boot from ``server.create_server``. Each
    resource's loader is a thin wrapper (most just delegate); the
    callable shape conforms to FastMCP's ``@mcp.resource()`` contract
    (no params, returns str / bytes / JSON-able).
    """

    # ---- Live-backed: session ----
    @mcp.resource(
        "ableton://session/snapshot",
        name="session_snapshot",
        description=(
            "Composed snapshot of the current Live session: global state "
            "(tempo, signature, transport, master), track list, return "
            "list. Loaded via 3 underlying tool calls; prefer this "
            "resource over calling them individually."
        ),
        mime_type="application/json",
    )
    def session_snapshot() -> str:
        return _session_snapshot()

    # ---- Live-backed: browser ----
    @mcp.resource(
        "ableton://browser/instruments",
        name="browser_instruments",
        description="Instruments tree (depth 3) from Live's browser.",
        mime_type="application/json",
    )
    def browser_instruments() -> str:
        return _browser_tree("instruments")

    @mcp.resource(
        "ableton://browser/effects",
        name="browser_effects",
        description=(
            "Effects tree (depth 3) — audio_effects root from Live's "
            "browser. MIDI effects live at a separate root; use "
            "ableton_browser(action='tree', root='midi_effects') for that."
        ),
        mime_type="application/json",
    )
    def browser_effects() -> str:
        return _browser_tree("audio_effects")

    @mcp.resource(
        "ableton://browser/drums",
        name="browser_drums",
        description="Drum kits / drum-rack content tree (depth 3).",
        mime_type="application/json",
    )
    def browser_drums() -> str:
        return _browser_tree("drums")

    @mcp.resource(
        "ableton://plugins/installed",
        name="plugins_installed",
        description=(
            "Flat list of installed VST/AU plugins (loadable nodes only). "
            "Loader equivalent to ableton_browser(action='plugins_list')."
        ),
        mime_type="application/json",
    )
    def plugins_installed() -> str:
        return _plugins_installed()

    # ---- Reference (static JSON) ----
    @mcp.resource(
        "ableton://reference/scales",
        name="reference_scales",
        description=(
            "Live's built-in scale dictionary: scale names + interval "
            "patterns (semitones from root) + root note names. Use to "
            "validate or pick a scale before generating notes."
        ),
        mime_type="application/json",
    )
    def reference_scales() -> str:
        return _read_reference_json("scales")

    @mcp.resource(
        "ableton://reference/device-params",
        name="reference_device_params",
        description=(
            "Parameter catalog by Live device class. Names match Live's "
            "exact strings — pass to ableton_device(action='set_parameter', "
            "parameter_name=...). Helps avoid invented parameter names."
        ),
        mime_type="application/json",
    )
    def reference_device_params() -> str:
        return _read_reference_json("device-params")

    # ---- Guides (static markdown) ----
    @mcp.resource(
        "ableton://guides/getting-started",
        name="guide_getting_started",
        description="First-steps orientation: the 11-tool surface and discovery patterns.",
        mime_type="text/markdown",
    )
    def guide_getting_started() -> str:
        return _read_guide("getting-started")

    @mcp.resource(
        "ableton://guides/conventions",
        name="guide_conventions",
        description=(
            "Addressing (1-based indices), time positions (beats not "
            "bars), value ranges, deliberate omissions."
        ),
        mime_type="text/markdown",
    )
    def guide_conventions() -> str:
        return _read_guide("conventions")

    @mcp.resource(
        "ableton://guides/error-recovery",
        name="guide_error_recovery",
        description="Common errors and the right fix for each.",
        mime_type="text/markdown",
    )
    def guide_error_recovery() -> str:
        return _read_guide("error-recovery")

    @mcp.resource(
        "ableton://guides/gaps",
        name="guide_gaps",
        description=(
            "Known gaps — what NOT to attempt today (gap #4 note ops, "
            "envelope reads, arrangement tempo automation, nested racks). "
            "Mirrors docs/mcp-requirements.md with current resolution "
            "status."
        ),
        mime_type="text/markdown",
    )
    def guide_gaps() -> str:
        return _read_guide("gaps")

    # ---- Templated DB-backed resources (W11-A introduction) ----
    @mcp.resource(
        "hallucinote://song/{slug}/annotations",
        name="song_annotations",
        description=(
            "Composer-intent annotations for the song identified by "
            "<slug>. Read-only mirror of "
            "ableton_annotation(action='list', song_slug=<slug>) "
            "exposed as a templated resource so agents can fetch "
            "annotations as a zero-turn-cost resource read before "
            "non-trivial composition. Unknown slug returns a teaching "
            "error matching the tool surface."
        ),
        mime_type="application/json",
    )
    def song_annotations(slug: str) -> str:
        return _song_annotations(slug)


__all__ = [
    "RESOURCE_URIS",
    "RESOURCE_TEMPLATE_URIS",
    "register_resources",
]
