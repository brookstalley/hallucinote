"""FastMCP server — 13 unified tools + 13 resources (all static) as MCP entry points.

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
import functools
import inspect
import logging
import os
import pathlib
from typing import Annotated, Any, Optional

import anyio
from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import client, schema
from .dispatcher import dispatch
from .wire import Request


# Param.type → Python type used for FastMCP's pydantic-derived JSONSchema.
_PARAM_TYPE_MAP: dict[str, Any] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "any": Any,  # polymorphic params (ableton_probe set's value)
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
    optional_type = Optional[py_type]  # type: ignore[valid-type]  # dynamic by design

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
hallucinote-mcp — 13 unified tools + 13 resources (all static) for Ableton Live,
structured for low-context-cost agent interaction.

Tools (call action='help' on any tool for its action menu):
  ableton_session       global state, master, transport, view, tempo, signature
  ableton_track         tracks: lifecycle, mixer state, sends, routing, monitor state
  ableton_return        return tracks
  ableton_clip          session + arrangement clips, replace_notes
  ableton_note          per-note ops (gap #4 blocked — read ableton://guides/gaps)
  ableton_device        devices on tracks/returns; set_parameter handles enums
  ableton_automation    envelopes (7 target_kinds via write_envelope)
  ableton_arrangement   arrangement layout + cue points (beats not bars)
  ableton_scene         session-view scenes + per-scene tempo/signature
  ableton_browser       instruments, effects, plugins
  ableton_render        audio capture: HallucinoteAnalyzer auto-load + WAV capture pass
  ableton_analysis      MixReport from a captures dir (loudness, master attribution, reverb verification)
  ableton_probe         LOM introspection: describe/get/set/call(+then) on a constrained path grammar

Resources (read via resources/read, no turn cost):
  ableton://session/snapshot          session+tracks+returns in one read
  ableton://browser/{instruments,effects,drums}  + ableton://plugins/installed
  ableton://reference/{scales,device-params}     static lookups
  ableton://reference/node-feature-matrix        feature × node-kind support (read before authoring)
  ableton://guides/{getting-started,conventions,error-recovery,gaps}
  ableton://server/info               running server version + package_root (install)

Multi-step workflows live as Claude Code skills (skills/) — not
MCP prompts — so the agent can invoke them directly. For ANY song
work, read /song-workflow first — it is the lifecycle map. The arc:
  /song-new -> /song-pick-instruments -> /compose-part ->
  /compose-review (READ the composition) -> /ableton-push ->
  /render-analyze (render+analyze in one step, poll loops kept out of context) ->
  /mix-review (READ the mix; needs Max for Live) ->
  /song-snapshot, then loop. Building blocks: /track-new-with-instrument,
  /return-new, /mix-sidechain, /clip-humanize, /ableton-pull, /song-context.
  The two review checkpoints (/compose-review, /mix-review) are easy to
  skip and shouldn't be — they apply the framework's ear to your work.

Hard constraints:
  - 1-based indexing throughout (track_index >= 1).
  - Time positions on the wire are BEATS, not bars.
  - Note ops REPLACE the clip's full note array (no per-note addressing).
  - Quantize/swing/groove/humanize are NOT MCP actions — Hallucinote
    owns the math; push the result via replace_notes. See
    ableton://guides/gaps for the full DB-as-source-of-truth rationale.
"""


