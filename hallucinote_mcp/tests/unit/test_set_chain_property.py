"""set_chain_property_handler — per-DrumChain choke_group / out_note (Chunk C).

Capability-probed (determination='probe'): choke_group / out_note exist on a
DrumChain only. The handler resolves a `chain`-terminal NodeAddr (Chunk A's
grammar), re-probes via hasattr, and teaches on a plain instrument-rack Chain —
never whitelists a class, never crashes. Validation + the probe run before any
write, so a refusal never half-applies.
"""
from __future__ import annotations
import pytest

from hallucinote_mcp.handlers.device import set_chain_property_handler


# --- fakes: the resolver only touches .devices / .chains / index ranges -------

class _DrumChain:
    """A DrumChain exposes settable choke_group / out_note (+ read-only in_note)."""
    def __init__(self, name="Kick", choke_group=0, out_note=36, in_note=36):
        self.name = name
        self.choke_group = choke_group
        self.out_note = out_note
        self.in_note = in_note


class _PlainChain:
    """A plain instrument/audio-rack chain — no choke_group / out_note."""
    def __init__(self, name="808"):
        self.name = name


class _Rack:
    class_name = "DrumGroupDevice"

    def __init__(self, chains):
        self.name = "Kit"
        self.chains = list(chains)


class _Track:
    def __init__(self, devices):
        self.name = "Drums"
        self.devices = list(devices)


class _Song:
    def __init__(self, track):
        self.tracks = [track]
        self.return_tracks = []
        self.master_track = _Track([])


class _Ctx:
    def __init__(self, song):
        self._song = song

    @property
    def song(self):
        return self._song


def _ctx_for(chain):
    return _Ctx(_Song(_Track([_Rack([chain])])))


_CHAIN_NODE = {
    "parent": {"kind": "track", "index": 1}, "terminal": "chain",
    "device_index": 1, "chain_index": 1,
}


def test_set_choke_group_writes_to_the_drumchain():
    chain = _DrumChain()
    res = set_chain_property_handler(
        _ctx_for(chain), node=_CHAIN_NODE, choke_group=3,
    )
    assert chain.choke_group == 3
    assert res["set"] == {"choke_group": 3}
    assert res["node"]["terminal"] == "chain" and res["node"]["chain_index"] == 1
    assert res["track_index"] == 1


def test_set_out_note_transpose():
    chain = _DrumChain(out_note=36)
    set_chain_property_handler(_ctx_for(chain), node=_CHAIN_NODE, out_note=60)
    assert chain.out_note == 60


def test_set_both_at_once():
    chain = _DrumChain()
    res = set_chain_property_handler(
        _ctx_for(chain), node=_CHAIN_NODE, choke_group=2, out_note=48,
    )
    assert (chain.choke_group, chain.out_note) == (2, 48)
    assert res["set"] == {"choke_group": 2, "out_note": 48}


def test_plain_chain_teaches_not_a_drumchain():
    chain = _PlainChain()
    with pytest.raises(NotImplementedError, match="DrumChain only"):
        set_chain_property_handler(
            _ctx_for(chain), node=_CHAIN_NODE, choke_group=1,
        )
    # No attribute was created on the plain chain.
    assert not hasattr(chain, "choke_group")


def test_no_property_passed_is_rejected():
    with pytest.raises(ValueError, match="at least one"):
        set_chain_property_handler(_ctx_for(_DrumChain()), node=_CHAIN_NODE)


def test_non_chain_terminal_is_rejected():
    node = {"parent": {"kind": "track", "index": 1}, "device_index": 1}  # device
    with pytest.raises(ValueError, match="must be 'chain'"):
        set_chain_property_handler(
            _ctx_for(_DrumChain()), node=node, choke_group=1,
        )


@pytest.mark.parametrize("bad", [-1, 128])
def test_out_note_range_validated_before_resolve(bad):
    # Validation precedes resolution — a plain chain context still raises the
    # VALUE error (not the capability one), proving order.
    with pytest.raises(ValueError, match="out_note"):
        set_chain_property_handler(
            _ctx_for(_PlainChain()), node=_CHAIN_NODE, out_note=bad,
        )


def test_negative_choke_group_validated():
    with pytest.raises(ValueError, match="choke_group"):
        set_chain_property_handler(
            _ctx_for(_DrumChain()), node=_CHAIN_NODE, choke_group=-1,
        )


