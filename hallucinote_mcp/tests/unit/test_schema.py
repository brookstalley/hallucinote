"""Schema dataclasses + registry."""
from __future__ import annotations

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.schema import Action, LiveOp, ParamSpec


def test_ten_tools_exposed():
    assert len(schema.TOOLS) == 10
    assert "ableton_session" in schema.TOOLS
    assert "ableton_scene" in schema.TOOLS  # the 10th-slot tool


def test_action_rejects_unknown_tool(isolated_registry):
    with pytest.raises(ValueError, match="not in TOOLS"):
        Action(
            tool="ableton_invented",
            name="nope",
            description="",
            declarative_op=LiveOp(kind="property_read", target="song", property="tempo"),
        )


def test_action_requires_exactly_one_executor(isolated_registry):
    with pytest.raises(ValueError, match="exactly one"):
        Action(tool="ableton_session", name="info", description="")

    op = LiveOp(kind="property_read", target="song", property="tempo")
    with pytest.raises(ValueError, match="exactly one"):
        Action(
            tool="ableton_session",
            name="info",
            description="",
            declarative_op=op,
            handler=lambda ctx: None,
        )


def test_help_action_does_not_require_executor():
    action = Action(tool="ableton_session", name="help", description="help text")
    assert action.handler is None and action.declarative_op is None


def test_help_action_rejects_executor_fields():
    """Insurance against a future typo silently attaching an executor to
    a 'help' action (which the dispatcher special-cases as metadata-only).
    """
    with pytest.raises(ValueError, match="help actions must not set"):
        Action(
            tool="ableton_session",
            name="help",
            description="",
            declarative_op=LiveOp(kind="property_read", target="song", property="tempo"),
        )
    with pytest.raises(ValueError, match="help actions must not set"):
        Action(
            tool="ableton_session",
            name="help",
            description="",
            handler=lambda ctx: None,
        )


def test_register_and_get(isolated_registry):
    action = Action(
        tool="ableton_session",
        name="set_tempo",
        description="Set song tempo.",
        params=(ParamSpec(name="bpm", type="float", minimum=20.0, maximum=999.0),),
        declarative_op=LiveOp(kind="property_write", target="song", property="tempo"),
        example="ableton_session(action='set_tempo', bpm=132)",
    )
    isolated_registry.register(action)
    assert isolated_registry.get("ableton_session", "set_tempo") is action
    assert isolated_registry.get("ableton_session", "nonexistent") is None


def test_register_rejects_duplicate(isolated_registry):
    action = Action(
        tool="ableton_session",
        name="set_tempo",
        description="",
        declarative_op=LiveOp(kind="property_write", target="song", property="tempo"),
        params=(ParamSpec(name="bpm", type="float"),),
    )
    isolated_registry.register(action)
    with pytest.raises(ValueError, match="already registered"):
        isolated_registry.register(action)


def test_register_help_actions_is_idempotent(isolated_registry):
    isolated_registry.register_help_actions()
    first_count = len(isolated_registry.all_actions())
    isolated_registry.register_help_actions()
    second_count = len(isolated_registry.all_actions())
    assert first_count == second_count == len(schema.TOOLS)
    for tool in schema.TOOLS:
        assert isolated_registry.get(tool, "help") is not None


def test_actions_for_sorts_help_first(isolated_registry):
    isolated_registry.register(
        Action(
            tool="ableton_session",
            name="set_tempo",
            description="",
            declarative_op=LiveOp(kind="property_write", target="song", property="tempo"),
            params=(ParamSpec(name="bpm", type="float"),),
        )
    )
    isolated_registry.register(
        Action(
            tool="ableton_session",
            name="info",
            description="",
            declarative_op=LiveOp(kind="property_read", target="song", property="tempo"),
        )
    )
    isolated_registry.register_help_actions()

    names = [a.name for a in isolated_registry.actions_for("ableton_session")]
    assert names[0] == "help"
    assert names[1:] == ["info", "set_tempo"]  # alphabetical after help


def test_required_and_optional_params_partition():
    action = Action(
        tool="ableton_track",
        name="set_property",
        description="",
        declarative_op=LiveOp(
            kind="property_write",
            target="song.tracks[{track_index-1}].mixer_device.volume",
            property="value",
        ),
        params=(
            ParamSpec(name="track_index", type="int", required=True),
            ParamSpec(name="property", type="str", required=True),
            ParamSpec(name="value", type="float", required=True),
            ParamSpec(name="ramp_ms", type="float", required=False),
        ),
    )
    assert action.required_params() == ("track_index", "property", "value")
    assert action.optional_params() == ("ramp_ms",)
