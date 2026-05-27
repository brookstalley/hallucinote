"""FastMCP server — 12 unified tools + 12 resources (11 static + 1 templated) as MCP entry points.

Each ``@mcp.tool()`` is a thin wrapper that:
  1. Builds a ``wire.Request`` from its arguments.
  2. Runs the dispatcher locally for fast-fail validation (no Live needed).
  3. If validation passed and execution requires Live, forwards to the
     Remote Script over TCP via ``client.send``.
  4. Returns the structured response (success or teaching error) as a dict.

Wire shape: each tool's input schema is synthesized at registration time
from the registry — ``action`` plus the *flattened* union of every action's
params on that tool, all keyword-only and optional. That makes the wire
shape match the docs (``ableton_session(action='set_tempo', bpm=132.0)``)
and removes the agent-hostile ``params={...}`` envelope that pydantic's
``extra='ignore'`` silently demanded under the old ``(action, params)``
wrapper.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import inspect
import logging
import os
import pathlib
from typing import Annotated, Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import client, schema
from .dispatcher import dispatch
from .wire import Request


# Param.type → Python type used for FastMCP's pydantic-derived JSONSchema.
_PARAM_TYPE_MAP: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
}


def _annotated_param_type(spec: schema.ParamSpec) -> Any:
    """Translate a ``ParamSpec`` into ``Annotated[Optional[T], Field(...)]``
    so FastMCP's pydantic-derived JSONSchema carries ``description``,
    ``minimum`` / ``maximum``, and ``enum`` — not just the Python type.

    Agents that consult the wire schema can prune impossible calls earlier
    (e.g. ``cc_number`` 0–127 limits, the seven ``target_kind`` enums)
    instead of waiting for the dispatcher's teaching error. Dispatch-time
    validation is unchanged; this widens the discovery surface only.
    """
    py_type = _PARAM_TYPE_MAP.get(spec.type, Any)
    optional_type = Optional[py_type]

    field_kwargs: dict[str, Any] = {"default": None}
    if spec.description:
        field_kwargs["description"] = spec.description
    if spec.minimum is not None:
        field_kwargs["ge"] = spec.minimum
    if spec.maximum is not None:
        field_kwargs["le"] = spec.maximum
    if spec.enum:
        # ``enum`` lives in ``json_schema_extra`` rather than ``Literal[...]``:
        # the dispatcher (not the wire schema) is the source of truth for
        # rejection, and a runtime ``Literal`` would force callers to widen
        # to ``str`` anyway since the enum members are runtime data.
        field_kwargs["json_schema_extra"] = {"enum": list(spec.enum)}

    return Annotated[optional_type, Field(**field_kwargs)]


logger = logging.getLogger("hallucinote_mcp")


PRIMER = """\
hallucinote-mcp — 12 unified tools + 12 resources (11 static + 1 per-song template) for Ableton Live,
structured for low-context-cost agent interaction.

