"""ableton_clip schema + handler behavior."""
from __future__ import annotations

from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------- Fakes ----------


class FakeClip:
    """In-memory stand-in for a Live Clip object."""

    def __init__(
        self,
        *,
        name: str = "Clip",
        length: float = 16.0,
        start_time: float = 0.0,
        kind: str = "midi",
    ):
        self.name = name
        self.length = length
        self.start_time = start_time
        self._kind = kind
        # MIDI-style notes-storage; mirrors what set_notes() takes.
        self.notes: tuple[tuple[int, float, float, int, bool], ...] = ()
        # Properties handler exercises these attributes.
        self.loop_start = 0.0
        self.loop_end = float(length)
        self.muted = False
        self.color = 0
        # Audio-only attributes — only present on audio clips so the
        # set_property handler can branch.
        if kind == "audio":
            self.gain = 0.0
            self.pitch_coarse = 0
            self.warping = True

    def set_notes(self, notes_tuple: tuple[tuple[int, float, float, int, bool], ...]) -> None:
        self.notes = tuple(notes_tuple)

    def fire(self) -> None:  # not used directly on clip; clip_slot.fire fires
        pass


class FakeClipSlot:
    def __init__(self, clip: FakeClip | None = None):
        self.clip = clip
        self.fire_calls = 0
        self.stop_calls = 0

    def create_clip(self, length: float) -> None:
        if self.clip is not None:
            raise RuntimeError("slot already has a clip")
        self.clip = FakeClip(length=length)

    def delete_clip(self) -> None:
        self.clip = None

    def fire(self) -> None:
        self.fire_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


class FakeArrangementClip(FakeClip):
    """Marker subclass so tests can assert arrangement-vs-session origin."""


class FakeTrack:
    def __init__(
        self,
        *,
        name: str = "Track",
        kind: str = "midi",
        slots: int = 8,
        arrangement_clips: list[FakeArrangementClip] | None = None,
    ):
        self.name = name
        self._kind = kind
        self.clip_slots = [FakeClipSlot() for _ in range(slots)]
        self.arrangement_clips = arrangement_clips or []
        self.stop_all_clips_calls = 0
        self.duplicate_calls: list[tuple[Any, float]] = []

    def create_midi_clip(self, start_beats: float, length: float) -> None:
        self.arrangement_clips.append(
            FakeArrangementClip(start_time=start_beats, length=length, kind="midi")
        )

    def create_audio_clip(self, start_beats: float, length: float) -> None:
        self.arrangement_clips.append(
            FakeArrangementClip(start_time=start_beats, length=length, kind="audio")
        )

    def delete_clip(self, clip: FakeArrangementClip) -> None:
        self.arrangement_clips.remove(clip)

    def duplicate_clip_to_arrangement(
        self, source: FakeClip, destination_beats: float
    ) -> None:
        self.duplicate_calls.append((source, destination_beats))
        # Live appends a copy at destination_beats; we mirror.
        copy = FakeArrangementClip(
            name=source.name, length=source.length, start_time=destination_beats
        )
        # Live's duplicate copies the source's note array; mirror that.
        copy.notes = source.notes
        self.arrangement_clips.append(copy)

    def stop_all_clips(self) -> None:
        self.stop_all_clips_calls += 1


class FakeSong:
    def __init__(self, tracks: list[FakeTrack] | None = None):
        self.tracks = tracks if tracks is not None else [
            FakeTrack(name="Drums"),
            FakeTrack(name="Bass", kind="audio"),
            FakeTrack(name="Lead"),
        ]
        self.return_tracks: list[Any] = []


class FakeCtx:
    def __init__(self, song: FakeSong | None = None):
        self._song = song if song is not None else FakeSong()
        self.run_on_main_calls = 0

    @property
    def song(self) -> FakeSong:
        return self._song

    def run_on_main(self, fn):
        self.run_on_main_calls += 1
        return fn()


@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


# ---------- Schema sanity ----------


_EXPECTED_CLIP_ACTIONS = {
    "help", "create", "delete", "rename", "fire", "stop",
    "set_property", "duplicate_to_arrangement", "replace_notes",
}
# Quantize / swing / groove are deliberately NOT actions on this tool — they're
# pure-math timing transforms owned by Hallucinote (DB is source of truth for
# note timing). See design doc §6.2.


