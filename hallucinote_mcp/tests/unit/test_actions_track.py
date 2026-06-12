"""ableton_track schema + handler behavior."""
from __future__ import annotations

from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------- Fakes ----------


def _live_volume_db(v: float) -> str:
    """Mimic Live's volume-fader display: dB = 40*(v - 0.85), '-inf dB' at 0.

    Monotonic across (0, 1] so the bisection in resolve_continuous_write
    converges; '-inf dB' at the floor exercises the muted -> None path. (Real
    Live bends below ~0.4; the linear region is enough to test the wiring.)
    """
    if v <= 0.0:
        return "-inf dB"
    return f"{40.0 * (v - 0.85):.1f} dB"


def _live_pan_display(v: float) -> str:
    """Mimic Live's pan display: '50L' / 'C' / '50R' — deliberately non-numeric
    at center, so value_display is refused for panning like in real Live."""
    if v == 0.0:
        return "C"
    return f"{abs(v) * 50:.0f}{'L' if v < 0 else 'R'}"


class FakeParam:
    def __init__(
        self,
        value: float = 0.0,
        *,
        min: float = 0.0,
        max: float = 1.0,
        str_for_value=None,
        is_quantized: bool = False,
    ):
        self.value = value
        self.min = min
        self.max = max
        self.is_quantized = is_quantized
        if str_for_value is not None:
            self.str_for_value = str_for_value


class FakeSend:
    def __init__(self, value: float = 0.0):
        self.value = value


class FakeMixer:
    def __init__(self, volume=0.85, panning=0.0, sends_count=2):
        self.volume = FakeParam(volume, str_for_value=_live_volume_db)
        self.panning = FakeParam(
            panning, min=-1.0, max=1.0, str_for_value=_live_pan_display
        )
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

    def delete_track(self, index_0based: int) -> None:
        # Live 12.4's C++ signature is delete_track(int). Passing the Track
        # wrapper raises ArgumentError at the C++ boundary. We mirror that
        # strictly here so handler bugs that pass a wrapper fail at test
        # time, not in production (Wave-2 W2-2 root cause).
        if not isinstance(index_0based, int) or isinstance(index_0based, bool):
            raise TypeError(
                "Song.delete_track(int) — got "
                f"{type(index_0based).__name__}; Live's C++ signature "
                f"rejects wrapper objects"
            )
        self._deleted_tracks.append(self.tracks[index_0based])
        del self.tracks[index_0based]

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
    "set_output_routing", "get_output_routing",
    "set_input_routing", "get_input_routing",
    "set_monitoring_state", "get_monitoring_state",
    "deletion_status",
}


def test_track_registers_seventeen_actions(loaded_actions):
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


# Regression: real Live re-wraps API objects on each property access, so
# ``song.tracks[i] is song.tracks[i]`` returns False for the same underlying
# track. The handler used to scan for identity and falsely raise "Live API
# bug" whenever the track was created successfully but its wrapper
# couldn't be matched — affecting every real Live ``create`` call. This
# fake reproduces that wrapper-recreation semantics.


class _ReWrappingFakeSong:
    """Mimics Live's wrapper-per-access behavior. Underlying data is stable;
    every ``song.tracks`` access returns a fresh list of fresh wrappers."""

    def __init__(self) -> None:
        self._underlying: list[dict] = [
            {"name": "Drums", "kind": "midi"},
            {"name": "Bass", "kind": "audio"},
        ]
        self.return_tracks: list = []

    @property
    def tracks(self):
        return [_FreshWrapper(d) for d in self._underlying]

    def create_midi_track(self, insert_at: int = -1):
        d = {"name": "Midi", "kind": "midi"}
        if insert_at == -1:
            self._underlying.append(d)
        else:
            self._underlying.insert(insert_at, d)
        return _FreshWrapper(d)

    def create_audio_track(self, insert_at: int = -1):  # not used here but
        d = {"name": "Audio", "kind": "audio"}             # symmetry
        if insert_at == -1:
            self._underlying.append(d)
        else:
            self._underlying.insert(insert_at, d)
        return _FreshWrapper(d)


