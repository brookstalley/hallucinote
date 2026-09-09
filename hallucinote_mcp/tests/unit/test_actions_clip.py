"""ableton_clip schema + handler behavior."""
from __future__ import annotations

from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------- Fakes ----------


# Live's two recorded refusals from ``create_audio_clip``, verbatim
# (docs/research/audio-first-class/lom-probe-results.md row 1c, executed
# against Live 12.4.1). The fakes raise these exact strings so the handler's
# error mapping is tested against what Live really says, not a paraphrase.
LIVE_WRONG_TRACK_ERROR = "Audio clips can only be created on audio tracks"
LIVE_BAD_PATH_ERROR = (
    "The provided path does not appear to point to a valid audio file"
)
# The third shape, recorded on Live 12.4.5 (probe row 17): Live checks
# absoluteness BEFORE existence, with its own string. The handler's own
# pre-check normally refuses a relative path first, so the fake filesystem
# never raises this — it is exercised directly against the mapper.
LIVE_RELATIVE_PATH_ERROR = "Please provide an absolute path"

# The one path the fake "filesystem" holds. Anything else refuses the way
# Live refuses a missing or undecodable file.
PROBE_WAV = "/tmp/aud1m4v_probe.wav"


class FakeClip:
    """In-memory stand-in for a Live Clip object."""

    def __init__(
        self,
        *,
        name: str = "Clip",
        length: float = 16.0,
        start_time: float = 0.0,
        kind: str = "midi",
        file_path: str = PROBE_WAV,
    ):
        self.name = name
        self.length = length
        self.start_time = start_time
        self._kind = kind
        # Live exposes ``clip.is_midi_clip`` and ``clip.is_audio_clip`` as
        # the kind discriminators; mirror both so handlers that pre-check
        # the kind (Wave-2 W2-C / B-26) and the list reader's ``is_audio``
        # hit our fake faithfully.
        self.is_midi_clip = (kind == "midi")
        self.is_audio_clip = (kind == "audio")
        # MIDI-style notes-storage; mirrors what set_notes() takes.
        self.notes: tuple[tuple[int, float, float, int, bool], ...] = ()
        # Properties handler exercises these attributes.
        self.loop_start = 0.0
        self.loop_end = float(length)
        self.muted = False
        self.color = 0
        # Markers exist on both clip kinds in Live (beats when warped,
        # seconds when not).
        self.start_marker = 0.0
        self.end_marker = float(length)
        # Audio-only attributes — only present on audio clips so the
        # set_property handler can branch.
        if kind == "audio":
            self.file_path = file_path
            self.gain = 0.0
            self.pitch_coarse = 0
            self.pitch_fine = 0.0
            self.warping = True
            self.warp_mode = 0

    def set_notes(self, notes_tuple: tuple[tuple[int, float, float, int, bool], ...]) -> None:
        self.notes = tuple(notes_tuple)

    def get_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        # Count-only stand-in: the arrangement list reads len(...) for
        # note_count. Returns one item per stored note (real Live windows by
        # the args; the full-range list-read passes the whole clip span).
        return list(self.notes)

    def remove_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        # Faithful windowed remove: drop notes whose (pitch, start) fall in the
        # [from_pitch, from_pitch+span) x [from_time, from_time+span) window.
        # replace_notes clears the full extent (0,128,0,length) before writing.
        lo_p, hi_p = from_pitch, from_pitch + pitch_span
        lo_t, hi_t = from_time, from_time + time_span
        self.notes = tuple(
            n for n in self.notes
            if not (lo_p <= n[0] < hi_p and lo_t <= n[1] < hi_t)
        )

    def fire(self) -> None:  # not used directly on clip; clip_slot.fire fires
        pass


class FakeClipSlot:
    def __init__(
        self,
        clip: FakeClip | None = None,
        *,
        track_kind: str = "midi",
        audio_files: tuple[str, ...] = (PROBE_WAV,),
    ):
        self.clip = clip
        self.fire_calls = 0
        self.stop_calls = 0
        # What the host track is, and what the fake filesystem holds —
        # both are what Live checks before it will make an audio clip.
        self._track_kind = track_kind
        self._audio_files = audio_files

    def create_clip(self, length: float) -> None:
        if self.clip is not None:
            raise RuntimeError("slot already has a clip")
        self.clip = FakeClip(length=length)

    def create_audio_clip(self, file_path: str) -> FakeClip:
        """Live 12.2+'s ClipSlot.create_audio_clip(abs_path) — one argument.

        Refuses exactly as Live 12.4.1 did under probe row 1c: a MIDI host
        track raises RuntimeError, an unloadable path raises ValueError.
        The clip's length comes from the "file", never from the caller.
        """
        if self._track_kind != "audio":
            raise RuntimeError(LIVE_WRONG_TRACK_ERROR)
        if file_path not in self._audio_files:
            raise ValueError(LIVE_BAD_PATH_ERROR)
        if self.clip is not None:
            raise RuntimeError("slot already has a clip")
        # 2.0s file at 120bpm read back as 4.0 beats in the probe.
        self.clip = FakeClip(length=4.0, kind="audio", file_path=file_path)
        return self.clip

    def delete_clip(self) -> None:
        self.clip = None

    def fire(self) -> None:
        self.fire_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


class FakeArrangementClip(FakeClip):
    """Marker subclass so tests can assert arrangement-vs-session origin."""


class OrphanProneArrangementClip(FakeArrangementClip):
    """Models Live's observed ARR-ORPHAN behavior: ``set_notes`` on an
    arrangement clip does NOT clear pre-existing notes — it MERGES the new
    array in, collapsing on (pitch, start) the way Live does, so notes from an
    older write generation at distinct (pitch, start) survive. ``remove_notes_
    extended`` (inherited) DOES clear properly, so a full-extent clear before
    the merge restores total-replace. This is the bug the prevention fix kills.
    """

    def set_notes(self, notes_tuple):
        merged = {(n[0], n[1]): n for n in self.notes}
        for n in notes_tuple:
            merged[(n[0], n[1])] = n
        self.notes = tuple(merged.values())


class StubbornOrphanArrangementClip(OrphanProneArrangementClip):
    """Worst case: the merge-not-replace ``set_notes`` AND a no-op clear, so
    orphans cannot be removed. Used to prove the read-back diagnostic surfaces
    a warning (notes_present > notes_written) when a clear genuinely fails."""

    def remove_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        pass  # clear fails — orphans persist


class FakeTrack:
    def __init__(
        self,
        *,
        name: str = "Track",
        kind: str = "midi",
        slots: int = 8,
        arrangement_clips: list[FakeArrangementClip] | None = None,
        audio_files: tuple[str, ...] = (PROBE_WAV,),
    ):
        self.name = name
        self._kind = kind
        self._audio_files = audio_files
        self.clip_slots = [
            FakeClipSlot(track_kind=kind, audio_files=audio_files)
            for _ in range(slots)
        ]
        self.arrangement_clips = arrangement_clips or []
        self.stop_all_clips_calls = 0
        self.duplicate_calls: list[tuple[Any, float]] = []

    def create_midi_clip(self, start_beats: float, length: float) -> None:
        self.arrangement_clips.append(
            FakeArrangementClip(start_time=start_beats, length=length, kind="midi")
        )
        self.arrangement_clips.sort(key=lambda c: c.start_time)

    def create_audio_clip(
        self, file_path: str, start_beats: float
    ) -> FakeArrangementClip:
        """Live's Track.create_audio_clip(path, position) — path FIRST.

        The mirror image of create_midi_clip(position, length): the file
        supplies the length, so the caller does not. Refusals are Live's own
        (probe row 1c).
        """
        if self._kind != "audio":
            raise RuntimeError(LIVE_WRONG_TRACK_ERROR)
        if file_path not in self._audio_files:
            raise ValueError(LIVE_BAD_PATH_ERROR)
        clip = FakeArrangementClip(
            start_time=start_beats, length=4.0, kind="audio",
            file_path=file_path,
        )
        self.arrangement_clips.append(clip)
        self.arrangement_clips.sort(key=lambda c: c.start_time)
        return clip

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
        copy.notes = source.notes
        # Live 12.4 B-24 side effect: when the destination region
        # overlaps an existing arrangement clip, Live emits a SECOND
        # copy of the overlapped clip starting at
        # ``destination_beats + source.length`` (the right-half-of-the-split,
        # but as a new arrangement clip). The original overlapped
        # clip stays in place. Mirror that behavior so the handler's
        # Wave-2 W2-H cleanup is exercised against a Live-faithful
        # fake.
        dest_end = destination_beats + source.length
        for existing in list(self.arrangement_clips):
            ex_start = existing.start_time
            ex_end = existing.start_time + existing.length
            # Overlap when destination intersects existing's interval.
            if ex_start < dest_end and ex_end > destination_beats:
                spurious = FakeArrangementClip(
                    name=existing.name,
                    length=existing.length,
                    start_time=dest_end,
                    kind=getattr(existing, "_kind", "midi"),
                )
                self.arrangement_clips.append(spurious)
                # Live only splits ONE overlapping clip per call (the
                # one whose interval contains destination_beats). Break
                # after the first match.
                break
        self.arrangement_clips.append(copy)
        # Keep arrangement_clips sorted by start_time (Live's invariant).
        self.arrangement_clips.sort(key=lambda c: c.start_time)

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

    def run_on_main(self, fn, **_kwargs):
        self.run_on_main_calls += 1
        return fn()