Tools (call action='help' on any tool for its action menu):
  ableton_session       global state, master, transport, view, tempo, signature
  ableton_track         tracks: lifecycle, mixer state, sends
  ableton_return        return tracks
  ableton_clip          session + arrangement clips, replace_notes
  ableton_note          per-note ops (gap #4 blocked — read ableton://guides/gaps)
  ableton_device        devices on tracks/returns; set_parameter handles enums
  ableton_automation    envelopes (7 target_kinds via write_envelope)
  ableton_arrangement   arrangement layout + cue points (beats not bars)
  ableton_scene         session-view scenes + per-scene tempo/signature
  ableton_browser       instruments, effects, plugins
  ableton_annotation    composer-intent annotations on a song's DB (W8-C surface)
  ableton_render        audio capture: HallucinoteAnalyzer auto-load + WAV capture pass

Resources (read via resources/read, no turn cost):
  ableton://session/snapshot          session+tracks+returns in one read
  ableton://browser/{instruments,effects,drums}  + ableton://plugins/installed
  ableton://reference/{scales,device-params}     static lookups
  ableton://guides/{getting-started,conventions,error-recovery,gaps}

Multi-step workflows live as Claude Code skills (.claude/skills/) — not
MCP prompts — so the agent can invoke them directly. Reach for:
  /song-new, /song-pick-instruments, /track-new-with-instrument,
  /return-new, /mix-sidechain, /clip-humanize, /pattern-compose.

Hard constraints:
  - 1-based indexing throughout (track_index >= 1).
  - Time positions on the wire are BEATS, not bars.
  - Note ops REPLACE the clip's full note array (no per-note addressing).
  - Quantize/swing/groove/humanize are NOT MCP actions — Hallucinote
    owns the math; push the result via replace_notes. See
    ableton://guides/gaps for the full DB-as-source-of-truth rationale.
"""


def create_server(name: str = "hallucinote-mcp") -> FastMCP:
    """Construct the FastMCP server with all 12 tools registered.

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

    # Wave M-6 + Arc 5 / P3: register 11 static resources (5 Live-backed +
    # 2 reference + 4 guides) and 1 per-song templated resource
    # (hallucinote://song/{slug}/annotations). Done before tool registration
    # so the resource URIs are visible to the client immediately on
    # initialize.
    from .resources import register_resources
    register_resources(mcp)

    # Define the unified tool entry points. Each is a thin wrapper around the
    # shared dispatcher; the wrapper exists only so FastMCP can register a
    # name + docstring for the MCP client to see.
    _register_tool(mcp, "ableton_session", "Global state, master, transport, view, tempo, signature, snapshot.")
    _register_tool(mcp, "ableton_track", "Tracks: lifecycle, mixer state, sends.")
    _register_tool(mcp, "ableton_return", "Return tracks: lifecycle, mixer state.")
    _register_tool(mcp, "ableton_clip", "Session + arrangement clips: lifecycle, set_property, replace_notes. Timing transforms (quantize/swing/groove) deliberately live in Hallucinote — see design doc §6.2.")
    _register_tool(mcp, "ableton_note", "Within-clip note operations (gap #4 blocked).")
    _register_tool(mcp, "ableton_device", "Devices on tracks/returns: load, parameters, routing.")
    _register_tool(mcp, "ableton_automation", "Envelopes across seven target families.")
    _register_tool(mcp, "ableton_arrangement", "Arrangement layout, cue points, loop region.")
    _register_tool(mcp, "ableton_scene", "Session-view scenes: clip-slot rows + tempo + signature.")
    _register_tool(mcp, "ableton_browser", "Instruments, effects, plugins; search and fetch.")
    _register_tool(mcp, "ableton_annotation", "Composer-intent annotations (W8-C): song/time/track-scoped composing notes attached to a song's DB. Distinct from the markdown decisions/annotations corpus surfaced via /song-context.")
    _register_tool(mcp, "ableton_render", "Audio capture pipeline. Auto-loads HallucinoteAnalyzer on every audio track + return + master (idempotent); render action plays the arrangement and writes per-surface WAVs + manifest.json to a captures dir. Consumed by Chunk 3's ableton_analysis.")

    return mcp


def handle_tool_call(
    tool: str,
    action: str,
    params: dict[str, Any] | None = None,
    *,
    allow_version_mismatch: bool = False,
) -> dict[str, Any]:
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

    ``allow_version_mismatch`` propagates to ``Request.allow_version_mismatch``
    and rides along to the Remote Script side as a per-call bypass of the
    strict version handshake. Default ``False`` preserves the strict
    behavior verbatim — the bypass is opt-in.
    """
    request = Request(
        tool=tool,
        action=action,
        params=params or {},
        allow_version_mismatch=allow_version_mismatch,
    )

    server_response = dispatch(request, context=None)

    if not server_response.needs_remote:
        return server_response.to_dict()

    # Server-side path resolution for ableton_render(render). The render
    # handler runs inside Live's process whose cwd is ``/`` (read-only on
    # macOS), so relative paths like ``songs/<slug>/captures/<ts>`` fail
    # with OSError. The MCP server's cwd IS the agent's repo root, so
    # resolve the default + any relative output_dir to absolute HERE
    # before forwarding.
    if request.tool == "ableton_render" and request.action == "render":
        request = _absolutize_render_output_dir(request)

    # Forward to the Remote Script. ableton_render(render) drives full-
    # arrangement playback before responding (minutes for a long song),
    # so disable the default 15s read timeout for that path. Every other
    # action returns within Live's main-thread budget — keep the bounded
    # default so a stalled handler surfaces as a structured timeout
    # error instead of hanging the MCP transport.
    read_timeout: float | None = 15.0
    if request.tool == "ableton_render" and request.action == "render":
        read_timeout = None
    try:
        remote_response = client.send(request, read_timeout=read_timeout)
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


def _absolutize_render_output_dir(request: Request) -> Request:
    """Resolve ``ableton_render(render)`` 's ``output_dir`` to an absolute
    path, computing the slug-derived default when missing.

    Why: the render handler runs on the Remote Script side (inside Live),
    whose cwd is ``/`` on macOS — a read-only filesystem. The handler's
    pre-existing default ``Path("songs") / slug / "captures" / ts`` is
    relative; resolved against Live's cwd it becomes ``/songs/...`` and
    ``mkdir(parents=True)`` raises ``OSError [Errno 30]``. The MCP server
    process IS in the agent's repo root, so we resolve here.

    Picking the timestamp here (rather than letting the handler do it)
    avoids time-of-check / time-of-use drift between the directory the
    server announces and the directory the handler creates.
    """
    params = dict(request.params)
    raw = params.get("output_dir")
    if isinstance(raw, str) and raw:
        resolved = pathlib.Path(raw)
        if not resolved.is_absolute():
            resolved = (pathlib.Path(os.getcwd()) / resolved).resolve()
        params["output_dir"] = str(resolved)
        return dataclasses.replace(request, params=params)
    # No explicit output_dir → compute the slug-derived default here,
    # absolute. song_slug is a required param; let the handler raise if
    # it's missing.
    song_slug = params.get("song_slug")
    if not isinstance(song_slug, str) or not song_slug:
        return request  # let the handler emit its own teaching error
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    default = pathlib.Path(os.getcwd()) / "songs" / song_slug / "captures" / ts
    params["output_dir"] = str(default.resolve())
    return dataclasses.replace(request, params=params)


def _collect_tool_params(tool_name: str) -> list[schema.ParamSpec]:
    """Union of every param across every action on this tool.

    Each unique param name appears once. Ordered alphabetically for
    deterministic schema generation (FastMCP/pydantic hashes the field
    order into the generated JSONSchema title — stability matters for
    snapshot tests and human review).

    If two actions on the same tool define a param with the same name
    but different ``type``, we widen by raising — callers should rename
    one of the params (no collisions exist today; the check is a
    guardrail against future divergence).
    """
    seen: dict[str, schema.ParamSpec] = {}
    for action in schema.actions_for(tool_name):
        if action.name == "help":
            continue
        for spec in action.params:
            existing = seen.get(spec.name)
            if existing is None:
                seen[spec.name] = spec
                continue
            if existing.type != spec.type:
                raise ValueError(
                    f"Param type conflict on {tool_name}: "
                    f"'{spec.name}' is {existing.type} in one action "
                    f"and {spec.type} in another — rename one to avoid "
                    f"a flat-schema collision."
                )
    return [seen[name] for name in sorted(seen)]


def _register_tool(mcp: FastMCP, tool_name: str, summary: str) -> None:
    """Register one of the unified tools on the FastMCP instance.

    The wrapper exposes a *flat* signature: ``(action, **params)`` where each
    param across every action on this tool becomes a keyword-only argument
    (all optional, since they're action-specific). FastMCP introspects the
    signature to build the tool's JSONSchema, so the wire shape Claude Code
    sees matches every example string (``ableton_session(action='set_tempo',
    bpm=132.0)``).

    Per-action validation still happens inside the dispatcher — this wrapper
    only widens the wire surface. Unknown params on a given action surface
    as the dispatcher's existing teaching error.
    """
    params = _collect_tool_params(tool_name)

    sig_params = [
        inspect.Parameter(
            "action",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=str,
        )
    ]
    annotations: dict[str, Any] = {"action": str, "return": dict}
    for spec in params:
        annotated = _annotated_param_type(spec)
        sig_params.append(
            inspect.Parameter(
                spec.name,
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=annotated,
            )
        )
        annotations[spec.name] = annotated

    # Envelope-level escape hatch: per-call bypass of the strict
    # server/Remote-Script version handshake. Injected as a synthetic
    # kwarg on every tool's signature so agents can reach it without
    # each action's schema needing to know about it. The wrapper pops
    # it before the dispatcher sees `params`, so action-level validation
    # never rejects it as "unknown param."
    sig_params.append(
        inspect.Parameter(
            "allow_version_mismatch",
            inspect.Parameter.KEYWORD_ONLY,
            default=None,
            annotation=Optional[bool],
        )
    )
    annotations["allow_version_mismatch"] = Optional[bool]

    def wrapper(**kwargs: Any) -> dict[str, Any]:
        action = kwargs.pop("action")
        allow_version_mismatch = bool(kwargs.pop("allow_version_mismatch", None) or False)
        # Drop None-valued kwargs — they represent "not supplied" by the
        # MCP client. Real None payloads aren't a thing in our action
        # surface (the dispatcher validates required fields below).
        passed = {k: v for k, v in kwargs.items() if v is not None}
        return handle_tool_call(
            tool_name, action, passed, allow_version_mismatch=allow_version_mismatch
        )

    wrapper.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        sig_params, return_annotation=dict
    )
    wrapper.__annotations__ = annotations
    wrapper.__name__ = tool_name
    wrapper.__doc__ = (
        f"{summary}\n\n"
        f"All operations dispatch on `action` (string). Use "
        f"`{tool_name}(action='help')` to see the full action menu with "
        f"required/optional params, examples, and tips."
    )

    mcp.tool(name=tool_name, description=wrapper.__doc__)(wrapper)


def registered_resource_uris(mcp: FastMCP) -> list[str]:
    """Return the URIs of all resources registered on the FastMCP instance.

    Symmetric to ``registered_tool_names`` but introspects the resource
    manager. Used by tests to assert "the 11 expected URIs are wired."
    """
    for attr in ("_resource_manager", "resource_manager"):
        manager = getattr(mcp, attr, None)
        if manager is None:
            continue
        for store_attr in ("_resources", "resources"):
            store = getattr(manager, store_attr, None)
            if isinstance(store, dict):
                # Each value may be a Resource object with `.uri`; keys
                # may be either URIs or names depending on FastMCP version.
                uris: list[str] = []
                for k, v in store.items():
                    uri = getattr(v, "uri", None) if v is not None else None
                    uris.append(str(uri) if uri is not None else str(k))
                return sorted(uris)
    raise RuntimeError(
        "Could not introspect FastMCP resource registry — FastMCP API may "
        "have changed"
    )


def registered_resource_template_uris(mcp: FastMCP) -> list[str]:
    """Return the URI templates of all templated resources on FastMCP.

    Templated resources can't be enumerated by concrete URI alone — the
    ``{slug}``-style placeholders stay unresolved until a client reads
    them with a binding. This helper returns the registered templates
    themselves so tests can assert "the W11-A surface is wired."

    Arc 5 / P3: first user. Future per-song hallucinote:// resources
    will surface here too.
    """
    for attr in ("_resource_manager", "resource_manager"):
        manager = getattr(mcp, attr, None)
        if manager is None:
            continue
        for store_attr in ("_templates", "templates"):
            store = getattr(manager, store_attr, None)
            if isinstance(store, dict):
                templates: list[str] = []
                for k, v in store.items():
                    template = (
                        getattr(v, "uri_template", None) if v is not None else None
                    )
                    templates.append(
                        str(template) if template is not None else str(k)
                    )
                return sorted(templates)
    raise RuntimeError(
        "Could not introspect FastMCP resource-template registry — "
        "FastMCP API may have changed"
    )


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
    "registered_resource_uris",
    "registered_resource_template_uris",
]
