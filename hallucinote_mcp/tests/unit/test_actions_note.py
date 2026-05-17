"""ableton_note schema + handler behavior — gap-#4-blocked stubs."""
from __future__ import annotations

from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# A minimal fake context — note handlers are pure stubs and never touch
# the Live API, so we don't need a fleshed-out song model.
class FakeSong:
    pass


class FakeCtx:
    def __init__(self) -> None:
        self._song = FakeSong()

    @property
    def song(self) -> Any:
        return self._song

    def run_on_main(self, fn):
        return fn()


@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


_EXPECTED_NOTE_ACTIONS = {"help", "list", "add", "update", "delete"}


def test_note_registers_five_actions(loaded_actions):
    names = {a.name for a in schema.actions_for("ableton_note")}
    assert names == _EXPECTED_NOTE_ACTIONS


def test_note_help_lists_planned_surface(loaded_actions):
    resp = dispatch(Request(tool="ableton_note", action="help"))
    assert resp.ok is True
    # Help works without Live, so agents can read the planned action menu
    # even though every other action is blocked.
    names = {a["name"] for a in resp.result["actions"]}
    assert names == _EXPECTED_NOTE_ACTIONS - {"help"}


def test_note_help_description_signals_the_gap(loaded_actions):
    """The help description must surface the gap-#4 blocker up front."""
    help_action = schema.get("ableton_note", "help")
    assert help_action is not None
    assert "gap #4" in help_action.description.lower()


@pytest.mark.parametrize(
    "action_name, params",
    [
        ("list",   {"track_index": 1, "location": "session", "clip_index": 1}),
        ("add",    {"track_index": 1, "location": "session", "clip_index": 1,
                    "notes": [{"pitch": 60, "start_time": 0, "duration": 1}]}),
        ("update", {"track_index": 1, "location": "session", "clip_index": 1,
                    "note_ids": [1, 2], "changes": {"velocity": 80}}),
        ("delete", {"track_index": 1, "location": "session", "clip_index": 1,
                    "note_ids": [1, 2]}),
    ],
)
def test_note_actions_return_gap_4_teaching_error(loaded_actions, action_name, params):
    """Every non-help action raises NotImplementedError with the gap-#4
    message — the dispatcher's broad-except wraps it into a structured
    error response that the LLM can read."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(tool="ableton_note", action=action_name, params=params),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    assert "gap #4" in err
    # Suggests the working alternative.
    assert "replace_notes" in err.lower()


def test_note_action_descriptions_signal_gap_4(loaded_actions):
    """Each blocked action's description must visibly carry the [BLOCKED] tag
    so agents reading help see the status before trying to invoke it.
    """
    for name in ("list", "add", "update", "delete"):
        action = schema.get("ableton_note", name)
        assert action is not None, name
        assert "BLOCKED" in action.description
        assert "gap #4" in action.description.lower()


def test_note_validation_runs_before_stub_fires(loaded_actions):
    """The gap-#4 stub must not eat malformed-param errors — validation
    happens upstream of the handler, so the agent sees a normal validation
    error for bad params, not a misleading gap-#4 error.
    """
    ctx = FakeCtx()
    resp = dispatch(
        # Missing required note_ids
        Request(
            tool="ableton_note", action="delete",
            params={"track_index": 1, "location": "session", "clip_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "note_ids" in (resp.error or "")
    # Must NOT have surfaced gap #4 — that's a separate concern.
    assert "gap #4" not in (resp.error or "").lower()


def test_note_validation_runs_on_invalid_location(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_note", action="list",
            params={"track_index": 1, "location": "wrong", "clip_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "not in enum" in (resp.error or "")
