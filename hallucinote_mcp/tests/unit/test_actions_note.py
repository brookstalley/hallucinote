"""ableton_note schema + handler behavior.

V1 close-out Chunk D: the READ side (``list``) is functional, returning
notes with Live's stable per-note IDs via ``clip.get_notes_extended()``.
The write surface (add / update / delete) remains gap-#4-blocked —
those tests pin the blocked status as a regression gate.
"""
from __future__ import annotations

from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# Minimal fake context for the gap-4 stub tests (those handlers never
# touch the Live API). The `list` tests below use a richer mock with a
# track + clip_slot + clip tree because the real handler resolves a clip.
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


# --- Mocks for the now-functional list handler -----------------------------

class _FakeNote:
    """Mirror of Live's note specification — exposes the attributes the
    handler reads from ``clip.get_notes_extended()``."""

    def __init__(self, *, note_id, pitch, start_time, duration,
                 velocity=100, mute=False):
        self.note_id = note_id
        self.pitch = pitch
        self.start_time = start_time
        self.duration = duration
        self.velocity = velocity
        self.mute = mute


class _FakeClipWithNotes:
    """Stand-in for a Live Clip that exposes ``get_notes_extended``."""

    def __init__(self, *, length=16.0, notes=()):
        self.length = length
        self._notes = list(notes)

    def get_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        # Real Live filters by the given window; for tests we return all.
        # Track the call so contract tests can verify args.
        self.last_call = (from_pitch, pitch_span, from_time, time_span)
        return list(self._notes)


class _FakeSlot:
    def __init__(self, clip=None):
        self.clip = clip


class _FakeTrack:
    def __init__(self, clip_slots):
        self.clip_slots = clip_slots
        self.arrangement_clips: list = []


class _FakeSongWithTracks:
    def __init__(self, tracks):
        self.tracks = tracks
        self.return_tracks: list = []


class _FakeCtxWithSong:
    def __init__(self, song):
        self._song = song

    @property
    def song(self):
        return self._song

    def run_on_main(self, fn):
        return fn()


@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


_EXPECTED_NOTE_ACTIONS = {"help", "list", "add", "update", "delete"}
_BLOCKED_WRITE_ACTIONS = {"add", "update", "delete"}


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
        ("add",    {"track_index": 1, "location": "session", "clip_index": 1,
                    "notes": [{"pitch": 60, "start_time": 0, "duration": 1}]}),
        ("update", {"track_index": 1, "location": "session", "clip_index": 1,
                    "note_ids": [1, 2], "changes": {"velocity": 80}}),
        ("delete", {"track_index": 1, "location": "session", "clip_index": 1,
                    "note_ids": [1, 2]}),
    ],
)
def test_note_write_actions_return_gap_4_teaching_error(
    loaded_actions, action_name, params
):
    """Write actions (add/update/delete) remain gap-#4-blocked. The
    handler raises NotImplementedError with a teaching message; the
    dispatcher's broad-except wraps it as a structured error the LLM
    can read."""
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


def test_note_write_action_descriptions_signal_gap_4(loaded_actions):
    """Blocked write actions must carry the [BLOCKED] tag in their
    description so agents reading help see the status before trying
    to invoke. The `list` action is now functional and intentionally
    NOT in this set."""
    for name in _BLOCKED_WRITE_ACTIONS:
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


# ---------------------------------------------------------------------------
# `list` handler behavior — V1 close-out Chunk D (gap #4 partial)
# ---------------------------------------------------------------------------


def _ctx_with_notes(clip_with_notes):
    """Build a minimal context: one track, one session slot, the clip."""
    slot = _FakeSlot(clip=clip_with_notes)
    track = _FakeTrack(clip_slots=[slot])
    return _FakeCtxWithSong(_FakeSongWithTracks([track]))


def test_note_list_returns_notes_with_stable_ids(loaded_actions):
    clip = _FakeClipWithNotes(
        length=8.0,
        notes=[
            _FakeNote(note_id=101, pitch=60, start_time=0.0,
                      duration=1.0, velocity=100, mute=False),
            _FakeNote(note_id=102, pitch=64, start_time=1.0,
                      duration=0.5, velocity=80, mute=True),
        ],
    )
    resp = dispatch(
        Request(
            tool="ableton_note", action="list",
            params={"track_index": 1, "location": "session", "clip_index": 1},
        ),
        context=_ctx_with_notes(clip),
    )
    assert resp.ok is True, resp.error
    result = resp.result
    assert result["track_index"] == 1
    assert result["location"] == "session"
    assert result["clip_index"] == 1
    assert result["notes"] == [
        {"note_id": 101, "pitch": 60, "start_time": 0.0,
         "duration": 1.0, "velocity": 100, "mute": False},
        {"note_id": 102, "pitch": 64, "start_time": 1.0,
         "duration": 0.5, "velocity": 80, "mute": True},
    ]


def test_note_list_calls_get_notes_extended_with_full_range(loaded_actions):
    """Handler must request the full pitch range (0..128) and the full
    clip duration so the result is the complete note set, not a window."""
    clip = _FakeClipWithNotes(length=12.0, notes=[])
    dispatch(
        Request(
            tool="ableton_note", action="list",
            params={"track_index": 1, "location": "session", "clip_index": 1},
        ),
        context=_ctx_with_notes(clip),
    )
    assert clip.last_call == (0, 128, 0.0, 12.0)


def test_note_list_returns_empty_when_clip_has_no_notes(loaded_actions):
    clip = _FakeClipWithNotes(length=4.0, notes=[])
    resp = dispatch(
        Request(
            tool="ableton_note", action="list",
            params={"track_index": 1, "location": "session", "clip_index": 1},
        ),
        context=_ctx_with_notes(clip),
    )
    assert resp.ok is True
    assert resp.result["notes"] == []


def test_note_list_description_no_longer_marked_blocked(loaded_actions):
    """Regression gate: V1 close-out lifted the BLOCKED tag from `list`."""
    action = schema.get("ableton_note", "list")
    assert action is not None
    assert "BLOCKED" not in action.description
    assert "stable per-note IDs" in action.description