def test_clip_registers_nine_actions(loaded_actions):
    names = {a.name for a in schema.actions_for("ableton_clip")}
    assert names == _EXPECTED_CLIP_ACTIONS


def test_clip_does_not_expose_timing_transforms(loaded_actions):
    """quantize / apply_groove / extract_groove must NOT be MCP actions.

    These are pure-math operations on a note array; Hallucinote owns the
    compute (DB-as-source-of-truth) and pushes pre-grooved notes via
    replace_notes. Locking the surface here so a well-meaning future PR
    that "adds the obvious quantize action" gets caught by CI.
    """
    for name in ("quantize", "swing", "apply_groove", "extract_groove"):
        assert schema.get("ableton_clip", name) is None, (
            f"ableton_clip(action={name!r}) is intentionally not exposed — "
            "see design doc §6.2. Implement in Hallucinote-space and push "
            "via ableton_clip(action='replace_notes', ...)."
        )


def test_clip_help_lists_all_actions(loaded_actions):
    resp = dispatch(Request(tool="ableton_clip", action="help"))
    assert resp.ok is True
    names = {a["name"] for a in resp.result["actions"]}
    assert names == _EXPECTED_CLIP_ACTIONS - {"help"}


def test_clip_replace_notes_action_replaces_add_notes_to_clip_name(loaded_actions):
    """Gap #1: the renamed action must be called 'replace_notes', not 'add_notes_to_clip'."""
    action = schema.get("ableton_clip", "replace_notes")
    assert action is not None
    # The destructive semantic must be visible in the description.
    desc = action.description.lower()
    assert "replace" in desc
    assert "gap #1" in desc


# ---------- create — session ----------