class _FreshWrapper:
    """A wrapper around an underlying dict — never `is`-equal to other
    wrappers around the same dict. Exactly the behavior Live's API
    exhibits with `_Live_Track_Wrapper`-style proxies."""

    def __init__(self, data: dict) -> None:
        self._data = data

    @property
    def name(self) -> str:
        return self._data["name"]

    @name.setter
    def name(self, value: str) -> None:
        self._data["name"] = value


class _ReWrappingCtx:
    def __init__(self) -> None:
        self._song = _ReWrappingFakeSong()

    @property
    def song(self) -> _ReWrappingFakeSong:
        return self._song

    def run_on_main(self, fn):
        return fn()


def test_create_handles_live_wrapper_recreation(loaded_actions):
    """The handler must not rely on ``new_track is song.tracks[i]`` — Live
    re-wraps API objects on every access, so identity is unreliable. The
    new index is determined from the create-call's known semantics
    (append == len-after; insert_at-N == N+1)."""
    ctx = _ReWrappingCtx()
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="create",
            params={"kind": "midi", "name": "Pad"},
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    # Appended to a 2-track song → new index is 3.
    assert resp.result["track_index"] == 3
    assert resp.result["name"] == "Pad"


def test_create_with_explicit_index_handles_wrapper_recreation(loaded_actions):
    """Insert-at-position path: ``index=2`` → new track ends up at 1-based 2."""
    ctx = _ReWrappingCtx()
    resp = dispatch(
        Request(
            tool="ableton_track",
            action="create",
            params={"kind": "midi", "name": "Lead", "index": 2},
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert resp.result["track_index"] == 2
    assert resp.result["name"] == "Lead"


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


def test_delete_refuses_last_remaining_track(loaded_actions):
    """W18-E: Live requires the set to contain at least one track. Deleting
    the last surviving track must surface a teaching error (with a
    recoverable hint) instead of letting Live's bare RuntimeError through.
    """
    song = FakeSong(tracks=[FakeTrack(name="OnlyOne")])
    ctx = FakeCtx(song=song)
    resp = dispatch(
        Request(tool="ableton_track", action="delete", params={"track_index": 1}),
        context=ctx,
    )
    assert resp.ok is False
    # Track wasn't deleted — refusal preceded Live's API call.
    assert len(song.tracks) == 1
    assert song._deleted_tracks == []
    # Error explains the constraint AND the path forward.
    assert "at least one track" in resp.error
    assert "ableton_track(action='create')" in resp.error


def test_delete_passes_int_to_live_api(loaded_actions):
    """Regression for Wave-2 W2-2 / Wave-1 B-23: ``Song.delete_track`` must
    receive a 0-based int, not the Track wrapper. The tightened FakeSong
    raises TypeError on a wrapper, so this test passes only when the
    handler does the right thing. Lock in the contract explicitly.
    """
    ctx = FakeCtx()
    resp = dispatch(
        Request(tool="ableton_track", action="delete", params={"track_index": 3}),
        context=ctx,
    )
    assert resp.ok is True, (
        f"delete handler regressed to passing a Track wrapper. "
        f"Response: {resp.to_dict()}"
    )


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
    # Wave-2 W2-D / B-15: result_template echoes track_index + name so
    # callers get a confirming response instead of result=None.
    assert resp.result == {"track_index": 1, "name": "Renamed"}, (
        f"track.rename should return {{track_index, name}}; got {resp.result!r}"
    )


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


# ---------- set_property: dB value_display (MIX-6K2P) ----------


def _set_property(ctx, **params):
    return dispatch(
        Request(tool="ableton_track", action="set_property", params=params),
        context=ctx,
    )


def test_set_property_volume_value_display_resolves_db(loaded_actions):
    # -8 dB inverts Live's fader curve to v = -8/40 + 0.85 = 0.65. The raw
    # converges to within one display quantum (the fader shows 0.1-dB steps);
    # the echoed display is the exact contract.
    ctx = FakeCtx()
    resp = _set_property(ctx, track_index=1, property="volume", value_display="-8 dB")
    assert resp.ok is True, resp.error
    assert ctx.song.tracks[0].mixer_device.volume.value == pytest.approx(0.65, abs=2e-3)
    assert resp.result["value_display"] == "-8.0 dB"


def test_set_property_volume_value_display_unity(loaded_actions):
    ctx = FakeCtx()
    resp = _set_property(ctx, track_index=1, property="volume", value_display="0 dB")
    assert resp.ok is True, resp.error
    assert ctx.song.tracks[0].mixer_device.volume.value == pytest.approx(0.85, abs=2e-3)


def test_set_property_value_only_echoes_db_for_volume(loaded_actions):
    # The raw-value path still works and now also echoes the achieved dB.
    ctx = FakeCtx()
    resp = _set_property(ctx, track_index=1, property="volume", value=0.65)
    assert resp.ok is True, resp.error
    assert resp.result["value"] == 0.65
    assert resp.result["value_display"] == "-8.0 dB"


def test_set_property_value_display_refused_on_panning(loaded_actions):
    # Pan's display ('C' at center) isn't a signed number, so it can't be
    # addressed by value_display — refused with guidance to use `value`.
    ctx = FakeCtx()
    resp = _set_property(ctx, track_index=1, property="panning", value_display="0 dB")
    assert resp.ok is False
    assert "value" in (resp.error or "").lower()


def test_set_property_value_display_refused_on_mute(loaded_actions):
    ctx = FakeCtx()
    resp = _set_property(ctx, track_index=1, property="mute", value_display="1")
    assert resp.ok is False
    assert "parameter-backed" in (resp.error or "")


def test_set_property_rejects_both_value_and_value_display(loaded_actions):
    ctx = FakeCtx()
    resp = _set_property(
        ctx, track_index=1, property="volume", value=0.5, value_display="-8 dB"
    )
    assert resp.ok is False
    assert "exactly one" in (resp.error or "")


def test_set_property_requires_value_when_no_display(loaded_actions):
    ctx = FakeCtx()
    resp = _set_property(ctx, track_index=1, property="volume")
    assert resp.ok is False
    assert "requires" in (resp.error or "")


def test_info_includes_volume_db(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(tool="ableton_track", action="info", params={"track_index": 1}),
        context=ctx,
    )
    assert resp.ok is True
    # Default fader is 0.85 -> 0 dB; no panning_db (pan has no dB sense).
    assert resp.result["volume_db"] == 0.0
    assert "panning_db" not in resp.result


def test_info_volume_db_is_none_when_fader_fully_down(loaded_actions):
    ctx = FakeCtx()
    ctx.song.tracks[0].mixer_device.volume.value = 0.0  # reads "-inf dB"
    resp = dispatch(
        Request(tool="ableton_track", action="info", params={"track_index": 1}),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["volume"] == 0.0
    assert resp.result["volume_db"] is None


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


# ---------- output routing ----------


class _Routing:
    """Mirrors Live's RoutingType / RoutingChannel — only ``display_name`` is
    needed by the handlers. Matched by display_name, never object identity:
    Live re-wraps these on every access, so two wrappers for the same routing
    target won't be ``is``-equal."""

    def __init__(self, name: str):
        self.display_name = name


def _track_with_output_routing(
    name: str = "Inst",
    *,
    targets: tuple[str, ...] = ("Ext. Out", "Main", "PRE-MAIN", "Sends Only"),
    channels: tuple[str, ...] = ("Pre FX", "Post FX", "Post Mixer", "Track In"),
    current_type: str = "Main",
    current_channel: str = "Post Mixer",
) -> FakeTrack:
    """A FakeTrack exposing Live's output_routing_* surface — opt-in like the
    device sidechain fakes. The base FakeTrack omits these attrs so the
    has_output_routing=False path stays testable. Default targets mirror the
    live-probed audio-track set (Ext. Out / Main / <bus> / Sends Only)."""
    t = FakeTrack(name=name, kind="audio")
    t.available_output_routing_types = [_Routing(n) for n in targets]
    t.available_output_routing_channels = [_Routing(n) for n in channels]
    t.output_routing_type = _Routing(current_type)
    t.output_routing_channel = _Routing(current_channel)
    return t


def test_set_output_routing_finds_by_display_name(loaded_actions):
    track = _track_with_output_routing()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_output_routing",
            params={"track_index": 1, "type_display_name": "PRE-MAIN"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    # Resolved by display_name against the available vector (not by `is`).
    assert track.output_routing_type.display_name == "PRE-MAIN"
    assert resp.result["output_routing_type"] == "PRE-MAIN"
    # No channel passed -> channel untouched, not echoed.
    assert "output_routing_channel" not in resp.result


def test_set_output_routing_with_channel(loaded_actions):
    track = _track_with_output_routing()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_output_routing",
            params={
                "track_index": 1,
                "type_display_name": "Main",
                "channel_display_name": "Post FX",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert track.output_routing_type.display_name == "Main"
    assert track.output_routing_channel.display_name == "Post FX"
    assert resp.result["output_routing_channel"] == "Post FX"


def test_set_output_routing_unknown_type_lists_available(loaded_actions):
    track = _track_with_output_routing()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_output_routing",
            params={"track_index": 1, "type_display_name": "Nonexistent"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    # The source track's OWN available targets are surfaced for teaching.
    assert "PRE-MAIN" in err and "Main" in err


def test_set_output_routing_unknown_channel_lists_available(loaded_actions):
    track = _track_with_output_routing()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_output_routing",
            params={
                "track_index": 1,
                "type_display_name": "Main",
                "channel_display_name": "Nope",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "Post Mixer" in err  # available channels surfaced


def test_set_output_routing_source_dependent_targets(loaded_actions):
    """A bare MIDI track legitimately lacks audio-track targets (live-probed:
    only 'Main' + 'Sends Only'). Routing it to an audio bus must fail loudly
    with the track's ACTUAL options, not crash."""
    midi_bus_less = _track_with_output_routing(
        name="BareMIDI", targets=("Main", "Sends Only"),
    )
    ctx = FakeCtx(FakeSong(tracks=[midi_bus_less]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_output_routing",
            params={"track_index": 1, "type_display_name": "PRE-MAIN"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "Sends Only" in err and "Main" in err
    assert "PRE-MAIN" not in err.split("not in available")[1]  # not an option here


def test_set_output_routing_missing_api_raises_teaching_error(loaded_actions):
    """A track family without the output_routing_* API (the master strip is
    the case) fails loudly, not a silent no-op."""
    bare = FakeTrack(name="NoRouting")  # base FakeTrack: no routing attrs
    ctx = FakeCtx(FakeSong(tracks=[bare]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_output_routing",
            params={"track_index": 1, "type_display_name": "Main"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "output_routing" in (resp.error or "")


def test_get_output_routing_returns_current_and_available(loaded_actions):
    track = _track_with_output_routing(current_type="Main", current_channel="Post Mixer")
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="get_output_routing",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    r = resp.result
    assert r["has_output_routing"] is True
    assert r["current_type"] == "Main"
    assert "PRE-MAIN" in r["available_types"]
    assert r["current_channel"] == "Post Mixer"
    assert "Track In" in r["available_channels"]


def test_get_output_routing_no_api_returns_false_no_raise(loaded_actions):
    """Symmetric with the device capability probe: get_ returns
    has_output_routing=False instead of raising when the API is absent."""
    bare = FakeTrack(name="NoRouting")  # base FakeTrack: no routing attrs
    ctx = FakeCtx(FakeSong(tracks=[bare]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="get_output_routing",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["has_output_routing"] is False
    assert "current_type" not in resp.result


def test_set_output_routing_rejects_out_of_range_index(loaded_actions):
    ctx = FakeCtx(FakeSong(tracks=[_track_with_output_routing()]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_output_routing",
            params={"track_index": 99, "type_display_name": "Main"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "out of range" in (resp.error or "")


# ---------- input routing ----------


def _track_with_input_routing(
    name: str = "Bus",
    *,
    sources: tuple[str, ...] = ("No Input", "Ext. In", "Drums", "Bass"),
    channels: tuple[str, ...] = ("Pre FX", "Post FX", "Post Mixer"),
    current_type: str = "No Input",
    current_channel: str = "Post FX",
    monitoring_state: int = 1,  # Auto
) -> FakeTrack:
    """A FakeTrack exposing Live's input_routing_* surface + monitor switch —
    a receiving-bus fake. Base FakeTrack omits these so the absent-API paths
    stay testable."""
    t = FakeTrack(name=name, kind="audio")
    t.available_input_routing_types = [_Routing(n) for n in sources]
    t.available_input_routing_channels = [_Routing(n) for n in channels]
    t.input_routing_type = _Routing(current_type)
    t.input_routing_channel = _Routing(current_channel)
    t.current_monitoring_state = monitoring_state
    return t


def test_set_input_routing_finds_by_display_name(loaded_actions):
    track = _track_with_input_routing()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_input_routing",
            params={"track_index": 1, "type_display_name": "Drums"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert track.input_routing_type.display_name == "Drums"
    assert resp.result["input_routing_type"] == "Drums"
    assert "input_routing_channel" not in resp.result


def test_set_input_routing_with_channel(loaded_actions):
    track = _track_with_input_routing()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_input_routing",
            params={
                "track_index": 1,
                "type_display_name": "Bass",
                "channel_display_name": "Pre FX",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert track.input_routing_type.display_name == "Bass"
    assert track.input_routing_channel.display_name == "Pre FX"
    assert resp.result["input_routing_channel"] == "Pre FX"


def test_set_input_routing_unknown_type_lists_available(loaded_actions):
    track = _track_with_input_routing()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_input_routing",
            params={"track_index": 1, "type_display_name": "Ghost"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "Drums" in err and "Ext. In" in err


def test_set_input_routing_missing_api_raises_teaching_error(loaded_actions):
    bare = FakeTrack(name="NoRouting")
    ctx = FakeCtx(FakeSong(tracks=[bare]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_input_routing",
            params={"track_index": 1, "type_display_name": "Drums"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "input_routing" in (resp.error or "")


def test_get_input_routing_returns_current_and_available(loaded_actions):
    track = _track_with_input_routing(current_type="No Input", current_channel="Post FX")
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="get_input_routing",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    r = resp.result
    assert r["has_input_routing"] is True
    assert r["current_type"] == "No Input"
    assert "Drums" in r["available_types"]
    assert "Post FX" in r["available_channels"]


def test_get_input_routing_no_api_returns_false_no_raise(loaded_actions):
    bare = FakeTrack(name="NoRouting")
    ctx = FakeCtx(FakeSong(tracks=[bare]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="get_input_routing",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["has_input_routing"] is False
    assert "current_type" not in resp.result


# ---------- monitor state ----------


def test_set_monitoring_state_in_round_trips(loaded_actions):
    """Acceptance: a receiving bus can be set Monitor=In and read back."""
    track = _track_with_input_routing(monitoring_state=1)  # starts Auto
    ctx = FakeCtx(FakeSong(tracks=[track]))
    set_resp = dispatch(
        Request(
            tool="ableton_track", action="set_monitoring_state",
            params={"track_index": 1, "state": "In"},
        ),
        context=ctx,
    )
    assert set_resp.ok is True, set_resp.error
    assert set_resp.result["monitoring_state"] == "In"
    # Side effect: Live's int enum, In == 0.
    assert track.current_monitoring_state == 0
    # Round-trip read.
    get_resp = dispatch(
        Request(
            tool="ableton_track", action="get_monitoring_state",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert get_resp.ok is True
    assert get_resp.result["has_monitoring_state"] is True
    assert get_resp.result["monitoring_state"] == "In"


def test_set_monitoring_state_rejects_unknown_state(loaded_actions):
    # The action schema's enum=('In','Auto','Off') means the dispatcher's
    # enum gate rejects this before the handler runs (the handler's own
    # ValueError is defense-in-depth for direct calls); either way the valid
    # states are surfaced.
    track = _track_with_input_routing()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_monitoring_state",
            params={"track_index": 1, "state": "Loud"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "In" in err and "Auto" in err and "Off" in err  # valid states listed


def test_set_monitoring_state_missing_switch_raises(loaded_actions):
    """Master / return tracks have no monitor switch — fail loudly."""
    bare = FakeTrack(name="NoMonitor")  # no current_monitoring_state attr
    ctx = FakeCtx(FakeSong(tracks=[bare]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_monitoring_state",
            params={"track_index": 1, "state": "In"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "current_monitoring_state" in (resp.error or "")


def test_get_monitoring_state_no_switch_returns_false_no_raise(loaded_actions):
    bare = FakeTrack(name="NoMonitor")
    ctx = FakeCtx(FakeSong(tracks=[bare]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="get_monitoring_state",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["has_monitoring_state"] is False
    assert "monitoring_state" not in resp.result


@pytest.mark.parametrize("state,raw", [("In", 0), ("Auto", 1), ("Off", 2)])
def test_set_monitoring_state_all_states_pin_raw_int(loaded_actions, state, raw):
    """Every state maps to its documented Live int, and reads back as the name
    — guards the In=0/Auto=1/Off=2 mapping in both directions."""
    track = _track_with_input_routing(monitoring_state=99)  # sentinel start
    ctx = FakeCtx(FakeSong(tracks=[track]))
    set_resp = dispatch(
        Request(
            tool="ableton_track", action="set_monitoring_state",
            params={"track_index": 1, "state": state},
        ),
        context=ctx,
    )
    assert set_resp.ok is True, set_resp.error
    assert track.current_monitoring_state == raw
    get_resp = dispatch(
        Request(
            tool="ableton_track", action="get_monitoring_state",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert get_resp.result["monitoring_state"] == state


def test_get_monitoring_state_unknown_int_surfaces_raw(loaded_actions):
    """An out-of-vocabulary int (a future Live enum shift) is not silently
    lost: name is None but the raw value is surfaced for diagnosis."""
    track = _track_with_input_routing(monitoring_state=7)
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="get_monitoring_state",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["has_monitoring_state"] is True
    assert resp.result["monitoring_state"] is None
    assert resp.result["monitoring_state_raw"] == 7


# ---------- atomicity: a bad channel must not half-apply the type ----------


def test_set_output_routing_atomic_on_channel_failure(loaded_actions):
    """If the channel name is invalid the output type reroute must NOT land —
    otherwise an error response masks a half-mutated session."""
    track = _track_with_output_routing(current_type="Main")
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_output_routing",
            params={
                "track_index": 1,
                "type_display_name": "PRE-MAIN",
                "channel_display_name": "Bogus",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    # Type untouched — still the original target, not the requested PRE-MAIN.
    assert track.output_routing_type.display_name == "Main"


def test_set_input_routing_atomic_on_channel_failure(loaded_actions):
    track = _track_with_input_routing(current_type="No Input")
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_input_routing",
            params={
                "track_index": 1,
                "type_display_name": "Drums",
                "channel_display_name": "Bogus",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert track.input_routing_type.display_name == "No Input"


def test_set_input_routing_unknown_channel_lists_available(loaded_actions):
    track = _track_with_input_routing()
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_track", action="set_input_routing",
            params={
                "track_index": 1,
                "type_display_name": "Drums",
                "channel_display_name": "Nope",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "Post FX" in (resp.error or "")  # available channels surfaced
