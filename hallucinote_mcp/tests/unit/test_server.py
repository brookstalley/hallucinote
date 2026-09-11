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


def get_registered_tool(mcp, name):
    """Fetch a single registered FastMCP ``Tool`` by name for ``.run()``.

    Symmetric with the production ``registered_tool_names`` helper: FastMCP's
    instance attribute for the tool manager (and the manager's internal store)
    has drifted across versions, so the lookup is centralized here in ONE place
    rather than spread across the call sites. Prefers the manager's public
    ``get_tool(name)`` method when present, falling back to the private dict
    store only if the public accessor is gone — keeping the version-coupling in
    a single, easy-to-update helper.
    """
    for attr in ("_tool_manager", "tool_manager"):
        manager = getattr(mcp, attr, None)
        if manager is None:
            continue
        getter = getattr(manager, "get_tool", None)
        if callable(getter):
            tool = getter(name)
            if tool is not None:
                return tool
        for store_attr in ("_tools", "tools"):
            store = getattr(manager, store_attr, None)
            if isinstance(store, dict) and name in store:
                return store[name]
    raise RuntimeError(
        f"Could not fetch tool {name!r} from FastMCP registry — "
        "FastMCP API may have changed"
    )


def test_create_server_registers_all_tools():
    server = create_server()
    names = registered_tool_names(server)
    assert sorted(names) == sorted(schema.TOOLS)


def test_primer_mentions_each_tool():
    for tool in schema.TOOLS:
        assert tool in PRIMER, f"PRIMER missing {tool}"


def test_primer_tool_count_matches_actual_registry():
    """Pattern-sweep guard (Chunk 2 Critic): the PRIMER's tool count
    headline ("N unified tools") drifted from 11 to 12 when
    `ableton_render` landed. A future tool addition without a
    parallel PRIMER edit gets caught here — mirrors the existing
    `test_primer_resource_count_matches_actual_registry` guard so
    the resource-count regression doesn't recur as a tool-count
    regression."""
    import re

    match = re.search(r"(\d+) unified tools", PRIMER)
    assert match is not None, (
        "PRIMER must advertise the total tool count (substring "
        "'N unified tools') so clients see the surface size on initialize"
    )
    assert int(match.group(1)) == len(schema.TOOLS), (
        f"PRIMER claims {match.group(1)} unified tools but schema.TOOLS "
        f"has {len(schema.TOOLS)}. Update PRIMER in "
        "hallucinote_mcp/src/hallucinote_mcp/server.py."
    )


def test_readme_tool_count_matches_actual_registry():
    """Pattern-sweep guard (Chunk 2 Critic): the project README's
    headline tool count drifts when a new tool lands. Pinned the same
    way the resource counts are pinned. Tolerates either bare 'N
    unified Ableton tools' or 'N unified tools' phrasing."""
    import re
    from pathlib import Path

    readme = Path(__file__).resolve().parents[3] / "README.md"
    text = readme.read_text()
    match = re.search(r"(\d+) unified (?:Ableton )?tools", text)
    assert match is not None, (
        "project README must advertise the total tool count (substring "
        "'N unified tools' or 'N unified Ableton tools')"
    )
    assert int(match.group(1)) == len(schema.TOOLS), (
        f"README claims {match.group(1)} unified tools but schema.TOOLS "
        f"has {len(schema.TOOLS)}. Update README.md."
    )


def test_mcp_readme_tool_count_matches_actual_registry():
    """Sibling guard for the hallucinote_mcp/README.md headline."""
    import re
    from pathlib import Path

    readme = Path(__file__).resolve().parents[2] / "README.md"
    text = readme.read_text()
    match = re.search(r"(\d+) unified tools", text)
    assert match is not None, (
        "hallucinote_mcp/README.md must advertise the tool count"
    )
    assert int(match.group(1)) == len(schema.TOOLS), (
        f"hallucinote_mcp/README claims {match.group(1)} unified tools "
        f"but schema.TOOLS has {len(schema.TOOLS)}."
    )


def test_marketplace_manifest_tool_count_matches_actual_registry():
    """The plugin marketplace description is the tool count a user reads
    BEFORE installing — in the `/plugin install` dialog — and it was the
    one count no guard pinned. Its phrasing is 'N Ableton Live tools',
    which the sibling README regexes ('N unified tools') never matched,
    so the number could drift silently on the most public surface of all.
    """
    import json
    import re
    from pathlib import Path

    manifest = (
        Path(__file__).resolve().parents[3]
        / ".claude-plugin"
        / "marketplace.json"
    )
    description = json.loads(manifest.read_text())["plugins"][0]["description"]
    match = re.search(r"(\d+) Ableton Live tools", description)
    assert match is not None, (
        "marketplace.json's plugin description must advertise the tool "
        "count (substring 'N Ableton Live tools')"
    )
    assert int(match.group(1)) == len(schema.TOOLS), (
        f"marketplace.json claims {match.group(1)} Ableton Live tools but "
        f"schema.TOOLS has {len(schema.TOOLS)}. Update "
        f".claude-plugin/marketplace.json — it is what the install dialog shows."
    )


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


def _register_set_tempo(isolated_registry):
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


def test_version_mismatch_refusal_refined_to_stale_server_hint(isolated_registry):
    """A version-mismatch refusal whose ``code`` marks it as the handshake
    error gets its hint rewritten when the server's OWN process is the stale
    half — running fingerprint != on-disk fingerprint (MCP-8H4N)."""
    from hallucinote_mcp.wire import Response, VERSION_MISMATCH_CODE

    _register_set_tempo(isolated_registry)
    refusal = Response(
        ok=False,
        error="Hallucinote MCP version mismatch: server reports X, RS is Y.",
        hint="If the Remote Script side is stale: run /ableton-mcp-install ...",
        code=VERSION_MISMATCH_CODE,
    )
    # Force the on-disk recompute to differ from the running __version__, i.e.
    # the package changed under a still-running server process.
    with patch(
        "hallucinote_mcp.server.client.send", return_value=refusal
    ), patch(
        "hallucinote_mcp._compute_content_fingerprint", return_value="0000deadbeef"
    ):
        response = handle_tool_call("ableton_session", "set_tempo", {"value": 132.0})

    assert response["ok"] is False
    # The real fix (respawn the server) is prescribed...
    assert "/mcp" in response["hint"]
    # ...and re-vendoring is explicitly dismissed, not prescribed as the fix.
    assert "will NOT help" in response["hint"]
    # The machine code is preserved for any downstream consumer.
    assert response["code"] == VERSION_MISMATCH_CODE


