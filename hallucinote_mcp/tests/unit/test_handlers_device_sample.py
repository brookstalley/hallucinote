"""``ableton_device(action='assign_sample')`` and the sampler read surface.

The contract is probe row 18 of `docs/research/audio-first-class/lom-probe-results.md`:
``SimplerDevice.replace_sample(abs_path)`` returns None, and ``device.sample``
is None before the call and afterwards a ``Sample`` whose ``file_path``
round-trips the path verbatim. The fakes here are built to exactly that shape,
so a test passing means the handler speaks the surface Live actually exposes.

The read half matters as much as the write: ``list`` and ``info`` report
``sample_file_path`` for any device with a sample slot — present and None for
an empty one, absent entirely for a device that has no slot. That difference is
what the push planner reads to tell "this sampler has nothing loaded" from
"this is a Compressor and can never play a sample".
"""
from __future__ import annotations

import threading
from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------- fakes, shaped to probe row 18 ----------


class FakeSample:
    """Live's ``Sample``, cut down to the one field the handlers read."""

    def __init__(self, file_path: str):
        self.file_path = file_path


class FakeDevice:
    """A device with NO sample slot — reading ``.sample`` raises, as Live does
    for a device class that has no such property."""

    def __init__(self, name: str, class_name: str = "Compressor2"):
        self.name = name
        self.class_name = class_name
        self.class_display_name = class_name
        self.is_active = True
        self.parameters: list[Any] = []

    @property
    def sample(self) -> Any:
        raise AttributeError("sample")


class FakeSimpler:
    """``OriginalSimpler``: ``sample`` is None until ``replace_sample`` runs."""

    def __init__(self, name: str = "Simpler", *, refuse: str | None = None):
        self.name = name
        self.class_name = "OriginalSimpler"
        self.class_display_name = "Simpler"
        self.is_active = True
        self.parameters: list[Any] = []
        self.sample: FakeSample | None = None
        self.replace_calls: list[str] = []
        self._refuse = refuse

    def replace_sample(self, path: str) -> None:
        self.replace_calls.append(path)
        if self._refuse is not None:
            raise RuntimeError(self._refuse)
        self.sample = FakeSample(path)


class FakeDeadSimpler(FakeSimpler):
    """Accepts the call and assigns nothing — the silent no-op Live can do."""

    def replace_sample(self, path: str) -> None:
        self.replace_calls.append(path)


class FakeStaleSimpler(FakeSimpler):
    """Accepts the call and keeps the sample it already had — the other silent
    no-op, invisible to a presence check."""

    def replace_sample(self, path: str) -> None:
        self.replace_calls.append(path)
        if self.sample is None:
            self.sample = FakeSample("/somewhere/previous.wav")


class FakeChain:
    def __init__(self, name: str, devices: list[Any] | None = None):
        self.name = name
        self.devices = list(devices or [])


class FakeRack(FakeDevice):
    def __init__(self, name: str = "Rack", chains: list[FakeChain] | None = None):
        super().__init__(name, class_name="InstrumentGroupDevice")
        self.class_display_name = "Instrument Rack"
        self.chains = list(chains or [])
        self.can_have_chains = True


class FakeTrack:
    def __init__(self, name: str = "T", devices: list[Any] | None = None):
        self.name = name
        self.devices = list(devices or [])


class FakeSong:
    def __init__(self, tracks: list[FakeTrack] | None = None):
        self.tracks = tracks or [FakeTrack("T1")]
        self.return_tracks = [FakeTrack("A-Rev")]
        self.master_track = FakeTrack("Master")


class FakeCtx:
    def __init__(self, song: FakeSong):
        self._song = song
        self._live_state_lock = threading.RLock()

    @property
    def song(self) -> FakeSong:
        return self._song

    @property
    def application(self) -> Any:
        """Assigning a sample reaches Live through the song, never the browser
        or the view — a test that trips this is exercising the wrong path."""
        raise AssertionError("assign_sample must not touch Live.Application")

    @property
    def live_state_lock(self) -> threading.RLock:
        return self._live_state_lock

    def run_on_main(self, fn, **_kwargs):
        return fn()


@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


