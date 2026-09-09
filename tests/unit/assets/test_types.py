"""The asset value objects refuse malformed values the same way for every producer."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hallucinote.assets.types import Derived, Source, Transform, validate_audio_array

_SHA = "a" * 64


def _source(**over):
    base = dict(name="line", path=Path("assets/sources/line.wav"), checksum=_SHA,
                sample_rate=44100, channels=1, duration_s=2.5)
    base.update(over)
    return Source(**base)


def test_source_accepts_a_well_formed_entry():
    s = _source()
    assert s.name == "line" and s.channels == 1


@pytest.mark.parametrize("field,value", [
    ("name", ""), ("checksum", "abc"), ("checksum", "A" * 64),
    ("sample_rate", 0), ("channels", 0), ("duration_s", -1.0),
])
def test_source_refuses_malformed_fields(field, value):
    with pytest.raises(ValueError, match=field):
        _source(**{field: value})


class _Reverse:
    kind = "reverse"

    def params(self):
        return {}

    def apply(self, audio, sample_rate, ctx):
        return audio[::-1]


def test_transform_protocol_is_structural():
    assert isinstance(_Reverse(), Transform)


def test_derived_requires_a_chain_and_hex_addresses():
    d = Derived(path=Path("d.wav"), address=_SHA, record_path=Path("d.json"),
                source_checksum=_SHA, chain=(_Reverse(),))
    assert d.reference_fingerprint is None
    with pytest.raises(ValueError, match="chain"):
        Derived(path=Path("d.wav"), address=_SHA, record_path=Path("d.json"),
                source_checksum=_SHA, chain=())
    with pytest.raises(ValueError, match="address"):
        Derived(path=Path("d.wav"), address="nope", record_path=Path("d.json"),
                source_checksum=_SHA, chain=(_Reverse(),))


def test_validate_audio_array_refuses_ambiguous_shapes():
    ok = validate_audio_array(np.zeros((100, 2)))
    assert ok.dtype == np.float32 and ok.shape == (100, 2)
    with pytest.raises(ValueError, match="2-D"):
        validate_audio_array(np.zeros(100))
    with pytest.raises(ValueError, match="axis 0"):
        validate_audio_array(np.zeros((2, 100)))