def test_version_mismatch_refusal_kept_when_server_process_current(isolated_registry):
    """When the server process is current (running fp == on-disk fp), the
    refusal's original re-vendor hint is preserved — the override fires only
    when the server side is genuinely the stale half."""
    from hallucinote_mcp.wire import Response, VERSION_MISMATCH_CODE

    _register_set_tempo(isolated_registry)
    original_hint = "If the Remote Script side is stale: run /ableton-mcp-install ..."
    refusal = Response(
        ok=False,
        error="Hallucinote MCP version mismatch: server reports X, RS is Y.",
        hint=original_hint,
        code=VERSION_MISMATCH_CODE,
    )
    # No fingerprint patch: import-time __version__ == fresh recompute, so the
    # server process is NOT stale and the hint must pass through untouched.
    with patch("hallucinote_mcp.server.client.send", return_value=refusal):
        response = handle_tool_call("ableton_session", "set_tempo", {"value": 132.0})

    assert response["hint"] == original_hint


def test_non_version_error_is_not_refined(isolated_registry):
    """An ordinary (non-handshake) error must pass through untouched even when
    the server process happens to be stale — the override keys on ``code``."""
    from hallucinote_mcp.wire import Response

    _register_set_tempo(isolated_registry)
    refusal = Response(ok=False, error="Track index out of range.", hint="check index")
    with patch(
        "hallucinote_mcp.server.client.send", return_value=refusal
    ), patch(
        "hallucinote_mcp._compute_content_fingerprint", return_value="0000deadbeef"
    ):
        response = handle_tool_call("ableton_session", "set_tempo", {"value": 132.0})

    assert response["hint"] == "check index"


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
# Server-side path resolution for ableton_render(start).
#
# The render worker runs inside Live's process (cwd = "/" on macOS,
# read-only). A relative output_dir like "songs/<slug>/captures/<ts>"
# resolves against Live's cwd and the mkdir raises OSError [Errno 30].
# handle_tool_call must absolutize the path BEFORE forwarding so the
# Remote Script sees only absolute paths. (The synchronous `render` action
# this preprocessing once served was retired — `start` is the entry now.)
# ---------------------------------------------------------------------------


def _existing_song_dir(tmp_path, slug: str = "demo"):
    """Make ``<tmp>/songs/<slug>/`` real before a default-destination render.

    ``_refuse_render_into_phantom_song_dir`` refuses to fill a slug-derived
    default that resolves to a directory that doesn't exist — the seatbelt that
    stopped a misresolved render from parking gigabytes of WAVs in an invented
    ``songs/<slug>/``. Tests about absolutization, timeouts or the retention
    sweep aren't about that guard, so they state the precondition every real
    render has: the song they're rendering exists.
    """
    song_dir = tmp_path / "songs" / slug
    song_dir.mkdir(parents=True, exist_ok=True)
    return song_dir


def test_start_call_absolutizes_relative_output_dir_before_forward(
    tmp_path, monkeypatch,
):
    """A relative output_dir gets absolutized against the MCP server's
    cwd (the agent's repo root). The wire request the Remote Script
    receives carries the absolute path."""
    from hallucinote_mcp.wire import Response

    monkeypatch.chdir(tmp_path)

    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call(
            "ableton_render",
            "start",
            {"song_slug": "demo", "output_dir": "songs/demo/captures/x"},
        )
    forwarded_request = send.call_args.args[0]
    output_dir = forwarded_request.params["output_dir"]
    # Absolute and rooted in the server's cwd (tmp_path). Real and
    # resolved tmp_path can differ on macOS (/var ↔ /private/var) — use
    # resolve() to compare canonical paths.
    import pathlib
    resolved_tmp = pathlib.Path(tmp_path).resolve()
    assert pathlib.Path(output_dir).is_absolute()
    assert pathlib.Path(output_dir).is_relative_to(resolved_tmp), (
        f"expected output_dir to be under {resolved_tmp}, got {output_dir}"
    )
    assert output_dir.endswith("songs/demo/captures/x")


def test_start_call_computes_default_output_dir_when_missing(
    tmp_path, monkeypatch,
):
    """When output_dir is omitted, the server fills in
    ``<cwd>/songs/<slug>/captures/<utc-ts>/`` so the Remote Script
    never sees a relative path."""
    import re
    import pathlib
    from hallucinote_mcp.wire import Response

    monkeypatch.chdir(tmp_path)
    _existing_song_dir(tmp_path)

    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call("ableton_render", "start", {"song_slug": "demo"})
    forwarded_request = send.call_args.args[0]
    output_dir = forwarded_request.params.get("output_dir")
    assert output_dir is not None, (
        "server must populate output_dir before forwarding so the "
        "Remote Script doesn't resolve relative paths against Live's "
        "read-only cwd"
    )
    resolved_tmp = pathlib.Path(tmp_path).resolve()
    assert pathlib.Path(output_dir).is_relative_to(resolved_tmp)
    # Shape: <cwd>/songs/demo/captures/YYYYMMDDTHHMMSSZ
    assert re.search(r"/songs/demo/captures/\d{8}T\d{6}Z$", output_dir), (
        f"unexpected default shape: {output_dir}"
    )


def test_start_call_passes_through_absolute_output_dir(
    tmp_path, monkeypatch,
):
    """An already-absolute output_dir is passed through unchanged."""
    from hallucinote_mcp.wire import Response

    monkeypatch.chdir(tmp_path)
    absolute_dir = str(tmp_path / "custom" / "captures")

    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call(
            "ableton_render", "start",
            {"song_slug": "demo", "output_dir": absolute_dir},
        )
    forwarded_request = send.call_args.args[0]
    assert forwarded_request.params["output_dir"] == absolute_dir


def test_render_ensure_loaded_call_does_not_touch_output_dir(
    tmp_path, monkeypatch,
):
    """``ensure_loaded`` (the no-capture sweep) has no output_dir param,
    so the absolutize hook must not invent one."""
    from hallucinote_mcp.wire import Response

    monkeypatch.chdir(tmp_path)

    forwarded = Response(ok=True, result={"loaded_count": 0})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call("ableton_render", "ensure_loaded", {})
    forwarded_request = send.call_args.args[0]
    assert "output_dir" not in forwarded_request.params