def create_server(name: str = "hallucinote-mcp") -> FastMCP:
    """Construct the FastMCP server with all 13 tools registered.

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

    # Wave M-6 + Arc 5 / P3: register 13 static resources (5 Live-backed +
    # 3 reference + 4 guides + 1 server self-report, INS-3W8P). Done before tool registration
    # so the resource URIs are visible to the client immediately on
    # initialize.
    from .resources import register_resources
    register_resources(mcp)

    # Define the unified tool entry points. Each is a thin wrapper around the
    # shared dispatcher; the wrapper exists only so FastMCP can register a
    # name + docstring for the MCP client to see.
    _register_tool(mcp, "ableton_session", "Global state, master, transport, view, tempo, signature, snapshot.")
    _register_tool(mcp, "ableton_track", "Tracks: lifecycle, mixer state, sends, input/output routing, monitor state.")
    _register_tool(mcp, "ableton_return", "Return tracks: lifecycle, mixer state.")
    _register_tool(mcp, "ableton_clip", "Session + arrangement clips: lifecycle, set_property, replace_notes. Timing transforms (quantize/swing/groove) deliberately live in Hallucinote — see design doc §6.2.")
    _register_tool(mcp, "ableton_note", "Within-clip note operations (gap #4 blocked).")
    _register_tool(mcp, "ableton_device", "Devices on tracks/returns: load, parameters, routing.")
    _register_tool(mcp, "ableton_automation", "Envelopes across seven target families.")
    _register_tool(mcp, "ableton_arrangement", "Arrangement layout, cue points, loop region.")
    _register_tool(mcp, "ableton_scene", "Session-view scenes: clip-slot rows + tempo + signature.")
    _register_tool(mcp, "ableton_browser", "Instruments, effects, plugins; search and fetch.")
    _register_tool(mcp, "ableton_render", "Audio capture pipeline. Auto-loads HallucinoteAnalyzer on every audio track + return AND the master (idempotent; DEV-6M2K re-enabled master device load on Live 12.4.2 — no hand-placement step). The start action backgrounds a render (the synchronous 'render' action was retired) — it plays the arrangement and writes per-surface WAVs + manifest.json to a captures dir; poll status to completion. Consumed by ableton_analysis.")
    _register_tool(mcp, "ableton_analysis", "Audio analysis pipeline. Consumes a captures dir written by ableton_render: per-stem loudness (LUFS-I/S/M + true peak), master-bus overshoot detection + per-band per-stem contribution attribution, per-return reverb RT60 measured from each return's captured ring-out (dry-source-free), and realized-vs-declared automation verification (device-parameter timbre flips, dynamic sends). Writes a MixReport JSON to songs/<slug>/analysis/.")
    _register_tool(mcp, "ableton_probe", "LOM capability probing: describe (class/properties/methods with signature docstrings), get (one property), set (write one property — settability is itself a finding), call (invoke a method, 'then' chains onto returned objects; can mutate — probe in scratch sets). Constrained path grammar: 'song'/'application' roots + '.attr'/'[index]' steps only.")

    return mcp


# Read-timeout policy lives in ``client`` — the single source of truth shared by
# this agent-forward route AND push_cli's direct dispatch (the ENV-9P4T blocker
# was the policy existing only here while the push route used the bare client
# default). We consume the resolver for the explicit pass below; ``client.send``
# also auto-resolves it when no read_timeout is passed, so the explicit pass is
# belt-and-suspenders, not the only guard. (The private timeout CONSTANTS are not
# re-exported here — tests assert the policy through ``client.read_timeout_for``,
# ENV-8K2R #6.)
from .client import read_timeout_for as _read_timeout_for  # noqa: E402


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

    # Server-side path resolution for ableton_render(start). The render worker
    # runs inside Live's process whose cwd is ``/`` (read-only on macOS), so
    # relative paths like ``songs/<slug>/captures/<ts>`` fail with OSError. The
    # MCP server's cwd IS the agent's repo root, so resolve the default + any
    # relative output_dir to absolute HERE before forwarding. (``start`` is the
    # only render entry now — the synchronous ``render`` action was retired,
    # MCP-9R3T; it took the same output_dir/db_seq preprocessing.)
    if request.tool == "ableton_render" and request.action == "start":
        request = _absolutize_render_output_dir(request)
        request = _attach_render_db_seq(request)
        _sweep_stale_takes(request)

    # Forward to the Remote Script with a per-action read-timeout (MCP-4T6Y):
    # render is unbounded (full-arrangement playback), ensure_loaded gets a
    # generous bounded window (25+ analyzer loads), everything else keeps the
    # default so a stalled handler surfaces as a structured timeout instead of
    # hanging the transport.
    read_timeout = _read_timeout_for(request.tool, request.action)
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

    return _refine_version_mismatch(remote_response).to_dict()


def _refine_version_mismatch(response: "client.Response") -> "client.Response":
    """Refine a Remote-Script version-mismatch refusal with the server side's
    own staleness diagnosis.

    The Remote Script can only guess "re-vendor"; the server side can check
    whether its *own process* is the stale half (running code vs. on-disk
    source) — the case the generic hint misdiagnoses. When it is, swap in the
    "respawn the server" remediation; otherwise leave the refusal untouched.
    """
    from . import stale_server_process_hint
    from .wire import VERSION_MISMATCH_CODE

    if response.code != VERSION_MISMATCH_CODE:
        return response
    hint = stale_server_process_hint()
    if hint is None:
        return response
    return dataclasses.replace(response, hint=hint)


def _absolutize_render_output_dir(request: Request) -> Request:
    """Resolve ``ableton_render(start)`` 's ``output_dir`` to an absolute
    path, computing the slug-derived default when missing.

    Why: the render handler runs on the Remote Script side (inside Live),
    whose cwd is ``/`` on macOS — a read-only filesystem. A relative default
    resolved against Live's cwd becomes ``/songs/...`` and
    ``mkdir(parents=True)`` raises ``OSError [Errno 30]``. The MCP server
    process can see the song, so we resolve the song dir via the project-root
    contract (``resolve_song_dir``; WSP-1K4D) and absolutize HERE — captures
    land in the song's own repo whatever the server's cwd. Falls back to the
    legacy cwd-relative ``songs/<slug>`` when the engine isn't importable.

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
    # Resolve the song dir via the project-root contract (WSP-1K4D) so captures
    # land in the song's OWN repo regardless of the server's cwd — a song may
    # live in its own repo, not under the server's cwd. Falls back to the legacy
    # cwd-relative songs/<slug> when the engine isn't importable (e.g. a uvx
    # MCP-only install with no hallucinote engine present).
    try:
        from hallucinote.workspace import resolve_song_dir

        song_dir = resolve_song_dir(song_slug)
        if not song_dir.is_absolute():
            song_dir = pathlib.Path(os.getcwd()) / song_dir
    except ImportError:
        song_dir = pathlib.Path(os.getcwd()) / "songs" / song_slug
    default = song_dir / "captures" / ts
    params["output_dir"] = str(default.resolve())
    return dataclasses.replace(request, params=params)