def test_create_session_clip_in_empty_slot(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip",
            action="create",
            params={
                "track_index": 1, "location": "session",
                "kind": "midi", "length": 8.0, "clip_index": 1,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["clip_index"] == 1
    assert resp.result["length"] == 8.0
    assert ctx.song.tracks[0].clip_slots[0].clip is not None


def test_create_session_clip_with_notes_populates_atomically(loaded_actions):
    ctx = FakeCtx()
    notes = [
        {"pitch": 60, "start_time": 0.0, "duration": 1.0, "velocity": 100},
        {"pitch": 64, "start_time": 1.0, "duration": 1.0, "velocity": 80},
    ]
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "kind": "midi", "length": 4.0, "notes": notes,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["notes_written"] == 2
    clip = ctx.song.tracks[0].clip_slots[0].clip
    assert len(clip.notes) == 2
    assert clip.notes[0] == (60, 0.0, 1.0, 100, False)


def test_create_session_clip_errors_on_occupied_slot(loaded_actions):
    ctx = FakeCtx()
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip(name="Existing")
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "kind": "midi", "length": 8.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "already occupied" in (resp.error or "")
    assert "replace=True" in (resp.error or "")


def test_create_session_clip_with_replace_clobbers(loaded_actions):
    ctx = FakeCtx()
    existing = FakeClip(name="Existing")
    ctx.song.tracks[0].clip_slots[0].clip = existing
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "kind": "midi", "length": 4.0, "replace": True,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    new_clip = ctx.song.tracks[0].clip_slots[0].clip
    assert new_clip is not existing
    assert new_clip.length == 4.0


def test_create_session_clip_missing_clip_index_errors(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "session",
                "kind": "midi", "length": 8.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "clip_index" in (resp.error or "")


def test_create_session_audio_clip_unsupported(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "kind": "audio", "length": 4.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "audio" in (resp.error or "").lower()


# ---------- create — arrangement ----------


def test_create_arrangement_midi_clip(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "arrangement",
                "kind": "midi", "length": 16.0, "start_beats": 16.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["clip_index"] == 1
    assert resp.result["start_beats"] == 16.0
    arr = ctx.song.tracks[0].arrangement_clips
    assert len(arr) == 1
    assert arr[0].start_time == 16.0


def test_create_arrangement_clip_missing_start_beats_errors(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "arrangement",
                "kind": "midi", "length": 16.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "start_beats" in (resp.error or "")


# ---------- create — generic validation ----------


def test_create_rejects_unknown_location(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "wrong", "clip_index": 1,
                "kind": "midi", "length": 4.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "not in enum" in (resp.error or "")


def test_create_rejects_zero_length(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "kind": "midi", "length": 0.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "> 0" in (resp.error or "") or "must be > 0" in (resp.error or "")


# ---------- delete ----------


def test_delete_session_clip_clears_slot(loaded_actions):
    ctx = FakeCtx()
    ctx.song.tracks[0].clip_slots[2].clip = FakeClip()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="delete",
            params={"track_index": 1, "location": "session", "clip_index": 3},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["deleted"] is True
    assert ctx.song.tracks[0].clip_slots[2].clip is None


def test_delete_session_empty_slot_errors(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="delete",
            params={"track_index": 1, "location": "session", "clip_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "empty" in (resp.error or "")


def test_delete_arrangement_clip_removes_from_list(loaded_actions):
    ctx = FakeCtx()
    track = ctx.song.tracks[0]
    track.arrangement_clips = [FakeArrangementClip(name="A"), FakeArrangementClip(name="B")]
    resp = dispatch(
        Request(
            tool="ableton_clip", action="delete",
            params={"track_index": 1, "location": "arrangement", "clip_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert len(track.arrangement_clips) == 1
    assert track.arrangement_clips[0].name == "B"


# ---------- rename ----------


def test_rename_session_clip(loaded_actions):
    ctx = FakeCtx()
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip(name="Old")
    resp = dispatch(
        Request(
            tool="ableton_clip", action="rename",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "name": "Verse",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.tracks[0].clip_slots[0].clip.name == "Verse"


def test_rename_arrangement_clip(loaded_actions):
    ctx = FakeCtx()
    ctx.song.tracks[0].arrangement_clips = [FakeArrangementClip(name="Old")]
    resp = dispatch(
        Request(
            tool="ableton_clip", action="rename",
            params={
                "track_index": 1, "location": "arrangement", "clip_index": 1,
                "name": "Intro",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.tracks[0].arrangement_clips[0].name == "Intro"


# ---------- fire / stop ----------


def test_fire_session_clip(loaded_actions):
    ctx = FakeCtx()
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="fire",
            params={"track_index": 1, "clip_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.tracks[0].clip_slots[0].fire_calls == 1


def test_fire_empty_slot_errors(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="fire",
            params={"track_index": 1, "clip_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "empty" in (resp.error or "")


def test_stop_session_clip_uses_slot_stop(loaded_actions):
    ctx = FakeCtx()
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="stop",
            params={"track_index": 1, "clip_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.tracks[0].clip_slots[0].stop_calls == 1


# ---------- set_property ----------


@pytest.mark.parametrize(
    "property_name, value",
    [
        ("loop_start", 2.0),
        ("loop_end", 14.0),
        ("muted", 1.0),
        ("color", 12),
    ],
)
def test_set_property_writes_each_midi_field(loaded_actions, property_name, value):
    ctx = FakeCtx()
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="set_property",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "property": property_name, "value": value,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True


def test_set_property_audio_property_on_midi_clip_errors(loaded_actions):
    """Audio-only properties (gain) should surface a teaching error on MIDI clips.

    The handler's NotImplementedError message explicitly names the
    audio-only properties — agents reading the error should learn what
    works on which kind of clip. Assert that specific contract, not a
    softer alternative.
    """
    ctx = FakeCtx()
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip(kind="midi")
    resp = dispatch(
        Request(
            tool="ableton_clip", action="set_property",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "property": "gain", "value": 0.5,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    assert "audio-only" in err, (
        f"error message should explicitly cite the audio-only restriction "
        f"(teaching contract); got {resp.error!r}"
    )
    assert "gain" in err  # names the offending property
    assert "pitch" in err and "warp" in err  # lists the family for context


def test_set_property_audio_property_on_audio_clip_works(loaded_actions):
    ctx = FakeCtx()
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip(kind="audio")
    resp = dispatch(
        Request(
            tool="ableton_clip", action="set_property",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "property": "gain", "value": 0.5,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True


def test_set_property_out_of_range_errors(loaded_actions):
    ctx = FakeCtx()
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip(kind="audio")
    resp = dispatch(
        Request(
            tool="ableton_clip", action="set_property",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "property": "gain", "value": 2.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "out of range" in (resp.error or "")


# ---------- replace_notes ----------


def test_replace_notes_overwrites_existing(loaded_actions):
    ctx = FakeCtx()
    clip = FakeClip()
    clip.notes = ((60, 0.0, 1.0, 100, False),)
    ctx.song.tracks[0].clip_slots[0].clip = clip
    new_notes = [
        {"pitch": 67, "start_time": 0.0, "duration": 0.5, "velocity": 90},
        {"pitch": 69, "start_time": 0.5, "duration": 0.5, "velocity": 90},
    ]
    resp = dispatch(
        Request(
            tool="ableton_clip", action="replace_notes",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "notes": new_notes,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["notes_written"] == 2
    assert len(clip.notes) == 2
    assert clip.notes[0] == (67, 0.0, 0.5, 90, False)


def test_replace_notes_omits_clip_index_to_suppress_relink_event(loaded_actions):
    """Critic note 1: ``replace_notes`` MUST NOT return ``clip_index``.

    Hallucinote's apply layer maps ``clip:`` keys to ``clip_index`` for the
    ableton-link binding and emits an ``ABLETON_LINK_SET`` event per relink.
    In-place note replace doesn't change the binding; omitting the field
    causes apply to take its ``if result_field not in res`` skip-path, which
    keeps the audit-log clean. This contract is load-bearing for the future
    event-store flip — guard it with a test.
    """
    ctx = FakeCtx()
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="replace_notes",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "notes": [{"pitch": 60, "start_time": 0.0, "duration": 1.0}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert "clip_index" not in resp.result, (
        "replace_notes return must omit clip_index — see handler docstring"
    )


def test_replace_notes_supports_legacy_field_names(loaded_actions):
    """Agent may emit 'start'/'length' instead of 'start_time'/'duration'."""
    ctx = FakeCtx()
    clip = FakeClip()
    ctx.song.tracks[0].clip_slots[0].clip = clip
    notes = [{"pitch": 60, "start": 0.0, "length": 1.0, "velocity": 80}]
    resp = dispatch(
        Request(
            tool="ableton_clip", action="replace_notes",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "notes": notes,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert clip.notes[0] == (60, 0.0, 1.0, 80, False)


def test_replace_notes_rejects_out_of_range_pitch(loaded_actions):
    ctx = FakeCtx()
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="replace_notes",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "notes": [{"pitch": 200, "start_time": 0.0, "duration": 1.0}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "pitch" in (resp.error or "").lower()


def test_replace_notes_rejects_missing_start(loaded_actions):
    ctx = FakeCtx()
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="replace_notes",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "notes": [{"pitch": 60, "duration": 1.0}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "start" in (resp.error or "").lower()


# ---------- duplicate_to_arrangement ----------


def test_duplicate_to_arrangement(loaded_actions):
    ctx = FakeCtx()
    source = FakeClip(name="Loop")
    ctx.song.tracks[0].clip_slots[0].clip = source
    resp = dispatch(
        Request(
            tool="ableton_clip", action="duplicate_to_arrangement",
            params={"track_index": 1, "clip_index": 1, "start_beats": 32.0},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["arrangement_clip_index"] == 1
    assert resp.result["start_beats"] == 32.0
    track = ctx.song.tracks[0]
    assert len(track.duplicate_calls) == 1
    assert track.duplicate_calls[0][1] == 32.0


def test_duplicate_from_empty_slot_errors(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="duplicate_to_arrangement",
            params={"track_index": 1, "clip_index": 1, "start_beats": 16.0},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "empty" in (resp.error or "")


# ---------- run_on_main discipline ----------


def test_clip_execution_marshals_to_main_thread(loaded_actions):
    """The dispatcher must wrap every executor in run_on_main."""
    ctx = FakeCtx()
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip()
    dispatch(
        Request(
            tool="ableton_clip", action="rename",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "name": "X",
            },
        ),
        context=ctx,
    )
    assert ctx.run_on_main_calls == 1


# ---------- needs_remote forwarding signal ----------


def test_clip_validation_error_does_not_set_needs_remote(loaded_actions):
    """A param-level rejection on the server side must not forward to Live."""
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={"track_index": 1, "location": "wrong",
                    "kind": "midi", "length": 4.0},
        ),
        context=None,
    )
    assert resp.ok is False
    assert resp.needs_remote is False


def test_clip_valid_call_without_context_sets_needs_remote(loaded_actions):
    """Server-side dispatch with valid params but no Live context must
    signal 'forward me to the Remote Script'.
    """
    resp = dispatch(
        Request(
            tool="ableton_clip", action="rename",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "name": "X",
            },
        ),
        context=None,
    )
    assert resp.ok is False
    assert resp.needs_remote is True