# ---------------------------------------------------------------------------
# MCP-4T6Y: per-action socket read-timeout policy.
#
# The default 15s window fits actions that return within Live's main-thread
# budget. ableton_render(ensure_loaded) breaks it: it loads the analyzer onto
# 25+ surfaces and routinely outruns 15s while the work continues server-side —
# it needs a generous but bounded window so a genuinely-stuck load still
# surfaces as a timeout. (The synchronous `render` — formerly THE unbounded
# case — was retired; `start` returns fast so the default suits it. The
# remaining None entry is automation perform_batch, MCP-9R3T.)
# ---------------------------------------------------------------------------


# The POLICY VALUES (which (tool, action) → which timeout) are owned by
# ``client.read_timeout_for`` and tested in test_client.py
# (``test_read_timeout_for_*``). The server-specific property kept here is that
# ``handle_tool_call`` CONSULTS that policy and forwards its result to
# ``client.send`` — ENV-8K2R #6 dropped the private-constant re-exports from
# ``server`` that the old duplicate policy-value tests reached through, so this
# asserts against the public resolver rather than re-deriving the table.


@pytest.mark.parametrize(
    "tool, action, params",
    [
        ("ableton_render", "start", {"song_slug": "demo"}),   # returns fast → default
        ("ableton_automation", "perform_batch", {"arcs": []}),  # unbounded (None)
        ("ableton_render", "ensure_loaded", {}),              # generous bounded
        ("ableton_session", "set_tempo", {"bpm": 132.0}),     # default bounded
    ],
)
def test_handle_tool_call_forwards_policy_read_timeout(
    tool, action, params, tmp_path, monkeypatch,
):
    """The read_timeout ``handle_tool_call`` forwards to ``client.send`` is
    EXACTLY what the policy returns for that (tool, action) — pinning the wiring,
    not re-asserting the policy table. start forwards the bounded default (it
    returns immediately — the realtime render runs on the worker, MCP-9R3T);
    perform_batch forwards the unbounded ``None`` (a bounded socket timeout would
    sever its only verification); ensure_loaded forwards the generous window
    (MCP-4T6Y); a normal action forwards the bounded default."""
    from hallucinote_mcp import client
    from hallucinote_mcp.wire import Response

    monkeypatch.chdir(tmp_path)
    _existing_song_dir(tmp_path)
    forwarded = Response(ok=True, result={})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call(tool, action, params)
    assert send.call_args.kwargs["read_timeout"] == client.read_timeout_for(
        tool, action
    )


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


def test_input_schema_propagates_enum_min_max_description_from_paramspec():
    """ParamSpec carries ``enum`` / ``minimum`` / ``maximum`` / ``description``;
    the flat-wire schema must surface them so agents can prune impossible
    calls before dispatch instead of only after the teaching error.

    Three representative checks: ``bpm`` (numeric min+max+description),
    ``target_kind`` (string enum), ``cc_number`` (integer min+max).
    Dispatch-time validation is the source of truth; this test pins the
    discovery surface.
    """
    mcp = create_server()
    tools = asyncio.run(mcp.list_tools())
    by_name = {t.name: t for t in tools}

    # bpm — numeric range + description (lives on ableton_session.set_tempo)
    sess_props = by_name["ableton_session"].inputSchema["properties"]
    bpm = sess_props["bpm"]
    assert bpm.get("description") == "Tempo in BPM. Live's allowed range is 20-999."
    # pydantic v2 emits the constraint inside the ``anyOf`` branch that
    # carries the actual type, not on the top-level node — Optional[float]
    # widens to ``anyOf: [{type: number, ...}, {type: null}]``.
    branches = bpm["anyOf"]
    number_branch = next(b for b in branches if b.get("type") == "number")
    assert number_branch["minimum"] == 20.0
    assert number_branch["maximum"] == 999.0

    # target_kind — string enum (lives on ableton_automation.write_envelope)
    auto_props = by_name["ableton_automation"].inputSchema["properties"]
    target_kind = auto_props["target_kind"]
    assert set(target_kind["enum"]) == {
        "clip_cc",
        "clip_pitch_bend",
        "note_expression",
        "device_parameter",
        "mixer_volume",
        "mixer_pan",
        "send_level",
    }

    # cc_number — integer range (lives on ableton_automation.write_envelope)
    cc_number = auto_props["cc_number"]
    cc_branches = cc_number["anyOf"]
    int_branch = next(b for b in cc_branches if b.get("type") == "integer")
    assert int_branch["minimum"] == 0
    assert int_branch["maximum"] == 127


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
    runner = get_registered_tool(mcp, tool.name)

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
    runner = get_registered_tool(mcp, "ableton_session")

    forwarded = Response(ok=True, result={"song_time": 16.0})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        asyncio.run(runner.run({"action": "seek", "bar": 5}))
    forwarded_req = send.call_args.args[0]
    assert forwarded_req.params == {"bar": 5}, (
        f"Optional kwarg leak: forwarded params={forwarded_req.params}; "
        "expected just {'bar': 5} with no implicit beat=None."
    )


def test_tool_wrappers_are_async_to_keep_event_loop_free():
    """MCP-9R3T/MCP-5N8K dispatch fix. FastMCP runs a SYNC tool INLINE on the
    event loop but AWAITS an async one (mcp func_metadata: `return fn(**args)`
    vs `await fn(**args)`). Our dispatch can BLOCK for ~45-60s — a `status`
    long-poll parks on threading.Event.wait / a socket read — so a sync wrapper
    would freeze the whole server for that window. Every tool wrapper MUST be
    async (it offloads the sync dispatch via anyio.to_thread); guard against a
    regression to a plain `def wrapper`."""
    import inspect as _inspect

    mcp = create_server()
    for name in registered_tool_names(mcp):
        fn = get_registered_tool(mcp, name).fn
        assert _inspect.iscoroutinefunction(fn), (
            f"{name}'s tool wrapper is sync; a sync tool runs inline on the MCP "
            "event loop, so a status long-poll would freeze every concurrent call"
        )