@pytest.fixture()
def wav(tmp_path):
    """A real file on disk — the handler existence-checks before calling Live."""
    path = tmp_path / "vox.wav"
    path.write_bytes(b"RIFF....WAVE")
    return str(path)


def _assign(ctx: FakeCtx, **params: Any):
    return dispatch(
        Request(tool="ableton_device", action="assign_sample", params=params),
        context=ctx,
    )


# ---------- the action exists on the tool ----------


def test_assign_sample_is_registered(loaded_actions):
    names = {a.name for a in schema.actions_for("ableton_device")}
    assert "assign_sample" in names


# ---------- assigning ----------


def test_assign_sample_points_a_simpler_at_the_file(loaded_actions, wav):
    simpler = FakeSimpler()
    ctx = FakeCtx(FakeSong([FakeTrack("Vox", devices=[simpler])]))

    resp = _assign(ctx, track_index=1, device_index=1, sample_path=wav)

    assert resp.ok is True, resp.error
    assert simpler.replace_calls == [wav]
    assert resp.result["sample_file_path"] == wav
    assert resp.result["track_index"] == 1
    assert resp.result["device_index"] == 1


def test_assign_sample_is_re_callable(loaded_actions, wav, tmp_path):
    """A second assignment REPLACES the first — the property the push planner
    relies on when it emits without knowing whether it already ran."""
    other = tmp_path / "other.wav"
    other.write_bytes(b"RIFF....WAVE")
    simpler = FakeSimpler()
    ctx = FakeCtx(FakeSong([FakeTrack("Vox", devices=[simpler])]))

    _assign(ctx, track_index=1, device_index=1, sample_path=wav)
    resp = _assign(ctx, track_index=1, device_index=1, sample_path=str(other))

    assert resp.ok is True, resp.error
    assert resp.result["sample_file_path"] == str(other)
    assert simpler.sample is not None
    assert simpler.sample.file_path == str(other)


def test_assign_sample_reaches_a_simpler_nested_in_a_rack(loaded_actions, wav):
    simpler = FakeSimpler("Inner")
    rack = FakeRack(chains=[FakeChain("Chain 1", devices=[FakeDevice("EQ"), simpler])])
    ctx = FakeCtx(FakeSong([FakeTrack("Keys", devices=[rack])]))

    resp = _assign(
        ctx,
        track_index=1,
        device_index=1,
        device_path=[{"chain_index": 1, "device_position": 2}],
        sample_path=wav,
    )

    assert resp.ok is True, resp.error
    assert simpler.replace_calls == [wav]
    assert resp.result["device_path"] == [{"chain_index": 1, "device_position": 2}]


def test_assign_sample_on_a_return_device(loaded_actions, wav):
    simpler = FakeSimpler()
    song = FakeSong()
    song.return_tracks = [FakeTrack("A-Rev", devices=[simpler])]
    ctx = FakeCtx(song)

    resp = _assign(ctx, return_index=1, device_index=1, sample_path=wav)

    assert resp.ok is True, resp.error
    assert resp.result["return_index"] == 1


# ---------- refusals, each naming its own cause ----------


def test_assign_sample_on_a_non_sampler_teaches(loaded_actions, wav):
    ctx = FakeCtx(FakeSong([FakeTrack("Drums", devices=[FakeDevice("Comp")])]))

    resp = _assign(ctx, track_index=1, device_index=1, sample_path=wav)

    assert resp.ok is False
    assert "Compressor2" in (resp.error or "")
    assert "Simpler" in (resp.error or "")


def test_assign_sample_refuses_a_relative_path(loaded_actions):
    simpler = FakeSimpler()
    ctx = FakeCtx(FakeSong([FakeTrack("Vox", devices=[simpler])]))

    resp = _assign(
        ctx, track_index=1, device_index=1, sample_path="assets/vox.wav",
    )

    assert resp.ok is False
    assert "ABSOLUTE" in (resp.error or "")
    assert simpler.replace_calls == []


