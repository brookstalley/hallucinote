"""ableton_return schema + handler behavior."""
from __future__ import annotations

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------- Fakes ----------


class FakeParam:
    def __init__(self, value: float = 0.0):
        self.value = value


class FakeMixer:
    def __init__(self, volume=0.85, panning=0.0):
        self.volume = FakeParam(volume)
        self.panning = FakeParam(panning)


class FakeReturn:
    def __init__(self, name: str = "A-Rev", color: int | None = None):
        self.name = name
        self.mixer_device = FakeMixer()
        self.mute = False
        self.solo = False
        self.color = color


class FakeSong:
    def __init__(self, returns=None):
        self.return_tracks: list[FakeReturn] = (
            returns if returns is not None else [
                FakeReturn(name="A-Reverb"),
                FakeReturn(name="B-Delay"),
            ]
        )
        self._created: list[FakeReturn] = []
        self._deleted: list[FakeReturn] = []

    def create_return_track(self) -> FakeReturn:
        new_ret = FakeReturn(name="Return")
        self._created.append(new_ret)
        self.return_tracks.append(new_ret)
        return new_ret

    def delete_return_track(self, index_0based: int) -> None:
        # Live 12.4's C++ signature is delete_return_track(int). Passing the
        # ReturnTrack wrapper raises ArgumentError at the C++ boundary. We
        # mirror that strictly here so handler bugs that pass a wrapper
        # fail at test time, not in production (Wave-2 W2-3 root cause).
        if not isinstance(index_0based, int) or isinstance(index_0based, bool):
            raise TypeError(
                "Song.delete_return_track(int) — got "
                f"{type(index_0based).__name__}; Live's C++ signature "
                f"rejects wrapper objects"
            )
        self._deleted.append(self.return_tracks[index_0based])
        del self.return_tracks[index_0based]


class FakeCtx:
    def __init__(self, song: FakeSong | None = None):
        self._song = song if song is not None else FakeSong()

    @property
    def song(self) -> FakeSong:
        return self._song

    def run_on_main(self, fn):
        return fn()


@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


# ---------- Schema sanity ----------


_EXPECTED_RETURN_ACTIONS = {
    "help", "list", "info", "create", "rename", "delete", "set_property",
}


def test_return_registers_seven_actions(loaded_actions):
    names = {a.name for a in schema.actions_for("ableton_return")}
    assert names == _EXPECTED_RETURN_ACTIONS


def test_return_help_lists_actions(loaded_actions):
    resp = dispatch(Request(tool="ableton_return", action="help"))
    assert resp.ok is True
    names = {a["name"] for a in resp.result["actions"]}
    assert names == _EXPECTED_RETURN_ACTIONS - {"help"}


# ---------- list / info ----------