def test_status_longpoll_does_not_block_concurrent_tool_calls():
    """The load-bearing behavior of the dispatch fix: while one tool call
    long-polls (blocking off-thread), a concurrent call is still served.

    Seed a running analyze job, then fire a `status` long-poll (it blocks until
    the job finishes) AND a quick `help` call concurrently; a finisher marks the
    job done after a delay. With the async wrapper + anyio.to_thread the loop
    stays free, so `help` completes DURING the long-poll. With a sync wrapper the
    long-poll would run inline and `help` could not be served until it returned —
    the order would invert. We assert `help` finishes before `status`.
    """
    import anyio

    from hallucinote_mcp.handlers.jobs import default_registry

    mcp = create_server()
    analysis = get_registered_tool(mcp, "ableton_analysis")
    reg = default_registry()
    job = reg.create(kind="analyze", detail={"report_dir": "/tmp/x"})  # running; won't self-finish
    order: list[str] = []

    async def main():
        async def poll():
            # default long-poll is 45s; the finisher releases it at ~0.6s
            await analysis.run({"action": "status", "job_id": job.job_id})
            order.append("status")

        async def quick():
            await anyio.sleep(0.1)  # ensure `poll` is in its blocking wait first
            await analysis.run({"action": "help"})
            order.append("help")

        async def finish():
            await anyio.sleep(0.6)  # well after `quick` would complete if served
            reg.mark_done(job.job_id, {"report": {}, "report_path": None})

        async with anyio.create_task_group() as tg:
            tg.start_soon(poll)
            tg.start_soon(quick)
            tg.start_soon(finish)

    try:
        anyio.run(main)
        assert order == ["help", "status"], (
            f"help must be served during the status long-poll; got {order}. "
            "An inverted order means the long-poll froze the event loop "
            "(regression to a synchronous tool wrapper)."
        )
    finally:
        # The job lives in the process-default registry — clear it so the
        # leftover doesn't colour another test's recent-jobs error message.
        reg._jobs.clear()  # noqa: SLF001 - test cleanup of the singleton
        reg._order.clear()  # noqa: SLF001


def test_help_action_works_via_fastmcp_with_no_kwargs():
    """The most common discovery call — ``action='help'`` with no other args
    — must succeed end-to-end through the FastMCP wrapper.
    """
    mcp = create_server()
    runner = get_registered_tool(mcp, "ableton_session")

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


def test_start_call_attaches_db_seq_from_song_db(tmp_path, monkeypatch):
    """AUD-4W7K: the server reads the song's latest audit-log seq at
    forward time and attaches it as db_seq — the render handler (inside
    Live's hallucinote-less env) just writes it into the manifest."""
    from hallucinote.db import mutations as M
    from hallucinote.db import queries as Q
    from hallucinote.db.connection import init_db
    from hallucinote_mcp.wire import Response

    db_path = tmp_path / "songs" / "demo" / "demo.db"
    db_path.parent.mkdir(parents=True)
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO songs (id, name) VALUES (?, ?)", ("song-demo", "demo"),
    )
    M.create_track(conn, song_id="song-demo", track_index=1, name="Drums")
    expected_seq = Q.get_latest_seq_for_song(conn, "song-demo")
    conn.commit()
    conn.close()
    assert expected_seq is not None  # the mutator emitted an event

    monkeypatch.setattr(
        "hallucinote.db.connection.resolve_db_path",
        lambda slug, **_: tmp_path / "songs" / slug / f"{slug}.db",
    )

    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call(
            "ableton_render", "start",
            {"song_slug": "demo", "output_dir": str(tmp_path / "captures")},
        )
    forwarded_request = send.call_args.args[0]
    assert forwarded_request.params["db_seq"] == expected_seq


def test_start_call_omits_db_seq_when_song_db_missing(tmp_path, monkeypatch):
    """Provenance is best-effort: no song DB → the param simply isn't
    attached (manifest.db_seq null); the render itself proceeds."""
    from hallucinote_mcp.wire import Response

    monkeypatch.setattr(
        "hallucinote.db.connection.resolve_db_path",
        lambda slug, **_: tmp_path / "songs" / slug / f"{slug}.db",
    )

    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call(
            "ableton_render", "start",
            {"song_slug": "nope", "output_dir": str(tmp_path / "captures")},
        )
    forwarded_request = send.call_args.args[0]
    assert "db_seq" not in forwarded_request.params


def test_start_call_respects_explicit_db_seq(tmp_path, monkeypatch):
    """An explicitly-supplied db_seq is passed through untouched — the
    server only fills the gap, it never overrides the caller."""
    from hallucinote_mcp.wire import Response

    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call(
            "ableton_render", "start",
            {"song_slug": "demo", "output_dir": str(tmp_path), "db_seq": 99},
        )
    assert send.call_args.args[0].params["db_seq"] == 99


def test_start_call_omits_db_seq_when_song_row_missing(tmp_path, monkeypatch):
    """A DB that exists but has no row for the slug degrades to no tag
    (the get_song_by_name -> None branch), never an error."""
    from hallucinote.db.connection import init_db
    from hallucinote_mcp.wire import Response

    db_path = tmp_path / "songs" / "demo" / "demo.db"
    db_path.parent.mkdir(parents=True)
    conn = init_db(db_path)
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "hallucinote.db.connection.resolve_db_path",
        lambda slug, **_: tmp_path / "songs" / slug / f"{slug}.db",
    )

    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call(
            "ableton_render", "start",
            {"song_slug": "demo", "output_dir": str(tmp_path / "captures")},
        )
    assert "db_seq" not in send.call_args.args[0].params


def test_start_call_swallows_seq_read_errors(tmp_path, monkeypatch, caplog):
    """The waivered broad catch: a corrupt song DB logs a warning and
    degrades to no tag — a render is never blocked over provenance."""
    import logging
    from hallucinote_mcp.wire import Response

    db_path = tmp_path / "songs" / "demo" / "demo.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("not a sqlite database", encoding="utf-8")

    monkeypatch.setattr(
        "hallucinote.db.connection.resolve_db_path",
        lambda slug, **_: tmp_path / "songs" / slug / f"{slug}.db",
    )

    forwarded = Response(ok=True, result={"status": "ok"})
    with caplog.at_level(logging.WARNING):
        with patch(
            "hallucinote_mcp.server.client.send", return_value=forwarded
        ) as send:
            handle_tool_call(
                "ableton_render", "start",
                {"song_slug": "demo", "output_dir": str(tmp_path / "captures")},
            )
    assert "db_seq" not in send.call_args.args[0].params
    assert "could not read latest db seq" in caplog.text