def _attach_render_db_seq(request: Request) -> Request:
    """Tag the forwarded render call with the song's latest audit-log seq.

    The render handler runs inside Live's vendored env (no hallucinote
    package), so the seq is read HERE — the MCP server process has the
    engine — and forwarded as the ``db_seq`` param the handler writes
    into ``manifest.json``. Read at render-trigger time, which matches
    the audio ONLY when the DB state has been pushed to Live first (the
    normal flow). Mutate-without-push leaves the tag pointing at DB
    state the audio doesn't reflect — the seq is "latest DB state at
    render time", not a proof of what Live played; consumers comparing
    by seq inherit that caveat (it's surfaced in the analyze action's
    compare_to description).

    Degrades to no tag (``manifest.db_seq`` absent → loads as None) when
    the engine isn't importable, the song DB doesn't exist yet, or an
    explicit ``db_seq`` was already supplied — never blocks a render over
    provenance.
    """
    params = dict(request.params)
    if params.get("db_seq") is not None:
        return request
    song_slug = params.get("song_slug")
    if not isinstance(song_slug, str) or not song_slug:
        return request  # let the handler emit its own teaching error
    try:
        from hallucinote.db.connection import connect, resolve_db_path
        from hallucinote.db import queries as Q

        db_path = resolve_db_path(song_slug)
        if not db_path.exists():
            return request
        # Bare connect (not init_db) is deliberate here: this is a best-effort,
        # side-effect-free provenance read on the render path — it must not ALTER
        # the song's schema as a side effect of a render. It reads only `songs` +
        # `events` (no post-schema-bump columns), so the legacy-DB column crash
        # the sync CLIs guard against can't occur; and the surrounding try/except
        # degrades to no db_seq if the read fails for any other reason.
        conn = connect(db_path)
        try:
            song = Q.get_song_by_name(conn, song_slug)
            if song is None:
                return request
            seq = Q.get_latest_seq_for_song(conn, song["id"])
        finally:
            conn.close()
    except Exception:  # prawduct:allow prawduct/broad-except -- provenance is best-effort; a render must never fail because the seq read did
        logger.warning(
            "render: could not read latest db seq for %r; manifest will "
            "carry no db_seq", song_slug, exc_info=True,
        )
        return request
    if seq is None:
        return request
    params["db_seq"] = seq
    return dataclasses.replace(request, params=params)


