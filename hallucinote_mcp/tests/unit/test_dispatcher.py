"""Dispatcher — validation, routing, help, declarative execution."""
from __future__ import annotations

from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import (
    ParamValidationError,
    dispatch,
    execute_declarative,
    help_for_tool,
    resolve_target,
    validate_params,
)
from hallucinote_mcp.schema import Action, LiveOp, ParamSpec
from hallucinote_mcp.wire import Request


# ---------- A tiny fake LiveContext for tests ----------


class FakeNode:
    """Recursive object with attribute and subscript access for navigation tests."""

    def __init__(self, **attrs: Any):
        for k, v in attrs.items():
            setattr(self, k, v)


class FakeLiveContext:
    """LiveContext stub for tests — synchronous, no thread marshaling.

    Mirrors the production ``LiveLiveContext`` Protocol: exposes ``song``,
    ``application``, and ``run_on_main``. Since tests run on a single
    thread, ``run_on_main`` just invokes the callable directly and
    returns the result (or re-raises).
    """

    def __init__(self, root: Any, application: Any = None):
        self._root = root
        self._application = application
        self.run_on_main_calls = 0

    @property
    def song(self) -> Any:
        return self._root

    @property
    def application(self) -> Any:
        return self._application

    def run_on_main(self, fn):
        self.run_on_main_calls += 1
        return fn()


# ---------- validate_params ----------


def _action_with_params(*params: ParamSpec) -> Action:
    return Action(
        tool="ableton_session",
        name="probe",
        description="",
        params=params,
        declarative_op=LiveOp(kind="property_read", target="song", property="tempo"),
    )


def test_validate_missing_required():
    action = _action_with_params(ParamSpec(name="bpm", type="float"))
    with pytest.raises(ParamValidationError) as exc:
        validate_params(action, {})
    assert exc.value.missing == ("bpm",)


def test_validate_unknown_param_rejected():
    action = _action_with_params(ParamSpec(name="bpm", type="float"))
    with pytest.raises(ParamValidationError, match="unknown param"):
        validate_params(action, {"bpm": 120, "extra": "junk"})


def test_validate_int_rejects_bool():
    action = _action_with_params(ParamSpec(name="idx", type="int"))
    with pytest.raises(ParamValidationError, match="must be int"):
        validate_params(action, {"idx": True})


def test_validate_float_accepts_int():
    action = _action_with_params(ParamSpec(name="bpm", type="float"))
    assert validate_params(action, {"bpm": 120}) == {"bpm": 120}


def test_validate_enum_rejects_outsider():
    action = _action_with_params(
        ParamSpec(name="view", type="str", enum=("session", "arranger"))
    )
    with pytest.raises(ParamValidationError, match="not in enum"):
        validate_params(action, {"view": "studio"})


def test_validate_min_max():
    action = _action_with_params(
        ParamSpec(name="bpm", type="float", minimum=20.0, maximum=999.0)
    )
    with pytest.raises(ParamValidationError, match="below minimum"):
        validate_params(action, {"bpm": 5})
    with pytest.raises(ParamValidationError, match="above maximum"):
        validate_params(action, {"bpm": 1500})


# ---------- resolve_target ----------


def test_resolve_target_substitutes_params():
    assert resolve_target("song.tracks[{idx}]", {"idx": 3}) == "song.tracks[3]"


def test_resolve_target_handles_minus_one_index():
    assert (
        resolve_target("song.tracks[{idx-1}]", {"idx": 5}) == "song.tracks[4]"
    )


# ---------- execute_declarative (now takes Song directly) ----------


def test_execute_declarative_property_read():
    root = FakeNode(tempo=132.0)
    op = LiveOp(kind="property_read", target="song", property="tempo")
    assert execute_declarative(op, {}, root) == 132.0


def test_execute_declarative_property_write():
    root = FakeNode(tempo=132.0)
    op = LiveOp(kind="property_write", target="song", property="tempo")
    execute_declarative(op, {"value": 140.0}, root)
    assert root.tempo == 140.0


def test_execute_declarative_method_call():
    captured = {}

    class Player:
        def fire(self, position, length):
            captured["args"] = (position, length)
            return "fired"

    root = FakeNode(transport=Player())
    op = LiveOp(
        kind="method_call",
        target="song.transport",
        method="fire",
        method_args=("position", "length"),
    )
    assert (
        execute_declarative(op, {"position": 0, "length": 4}, root) == "fired"
    )
    assert captured["args"] == (0, 4)


def test_execute_declarative_indexed_walk():
    """Verify song.tracks[i] walks subscript correctly."""
    track0 = FakeNode(name="lead")
    track1 = FakeNode(name="bass")
    root = FakeNode(tracks=[track0, track1])
    op = LiveOp(
        kind="property_read",
        target="song.tracks[{track_index-1}]",
        property="name",
    )
    assert execute_declarative(op, {"track_index": 2}, root) == "bass"


def test_execute_declarative_property_write_with_custom_value_param():
    """LiveOp.value_param lets a declarative property_write read its value from
    a domain-friendly param name (e.g. ``bpm`` for ``set_tempo``) without
    forcing a handler. Added in M-1.
    """
    root = FakeNode(tempo=120.0)
    op = LiveOp(
        kind="property_write",
        target="song",
        property="tempo",
        value_param="bpm",
    )
    execute_declarative(op, {"bpm": 145.5}, root)
    assert root.tempo == 145.5


# ---------- dispatch (top-level) ----------


def test_dispatch_unknown_tool_returns_structured_error():
    request = Request(tool="ableton_unknown", action="help")
    resp = dispatch(request)
    assert resp.ok is False
    assert resp.valid_actions == tuple(schema.TOOLS)
    assert "unknown tool" in (resp.error or "")