def test_annotated_param_type_any_is_explicit_not_fallback():
    # 'any' must be a first-class _PARAM_TYPE_MAP entry; regressing to the
    # .get() fallback would silently re-annotate polymorphic params
    # (ableton_probe set's value) as bare `typing.Any`, which emits an empty
    # `{}` schema branch — a client then has no type to serialize a string
    # against and the payload dies in its own JSON parse. The entry must be a
    # union spelling out every JSON type.
    import typing

    from hallucinote_mcp.server import _PARAM_TYPE_MAP

    entry = _PARAM_TYPE_MAP["any"]
    assert entry is not typing.Any, (
        "'any' regressed to bare typing.Any — the emitted schema loses every "
        "type name"
    )
    assert typing.get_origin(entry) is typing.Union
    assert set(typing.get_args(entry)) == {
        bool, int, float, str, dict, list, type(None)
    }


# ---------------------------------------------------------------------------
# Capture retention on the render path.
#
# Renders write 32-bit-float WAVs per surface — gigabytes per take on a real
# song — and nothing else deletes them. handle_tool_call sweeps the song's
# captures root before forwarding a render, keeping the newest N takes. These
# tests pin what must survive: the incoming take, pinned takes, and (when the
# sweep fails outright) the render itself.
# ---------------------------------------------------------------------------


def _seed_take(captures_root, name, captured_at, *, pinned=False):
    """A take dir shaped like a real render's output."""
    import json
    take = captures_root / name
    take.mkdir(parents=True)
    (take / "manifest.json").write_text(
        json.dumps({"schema_version": "1", "captured_at": captured_at}),
        encoding="utf-8",
    )
    (take / "master.wav").write_bytes(b"\0" * 4096)
    if pinned:
        (take / ".pinned").write_text("", encoding="utf-8")
    return take


def _render_start(params):
    from hallucinote_mcp.wire import Response
    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call("ableton_render", "start", params)
    return send


