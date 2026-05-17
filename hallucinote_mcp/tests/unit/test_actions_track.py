"""ableton_track schema + handler behavior."""
from __future__ import annotations

from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------- Fakes ----------


class FakeParam:
    def __init__(self, value: float = 0.0):
        self.value = value


class FakeSend:
    def __init__(self, value: float = 0.0):
        self.value = value


class FakeMixer:
    def __init__(self, volume=0.85, panning=0.0, sends_count=2):
        self.volume = FakeParam(volume)
        self.panning = FakeParam(panning)
        self.sends = [FakeSend() for _ in range(sends_count)]


class FakeTrack:
    def __init__(
        self,
        name: str = "Track",
        kind: str = "midi",
        sends_count: int = 2,
        color: int | None = None,
    ):
        self.name = name
        self.mixer_device = FakeMixer(sends_count=sends_count)
        self.mute = False
        self.solo = False
        self.arm = False
        self.color = color
        self.has_midi_input = kind == "midi"
        self.has_audio_input = kind == "audio"
        self.is_foldable = False
        self.is_grouped = False


class FakeReturn:
    def __init__(self, name: str = "A-Rev", color: int | None = None):
        self.name = name
        self.color = color


class FakeSong:
    def __init__(self, tracks: list[FakeTrack] | None = None, returns: list[FakeReturn] | None = None):
        self.tracks = tracks if tracks is not None else [
            FakeTrack(name="Drums"), FakeTrack(name="Bass", kind="audio"), FakeTrack(name="Lead"),
        ]
        self.return_tracks = returns if returns is not None else [
            FakeReturn(name="A-Reverb"), FakeReturn(name="B-Delay"),
        ]
        self._deleted_tracks: list[FakeTrack] = []
        self._created_tracks: list[FakeTrack] = []

    def delete_track(self, track: FakeTrack) -> None:
        self._deleted_tracks.append(track)
        self.tracks.remove(track)

    def create_midi_track(self, insert_at: int = -1) -> FakeTrack:
        t = FakeTrack(name="Midi", kind="midi")
        self._created_tracks.append(t)
        if insert_at == -1:
            self.tracks.append(t)
        else:
            self.tracks.insert(insert_at, t)
        return t

    def create_audio_track(self, insert_at: int = -1) -> FakeTrack:
        t = FakeTrack(name="Audio", kind="audio")
        self._created_tracks.append(t)
        if insert_at == -1:
            self.tracks.append(t)
        else:
            self.tracks.insert(insert_at, t)
        return t


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


_EXPECTED_TRACK_ACTIONS = {
    "help", "list", "info", "create", "delete", "rename",
    "set_property", "get_property", "set_send", "get_sends",
    "deletion_status",
}


def test_track_registers_eleven_actions(loaded_actions):
    names = {a.name for a in schema.actions_for("ableton_track")}
    assert names == _EXPECTED_TRACK_ACTIONS


def test_track_help_lists_all_actions(loaded_actions):
    resp = dispatch(Request(tool="ableton_track", action="help"))
    assert resp.ok is True
    names = {a["name"] for a in resp.result["actions"]}
    assert names == _EXPECTED_TRACK_ACTIONS - {"help"}


# ---------- list / info ----------