def test_assign_sample_refuses_a_path_with_no_file(loaded_actions, tmp_path):
    simpler = FakeSimpler()
    ctx = FakeCtx(FakeSong([FakeTrack("Vox", devices=[simpler])]))
    missing = str(tmp_path / "gone.wav")

    resp = _assign(ctx, track_index=1, device_index=1, sample_path=missing)

    assert resp.ok is False
    assert "no file at" in (resp.error or "")
    assert missing in (resp.error or "")
    assert simpler.replace_calls == []


def test_assign_sample_surfaces_lives_own_refusal(loaded_actions, wav):
    simpler = FakeSimpler(refuse="The provided path does not appear to point to a valid audio file")
    ctx = FakeCtx(FakeSong([FakeTrack("Vox", devices=[simpler])]))

    resp = _assign(ctx, track_index=1, device_index=1, sample_path=wav)

    assert resp.ok is False
    assert "valid audio file" in (resp.error or "")
    assert "decode" in (resp.error or "")


def test_assign_sample_refuses_a_silent_no_op(loaded_actions, wav):
    """The call returned and the device still reports nothing loaded — the push
    must not read that as an assignment that happened."""
    ctx = FakeCtx(FakeSong([FakeTrack("Vox", devices=[FakeDeadSimpler()])]))

    resp = _assign(ctx, track_index=1, device_index=1, sample_path=wav)

    assert resp.ok is False
    assert "still" in (resp.error or "")
    assert "no sample" in (resp.error or "")


def test_assign_sample_refuses_a_sampler_that_kept_its_old_sample(loaded_actions, wav):
    """The call returned, the device answers ``.sample`` — but with the file it
    already had. A presence check would call that an assignment."""
    ctx = FakeCtx(FakeSong([FakeTrack("Vox", devices=[FakeStaleSimpler()])]))

    resp = _assign(ctx, track_index=1, device_index=1, sample_path=wav)

    assert resp.ok is False
    assert "previous.wav" in (resp.error or "")
    assert "kept the previous sample" in (resp.error or "")


def test_assign_sample_needs_exactly_one_parent(loaded_actions, wav):
    ctx = FakeCtx(FakeSong([FakeTrack("Vox", devices=[FakeSimpler()])]))

    resp = _assign(ctx, device_index=1, sample_path=wav)

    assert resp.ok is False
    assert "track_index" in (resp.error or "")


# ---------- the read surface the planner diffs against ----------


def test_info_reports_the_assigned_sample(loaded_actions, wav):
    simpler = FakeSimpler()
    simpler.sample = FakeSample(wav)
    ctx = FakeCtx(FakeSong([FakeTrack("Vox", devices=[simpler])]))

    resp = dispatch(
        Request(
            tool="ableton_device", action="info",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )

    assert resp.ok is True, resp.error
    assert resp.result["sample_file_path"] == wav


def test_info_reports_an_empty_slot_as_none_not_absent(loaded_actions):
    """A Simpler with nothing loaded still ANSWERS the question — the key is
    present with a None value, which is how a caller tells an empty sampler
    from a device that has no slot at all."""
    ctx = FakeCtx(FakeSong([FakeTrack("Vox", devices=[FakeSimpler()])]))

    resp = dispatch(
        Request(
            tool="ableton_device", action="info",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )

    assert resp.ok is True, resp.error
    assert "sample_file_path" in resp.result
    assert resp.result["sample_file_path"] is None


def test_info_omits_the_key_for_a_device_with_no_sample_slot(loaded_actions):
    ctx = FakeCtx(FakeSong([FakeTrack("Drums", devices=[FakeDevice("Comp")])]))

    resp = dispatch(
        Request(
            tool="ableton_device", action="info",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )

    assert resp.ok is True, resp.error
    assert "sample_file_path" not in resp.result


def test_list_reports_the_sample_per_device(loaded_actions, wav):
    simpler = FakeSimpler()
    simpler.sample = FakeSample(wav)
    ctx = FakeCtx(
        FakeSong([FakeTrack("Vox", devices=[FakeDevice("Comp"), simpler])])
    )

    resp = dispatch(
        Request(
            tool="ableton_device", action="list", params={"track_index": 1},
        ),
        context=ctx,
    )

    assert resp.ok is True, resp.error
    comp, simp = resp.result["devices"]
    assert "sample_file_path" not in comp
    assert simp["sample_file_path"] == wav