def _sweep_stale_takes(request: Request) -> None:
    """Apply the capture-retention window before this render writes a new take.

    Renders are 48 kHz / stereo / 32-bit float across every track, return and
    the master — ~23 MB per surface-minute, so a full-length multi-track song
    costs gigabytes per take. Nothing else deletes them, so without this the
    song's ``captures/`` grows without bound. Retention runs HERE, at render
    start, because it is the one moment no take is in flight: the job registry
    allows one render at a time, so the sweep cannot race a capture, and a take
    the operator may still want to re-analyze survives until the window moves.

    Scope is deliberately the song's OWN captures root — never the parent of a
    caller-supplied ``output_dir``. A caller may point a render anywhere; deriving
    the sweep target from that path would let an unrelated directory be swept.
    The dir this render is about to write is protected explicitly, so a rerun
    into an existing timestamp can't delete itself.

    Best-effort and never render-affecting: disk hygiene must not cost a
    capture, so any failure logs and lets the render proceed. Silently a no-op
    when the engine isn't importable (a uvx MCP-only install), mirroring
    ``_absolutize_render_output_dir``'s fallback.
    """
    try:
        from hallucinote.takes import (
            execute_sweep,
            format_bytes,
            keep_from_env,
            plan_sweep,
            sweep_enabled,
        )
        from hallucinote.workspace import resolve_song_dir
    except ImportError:
        return

    song_slug = request.params.get("song_slug")
    if not isinstance(song_slug, str) or not song_slug:
        return
    if not sweep_enabled():
        return

    try:
        song_dir = resolve_song_dir(song_slug)
        if not song_dir.is_absolute():
            song_dir = pathlib.Path(os.getcwd()) / song_dir
        captures_root = song_dir / "captures"

        protect: list[pathlib.Path] = []
        outgoing = request.params.get("output_dir")
        if isinstance(outgoing, str) and outgoing:
            protect.append(pathlib.Path(outgoing))

        plan = plan_sweep(captures_root, keep=keep_from_env(), protect=protect)
        if not plan.sweep:
            return
        result = execute_sweep(plan)
        if result.removed:
            logger.info(
                "render: swept %d stale capture take(s) for %r, freeing %s "
                "(keeping the newest %d; pin a take with a .pinned file to "
                "keep it permanently)",
                len(result.removed), song_slug,
                format_bytes(result.freed_bytes), plan.keep,
            )
        for path, err in result.failures:
            logger.warning("render: could not remove stale take %s: %s", path, err)
    except Exception:  # prawduct:allow prawduct/broad-except -- retention is best-effort disk hygiene; a render must never fail because the sweep did
        logger.warning(
            "render: capture retention sweep failed for %r; proceeding with "
            "the render (disk may keep growing)", song_slug, exc_info=True,
        )


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

    async def wrapper(**kwargs: Any) -> dict[str, Any]:
        action = kwargs.pop("action")
        allow_version_mismatch = bool(kwargs.pop("allow_version_mismatch", None) or False)
        # Drop None-valued kwargs — they represent "not supplied" by the
        # MCP client. Real None payloads aren't a thing in our action
        # surface (the dispatcher validates required fields below).
        passed = {k: v for k, v in kwargs.items() if v is not None}
        # Offload the SYNCHRONOUS, possibly long-BLOCKING dispatch onto a worker
        # thread so the MCP event loop stays free. handle_tool_call blocks for
        # the whole call: a `status` long-poll parks on threading.Event.wait /
        # a socket read for ~45-60s, and render/analyze are unbounded. FastMCP
        # runs a SYNC tool INLINE on the loop thread (mcp func_metadata:
        # `return fn(**args)` — verified, no internal to_thread), so a sync
        # wrapper would freeze the entire server (every other in-flight tool
        # call) for that window — violating "a concurrent call must not hang
        # behind a running job". FastMCP AWAITS an async tool, so offloading via
        # anyio.to_thread keeps the loop responsive while one call long-polls.
        # Concurrency is safe: client.send opens a fresh socket per call and
        # Live's run_on_main FIFO-serializes main-thread touches. (MCP-9R3T /
        # MCP-5N8K async render+analyze.)
        return await anyio.to_thread.run_sync(
            functools.partial(
                handle_tool_call,
                tool_name,
                action,
                passed,
                allow_version_mismatch=allow_version_mismatch,
            )
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