def test_render_start_sweeps_stale_takes_keeping_the_newest_two(
    tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HALLUCINOTE_CAPTURE_KEEP", raising=False)
    monkeypatch.delenv("HALLUCINOTE_CAPTURE_SWEEP", raising=False)
    captures = tmp_path / "songs" / "demo" / "captures"
    for i in range(5):
        _seed_take(captures, f"take-{i}", f"2026060{i}T000000Z")

    _render_start({"song_slug": "demo"})

    survivors = sorted(p.name for p in captures.iterdir())
    # The two newest takes, plus the dir this render is about to write.
    assert "take-4" in survivors and "take-3" in survivors
    assert "take-0" not in survivors
    assert "take-1" not in survivors
    assert "take-2" not in survivors


def test_render_start_never_sweeps_the_dir_it_is_about_to_write(
    tmp_path, monkeypatch,
):
    """A rerun into an existing timestamp must not delete its own target."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HALLUCINOTE_CAPTURE_KEEP", raising=False)
    monkeypatch.setenv("HALLUCINOTE_CAPTURE_SWEEP", "1")
    captures = tmp_path / "songs" / "demo" / "captures"
    # The incoming dir already exists AND is the oldest, so a naive keep-2
    # sweep would delete it out from under the render.
    incoming = _seed_take(captures, "incoming", "20260101T000000Z")
    for i in range(3):
        _seed_take(captures, f"take-{i}", f"2026060{i}T000000Z")

    _render_start({"song_slug": "demo", "output_dir": str(incoming)})

    assert incoming.exists()


def test_render_start_keeps_pinned_takes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HALLUCINOTE_CAPTURE_KEEP", raising=False)
    monkeypatch.delenv("HALLUCINOTE_CAPTURE_SWEEP", raising=False)
    captures = tmp_path / "songs" / "demo" / "captures"
    _seed_take(captures, "reference", "20260101T000000Z", pinned=True)
    for i in range(4):
        _seed_take(captures, f"take-{i}", f"2026060{i}T000000Z")

    _render_start({"song_slug": "demo"})

    assert (captures / "reference").exists()


def test_render_start_sweep_respects_the_keep_env_var(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HALLUCINOTE_CAPTURE_KEEP", "1")
    monkeypatch.delenv("HALLUCINOTE_CAPTURE_SWEEP", raising=False)
    captures = tmp_path / "songs" / "demo" / "captures"
    for i in range(4):
        _seed_take(captures, f"take-{i}", f"2026060{i}T000000Z")

    _render_start({"song_slug": "demo"})

    survivors = {p.name for p in captures.iterdir() if p.name.startswith("take-")}
    assert survivors == {"take-3"}


def test_render_start_sweep_disabled_by_env_keeps_everything(
    tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HALLUCINOTE_CAPTURE_SWEEP", "0")
    captures = tmp_path / "songs" / "demo" / "captures"
    for i in range(5):
        _seed_take(captures, f"take-{i}", f"2026060{i}T000000Z")

    _render_start({"song_slug": "demo"})

    survivors = {p.name for p in captures.iterdir() if p.name.startswith("take-")}
    assert survivors == {f"take-{i}" for i in range(5)}


def test_render_proceeds_when_the_sweep_raises(tmp_path, monkeypatch, caplog):
    """Disk hygiene must never cost a capture."""
    import logging
    monkeypatch.chdir(tmp_path)
    _existing_song_dir(tmp_path)
    monkeypatch.delenv("HALLUCINOTE_CAPTURE_SWEEP", raising=False)

    def _boom(*a, **kw):
        raise OSError("disk on fire")

    monkeypatch.setattr("hallucinote.takes.plan_sweep", _boom)
    with caplog.at_level(logging.WARNING):
        send = _render_start({"song_slug": "demo"})

    assert send.called, "the render must still be forwarded"
    assert "retention sweep failed" in caplog.text


def test_render_start_sweep_scoped_to_the_song_not_an_arbitrary_output_dir(
    tmp_path, monkeypatch,
):
    """An output_dir outside the song's captures root must not cause a sweep
    of whatever directory happens to contain it.

    Asserts both halves, so it can't pass by sweeping nothing at all: the
    unrelated directory is untouched AND the song's own captures root is still
    swept on the same call.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HALLUCINOTE_CAPTURE_KEEP", raising=False)
    monkeypatch.delenv("HALLUCINOTE_CAPTURE_SWEEP", raising=False)
    elsewhere = tmp_path / "elsewhere"
    for i in range(4):
        _seed_take(elsewhere, f"take-{i}", f"2026060{i}T000000Z")
    captures = tmp_path / "songs" / "demo" / "captures"
    for i in range(4):
        _seed_take(captures, f"song-take-{i}", f"2026060{i}T000000Z")

    _render_start(
        {"song_slug": "demo", "output_dir": str(elsewhere / "new-take")}
    )

    assert {p.name for p in elsewhere.iterdir()} == {f"take-{i}" for i in range(4)}
    assert {p.name for p in captures.iterdir()} == {"song-take-3", "song-take-2"}


def test_render_start_refuses_a_traversal_slug_before_sweeping(
    tmp_path, monkeypatch, caplog,
):
    """A malicious/typo'd song_slug must never aim the sweep outside the song
    tree. `Path("songs") / "/abs"` is `/abs`, so an absolute slug would
    otherwise replace the songs root entirely."""
    import logging
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HALLUCINOTE_CAPTURE_SWEEP", raising=False)
    # Seeded under <victim>/captures because that is exactly where an absolute
    # slug lands the sweep: resolve_song_dir(slug) / "captures". Without the
    # validation these three are swept down to two.
    victim = tmp_path / "victim" / "captures"
    _seed_take(victim, "precious", "20260601T000000Z")
    _seed_take(victim, "precious-2", "20260602T000000Z")
    _seed_take(victim, "precious-3", "20260603T000000Z")

    with caplog.at_level(logging.WARNING):
        send = _render_start(
            {
                "song_slug": str(tmp_path / "victim"),
                "output_dir": str(victim / "new"),
            }
        )

    assert {p.name for p in victim.iterdir()} == {
        "precious", "precious-2", "precious-3",
    }
    assert send.called, "the render itself is not the sweep's business to block"


def test_render_start_logs_when_the_sweep_is_disabled(tmp_path, monkeypatch, caplog):
    """A silent no-op looks identical to an env var that never reached this
    process, so the opt-out confirms itself in the log."""
    import logging
    monkeypatch.chdir(tmp_path)
    _existing_song_dir(tmp_path)
    monkeypatch.setenv("HALLUCINOTE_CAPTURE_SWEEP", "0")

    with caplog.at_level(logging.INFO, logger="hallucinote_mcp"):
        _render_start({"song_slug": "demo"})

    assert "retention sweep disabled" in caplog.text


def test_sweep_env_name_matches_the_engine_constant():
    """server.py names the var literally (it must read correctly even with no
    engine installed); this pins it to the engine's definition."""
    from hallucinote.takes import ENV_SWEEP
    from hallucinote_mcp.server import _CAPTURE_SWEEP_ENV

    assert _CAPTURE_SWEEP_ENV == ENV_SWEEP


def test_render_start_sweep_names_the_takes_it_removed(tmp_path, monkeypatch, caplog):
    """The log is the only record a take existed once its directory is gone."""
    import logging
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HALLUCINOTE_CAPTURE_KEEP", raising=False)
    monkeypatch.delenv("HALLUCINOTE_CAPTURE_SWEEP", raising=False)
    captures = tmp_path / "songs" / "demo" / "captures"
    for i in range(4):
        _seed_take(captures, f"take-{i}", f"2026060{i}T000000Z")

    with caplog.at_level(logging.INFO, logger="hallucinote_mcp"):
        _render_start({"song_slug": "demo"})

    assert "take-0" in caplog.text and "take-1" in caplog.text


def test_render_start_logs_when_the_engine_is_unavailable(
    tmp_path, monkeypatch, caplog,
):
    """An MCP-only install can never sweep, and that condition is PERMANENT —
    so it says so rather than letting captures pile up unexplained."""
    import builtins
    import logging
    monkeypatch.chdir(tmp_path)
    _existing_song_dir(tmp_path)
    monkeypatch.delenv("HALLUCINOTE_CAPTURE_SWEEP", raising=False)

    real_import = builtins.__import__

    def _no_takes(name, *a, **kw):
        if name == "hallucinote.takes":
            raise ImportError("no engine here")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _no_takes)
    with caplog.at_level(logging.INFO, logger="hallucinote_mcp"):
        send = _render_start({"song_slug": "demo"})

    assert "capture retention unavailable" in caplog.text
    assert send.called


# ---------------------------------------------------------------------------
# Render destination safety — the phantom song dir.
#
# `ableton_render(action='start')` with no output_dir builds its destination
# from the slug. When that resolved to a directory that didn't exist, nothing
# refused: the Live-side handler's mkdir(parents=True) invented the whole tree
# and the capture pass filled it with ~290 MB of WAVs. Because the render
# SUCCEEDED, the misfile stayed invisible until analysis reported the song
# unbuilt. These pin both halves — resolve it right, and refuse rather than
# invent when it can't be resolved.
# ---------------------------------------------------------------------------


@pytest.fixture
def proj(tmp_path):
    """An isolated project dir, one level inside `tmp_path`.

    Slug resolution consults the project dir's SIBLINGS (the two-repo topology
    rung), and pytest's `tmp_path` siblings are other tests' `tmp_path`s — some
    of which plant workspace markers and build songs. Nesting one level gives
    each test its own neighbourhood so no test can be steered by another's
    fixtures.
    """
    d = tmp_path / "proj"
    d.mkdir()
    return d


def test_render_default_finds_a_workspace_below_the_project_dir(
    proj, monkeypatch,
):
    """The defect: project dir above, `hallucinote.toml` below. Captures must
    land in the song's own workspace, not a fabricated `songs/<slug>/`."""
    import pathlib
    from hallucinote_mcp.wire import Response

    monkeypatch.delenv("HALLUCINOTE_SONGS_ROOT", raising=False)
    ws = proj / "examples"
    (ws / "demo").mkdir(parents=True)
    (ws / "hallucinote.toml").write_text(
        '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n'
    )
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    monkeypatch.chdir(proj)

    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call("ableton_render", "start", {"song_slug": "demo"})

    output_dir = pathlib.Path(send.call_args.args[0].params["output_dir"])
    assert output_dir.is_relative_to((ws / "demo").resolve()), (
        f"captures must land in the resolved workspace, got {output_dir}"
    )
    assert not (proj / "songs").exists(), (
        "the legacy path must not even be named once the workspace resolves"
    )