@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


# ---------- Schema sanity ----------


_EXPECTED_CLIP_ACTIONS = {
    "help", "list", "create", "delete", "rename", "fire", "stop",
    "set_property", "duplicate_to_arrangement", "replace_notes",
}
# Quantize / swing / groove are deliberately NOT actions on this tool — they're
# pure-math timing transforms owned by Hallucinote (DB is source of truth for
# note timing). See design doc §6.2.


def test_clip_registers_ten_actions(loaded_actions):
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


# ---------- list ----------


def test_list_session_returns_every_slot_with_empties(loaded_actions):
    """Session list emits one entry per slot — empty slots carry
    {clip_index, empty: True}; populated slots add name, length and the
    is_audio discriminator (audio conform fields ride along only when it is
    true — see the read-surface section)."""
    track = FakeTrack(name="T1", slots=4)
    track.clip_slots[0].clip = FakeClip(name="Verse", length=16.0)
    track.clip_slots[2].clip = FakeClip(name="Chorus", length=8.0)
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 1, "location": "session"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["track_index"] == 1
    assert resp.result["location"] == "session"
    clips = resp.result["clips"]
    assert len(clips) == 4
    assert clips[0] == {
        "clip_index": 1, "empty": False, "name": "Verse", "length": 16.0,
        "is_audio": False,
    }
    assert clips[1] == {"clip_index": 2, "empty": True}
    assert clips[2] == {
        "clip_index": 3, "empty": False, "name": "Chorus", "length": 8.0,
        "is_audio": False,
    }
    assert clips[3] == {"clip_index": 4, "empty": True}


def test_list_session_all_empty_track(loaded_actions):
    track = FakeTrack(name="T1", slots=3)
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 1, "location": "session"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["clips"] == [
        {"clip_index": 1, "empty": True},
        {"clip_index": 2, "empty": True},
        {"clip_index": 3, "empty": True},
    ]


def test_list_arrangement_returns_placements_with_indices(loaded_actions):
    """Arrangement list returns 1-based arrangement_clip_index, name,
    start_beats, length, muted, note_count, is_audio — preserves order from
    track.arrangement_clips."""
    arr = [
        FakeArrangementClip(name="A", start_time=0.0, length=8.0),
        FakeArrangementClip(name="B", start_time=8.0, length=8.0),
        FakeArrangementClip(name="C", start_time=24.5, length=16.5),
    ]
    track = FakeTrack(name="T1", arrangement_clips=arr)
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 1, "location": "arrangement"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["track_index"] == 1
    assert resp.result["location"] == "arrangement"
    clips = resp.result["clips"]
    assert len(clips) == 3
    assert clips[0] == {
        "arrangement_clip_index": 1, "name": "A",
        "start_beats": 0.0, "length": 8.0, "muted": False, "note_count": 0,
        "is_audio": False,
    }
    assert clips[1] == {
        "arrangement_clip_index": 2, "name": "B",
        "start_beats": 8.0, "length": 8.0, "muted": False, "note_count": 0,
        "is_audio": False,
    }
    assert clips[2] == {
        "arrangement_clip_index": 3, "name": "C",
        "start_beats": 24.5, "length": 16.5, "muted": False, "note_count": 0,
        "is_audio": False,
    }


def test_list_arrangement_reports_note_count_and_muted(loaded_actions):
    """note_count distinguishes a full placement from an empty one (the 'track
    shows no events' question a bare name/length can't answer); muted surfaces a
    silenced placement. A MIDI clip with notes reports their count."""
    full = FakeArrangementClip(name="Full", start_time=0.0, length=8.0)
    full.set_notes((
        (60, 0.0, 1.0, 100, False),
        (62, 1.0, 1.0, 100, False),
        (64, 2.0, 1.0, 100, False),
    ))
    empty = FakeArrangementClip(name="Empty", start_time=8.0, length=400.0)
    empty.muted = True
    track = FakeTrack(name="T1", arrangement_clips=[full, empty])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 1, "location": "arrangement"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    clips = resp.result["clips"]
    assert clips[0]["name"] == "Full"
    assert clips[0]["note_count"] == 3
    assert clips[0]["muted"] is False
    # A long but empty clip is indistinguishable from a full one on name/length
    # alone — note_count is what reveals it.
    assert clips[1]["name"] == "Empty"
    assert clips[1]["note_count"] == 0
    assert clips[1]["muted"] is True


def test_list_arrangement_audio_clip_note_count_is_none(loaded_actions):
    """note_count is MIDI-only (get_notes_extended raises on audio clips), so an
    audio arrangement clip reports note_count=None rather than crashing."""
    audio = FakeArrangementClip(name="Stem", start_time=0.0, length=16.0, kind="audio")
    track = FakeTrack(name="Audio", kind="audio", arrangement_clips=[audio])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 1, "location": "arrangement"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    entry = resp.result["clips"][0]
    assert entry["note_count"] is None
    assert entry["muted"] is False


def test_list_arrangement_empty_track(loaded_actions):
    track = FakeTrack(name="T1", arrangement_clips=[])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 1, "location": "arrangement"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["clips"] == []


def test_list_arrangement_preserves_float_fidelity(loaded_actions):
    """Float positions / lengths round-trip without rounding."""
    arr = [
        FakeArrangementClip(
            name="Fractional", start_time=1.3333333, length=2.6666667,
        ),
    ]
    track = FakeTrack(name="T1", arrangement_clips=arr)
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 1, "location": "arrangement"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    clip = resp.result["clips"][0]
    assert clip["start_beats"] == pytest.approx(1.3333333, rel=0, abs=1e-9)
    assert clip["length"] == pytest.approx(2.6666667, rel=0, abs=1e-9)


def test_list_out_of_range_track_index_errors(loaded_actions):
    ctx = FakeCtx()  # default song has 3 tracks
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 99, "location": "session"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "track_index" in (resp.error or "")
    assert "out of range" in (resp.error or "")