def test_dispatch_unknown_action_returns_valid_action_list(isolated_registry):
    isolated_registry.register_help_actions()
    request = Request(tool="ableton_session", action="set_phaser")
    resp = dispatch(request)
    assert resp.ok is False
    assert resp.valid_actions == ("help",)
    assert "ableton_session(action='help')" in (resp.example or "")


def test_dispatch_help_returns_help_structure(isolated_registry):
    isolated_registry.register(
        Action(
            tool="ableton_session",
            name="set_tempo",
            description="Set song tempo.",
            params=(ParamSpec(name="bpm", type="float", minimum=20.0),),
            declarative_op=LiveOp(
                kind="property_write", target="song", property="tempo"
            ),
            example="ableton_session(action='set_tempo', bpm=132)",
        )
    )
    isolated_registry.register_help_actions()
    resp = dispatch(Request(tool="ableton_session", action="help"))
    assert resp.ok is True
    result = resp.result
    assert result["tool"] == "ableton_session"
    names = [a["name"] for a in result["actions"]]
    assert names == ["set_tempo"]  # help itself is omitted from the action list


def test_dispatch_param_validation_error_includes_help_hint(isolated_registry):
    isolated_registry.register(
        Action(
            tool="ableton_session",
            name="set_tempo",
            description="",
            params=(ParamSpec(name="bpm", type="float"),),
            declarative_op=LiveOp(
                kind="property_write", target="song", property="tempo"
            ),
            example="ableton_session(action='set_tempo', bpm=132)",
        )
    )
    resp = dispatch(Request(tool="ableton_session", action="set_tempo", params={}))
    assert resp.ok is False
    assert resp.required == ("bpm",)
    assert "set_tempo" in (resp.example or "")


def test_dispatch_executes_declarative_with_context(isolated_registry):
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
    root = FakeNode(tempo=120.0)
    ctx = FakeLiveContext(root)
    resp = dispatch(
        Request(tool="ableton_session", action="set_tempo", params={"value": 140.0}),
        context=ctx,
    )
    assert resp.ok is True
    assert root.tempo == 140.0
    # Confirm the dispatcher marshaled exactly once — proves the atomicity
    # fix from the M-0 Critic round (one main-thread bounce per dispatch).
    assert ctx.run_on_main_calls == 1


def test_dispatch_without_context_sets_needs_remote_flag(isolated_registry):
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
    resp = dispatch(
        Request(tool="ableton_session", action="set_tempo", params={"value": 132}),
        context=None,
    )
    assert resp.ok is False
    assert resp.needs_remote is True
    # needs_remote must not be serialized to the wire — it's a server-internal flag.
    assert "needs_remote" not in resp.to_dict()


def test_dispatch_handler_path(isolated_registry):
    captured: dict[str, Any] = {}

    def my_handler(context: FakeLiveContext, *, name: str) -> dict[str, str]:
        captured["context"] = context
        captured["name"] = name
        return {"ok": True, "name": name}

    isolated_registry.register(
        Action(
            tool="ableton_session",
            name="snapshot",
            description="",
            params=(ParamSpec(name="name", type="str"),),
            handler=my_handler,
        )
    )
    ctx = FakeLiveContext(FakeNode())
    resp = dispatch(
        Request(tool="ableton_session", action="snapshot", params={"name": "verse"}),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result == {"ok": True, "name": "verse"}
    assert captured == {"context": ctx, "name": "verse"}


def test_dispatch_translates_executor_exception_to_structured_error(isolated_registry, caplog):
    import logging

    def boom(_context: FakeLiveContext) -> None:
        raise RuntimeError("Live API rejected the value")

    isolated_registry.register(
        Action(
            tool="ableton_session",
            name="info",
            description="",
            handler=boom,
        )
    )
    with caplog.at_level(logging.ERROR, logger="hallucinote_mcp.dispatcher"):
        resp = dispatch(
            Request(tool="ableton_session", action="info"),
            context=FakeLiveContext(FakeNode()),
        )
    assert resp.ok is False
    assert "RuntimeError" in (resp.error or "")
    assert "Live API rejected" in (resp.error or "")
    # Critic finding W2: dispatcher must log the exception so the server
    # operator has a record. Don't just translate; log too.
    assert any("executor failed" in record.message for record in caplog.records)


# ---------- help_for_tool ----------


def test_help_for_tool_includes_params_and_example(isolated_registry):
    isolated_registry.register(
        Action(
            tool="ableton_track",
            name="set_property",
            description="Write a track property.",
            params=(
                ParamSpec(name="track_index", type="int", minimum=1, description="1-based"),
                ParamSpec(
                    name="property",
                    type="str",
                    enum=("volume", "panning", "mute"),
                ),
                ParamSpec(name="value", type="float"),
                ParamSpec(name="ramp_ms", type="float", required=False),
            ),
            declarative_op=LiveOp(
                kind="property_write",
                target="song.tracks[{track_index-1}].mixer_device.volume",
                property="value",
            ),
            example="ableton_track(action='set_property', track_index=5, property='volume', value=0.7)",
            tips=("Volumes are 0.0-1.0 not dB.",),
        )
    )
    h = help_for_tool("ableton_track")
    assert h["tool"] == "ableton_track"
    only = h["actions"][0]
    assert only["name"] == "set_property"
    assert only["required"] == ["track_index", "property", "value"]
    assert only["optional"] == ["ramp_ms"]
    assert only["tips"] == ["Volumes are 0.0-1.0 not dB."]
    # Enum surfaces in the param entry
    prop_entry = [p for p in only["params"] if p["name"] == "property"][0]
    assert prop_entry["enum"] == ["volume", "panning", "mute"]