def test_render_refuses_to_write_into_a_song_dir_that_does_not_exist(
    proj, monkeypatch,
):
    """No resolution is perfect — a typo'd slug, an ambiguous descent. The
    render must refuse rather than invent a tree and fill it with gigabytes."""
    monkeypatch.delenv("HALLUCINOTE_SONGS_ROOT", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    monkeypatch.chdir(proj)

    with patch("hallucinote_mcp.server.client.send") as send:
        response = handle_tool_call("ableton_render", "start", {"song_slug": "demo"})

    assert response["ok"] is False
    assert not send.called, "a refused render must never reach Live"
    assert "does not exist" in response["error"]
    # Diagnoses rather than blames the slug.
    assert "no hallucinote.toml workspace marker" in response["error"]


def test_render_refusal_does_not_apply_to_an_explicit_output_dir(
    proj, monkeypatch,
):
    """A caller naming a destination is saying "put it here" — the guard is
    only ever about the DERIVED default."""
    from hallucinote_mcp.wire import Response

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    monkeypatch.chdir(proj)
    target = str(proj / "anywhere" / "captures")

    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        response = handle_tool_call(
            "ableton_render", "start",
            {"song_slug": "demo", "output_dir": target},
        )
    assert response["ok"] is True
    assert send.call_args.args[0].params["output_dir"] == target


def test_render_db_seq_is_tagged_for_a_workspace_below_the_project_dir(
    proj, monkeypatch,
):
    """Downstream symptom of the same misresolution: `manifest.db_seq` came
    back null (the DB "didn't exist"), so the capture could never serve as a
    `--compare` baseline."""
    from hallucinote.db import mutations as M
    from hallucinote.db.connection import init_db
    from hallucinote_mcp.wire import Response

    monkeypatch.delenv("HALLUCINOTE_SONGS_ROOT", raising=False)
    ws = proj / "examples"
    song_dir = ws / "demo"
    song_dir.mkdir(parents=True)
    (ws / "hallucinote.toml").write_text(
        '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n'
    )
    conn = init_db(song_dir / "demo.db")
    M.create_song(conn, name="demo")
    conn.commit()
    conn.close()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    monkeypatch.chdir(proj)

    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call("ableton_render", "start", {"song_slug": "demo"})

    assert send.call_args.args[0].params.get("db_seq") is not None, (
        "a resolvable song DB must tag the render with its audit-log seq"
    )


def test_render_default_finds_the_sibling_songs_repo(proj, monkeypatch):
    """The reported failure on the render side. A session rooted at the
    framework repo — which ships a demo workspace at `examples/` — used to send
    every slug into that demo workspace, so captures for a song in the sibling
    songs repo landed in the wrong tree (workable around only by passing an
    explicit `output_dir`; `ableton_analysis` had no such escape hatch).
    """
    import pathlib
    from hallucinote_mcp.wire import Response

    monkeypatch.delenv("HALLUCINOTE_SONGS_ROOT", raising=False)
    demo_ws = proj / "examples"
    (demo_ws / "b-natural").mkdir(parents=True)
    (demo_ws / "b-natural" / "build.py").write_text("# built\n")
    (demo_ws / "hallucinote.toml").write_text(
        '[workspace]\nlayout = "monorepo"\nsongs_root = "."\n'
    )
    song_dir = proj.parent / "songs-repo" / "songs" / "the-argument"
    song_dir.mkdir(parents=True)
    (song_dir / "build.py").write_text("# built\n")
    (proj.parent / "songs-repo" / "hallucinote.toml").write_text(
        '[workspace]\nlayout = "monorepo"\nsongs_root = "songs"\n'
    )
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    monkeypatch.chdir(proj)

    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        response = handle_tool_call(
            "ableton_render", "start", {"song_slug": "the-argument"},
        )

    assert response["ok"] is True
    output_dir = pathlib.Path(send.call_args.args[0].params["output_dir"])
    assert output_dir.is_relative_to(song_dir.resolve()), (
        f"captures must land in the sibling songs repo, got {output_dir}"
    )
    assert not (demo_ws / "the-argument").exists(), (
        "the demo workspace must not be named for a song it does not hold"
    )


def test_render_refuses_and_names_both_workspaces_when_two_hold_the_song(
    proj, monkeypatch,
):
    """Ambiguity stays honest at the render boundary too: refuse, name the
    candidates, and never invent a tree to fill with gigabytes."""
    monkeypatch.delenv("HALLUCINOTE_SONGS_ROOT", raising=False)
    roots = []
    for name in ("repo-a", "repo-b"):
        root = proj.parent / name
        (root / "songs" / "demo").mkdir(parents=True)
        (root / "songs" / "demo" / "build.py").write_text("# built\n")
        (root / "hallucinote.toml").write_text(
            '[workspace]\nlayout = "monorepo"\nsongs_root = "songs"\n'
        )
        roots.append(root)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    monkeypatch.chdir(proj)

    with patch("hallucinote_mcp.server.client.send") as send:
        response = handle_tool_call("ableton_render", "start", {"song_slug": "demo"})

    assert response["ok"] is False
    assert not send.called, "a refused render must never reach Live"
    assert "ambiguous" in response["error"], response["error"]
    for root in roots:
        assert str(root.resolve()) in response["error"], response["error"]
    assert not (proj / "songs").exists()


# ---------------------------------------------------------------------------
# AUD-5M8H — AUDIO_CAPTURED audit event on render completion
#
# The render worker runs inside Live's vendored env with no `hallucinote`
# engine and no DB, so the event is appended HERE, in the server process, off
# the status response — the first moment this side learns a capture finished.
# ---------------------------------------------------------------------------


def _capture_audit_fixture(tmp_path, monkeypatch):
    """A song DB the server can resolve, plus the status response shape
    `job.status_result()` actually returns for a finished render."""
    from hallucinote.db.connection import init_db

    db_path = tmp_path / "songs" / "demo" / "demo.db"
    db_path.parent.mkdir(parents=True)
    conn = init_db(db_path)
    conn.execute(
        "INSERT INTO songs (id, name) VALUES (?, ?)", ("song-demo", "demo"),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        "hallucinote.db.connection.resolve_db_path",
        lambda slug, **_: tmp_path / "songs" / slug / f"{slug}.db",
    )
    return db_path


def _done_status(captures_dir, *, db_seq=41, tracks=3):
    return {
        "job_id": "job-1",
        "kind": "render",
        "state": "done",
        "progress": {},
        "captures_dir": str(captures_dir),
        "manifest": {
            "song_slug": "demo",
            "db_seq": db_seq,
            "tracks": [{"track_id": i} for i in range(tracks)],
        },
        "render_status": "ok",
    }


def _audio_events(db_path):
    import json

    from hallucinote.db import events as E
    from hallucinote.db.connection import connect

    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT payload_json FROM events WHERE kind = ?", (E.AUDIO_CAPTURED,),
        ).fetchall()
    finally:
        conn.close()
    return [json.loads(r["payload_json"]) for r in rows]


