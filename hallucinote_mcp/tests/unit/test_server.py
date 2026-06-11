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
# Server-side path resolution for ableton_render(render).
#
# The render handler runs inside Live's process (cwd = "/" on macOS,
# read-only). A relative output_dir like "songs/<slug>/captures/<ts>"
# resolves against Live's cwd and the mkdir raises OSError [Errno 30].
# handle_tool_call must absolutize the path BEFORE forwarding so the
# Remote Script sees only absolute paths.
# ---------------------------------------------------------------------------


def test_render_call_absolutizes_relative_output_dir_before_forward(
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
            "render",
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


def test_render_call_computes_default_output_dir_when_missing(
    tmp_path, monkeypatch,
):
    """When output_dir is omitted, the server fills in
    ``<cwd>/songs/<slug>/captures/<utc-ts>/`` so the Remote Script
    never sees a relative path."""
    import re
    import pathlib
    from hallucinote_mcp.wire import Response

    monkeypatch.chdir(tmp_path)

    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call("ableton_render", "render", {"song_slug": "demo"})
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


def test_render_call_passes_through_absolute_output_dir(
    tmp_path, monkeypatch,
):
    """An already-absolute output_dir is passed through unchanged."""
    from hallucinote_mcp.wire import Response

    monkeypatch.chdir(tmp_path)
    absolute_dir = str(tmp_path / "custom" / "captures")

    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call(
            "ableton_render", "render",
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
# budget. Two ableton_render actions break it: render (full playback) needs no
# bound; ensure_loaded loads the analyzer onto 25+ surfaces and routinely
# outruns 15s while the work continues server-side — it needs a generous but
# bounded window so a genuinely-stuck load still surfaces as a timeout.
# ---------------------------------------------------------------------------


def test_read_timeout_render_is_unbounded():
    from hallucinote_mcp.server import _read_timeout_for
    assert _read_timeout_for("ableton_render", "render") is None


def test_read_timeout_ensure_loaded_is_generous_but_bounded():
    from hallucinote_mcp.server import _DEFAULT_READ_TIMEOUT, _read_timeout_for
    t = _read_timeout_for("ableton_render", "ensure_loaded")
    # Bounded (not the unbounded render case) but well clear of the default —
    # the whole point is that 15s was too short.
    assert t is not None
    assert t > _DEFAULT_READ_TIMEOUT


def test_read_timeout_default_action_keeps_bounded_default():
    from hallucinote_mcp.server import _DEFAULT_READ_TIMEOUT, _read_timeout_for
    assert _read_timeout_for("ableton_session", "set_tempo") == _DEFAULT_READ_TIMEOUT
    # ensure_loaded on a non-render tool is NOT special-cased — the policy is
    # keyed on (tool, action), not action alone.
    assert _read_timeout_for("ableton_track", "ensure_loaded") == _DEFAULT_READ_TIMEOUT


def test_handle_tool_call_forwards_ensure_loaded_with_generous_timeout(
    tmp_path, monkeypatch,
):
    """The selected timeout must actually reach client.send — pin the wiring,
    not just the policy table. Before MCP-4T6Y this forwarded with the 15s
    default and timed out mid-load."""
    from hallucinote_mcp.server import _ENSURE_LOADED_READ_TIMEOUT
    from hallucinote_mcp.wire import Response

    monkeypatch.chdir(tmp_path)
    forwarded = Response(ok=True, result={"loaded_count": 25})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call("ableton_render", "ensure_loaded", {})
    assert send.call_args.kwargs["read_timeout"] == _ENSURE_LOADED_READ_TIMEOUT


def test_handle_tool_call_forwards_render_with_unbounded_timeout(
    tmp_path, monkeypatch,
):
    """Regression: render must keep its unbounded (None) read timeout through
    the refactor to the policy table."""
    from hallucinote_mcp.wire import Response

    monkeypatch.chdir(tmp_path)
    forwarded = Response(ok=True, result={"captures_dir": str(tmp_path)})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call("ableton_render", "render", {"song_slug": "demo"})
    assert send.call_args.kwargs["read_timeout"] is None


def test_handle_tool_call_forwards_default_action_with_bounded_timeout(
    isolated_registry,
):
    """A normal mutating call keeps the 15s default so a stalled handler
    surfaces as a structured timeout instead of hanging the transport."""
    from hallucinote_mcp.schema import Action, LiveOp, ParamSpec
    from hallucinote_mcp.server import _DEFAULT_READ_TIMEOUT
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
        handle_tool_call("ableton_session", "set_tempo", {"value": 132.0})
    assert send.call_args.kwargs["read_timeout"] == _DEFAULT_READ_TIMEOUT


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


def test_render_call_attaches_db_seq_from_song_db(tmp_path, monkeypatch):
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
            "ableton_render", "render",
            {"song_slug": "demo", "output_dir": str(tmp_path / "captures")},
        )
    forwarded_request = send.call_args.args[0]
    assert forwarded_request.params["db_seq"] == expected_seq


def test_render_call_omits_db_seq_when_song_db_missing(tmp_path, monkeypatch):
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
            "ableton_render", "render",
            {"song_slug": "nope", "output_dir": str(tmp_path / "captures")},
        )
    forwarded_request = send.call_args.args[0]
    assert "db_seq" not in forwarded_request.params


def test_render_call_respects_explicit_db_seq(tmp_path, monkeypatch):
    """An explicitly-supplied db_seq is passed through untouched — the
    server only fills the gap, it never overrides the caller."""
    from hallucinote_mcp.wire import Response

    forwarded = Response(ok=True, result={"status": "ok"})
    with patch("hallucinote_mcp.server.client.send", return_value=forwarded) as send:
        handle_tool_call(
            "ableton_render", "render",
            {"song_slug": "demo", "output_dir": str(tmp_path), "db_seq": 99},
        )
    assert send.call_args.args[0].params["db_seq"] == 99


def test_render_call_omits_db_seq_when_song_row_missing(tmp_path, monkeypatch):
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
            "ableton_render", "render",
            {"song_slug": "demo", "output_dir": str(tmp_path / "captures")},
        )
    assert "db_seq" not in send.call_args.args[0].params


def test_render_call_swallows_seq_read_errors(tmp_path, monkeypatch, caplog):
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
                "ableton_render", "render",
                {"song_slug": "demo", "output_dir": str(tmp_path / "captures")},
            )
    assert "db_seq" not in send.call_args.args[0].params
    assert "could not read latest db seq" in caplog.text


def test_annotated_param_type_any_is_explicit_not_fallback():
    # 'any' must be a first-class _PARAM_TYPE_MAP entry; regressing to the
    # .get() fallback would still work today, but the explicit entry is the
    # documented contract for polymorphic params (ableton_probe set's value).
    from hallucinote_mcp.server import _PARAM_TYPE_MAP
    from typing import Any
    assert _PARAM_TYPE_MAP["any"] is Any