def test_list_returns_thin_index(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(Request(tool="ableton_return", action="list"), context=ctx)
    assert resp.ok is True
    returns = resp.result["returns"]
    assert [r["name"] for r in returns] == ["A-Reverb", "B-Delay"]
    assert [r["return_index"] for r in returns] == [1, 2]


def test_info_returns_mixer_state(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(tool="ableton_return", action="info", params={"return_index": 1}),
        context=ctx,
    )
    assert resp.ok is True
    r = resp.result
    assert r["return_index"] == 1
    assert r["name"] == "A-Reverb"
    assert r["volume"] == 0.85


# ---------- create / delete ----------


def test_create_return_appends(loaded_actions):
    ctx = FakeCtx()
    before = len(ctx.song.return_tracks)
    resp = dispatch(
        Request(
            tool="ableton_return",
            action="create",
            params={"name": "C-Plate"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["return_index"] == before + 1
    assert resp.result["name"] == "C-Plate"
    assert ctx.song.return_tracks[-1].name == "C-Plate"


# Regression: real Live re-wraps return-track objects on each property
# access, so scanning ``song.return_tracks`` for ``new_return`` by ``is``
# used to spuriously fail and the handler raised a false-positive "Live
# API bug". The fix uses the deterministic post-append length (Live's
# ``create_return_track()`` always appends).


class _ReWrappingReturnSong:
    """Wrapper-per-access semantics for return_tracks."""

    def __init__(self) -> None:
        self._underlying: list[dict] = [
            {"name": "A-Reverb"}, {"name": "B-Delay"},
        ]

    @property
    def return_tracks(self):
        return [_FreshReturnWrapper(d) for d in self._underlying]

    def create_return_track(self):
        d = {"name": "Return"}
        self._underlying.append(d)
        return _FreshReturnWrapper(d)


class _FreshReturnWrapper:
    def __init__(self, data: dict) -> None:
        self._data = data

    @property
    def name(self) -> str:
        return self._data["name"]

    @name.setter
    def name(self, value: str) -> None:
        self._data["name"] = value


class _ReturnCtx:
    def __init__(self) -> None:
        self._song = _ReWrappingReturnSong()

    @property
    def song(self):
        return self._song

    def run_on_main(self, fn):
        return fn()


def test_create_return_handles_live_wrapper_recreation(loaded_actions):
    """The new return's index is computed as len-after-append, no scan."""
    ctx = _ReturnCtx()
    resp = dispatch(
        Request(
            tool="ableton_return", action="create",
            params={"name": "C-Plate"},
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert resp.result["return_index"] == 3  # appended to a 2-return song
    assert resp.result["name"] == "C-Plate"


# ---------- W3-H: name-clobber mitigation + rename action ----------


class _PrefixingReturn:
    """Mirrors Live 12.x's slot-letter auto-prefix on FIRST name write.

    Empirical Live behavior observed 2026-05-17 / 2026-05-18: setting
    ``new_return.name = "X"`` right after create_return_track() yields
    ``"<slot>-X"``. A SUBSEQUENT name write lands cleanly (Live's
    prefix logic appears to fire only on the first-name-set-after-create).
    """

    def __init__(self, slot_letter: str = "C"):
        self._name = "Return"
        self._slot_letter = slot_letter
        self._writes_since_create = 0

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._writes_since_create += 1
        if self._writes_since_create == 1:
            # First write after create: Live's auto-prefix fires.
            self._name = f"{self._slot_letter}-{value}"
        else:
            # Subsequent writes land cleanly.
            self._name = value


class _PrefixingSong:
    def __init__(self):
        self.return_tracks: list = [
            FakeReturn(name="A-Reverb"),
            FakeReturn(name="B-Delay"),
        ]

    def create_return_track(self):
        new_ret = _PrefixingReturn(slot_letter="C")
        self.return_tracks.append(new_ret)
        return new_ret


def test_create_return_retries_once_when_live_prefixes_name(loaded_actions):
    """W3-H: when Live mutates the name on the first write, the handler
    detects the mismatch and retries once. The second write lands
    cleanly (empirical Live behavior — auto-prefix logic fires only on
    first-set-after-create).
    """
    ctx = FakeCtx(song=_PrefixingSong())
    resp = dispatch(
        Request(
            tool="ableton_return",
            action="create",
            params={"name": "TestReturn"},
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    # Pre-W3-H: would return "C-TestReturn". Post-W3-H: handler's retry
    # gets us back to "TestReturn".
    assert resp.result["name"] == "TestReturn", (
        f"create handler did not retry the name write after Live's "
        f"first-write prefix clobber: got {resp.result['name']!r}"
    )


class _AlwaysPrefixingReturn(_PrefixingReturn):
    """Worst-case: Live prefixes on EVERY write. The handler retries
    but the result is still prefixed. We accept that and report what
    Live gave us — the rename action is the explicit recovery path."""

    @_PrefixingReturn.name.setter
    def name(self, value: str) -> None:
        # type:ignore[no-redef]
        self._name = f"{self._slot_letter}-{value}"


class _AlwaysPrefixingSong:
    def __init__(self):
        self.return_tracks: list = [FakeReturn(name="A-R"), FakeReturn(name="B-D")]

    def create_return_track(self):
        new_ret = _AlwaysPrefixingReturn(slot_letter="C")
        self.return_tracks.append(new_ret)
        return new_ret


def test_create_return_accepts_final_name_when_retry_does_not_help(loaded_actions):
    """W3-H: when retry doesn't undo Live's prefix, the handler accepts
    what Live gave us and reports it in result["name"]. The caller can
    detect the mismatch and use the rename action to fix it explicitly."""
    ctx = FakeCtx(song=_AlwaysPrefixingSong())
    resp = dispatch(
        Request(
            tool="ableton_return",
            action="create",
            params={"name": "TestReturn"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    # Live always prefixed; handler returns what Live gave us. Caller
    # who needs the clean name can call rename next.
    assert resp.result["name"] == "C-TestReturn"


def test_rename_return_writes_name(loaded_actions):
    """W3-H: new ``rename`` action — the recovery path when create's
    name-clobber retry didn't fully resolve, or when the user just wants
    to rename a return mid-session."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_return",
            action="rename",
            params={"return_index": 1, "name": "Plate"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result == {"return_index": 1, "name": "Plate"}
    assert ctx.song.return_tracks[0].name == "Plate"


def test_rename_return_out_of_range(loaded_actions):
    """Range check fires before the name write — teaching error, no mutation."""
    ctx = FakeCtx()
    pre_names = [r.name for r in ctx.song.return_tracks]
    resp = dispatch(
        Request(
            tool="ableton_return",
            action="rename",
            params={"return_index": 99, "name": "Whatever"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "99" in (resp.error or "")
    # No mutation despite the failed call.
    assert [r.name for r in ctx.song.return_tracks] == pre_names


# ---------- create teaching error ----------


def test_create_return_raises_if_live_api_missing(loaded_actions):
    """If Live (or our fake) doesn't expose ``create_return_track``, we get a
    teaching error rather than a raw AttributeError.
    """
    class _BareSong:
        return_tracks: list = []
    ctx = FakeCtx(song=_BareSong())
    resp = dispatch(
        Request(tool="ableton_return", action="create", params={"name": "x"}),
        context=ctx,
    )
    assert resp.ok is False
    assert "create_return_track" in (resp.error or "")


def test_delete_return_removes(loaded_actions):
    ctx = FakeCtx()
    target = ctx.song.return_tracks[1]
    resp = dispatch(
        Request(
            tool="ableton_return",
            action="delete",
            params={"return_index": 2},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["deleted_return_index"] == 2
    assert target not in ctx.song.return_tracks


def test_delete_return_passes_int_to_live_api(loaded_actions):
    """Regression for Wave-2 W2-3: ``Song.delete_return_track`` must receive
    a 0-based int, not the ReturnTrack wrapper. The tightened FakeSong
    raises TypeError on a wrapper, so this test passes only when the
    handler does the right thing.
    """
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_return",
            action="delete",
            params={"return_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True, (
        f"return.delete handler regressed to passing a ReturnTrack wrapper. "
        f"Response: {resp.to_dict()}"
    )


def test_delete_return_raises_if_live_api_missing(loaded_actions):
    """Symmetric to test_create_return_raises_if_live_api_missing — older Live
    builds may not expose ``delete_return_track``; we surface a teaching
    error instead of a raw AttributeError."""

    class _BareSong:
        # Has return_tracks (so range check passes) but no delete_return_track.
        return_tracks = [FakeReturn(name="A")]

    ctx = FakeCtx(song=_BareSong())
    resp = dispatch(
        Request(tool="ableton_return", action="delete", params={"return_index": 1}),
        context=ctx,
    )
    assert resp.ok is False
    assert "delete_return_track" in (resp.error or "")


# ---------- set_property ----------


@pytest.mark.parametrize(
    "property_name, value, expected",
    [
        ("volume", 0.4, 0.4),
        ("panning", 0.2, 0.2),
        ("mute", 1.0, True),
        ("solo", 0, False),
        ("color", 8, 8),
    ],
)
def test_set_property_writes_each_field(loaded_actions, property_name, value, expected):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_return",
            action="set_property",
            params={"return_index": 1, "property": property_name, "value": value},
        ),
        context=ctx,
    )
    assert resp.ok is True
    ret = ctx.song.return_tracks[0]
    if property_name == "volume":
        assert ret.mixer_device.volume.value == expected
    elif property_name == "panning":
        assert ret.mixer_device.panning.value == expected
    elif property_name in ("mute", "solo"):
        assert getattr(ret, property_name) is expected
    elif property_name == "color":
        assert ret.color == expected


def test_set_property_rejects_arm(loaded_actions):
    """Returns can't be armed — schema enum excludes it; validation rejects."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_return",
            action="set_property",
            params={"return_index": 1, "property": "arm", "value": 1},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "not in enum" in (resp.error or "")


def test_set_property_enforces_volume_range(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_return",
            action="set_property",
            params={"return_index": 1, "property": "volume", "value": 1.2},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "out of range" in (resp.error or "")


@pytest.mark.parametrize("bad_value", [-1.5, 1.5])
def test_set_property_enforces_panning_range(loaded_actions, bad_value):
    """Symmetric to track panning range — out-of-range pan values fail with
    a teaching error instead of Live's silent clamp."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_return",
            action="set_property",
            params={"return_index": 1, "property": "panning", "value": bad_value},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "out of range" in (resp.error or "")