def test_render_status_done_records_the_capture_audit_event(tmp_path, monkeypatch):
    from hallucinote_mcp.wire import Response

    db_path = _capture_audit_fixture(tmp_path, monkeypatch)
    captures_dir = tmp_path / "songs" / "demo" / "captures" / "20260811-120000"

    forwarded = Response(ok=True, result=_done_status(captures_dir))
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded):
        handle_tool_call("ableton_render", "status", {"job_id": "job-1"})

    assert _audio_events(db_path) == [{
        "captures_dir": str(captures_dir),
        "manifest_seq": 41,
        "track_count": 3,
    }]


def test_repeated_status_polls_record_the_capture_once(tmp_path, monkeypatch):
    """The agent polls until it reads `done` and every later poll reads `done`
    too — one take must not become one event per poll."""
    from hallucinote_mcp.wire import Response

    db_path = _capture_audit_fixture(tmp_path, monkeypatch)
    captures_dir = tmp_path / "songs" / "demo" / "captures" / "20260811-120000"

    forwarded = Response(ok=True, result=_done_status(captures_dir))
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded):
        for _ in range(4):
            handle_tool_call("ableton_render", "status", {"job_id": "job-1"})

    assert len(_audio_events(db_path)) == 1


def test_render_still_running_records_nothing(tmp_path, monkeypatch):
    from hallucinote_mcp.wire import Response

    db_path = _capture_audit_fixture(tmp_path, monkeypatch)
    running = {
        "job_id": "job-1", "kind": "render", "state": "running",
        "progress": {"beat": 12}, "captures_dir": str(tmp_path / "c"),
    }
    forwarded = Response(ok=True, result=running)
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded):
        handle_tool_call("ableton_render", "status", {"job_id": "job-1"})

    assert _audio_events(db_path) == []


def test_a_failed_capture_audit_never_fails_the_render(tmp_path, monkeypatch):
    """Best-effort, exactly like `_attach_render_db_seq`: a capture that
    actually succeeded must not be reported as failed because an audit row
    could not be written."""
    from hallucinote_mcp.wire import Response

    _capture_audit_fixture(tmp_path, monkeypatch)
    captures_dir = tmp_path / "songs" / "demo" / "captures" / "20260811-120000"

    import sqlite3

    def _boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(
        "hallucinote.db.mutations.record_audio_capture", _boom,
    )
    forwarded = Response(ok=True, result=_done_status(captures_dir))
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded):
        out = handle_tool_call("ableton_render", "status", {"job_id": "job-1"})

    assert out["ok"] is True, "the render succeeded; the audit row is incidental"


def test_render_status_done_self_ignores_the_captures_root(tmp_path, monkeypatch):
    """WSP-3R7K: a default-path render marks its captures ROOT ignored, so a
    workspace created before `init-workspace` stops surfacing gigabytes of WAVs
    as committable."""
    from hallucinote_mcp.wire import Response

    _capture_audit_fixture(tmp_path, monkeypatch)
    captures_root = tmp_path / "songs" / "demo" / "captures"
    captures_dir = captures_root / "20260811-120000"
    captures_dir.mkdir(parents=True)
    # takes.py binds the resolver at import, so patch it where it is USED.
    monkeypatch.setattr(
        "hallucinote.takes.resolve_song_dir",
        lambda slug, **_: tmp_path / "songs" / slug,
    )

    forwarded = Response(ok=True, result=_done_status(captures_dir))
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded):
        handle_tool_call("ableton_render", "status", {"job_id": "job-1"})

    assert (captures_root / ".gitignore").read_text().rstrip().endswith("*")


def test_a_foreign_output_dir_never_gets_a_blanket_ignore_written_above_it(
    tmp_path, monkeypatch,
):
    """`output_dir` is caller-controlled — "a caller may render anywhere" — and
    `self_ignore_dir` writes a blanket `*`. Deriving the target from
    `captures_dir.parent` would let a render into `songs/<slug>/captures` drop
    build.py, decisions/ and captured_session.json out of `git status`. The
    target comes from the SLUG, and a render outside that root is the caller's
    own directory to manage.

    This mirrors the rule `_sweep_stale_takes` already states for retention.
    """
    from hallucinote_mcp.wire import Response

    _capture_audit_fixture(tmp_path, monkeypatch)
    # takes.py binds the resolver at import, so patch it where it is USED.
    monkeypatch.setattr(
        "hallucinote.takes.resolve_song_dir",
        lambda slug, **_: tmp_path / "songs" / slug,
    )
    # The dangerous shape: output_dir IS the song's captures root, so its parent
    # is the song dir itself.
    song_dir = tmp_path / "songs" / "demo"
    elsewhere = tmp_path / "scratch" / "renders"
    elsewhere.mkdir(parents=True)

    forwarded = Response(ok=True, result=_done_status(elsewhere))
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded):
        handle_tool_call("ableton_render", "status", {"job_id": "job-1"})

    assert not (elsewhere.parent / ".gitignore").exists(), (
        "a blanket ignore must never be written into a tree the caller chose"
    )
    assert not (song_dir / ".gitignore").exists(), (
        "and never into the song dir, which holds build.py and the snapshot"
    )