def test_list_bad_location_errors(loaded_actions):
    """The schema enum should reject before the handler sees it; either
    way the request fails."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 1, "location": "bogus"},
        ),
        context=ctx,
    )
    assert resp.ok is False


def test_list_arrangement_index_is_arrangement_clip_index_not_clip_index(
    loaded_actions,
):
    """Terminology contract: arrangement entries must use
    'arrangement_clip_index', not 'clip_index'. See docs/terminology.md —
    'clip_index' is reserved for session slots; arrangement placements use
    the fully qualified name to keep the two senses unconfused.
    """
    arr = [FakeArrangementClip(name="A", start_time=0.0, length=4.0)]
    track = FakeTrack(name="T1", arrangement_clips=arr)
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 1, "location": "arrangement"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    entry = resp.result["clips"][0]
    assert "arrangement_clip_index" in entry
    assert "clip_index" not in entry


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


def test_create_session_audio_clip_on_a_midi_track_teaches_the_fix(loaded_actions):
    """Session audio creation is supported now (Live 12.2's
    ClipSlot.create_audio_clip), so the only thing left to refuse here is
    the host: track 1 is a MIDI track. Live answers that with a bare
    RuntimeError; the handler must turn it into an instruction.
    """
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "kind": "audio", "audio_path": PROBE_WAV,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "audio track" in err.lower(), err
    # The fix, not just the diagnosis.
    assert "kind='audio'" in err, err
    # Live's own words are quoted so the operator can search for them.
    assert LIVE_WRONG_TRACK_ERROR.lower() in err.lower(), err


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
    assert resp.result["arrangement_clip_index"] == 1
    assert resp.result["start_beats"] == 16.0
    arr = ctx.song.tracks[0].arrangement_clips
    assert len(arr) == 1
    assert arr[0].start_time == 16.0


# Regression: real Live re-wraps API objects on each property access, so
# scanning ``track.arrangement_clips`` for ``c is new_clip`` used to
# spuriously fail and the result was missing the ``arrangement_clip_index``
# field — the apply layer's link recorder reads that field, so a missing
# index broke the link write silently. The fix resolves by start-time
# match instead of identity (Live's arrangement_clips are start-sorted).


class _WrapperRecreatingArrangementTrack:
    """Underlying clip data is stable; every ``arrangement_clips`` access
    returns a fresh list of fresh wrappers. Mirrors Live 12.x's wrapper
    semantics."""

    def __init__(self) -> None:
        # list of {"start_time", "length", "kind", "name"}
        self._underlying: list[dict] = []

    @property
    def arrangement_clips(self):
        return [_FreshClipWrapper(d) for d in self._underlying]

    def create_midi_clip(self, start_beats: float, length: float) -> None:
        self._underlying.append(
            {"start_time": float(start_beats), "length": float(length),
             "kind": "midi", "name": ""}
        )


class _FreshClipWrapper:
    def __init__(self, data: dict) -> None:
        self._data = data
        # Notes accumulator the handler may call set_notes on.
        self._notes: list = []

    @property
    def start_time(self) -> float:
        return self._data["start_time"]

    @property
    def length(self) -> float:
        return self._data["length"]

    @property
    def name(self) -> str:
        return self._data["name"]

    @name.setter
    def name(self, value: str) -> None:
        self._data["name"] = value

    def set_notes(self, notes) -> None:  # pragma: no cover — exercised indirectly
        self._notes = list(notes)


class _ArrangementClipSong:
    def __init__(self) -> None:
        self.tracks = [_WrapperRecreatingArrangementTrack()]


class _ArrangementClipCtx:
    def __init__(self) -> None:
        self._song = _ArrangementClipSong()

    @property
    def song(self):
        return self._song

    def run_on_main(self, fn, **_kwargs):
        return fn()


def test_create_arrangement_clip_returns_index_under_wrapper_recreation(
    loaded_actions,
):
    """First clip in an empty track → arrangement_clip_index == 1, even
    when the wrapper returned by Live's create_*_clip is not ``is``-equal
    to anything in ``track.arrangement_clips``."""
    ctx = _ArrangementClipCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "arrangement",
                "kind": "midi", "length": 16.0, "start_beats": 16.0,
                "name": "Intro",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert resp.result["arrangement_clip_index"] == 1
    assert resp.result["start_beats"] == 16.0


def test_create_arrangement_clip_index_for_second_clip_under_wrapper_recreation(
    loaded_actions,
):
    """A second clip created later in time lands at arrangement_clip_index 2
    (start-sorted). Catches an off-by-one if the lookup ever returned the
    first clip instead of the new one."""
    ctx = _ArrangementClipCtx()
    # First clip at beat 0.
    dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "arrangement",
                "kind": "midi", "length": 8.0, "start_beats": 0.0,
            },
        ),
        context=ctx,
    )
    # Second clip at beat 16.
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "arrangement",
                "kind": "midi", "length": 8.0, "start_beats": 16.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["arrangement_clip_index"] == 2


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
    # Nothing overridden → no teaching block on the result.
    assert "still_overridden" not in resp.result


def test_stop_session_clip_teaches_when_arrangement_still_overridden(loaded_actions):
    """Stopping the Session clip does not clear the global override latch, so
    the track stays silent. The result must say so (still_overridden + a note
    naming the recovery) instead of a bare stopped:true (MCP-7P3R direction 4)."""
    ctx = FakeCtx()
    ctx.song.back_to_arranger = 1  # a leftover firing clip elsewhere keeps it latched
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="stop",
            params={"track_index": 1, "clip_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["stopped"] is True
    assert resp.result["still_overridden"] is True
    assert "Back to Arrangement" in resp.result["note"]


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
    assert resp.result["notes_present"] == 2
    assert len(clip.notes) == 2
    assert clip.notes[0] == (67, 0.0, 0.5, 90, False)


def test_replace_notes_arrangement_clears_orphans_before_write(loaded_actions):
    """ARR-ORPHAN: on an arrangement clip whose ``set_notes`` does NOT clear
    pre-existing notes (Live's observed behavior), replace_notes must still
    leave exactly the written set — the full-extent clear removes the older-
    generation orphans before the merge-style ``set_notes`` runs. Without the
    clear, the clip would keep the 5 stale notes (the alien Drums chorus2 bug).
    """
    orphans = (
        # 5 older-generation notes at distinct (pitch, start), inside the clip
        # extent — the shape that survived on alien's Drums chorus2.
        (40, 22.5, 0.25, 30, False),
        (42, 23.0, 0.25, 28, False),
        (44, 24.0, 0.25, 31, False),
        (46, 25.5, 0.25, 27, False),
        (48, 26.0, 0.25, 29, False),
    )
    clip = OrphanProneArrangementClip(name="Drums chorus2", length=32.0)
    clip.notes = orphans
    track = FakeTrack(name="Drums", arrangement_clips=[clip])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    new_notes = [
        {"pitch": 36, "start_time": float(i), "duration": 0.5, "velocity": 100}
        for i in range(8)
    ]
    resp = dispatch(
        Request(
            tool="ableton_clip", action="replace_notes",
            params={
                "track_index": 1, "location": "arrangement", "clip_index": 1,
                "notes": new_notes,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    # Orphans gone: clip holds exactly the 8 written notes, none of the 5 old.
    assert len(clip.notes) == 8
    assert all(n[0] == 36 for n in clip.notes)
    assert resp.result["notes_written"] == 8
    assert resp.result["notes_present"] == 8
    assert "warning" not in resp.result  # faithful → no orphan warning


def test_replace_notes_reports_orphan_survival_when_clear_fails(loaded_actions):
    """Diagnostic read-back: if a clear genuinely fails (modeled by a no-op
    remove + merge-style ``set_notes``), the post-write read-back surfaces it —
    ``notes_present`` exceeds ``notes_written`` and a warning names the
    orphan-survival, so a caller never trusts a silent lie again."""
    orphans = (
        (40, 22.5, 0.25, 30, False),
        (42, 23.0, 0.25, 28, False),
    )
    clip = StubbornOrphanArrangementClip(name="Drums chorus2", length=32.0)
    clip.notes = orphans
    track = FakeTrack(name="Drums", arrangement_clips=[clip])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    new_notes = [
        {"pitch": 36, "start_time": float(i), "duration": 0.5, "velocity": 100}
        for i in range(4)
    ]
    resp = dispatch(
        Request(
            tool="ableton_clip", action="replace_notes",
            params={
                "track_index": 1, "location": "arrangement", "clip_index": 1,
                "notes": new_notes,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["notes_written"] == 4
    assert resp.result["notes_present"] == 6  # 4 written + 2 surviving orphans
    assert "warning" in resp.result
    assert "orphan-survival" in resp.result["warning"]
    assert "2 unexpected" in resp.result["warning"]


def test_replace_notes_collapse_does_not_warn(loaded_actions):
    """Cry-wolf guard: Live collapses same-(pitch, start) notes, so a faithful
    write of stacked notes (e.g. add_wildness) legitimately yields FEWER notes
    in the clip. ``notes_present`` < ``notes_written`` must NOT warn — only an
    EXCESS signals a leak (the capability report's normalization #1)."""
    clip = OrphanProneArrangementClip(name="Riff", length=32.0)  # starts empty
    track = FakeTrack(name="Riff", arrangement_clips=[clip])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    stacked = [
        {"pitch": 40, "start_time": 0.0, "duration": 1.0, "velocity": 100},
        # same (pitch, start) as above — Live keeps one; a faithful collapse.
        {"pitch": 40, "start_time": 0.0, "duration": 0.5, "velocity": 60},
        {"pitch": 42, "start_time": 1.0, "duration": 1.0, "velocity": 100},
    ]
    resp = dispatch(
        Request(
            tool="ableton_clip", action="replace_notes",
            params={
                "track_index": 1, "location": "arrangement", "clip_index": 1,
                "notes": stacked,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["notes_written"] == 3
    assert resp.result["notes_present"] == 2  # collapsed to 2 distinct (pitch,start)
    assert "warning" not in resp.result  # collapse is faithful, not a leak


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


def test_duplicate_to_arrangement_cleans_up_spurious_split_clip(loaded_actions):
    """Wave-2 W2-H / B-24: when the destination region overlaps an
    existing arrangement clip, Live emits a spurious second copy of the
    overlapped clip at ``dest_beats + source.length``. The handler
    detects + deletes it.

    Real-Live repro:
      - Scaffold at 0..32 already in arrangement
      - duplicate_to_arrangement(clip_index=N, start_beats=16) where
        source slot N is a 4-beat DupSource clip
      - Pre-fix result: [Scaffold 0..32, DupSource 16..20, Scaffold 20..52]
      - Post-fix result: [Scaffold 0..32, DupSource 16..20] — the
        third clip is deleted, and `spurious_clips_removed` reports it.
    """
    ctx = FakeCtx()
    track = ctx.song.tracks[0]
    # Existing Scaffold clip at 0..32.
    track.arrangement_clips.append(
        FakeArrangementClip(name="Scaffold", length=32.0, start_time=0.0)
    )
    # Session source: a 4-beat DupSource clip.
    dup_source = FakeClip(name="DupSource", length=4.0)
    track.clip_slots[1].clip = dup_source

    resp = dispatch(
        Request(
            tool="ableton_clip", action="duplicate_to_arrangement",
            params={"track_index": 1, "clip_index": 2, "start_beats": 16.0},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    # The requested duplicate lands at 16..20.
    assert resp.result["start_beats"] == 16.0
    # Arrangement state: just the original Scaffold + the requested DupSource.
    names_and_starts = [
        (c.name, c.start_time) for c in track.arrangement_clips
    ]
    assert names_and_starts == [
        ("Scaffold", 0.0),
        ("DupSource", 16.0),
    ], f"unexpected arrangement state: {names_and_starts}"
    # The handler reports the cleanup.
    removed = resp.result.get("spurious_clips_removed") or []
    assert len(removed) == 1
    assert removed[0]["name"] == "Scaffold"
    assert removed[0]["start_beats"] == 20.0
    assert removed[0]["length"] == 32.0


def test_duplicate_to_arrangement_per_clip_delete_fallback(loaded_actions):
    """When Track.delete_clip raises, the handler tries per-clip
    ``clip.delete()`` as a fallback. Build a FakeTrack where
    delete_clip raises but FakeArrangementClip exposes ``.delete()``,
    and confirm the spurious clip still goes away (reported in
    spurious_clips_removed, NOT spurious_clips_remaining).
    """
    ctx = FakeCtx()
    track = ctx.song.tracks[0]
    track.arrangement_clips.append(
        FakeArrangementClip(name="Scaffold", length=32.0, start_time=0.0)
    )
    track.clip_slots[1].clip = FakeClip(name="DupSource", length=4.0)

    # Override Track.delete_clip to raise — forces the fallback.
    def _raise(_clip):
        raise RuntimeError("simulated: Track.delete_clip not supported")
    track.delete_clip = _raise

    # Add per-clip delete() to the arrangement clips (FakeArrangementClip
    # doesn't have one by default).
    for c in track.arrangement_clips:
        c.delete = lambda c=c: track.arrangement_clips.remove(c)

    # The spurious clip will be added by duplicate; its `delete` won't
    # exist yet. The handler's fallback chain uses getattr — and clips
    # that lack the method end up in `spurious_clips_remaining`. To
    # specifically exercise the fallback-success path, attach delete()
    # to NEW arrangement clips too via a track-level hook. Simplest:
    # monkey-patch the fake's duplicate to add `.delete` to new clips.
    original_duplicate = track.duplicate_clip_to_arrangement.__func__

    def patched_duplicate(self, source, dest):
        original_duplicate(self, source, dest)
        for c in self.arrangement_clips:
            if not hasattr(c, "delete"):
                c.delete = lambda c=c: self.arrangement_clips.remove(c)
    track.duplicate_clip_to_arrangement = patched_duplicate.__get__(track)

    resp = dispatch(
        Request(
            tool="ableton_clip", action="duplicate_to_arrangement",
            params={"track_index": 1, "clip_index": 2, "start_beats": 16.0},
        ),
        context=ctx,
    )
    assert resp.ok is True
    removed = resp.result.get("spurious_clips_removed") or []
    assert len(removed) == 1, (
        f"per-clip delete fallback should have cleaned up the spurious "
        f"clip. Result: {resp.result!r}"
    )
    assert "spurious_clips_remaining" not in resp.result


def test_duplicate_to_arrangement_reports_undeletable_spurious(loaded_actions):
    """When neither Track.delete_clip nor per-clip delete is exposed,
    the handler reports the spurious clip in spurious_clips_remaining
    so the agent knows the cleanup is incomplete (best-effort
    contract).
    """
    ctx = FakeCtx()
    track = ctx.song.tracks[0]
    track.arrangement_clips.append(
        FakeArrangementClip(name="Scaffold", length=32.0, start_time=0.0)
    )
    track.clip_slots[1].clip = FakeClip(name="DupSource", length=4.0)

    # Remove both delete paths.
    def _no_delete(_clip):
        raise RuntimeError("simulated")
    track.delete_clip = _no_delete
    # Don't add .delete to the arrangement clips.

    resp = dispatch(
        Request(
            tool="ableton_clip", action="duplicate_to_arrangement",
            params={"track_index": 1, "clip_index": 2, "start_beats": 16.0},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    # The requested clip IS in place.
    assert resp.result["start_beats"] == 16.0
    # The spurious clip is reported but not removed.
    remaining = resp.result.get("spurious_clips_remaining") or []
    assert len(remaining) == 1
    assert remaining[0]["start_beats"] == 20.0
    assert "spurious_clips_removed" not in resp.result


def test_duplicate_to_arrangement_no_overlap_no_spurious(loaded_actions):
    """When the destination doesn't overlap any existing clip, the
    cleanup path is a no-op — no spurious_clips_removed key in the
    response.
    """
    ctx = FakeCtx()
    track = ctx.song.tracks[0]
    # Existing clip well clear of the destination.
    track.arrangement_clips.append(
        FakeArrangementClip(name="Far", length=4.0, start_time=64.0)
    )
    source = FakeClip(name="Loop", length=8.0)
    track.clip_slots[0].clip = source

    resp = dispatch(
        Request(
            tool="ableton_clip", action="duplicate_to_arrangement",
            params={"track_index": 1, "clip_index": 1, "start_beats": 16.0},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert "spurious_clips_removed" not in resp.result
    assert "spurious_clips_remaining" not in resp.result


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


# ---------- B4: inline-notes soft-cap guardrail (parity-locked) ----------

from hallucinote_mcp.handlers.clip import INLINE_NOTES_SOFT_CAP  # noqa: E402


def _make_notes(n: int) -> list[dict[str, Any]]:
    """n valid note dicts, spaced so start_times stay non-negative + in-range."""
    return [
        {"pitch": 60, "start_time": i * 0.25, "duration": 0.25, "velocity": 90}
        for i in range(n)
    ]


def _create_result(ctx, notes):
    return dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "kind": "midi", "length": 64.0, "notes": notes,
            },
        ),
        context=ctx,
    )


def _replace_result(ctx, notes):
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip()
    return dispatch(
        Request(
            tool="ableton_clip", action="replace_notes",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "notes": notes,
            },
        ),
        context=ctx,
    )


def test_inline_notes_no_warning_at_or_below_cap(loaded_actions):
    """Trivial edits (<= cap) stay frictionless — no warning on either action."""
    notes = _make_notes(INLINE_NOTES_SOFT_CAP)  # exactly the cap → silent
    assert "warning" not in _create_result(FakeCtx(), notes).result
    assert "warning" not in _replace_result(FakeCtx(), notes).result


def test_inline_notes_warning_above_cap_is_non_blocking(loaded_actions):
    """Above the cap: a teaching warning fires, but the write still succeeds."""
    notes = _make_notes(INLINE_NOTES_SOFT_CAP + 1)
    for result in (_create_result(FakeCtx(), notes).result,
                   _replace_result(FakeCtx(), notes).result):
        # Non-blocking: the notes were actually written.
        assert result["notes_written"] == INLINE_NOTES_SOFT_CAP + 1
        warning = result["warning"]
        # Points at the DB / scoped-push path, not just "too many notes".
        assert "push-notes" in warning
        assert "/compose-part" in warning
        assert str(INLINE_NOTES_SOFT_CAP) in warning


def test_inline_notes_warning_parity_between_create_and_replace(loaded_actions):
    """Lock: both inline-note actions emit the IDENTICAL warning at the same
    threshold. Adding a third note-accepting path? Route it through
    ``_inline_notes_warning`` and add it here."""
    notes = _make_notes(INLINE_NOTES_SOFT_CAP + 5)
    create_warning = _create_result(FakeCtx(), notes).result["warning"]
    replace_warning = _replace_result(FakeCtx(), notes).result["warning"]
    assert create_warning == replace_warning


def test_duplicate_to_arrangement_detects_spurious_clip_colliding_with_an_existing_start(
    loaded_actions,
):
    """ARR-6T8N: spurious-clip detection used a SET of before-start_times, so a
    pre-existing clip sitting at exactly ``dest_beats + source.length`` — the
    very position Live's B-24 split emits its copy at — masked the new one:
    the start_time was already in the set, so the surplus clip was waved
    through and left in the arrangement.

    Layout: Scaffold 0..32 (the clip that gets split) plus a Marker clip that
    already starts at 20.0 = dest(16) + source length(4). After the duplicate
    there are TWO clips at 20.0 and only one of them existed before.
    """
    ctx = FakeCtx()
    track = ctx.song.tracks[0]
    track.arrangement_clips.append(
        FakeArrangementClip(name="Scaffold", length=32.0, start_time=0.0)
    )
    # Sits exactly where the B-24 side effect will land.
    track.arrangement_clips.append(
        FakeArrangementClip(name="Marker", length=2.0, start_time=20.0)
    )
    track.clip_slots[1].clip = FakeClip(name="DupSource", length=4.0)

    resp = dispatch(
        Request(
            tool="ableton_clip", action="duplicate_to_arrangement",
            params={"track_index": 1, "clip_index": 2, "start_beats": 16.0},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error

    names_and_starts = sorted(
        (c.start_time, c.name) for c in track.arrangement_clips
    )
    assert names_and_starts == [
        (0.0, "Scaffold"),
        (16.0, "DupSource"),
        (20.0, "Marker"),
    ], (
        "the spurious split copy at 20.0 must be removed while the "
        f"pre-existing Marker at 20.0 survives; got {names_and_starts}"
    )
    removed = resp.result.get("spurious_clips_removed") or []
    assert len(removed) == 1, (
        "exactly one surplus clip should be detected — a start-time SET sees "
        "20.0 as 'already present' and detects nothing"
    )
    assert removed[0]["name"] == "Scaffold"


def test_duplicate_to_arrangement_survives_reversed_enumeration_at_a_tied_start(
    loaded_actions,
):
    """The same collision as the test above, with Live enumerating the split
    copy BEFORE the operator's pre-existing clip.

    The original walk paired after-clips to before-counts positionally, so the
    first clip encountered at a tied start was treated as pre-existing and the
    second was deleted. Under this ordering that deletes the operator's
    authored Marker and keeps the artifact — reported as a successful cleanup,
    which is the shape of a silent data-loss bug. Resolution is by identity
    now, so the ordering does not decide who dies.
    """
    ctx = FakeCtx()
    track = ctx.song.tracks[0]
    track.arrangement_clips.append(
        FakeArrangementClip(name="Scaffold", length=32.0, start_time=0.0)
    )
    track.arrangement_clips.append(
        FakeArrangementClip(name="Marker", length=2.0, start_time=20.0)
    )
    track.clip_slots[1].clip = FakeClip(name="DupSource", length=4.0)

    real_duplicate = track.duplicate_clip_to_arrangement

    def duplicate_then_reverse_the_tie(source, destination_beats):
        real_duplicate(source, destination_beats)
        # Live's enumeration order for two clips at one start is not ours to
        # control; model the adversarial one.
        tied = [c for c in track.arrangement_clips if c.start_time == 20.0]
        assert len(tied) == 2, "the B-24 side effect should have collided here"
        for c in tied:
            track.arrangement_clips.remove(c)
        # Split copy first, operator's clip second.
        for c in sorted(tied, key=lambda c: c.name != "Scaffold"):
            track.arrangement_clips.append(c)

    track.duplicate_clip_to_arrangement = duplicate_then_reverse_the_tie

    resp = dispatch(
        Request(
            tool="ableton_clip", action="duplicate_to_arrangement",
            params={"track_index": 1, "clip_index": 2, "start_beats": 16.0},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error

    survivors = sorted((c.start_time, c.name) for c in track.arrangement_clips)
    assert (20.0, "Marker") in survivors, (
        "the operator's pre-existing Marker must survive regardless of the "
        f"order Live enumerated the tied clips in; got {survivors}"
    )
    assert (20.0, "Scaffold") not in survivors, (
        f"the split copy at 20.0 is the one to remove; got {survivors}"
    )
    removed = resp.result.get("spurious_clips_removed") or []
    assert [r["name"] for r in removed] == ["Scaffold"]


def test_duplicate_to_arrangement_deletes_nothing_when_the_tied_clips_are_identical(
    loaded_actions,
):
    """When the split copy and the operator's clip share (start, length, name)
    there is no evidence for which one to delete, so nothing may be deleted.

    Identity resolution answers the ordering question only while the clips are
    distinguishable. Where the same identity occurs twice, drawing one of the
    pair down against the before-state and calling the other the newcomer is
    the enumeration-order coin-flip again, one level down — and in Live the
    split copy carries the OVERLAPPED clip's content, so the two are not
    interchangeable. The non-destructive channel is the answer.
    """
    ctx = FakeCtx()
    track = ctx.song.tracks[0]
    track.arrangement_clips.append(
        FakeArrangementClip(name="Scaffold", length=32.0, start_time=0.0)
    )
    # Identical to the copy Live's B-24 split will emit at 20.0: the split
    # copy is a copy OF Scaffold, so name and length match exactly.
    track.arrangement_clips.append(
        FakeArrangementClip(name="Scaffold", length=32.0, start_time=20.0)
    )
    track.clip_slots[1].clip = FakeClip(name="DupSource", length=4.0)

    resp = dispatch(
        Request(
            tool="ableton_clip", action="duplicate_to_arrangement",
            params={"track_index": 1, "clip_index": 2, "start_beats": 16.0},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error

    at_20 = [c for c in track.arrangement_clips if c.start_time == 20.0]
    assert len(at_20) == 2, (
        "neither tied clip may be deleted — there is no evidence for which "
        f"is the artifact; got {[(c.start_time, c.name) for c in at_20]}"
    )
    assert not resp.result.get("spurious_clips_removed"), (
        "nothing was identified, so nothing may be reported as removed"
    )
    remaining = resp.result.get("spurious_clips_remaining") or []
    assert len(remaining) == 2, remaining
    assert all("reason" in r for r in remaining), (
        "the operator needs to know why cleanup stopped, not just that it did"
    )


def test_duplicate_to_arrangement_leaves_a_pre_existing_clip_at_the_destination_alone(
    loaded_actions,
):
    """The counting walk must not mistake a pre-existing clip for the new one
    (or vice versa) when both sit at the destination beat. Nothing is spurious
    here — no overlap split fires — so nothing may be deleted."""
    ctx = FakeCtx()
    track = ctx.song.tracks[0]
    track.arrangement_clips.append(
        FakeArrangementClip(name="Pre", length=2.0, start_time=16.0)
    )
    track.clip_slots[1].clip = FakeClip(name="DupSource", length=4.0)

    resp = dispatch(
        Request(
            tool="ableton_clip", action="duplicate_to_arrangement",
            params={"track_index": 1, "clip_index": 2, "start_beats": 16.0},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    names = sorted(c.name for c in track.arrangement_clips)
    assert names == ["DupSource", "Pre"], (
        f"neither clip at the destination may be deleted; got {names}"
    )


# ---------- create — audio clips (SMP-6V2K R1.1) ----------
#
# The Live calls under test were executed against a running Live 12.4.1 and
# recorded verbatim in docs/research/audio-first-class/lom-probe-results.md
# rows 1a (ClipSlot.create_audio_clip(abs_path)), 1b
# (Track.create_audio_clip(path, beats)) and 1c (both refusals). The fakes
# above mirror those signatures and those error strings, so these tests
# assert against what Live does rather than against a paraphrase of it.


def test_create_session_audio_clip_loads_the_file(loaded_actions):
    """Row 1a: one call, a real clip in the slot, playing the file we named."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 2, "location": "session", "clip_index": 1,
                "kind": "audio", "audio_path": PROBE_WAV,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["kind"] == "audio"
    assert resp.result["clip_index"] == 1
    # The file_path is read back OFF THE CLIP — the evidence that a file
    # loaded, not merely that the call returned.
    assert resp.result["file_path"] == PROBE_WAV
    # Length comes from the file, not from the caller.
    assert resp.result["length"] == 4.0
    clip = ctx.song.tracks[1].clip_slots[0].clip
    assert clip is not None
    assert clip.is_audio_clip is True
    assert clip.file_path == PROBE_WAV


def test_create_session_audio_clip_replace_clobbers_the_occupant(loaded_actions):
    ctx = FakeCtx()
    existing = FakeClip(name="Existing")
    ctx.song.tracks[1].clip_slots[0].clip = existing
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 2, "location": "session", "clip_index": 1,
                "kind": "audio", "audio_path": PROBE_WAV, "replace": True,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    new_clip = ctx.song.tracks[1].clip_slots[0].clip
    assert new_clip is not existing
    assert new_clip.file_path == PROBE_WAV


def test_create_session_audio_clip_names_the_clip(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 2, "location": "session", "clip_index": 1,
                "kind": "audio", "audio_path": PROBE_WAV, "name": "Line 1",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["name"] == "Line 1"
    assert ctx.song.tracks[1].clip_slots[0].clip.name == "Line 1"


def test_create_arrangement_audio_clip_places_at_start_beats(loaded_actions):
    """Row 1b: Track.create_audio_clip(path, beats) — note the argument order,
    the mirror image of create_midi_clip(beats, length). The fake's signature
    is Live's, so a handler that passed them the other way round would place
    the clip at a nonsense position (or refuse the path)."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 2, "location": "arrangement",
                "kind": "audio", "audio_path": PROBE_WAV, "start_beats": 16.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["arrangement_clip_index"] == 1
    assert resp.result["start_beats"] == 16.0
    assert resp.result["file_path"] == PROBE_WAV
    arr = ctx.song.tracks[1].arrangement_clips
    assert len(arr) == 1
    assert arr[0].start_time == 16.0
    assert arr[0].file_path == PROBE_WAV
    assert arr[0].is_audio_clip is True


def test_create_arrangement_audio_clip_index_when_a_clip_already_sits_there(
    loaded_actions,
):
    """The new clip must be told apart from one already at that beat.

    Matching on (start, length) is what the MIDI path used to do and it
    cannot work for audio — the length comes from the file and is unknown
    until after the call. The positional multiset answers it: skip as many
    clips at this beat as were there before.
    """
    ctx = FakeCtx()
    track = ctx.song.tracks[1]
    track.arrangement_clips.append(
        FakeArrangementClip(name="Pre", start_time=16.0, length=4.0)
    )
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 2, "location": "arrangement",
                "kind": "audio", "audio_path": PROBE_WAV, "start_beats": 16.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["arrangement_clip_index"] == 2, (
        "the pre-existing clip at that beat must not be reported as the new one"
    )
    assert len(track.arrangement_clips) == 2
    assert track.arrangement_clips[1].file_path == PROBE_WAV


def test_create_arrangement_audio_clip_on_a_midi_track_teaches_the_fix(
    loaded_actions,
):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "arrangement",
                "kind": "audio", "audio_path": PROBE_WAV, "start_beats": 0.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "audio track" in err.lower(), err
    assert "kind='audio'" in err, err


@pytest.mark.parametrize("location, extra", [
    ("session", {"clip_index": 1}),
    ("arrangement", {"start_beats": 0.0}),
])
def test_create_audio_clip_unloadable_path_teaches_both_causes(
    loaded_actions, location, extra
):
    """Row 1c: Live reports a MISSING file and an UNDECODABLE one with the
    same ValueError, so the teaching error has to name both — an operator
    who only checks that the file exists would otherwise stop looking."""
    ctx = FakeCtx()
    params = {
        "track_index": 2, "location": location,
        "kind": "audio", "audio_path": "/tmp/does-not-exist.wav",
    }
    params.update(extra)
    resp = dispatch(
        Request(tool="ableton_clip", action="create", params=params),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    assert "/tmp/does-not-exist.wav" in err, err
    assert "exists" in err, err
    assert "decode" in err, err


def test_live_relative_path_refusal_teaches_the_same_fix():
    """Probe row 17: Live's own absoluteness check has a third error string,
    raised before the file is looked at. When it arrives — Live's idea of
    'absolute' stricter than os.path.isabs, a future build — it must teach
    the same fix as the handler's pre-check, not surface as a bare ValueError
    that reads like a corrupt file. Unknown strings still pass through
    untouched."""
    from hallucinote_mcp.handlers.clip import _create_audio_clip

    def live_refuses(*_args):
        raise ValueError(LIVE_RELATIVE_PATH_ERROR)

    with pytest.raises(ValueError) as exc_info:
        _create_audio_clip(
            live_refuses, ("scratchpad/probe.wav",),
            track_index=3, audio_path="scratchpad/probe.wav",
        )
    err = str(exc_info.value)
    assert "absolute" in err.lower(), err
    assert "resolve_audio_path" in err, err
    assert LIVE_RELATIVE_PATH_ERROR in err, err
    assert "decode" not in err.lower(), "must not be mislabelled as the bad-file refusal"

    def live_says_something_new(*_args):
        raise ValueError("some refusal this build never saw")

    with pytest.raises(ValueError, match="never saw") as unknown:
        _create_audio_clip(
            live_says_something_new, ("/abs/x.wav",),
            track_index=3, audio_path="/abs/x.wav",
        )
    assert "resolve_audio_path" not in str(unknown.value)


def test_create_audio_clip_requires_an_absolute_path(loaded_actions):
    """Live resolves nothing. A song-relative reference is the engine's to
    resolve (paths.resolve_audio_path) before the call reaches the wire, and
    the error has to say so — otherwise the caller reads Live's generic
    'not a valid audio file' and goes hunting for a corrupt WAV."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 2, "location": "session", "clip_index": 1,
                "kind": "audio", "audio_path": "assets/line.wav",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "absolute" in err.lower(), err
    assert "resolve_audio_path" in err, err


def test_create_audio_clip_requires_audio_path(loaded_actions):
    """There is no such thing as an empty audio clip — the file IS the clip."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 2, "location": "session", "clip_index": 1,
                "kind": "audio", "length": 4.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "audio_path" in (resp.error or ""), resp.error


def test_create_audio_clip_refuses_notes(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 2, "location": "session", "clip_index": 1,
                "kind": "audio", "audio_path": PROBE_WAV,
                "notes": [{"pitch": 60, "start_time": 0.0, "duration": 1.0}],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "note" in (resp.error or "").lower(), resp.error
    # Nothing was created — the refusal happens before Live is touched.
    assert ctx.song.tracks[1].clip_slots[0].clip is None


def test_create_audio_clip_ignores_length_and_says_so(loaded_actions):
    """A caller who passes length must not be left believing it took effect:
    Live's create_audio_clip has no length argument at all."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 2, "location": "session", "clip_index": 1,
                "kind": "audio", "audio_path": PROBE_WAV, "length": 16.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["length"] == 4.0, "the file's length wins"
    warning = resp.result.get("warning", "")
    assert "ignored" in warning.lower(), warning
    assert "start_marker" in warning, warning


def test_create_midi_clip_requires_length(loaded_actions):
    """length went optional on the schema so audio need not invent one; MIDI
    still cannot do without it, and the handler is now where that is said."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "kind": "midi",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "length" in (resp.error or ""), resp.error


def test_create_midi_clip_rejects_audio_path(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "kind": "midi", "length": 4.0, "audio_path": PROBE_WAV,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "kind='audio'" in (resp.error or ""), resp.error


def test_create_no_longer_reports_audio_path_deferred(loaded_actions):
    """The reserved no-op is REPLACED, not wrapped: nothing on the wire may
    still say a path was received but not loaded."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 2, "location": "session", "clip_index": 1,
                "kind": "audio", "audio_path": PROBE_WAV,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert "audio_path_deferred" not in resp.result


# ---------- set_property — the audio conform surface ----------


@pytest.mark.parametrize("property_name, value, attr, expected", [
    ("pitch_coarse", -5, "pitch_coarse", -5),
    ("pitch_fine", 12.5, "pitch_fine", 12.5),
    ("warp_mode", 6, "warp_mode", 6),
    ("start_marker", 2.0, "start_marker", 2.0),
    ("end_marker", 6.0, "end_marker", 6.0),
])
def test_set_property_writes_each_conform_field(
    loaded_actions, property_name, value, attr, expected
):
    ctx = FakeCtx()
    clip = FakeClip(kind="audio")
    ctx.song.tracks[1].clip_slots[0].clip = clip
    resp = dispatch(
        Request(
            tool="ableton_clip", action="set_property",
            params={
                "track_index": 2, "location": "session", "clip_index": 1,
                "property": property_name, "value": value,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert getattr(clip, attr) == expected


def test_set_property_pitch_and_pitch_coarse_are_the_same_property(loaded_actions):
    """action='list' reports pitch_coarse; set_property has always taken
    'pitch'. Both spellings must reach the same Live attribute or a value
    read back cannot be written back."""
    ctx = FakeCtx()
    clip = FakeClip(kind="audio")
    ctx.song.tracks[1].clip_slots[0].clip = clip
    for name, value in (("pitch", 7), ("pitch_coarse", -3)):
        resp = dispatch(
            Request(
                tool="ableton_clip", action="set_property",
                params={
                    "track_index": 2, "location": "session", "clip_index": 1,
                    "property": name, "value": value,
                },
            ),
            context=ctx,
        )
        assert resp.ok is True, resp.error
        assert clip.pitch_coarse == value


@pytest.mark.parametrize("property_name, value", [
    ("pitch_fine", 12.5),
    ("warp_mode", 4),
    ("pitch_coarse", 3),
])
def test_set_property_new_audio_fields_refuse_midi_clips(
    loaded_actions, property_name, value
):
    ctx = FakeCtx()
    ctx.song.tracks[0].clip_slots[0].clip = FakeClip(kind="midi")
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
    assert resp.ok is False
    assert "audio-only" in (resp.error or "").lower(), resp.error


@pytest.mark.parametrize("property_name", ["start_marker", "end_marker"])
def test_set_property_markers_are_not_audio_only(loaded_actions, property_name):
    """A MIDI clip has markers too. Classing them audio-only would refuse a
    write Live accepts."""
    ctx = FakeCtx()
    clip = FakeClip(kind="midi")
    ctx.song.tracks[0].clip_slots[0].clip = clip
    resp = dispatch(
        Request(
            tool="ableton_clip", action="set_property",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "property": property_name, "value": 3.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert getattr(clip, property_name) == 3.0


@pytest.mark.parametrize("property_name, value", [
    ("pitch_fine", 51.0),
    ("pitch_fine", -51.0),
    ("warp_mode", 7),
    ("warp_mode", -1),
    ("gain", -0.5),
    ("gain", 1.5),
])
def test_set_property_conform_bounds_are_enforced(
    loaded_actions, property_name, value
):
    ctx = FakeCtx()
    ctx.song.tracks[1].clip_slots[0].clip = FakeClip(kind="audio")
    resp = dispatch(
        Request(
            tool="ableton_clip", action="set_property",
            params={
                "track_index": 2, "location": "session", "clip_index": 1,
                "property": property_name, "value": value,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "out of range" in (resp.error or ""), resp.error


def test_set_property_has_no_reverse(loaded_actions):
    """Live exposes NO settable reverse on a Clip (lom-audio-clip-surface.md
    §4, 'confirmed absent'). Accepting the name here would promise a
    materialization that does not exist; reverse is a derived asset or a
    sampler parameter instead."""
    action = schema.get("ableton_clip", "set_property")
    prop_spec = next(p for p in action.params if p.name == "property")
    assert "reverse" not in (prop_spec.enum or ()), (
        "reverse is not a Live clip property — do not add it to the enum"
    )
    ctx = FakeCtx()
    ctx.song.tracks[1].clip_slots[0].clip = FakeClip(kind="audio")
    resp = dispatch(
        Request(
            tool="ableton_clip", action="set_property",
            params={
                "track_index": 2, "location": "session", "clip_index": 1,
                "property": "reverse", "value": 1,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False


# ---------- list — the audio read surface (SMP-6V2K R1.2) ----------


_EXPECTED_AUDIO_FIELDS = {
    "file_path", "gain", "pitch_coarse", "pitch_fine", "warping",
    "warp_mode", "start_marker", "end_marker",
}


def test_list_session_audio_clip_reports_its_conform_state(loaded_actions):
    """The whole entry, asserted exactly: this shape is what pull ingests a
    hand-dragged clip through, so it is a contract and not an example."""
    clip = FakeClip(name="Line 1", length=4.0, kind="audio")
    clip.gain = 0.8
    clip.pitch_coarse = -2
    clip.pitch_fine = 15.0
    clip.warping = True
    clip.warp_mode = 6
    clip.start_marker = 0.5
    clip.end_marker = 3.5
    track = FakeTrack(name="Dialogue", kind="audio", slots=2)
    track.clip_slots[0].clip = clip
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 1, "location": "session"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["clips"][0] == {
        "clip_index": 1,
        "empty": False,
        "name": "Line 1",
        "length": 4.0,
        "is_audio": True,
        "file_path": PROBE_WAV,
        "gain": 0.8,
        "pitch_coarse": -2,
        "pitch_fine": 15.0,
        "warping": True,
        "warp_mode": 6,
        "start_marker": 0.5,
        "end_marker": 3.5,
    }


def test_list_arrangement_audio_clip_reports_its_conform_state(loaded_actions):
    clip = FakeArrangementClip(
        name="Line 2", start_time=8.0, length=4.0, kind="audio"
    )
    clip.warping = False
    clip.warp_mode = 3
    clip.start_marker = 1.25
    clip.end_marker = 2.5
    track = FakeTrack(name="Dialogue", kind="audio", arrangement_clips=[clip])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 1, "location": "arrangement"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    entry = resp.result["clips"][0]
    assert entry == {
        "arrangement_clip_index": 1,
        "name": "Line 2",
        "start_beats": 8.0,
        "length": 4.0,
        "muted": False,
        "note_count": None,
        "is_audio": True,
        "file_path": PROBE_WAV,
        "gain": 0.0,
        "pitch_coarse": 0,
        "pitch_fine": 0.0,
        "warping": False,
        "warp_mode": 3,
        "start_marker": 1.25,
        "end_marker": 2.5,
    }


@pytest.mark.parametrize("location", ["session", "arrangement"])
def test_list_midi_clip_omits_the_audio_fields_entirely(loaded_actions, location):
    """Absent, not null. A null-filled MIDI entry would read as 'an audio clip
    whose file we could not determine' — the one confusion the discriminator
    exists to prevent."""
    midi = FakeArrangementClip(name="Riff", start_time=0.0, length=8.0)
    track = FakeTrack(name="Lead", slots=2, arrangement_clips=[midi])
    track.clip_slots[0].clip = FakeClip(name="Riff", length=8.0)
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 1, "location": location},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    entry = resp.result["clips"][0]
    assert entry["is_audio"] is False
    leaked = _EXPECTED_AUDIO_FIELDS & set(entry)
    assert not leaked, f"MIDI entry must omit the audio fields; leaked {leaked}"


def test_list_discriminator_falls_back_to_is_midi_clip(loaded_actions):
    """A wrapper exposing only the MIDI half of the discriminator must still
    be read correctly — reporting a sample-playing clip as MIDI would send
    pull looking for notes that do not exist."""
    clip = FakeClip(name="Stem", length=4.0, kind="audio")
    del clip.is_audio_clip
    track = FakeTrack(name="Dialogue", kind="audio", slots=1)
    track.clip_slots[0].clip = clip
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 1, "location": "session"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    entry = resp.result["clips"][0]
    assert entry["is_audio"] is True
    assert entry["file_path"] == PROBE_WAV


def test_list_empty_slot_carries_no_discriminator(loaded_actions):
    """An empty slot holds no clip, so it is neither audio nor MIDI — saying
    is_audio: False there would assert something about a clip that isn't."""
    track = FakeTrack(name="T1", slots=2)
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_clip", action="list",
            params={"track_index": 1, "location": "session"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["clips"][0] == {"clip_index": 1, "empty": True}


def test_list_round_trips_into_set_property(loaded_actions):
    """R1.2's real requirement: every conform field the read surface reports
    must be writable under a name set_property accepts. A read that cannot be
    written back is not a round trip."""
    list_action = schema.get("ableton_clip", "list")
    assert list_action is not None
    set_action = schema.get("ableton_clip", "set_property")
    writable = set(
        next(p for p in set_action.params if p.name == "property").enum or ()
    )
    # file_path is Live-read-only (re-pointing a clip is delete-and-recreate),
    # so it is the one reported field with no writer.
    not_writable = (_EXPECTED_AUDIO_FIELDS - writable) - {"file_path"}
    assert not not_writable, (
        f"reported but not writable: {sorted(not_writable)} — either add the "
        f"property to set_property or stop reporting it"
    )


# ---------- create schema ----------


def test_create_length_is_optional_and_audio_path_is_required_for_audio(
    loaded_actions,
):
    """The schema can't express 'required for one kind' — the handler owns
    that (tested above). What the schema owes is not blocking an audio create
    on a length Live has no argument for."""
    action = schema.get("ableton_clip", "create")
    params = {p.name: p for p in action.params}
    assert params["length"].required is False
    assert "kind='midi'" in params["length"].description
    assert "ABSOLUTE" in params["audio_path"].description
    assert "audio_path_deferred" not in params["audio_path"].description


def test_set_property_enum_declares_the_whole_conform_surface(loaded_actions):
    """R1.1 conforms a placed sample through these names; if the schema does
    not declare one, the dispatcher rejects the call before the handler ever
    sees it."""
    action = schema.get("ableton_clip", "set_property")
    declared = set(next(p for p in action.params if p.name == "property").enum or ())
    assert {
        "gain", "pitch", "pitch_coarse", "pitch_fine", "warp", "warping",
        "warp_mode", "start_marker", "end_marker",
    } <= declared


def test_set_property_enum_matches_the_handler_property_table(loaded_actions):
    """Two lists, one contract: the dispatcher validates against the schema
    enum and the handler against its own table. A name in one and not the
    other is either an unreachable property or a dispatcher rejection the
    handler was written to serve."""
    from hallucinote_mcp.handlers.clip import _CLIP_PROPERTIES as handler_table

    action = schema.get("ableton_clip", "set_property")
    declared = set(next(p for p in action.params if p.name == "property").enum or ())
    assert declared == set(handler_table)


def test_set_property_gain_domain_matches_live_and_the_db(loaded_actions):
    """Live clip gain is LINEAR 0.0-1.0, not dB (lom-audio-clip-surface.md §4,
    cross-checked against the installed 12.4.1 LomTypes gate table), and
    `db/mutations/clips.py` `_validate_audio_fields` enforces exactly that
    range. A wire that accepted a negative gain would take a value neither
    Live nor the DB can hold and would diverge the two authoring surfaces.
    """
    ctx = FakeCtx()
    ctx.song.tracks[1].clip_slots[0].clip = FakeClip(kind="audio")
    for value in (0.0, 1.0):
        resp = dispatch(
            Request(
                tool="ableton_clip", action="set_property",
                params={
                    "track_index": 2, "location": "session", "clip_index": 1,
                    "property": "gain", "value": value,
                },
            ),
            context=ctx,
        )
        assert resp.ok is True, (value, resp.error)


def test_replace_that_fails_to_recreate_says_the_slot_is_now_empty(loaded_actions):
    """A slot holds one clip, so replace=True deletes before it creates, and
    Live only refuses a wrong-kind create after that point. The old clip is
    gone either way; what the caller must not get is an error that reads like
    a rejected call which changed nothing.
    """
    ctx = FakeCtx()
    midi_track = ctx.song.tracks[0]
    slot = midi_track.clip_slots[0]
    slot.clip = FakeClip(kind="midi")
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 1, "location": "session", "clip_index": 1,
                "kind": "audio", "audio_path": "/tmp/line.wav",
                "replace": True,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "now EMPTY" in err, err
    assert "audio track" in err, err
    assert slot.clip is None


def test_replace_failure_disclosure_survives_an_awkward_exception_type(loaded_actions):
    """The disclosure is built by re-raising the original exception's TYPE with a
    new message, which assumes a constructor that takes one string. Not every
    exception has one, and this is the worst possible path for a raise inside the
    handler: the clip is already deleted, so losing the disclosure would leave a
    caller with a TypeError and no idea their slot was emptied.
    """
    class AwkwardError(Exception):
        def __init__(self, a, b):  # noqa: D107 - deliberately not single-arg
            super().__init__(a, b)
            self.a, self.b = a, b

    ctx = FakeCtx()
    track = ctx.song.tracks[1]
    slot = track.clip_slots[0]
    slot.clip = FakeClip(kind="audio")

    def _boom(_path):
        raise AwkwardError("live blew up", 42)

    slot.create_audio_clip = _boom
    resp = dispatch(
        Request(
            tool="ableton_clip", action="create",
            params={
                "track_index": 2, "location": "session", "clip_index": 1,
                "kind": "audio", "audio_path": "/tmp/line.wav",
                "replace": True,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "now EMPTY" in err, err
    assert "live blew up" in err, err
    assert slot.clip is None