def test_list_returns_thin_index(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(Request(tool="ableton_track", action="list"), context=ctx)
    assert resp.ok is True
    tracks = resp.result["tracks"]
    assert [t["track_index"] for t in tracks] == [1, 2, 3]
    assert [t["name"] for t in tracks] == ["Drums", "Bass", "Lead"]
    assert tracks[0]["kind"] == "midi"
    assert tracks[1]["kind"] == "audio"


def test_info_returns_mixer_state(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(tool="ableton_track", action="info", params={"track_index": 1}),
        context=ctx,
    )
    assert resp.ok is True
    r = resp.result
    assert r["track_index"] == 1
    assert r["name"] == "Drums"
    assert r["volume"] == 0.85
    assert r["mute"] is False


def test_info_rejects_out_of_range_index(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(tool="ableton_track", action="info", params={"track_index": 99}),
        context=ctx,
    )
    assert resp.ok is False
    assert "out of range" in (resp.error or "")


# ---------- create / delete / rename ----------


def test_create_midi_track_appends(loaded_actions):
    ctx = FakeCtx()
    before = len(ctx.song.tracks)
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="create",
            params={"kind": "midi", "name": "Pad"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["kind"] == "midi"
    assert resp.result["name"] == "Pad"
    assert resp.result["track_index"] == before + 1
    assert ctx.song.tracks[-1].name == "Pad"


def test_create_audio_track_inserts_at_index(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="create",
            params={"kind": "audio", "name": "Guitar", "index": 2},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.tracks[1].name == "Guitar"
    assert resp.result["track_index"] == 2


def test_create_rejects_unknown_kind(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="create",
            params={"kind": "group", "name": "Drums-Group"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    # Enum kicks in before the handler runs.
    assert "not in enum" in (resp.error or "")


def test_create_with_instrument_uri_is_deferred(loaded_actions):
    """instrument_uri round-trips in the result but no device is loaded in M-2."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="create",
            params={
                "kind": "midi",
                "name": "Lead",
                "instrument_uri": "query:Operator",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["instrument_uri_deferred"] == "query:Operator"


def test_delete_removes_track(loaded_actions):
    ctx = FakeCtx()
    target = ctx.song.tracks[1]
    resp = dispatch(
        Request(tool="ableton_track", action="delete", params={"track_index": 2}),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["deleted_track_index"] == 2
    assert target in ctx.song._deleted_tracks
    assert target not in ctx.song.tracks


def test_rename_via_declarative_path(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="rename",
            params={"track_index": 1, "name": "Renamed"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.tracks[0].name == "Renamed"


# ---------- set_property / get_property ----------


@pytest.mark.parametrize(
    "property_name, value, expected",
    [
        ("volume", 0.5, 0.5),
        ("panning", -0.3, -0.3),
        ("mute", 1.0, True),
        ("solo", 1, True),
        ("arm", 0, False),
        ("color", 12, 12),
    ],
)
def test_set_property_writes_each_field(loaded_actions, property_name, value, expected):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="set_property",
            params={"track_index": 1, "property": property_name, "value": value},
        ),
        context=ctx,
    )
    assert resp.ok is True
    track = ctx.song.tracks[0]
    if property_name == "volume":
        assert track.mixer_device.volume.value == expected
    elif property_name == "panning":
        assert track.mixer_device.panning.value == expected
    elif property_name in ("mute", "solo", "arm"):
        assert getattr(track, property_name) is expected
    elif property_name == "color":
        assert track.color == expected


@pytest.mark.parametrize(
    "property_name, bad_value",
    [
        ("volume", 1.5),
        ("volume", -0.1),
        ("panning", 1.5),
        ("panning", -1.5),
    ],
)
def test_set_property_enforces_range(loaded_actions, property_name, bad_value):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="set_property",
            params={"track_index": 1, "property": property_name, "value": bad_value},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "out of range" in (resp.error or "")


def test_get_property_reads_each_field(loaded_actions):
    ctx = FakeCtx()
    ctx.song.tracks[0].mixer_device.volume.value = 0.6
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="get_property",
            params={"track_index": 1, "property": "volume"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["value"] == 0.6


# ---------- sends ----------


def test_set_send_writes_normalized_level(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="set_send",
            params={"track_index": 1, "return_index": 2, "value": 0.4},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.tracks[0].mixer_device.sends[1].value == 0.4


def test_set_send_rejects_out_of_range_value(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="set_send",
            params={"track_index": 1, "return_index": 1, "value": 1.5},
        ),
        context=ctx,
    )
    # Schema enforces maximum=1.0 — kicks in before the handler.
    assert resp.ok is False
    assert "above maximum" in (resp.error or "")


def test_set_send_rejects_unknown_return(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="set_send",
            params={"track_index": 1, "return_index": 99, "value": 0.5},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "out of range" in (resp.error or "")


def test_get_sends_pairs_levels_with_return_names(loaded_actions):
    ctx = FakeCtx()
    ctx.song.tracks[0].mixer_device.sends[0].value = 0.3
    ctx.song.tracks[0].mixer_device.sends[1].value = 0.7
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="get_sends",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    sends = resp.result["sends"]
    assert sends == [
        {"return_index": 1, "return_name": "A-Reverb", "value": 0.3},
        {"return_index": 2, "return_name": "B-Delay", "value": 0.7},
    ]


# ---------- deletion_status ----------


def test_deletion_status_default_all_tracks(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(tool="ableton_track", action="deletion_status"),
        context=ctx,
    )
    assert resp.ok is True
    assert len(resp.result["tracks"]) == 3
    assert all(t["present"] for t in resp.result["tracks"])


def test_deletion_status_marks_nonexistent_indices(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="deletion_status",
            params={"track_indices": [1, 99]},
        ),
        context=ctx,
    )
    assert resp.ok is True
    rows = {r["track_index"]: r for r in resp.result["tracks"]}
    assert rows[1]["present"] is True
    assert rows[99]["present"] is False