def test_partial_capability_does_not_half_apply():
    """If a chain has choke_group but (hypothetically) not out_note, the probe
    refuses BOTH before any setattr — atomicity."""
    chain = _DrumChain()
    del chain.out_note  # now lacks out_note but still has choke_group
    with pytest.raises(NotImplementedError, match="out_note"):
        set_chain_property_handler(
            _ctx_for(chain), node=_CHAIN_NODE, choke_group=5, out_note=60,
        )
    # choke_group must NOT have been written despite being settable.
    assert chain.choke_group == 0


# --------------------------------------------------------------------------
# NODE-ADDR Chunk F — per-chain mixer state (mute / solo / volume / pan).
# These exist on EVERY chain (not just DrumChains): mute/solo are bools on the
# Chain, volume/pan are values on its ChainMixerDevice.
# --------------------------------------------------------------------------

class _Param:
    def __init__(self, value=0.0):
        self.value = value


class _ChainMixer:
    def __init__(self, volume=0.85, panning=0.0):
        self.volume = _Param(volume)
        self.panning = _Param(panning)


class _MixerChain:
    """Every Live Chain (plain or drum) has mute/solo bools + a ChainMixerDevice."""
    def __init__(self, name="A"):
        self.name = name
        self.mute = False
        self.solo = False
        self.mixer_device = _ChainMixer()


class _FullDrumChain(_MixerChain):
    """A real DrumChain has BOTH per-drum props AND mixer state."""
    def __init__(self, name="Kick"):
        super().__init__(name)
        self.choke_group = 0
        self.out_note = 36
        self.in_note = 36


def test_set_mute_solo_on_a_chain():
    chain = _MixerChain()
    res = set_chain_property_handler(
        _ctx_for(chain), node=_CHAIN_NODE, mute=True, solo=True,
    )
    assert chain.mute is True and chain.solo is True
    assert res["set"] == {"mute": True, "solo": True}


def test_set_volume_pan_writes_mixer_device_params():
    chain = _MixerChain()
    set_chain_property_handler(
        _ctx_for(chain), node=_CHAIN_NODE, volume=0.5, pan=-0.3,
    )
    assert chain.mixer_device.volume.value == 0.5
    assert chain.mixer_device.panning.value == -0.3


def test_mixer_state_on_a_plain_chain_not_just_drum():
    """mixer state does NOT gate on chain class — a plain chain takes it."""
    chain = _MixerChain(name="808")
    set_chain_property_handler(_ctx_for(chain), node=_CHAIN_NODE, mute=True)
    assert chain.mute is True


def test_choke_and_mixer_together_on_a_drumchain():
    chain = _FullDrumChain()
    res = set_chain_property_handler(
        _ctx_for(chain), node=_CHAIN_NODE, choke_group=2, mute=True, volume=0.6,
    )
    assert chain.choke_group == 2 and chain.mute is True
    assert chain.mixer_device.volume.value == 0.6
    assert res["set"] == {"choke_group": 2, "mute": True, "volume": 0.6}


def test_mute_must_be_bool_on_the_wire():
    with pytest.raises(ValueError, match="mute"):
        set_chain_property_handler(
            _ctx_for(_MixerChain()), node=_CHAIN_NODE, mute=1,  # int, not bool
        )


@pytest.mark.parametrize("bad", [-0.1, 1.5])
def test_volume_range_validated(bad):
    with pytest.raises(ValueError, match="volume"):
        set_chain_property_handler(
            _ctx_for(_MixerChain()), node=_CHAIN_NODE, volume=bad,
        )


@pytest.mark.parametrize("bad", [-1.5, 2.0])
def test_pan_range_validated(bad):
    with pytest.raises(ValueError, match="pan"):
        set_chain_property_handler(
            _ctx_for(_MixerChain()), node=_CHAIN_NODE, pan=bad,
        )


def test_invalid_pan_does_not_write_volume():
    """All fields validate up front, so a bad pan refuses before any write."""
    chain = _MixerChain()
    with pytest.raises(ValueError, match="pan"):
        set_chain_property_handler(
            _ctx_for(chain), node=_CHAIN_NODE, volume=0.5, pan=2.0,
        )
    assert chain.mixer_device.volume.value == 0.85  # untouched


def test_chain_without_mixer_device_teaches_for_volume():
    chain = _PlainChain()  # no mixer_device
    with pytest.raises(NotImplementedError, match="mixer"):
        set_chain_property_handler(
            _ctx_for(chain), node=_CHAIN_NODE, volume=0.5,
        )
