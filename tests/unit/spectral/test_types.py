"""The spectral shapes: fields validate, schedules refuse overlap, masks stay bounded."""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.spectral.types import (
    MAX_DEPTH_DB,
    MaskParams,
    ReferenceSchedule,
    ReferenceSpan,
    ResolutionReport,
    SpectralField,
    validate_node_ref,
)


def test_resolution_reports_what_a_window_achieves_at_a_pitch():
    r = ResolutionReport(n_fft=2048, hop=512, sample_rate=44100)
    assert r.bin_hz == pytest.approx(21.53, abs=0.01)
    # A semitone is 100 cents; one bin at 55 Hz is far wider than that.
    assert r.achieved_cents_at_hz(55.0) > 500
    long = ResolutionReport(n_fft=2048, hop=512, sample_rate=44100, low_knee_hz=200.0, low_n_fft=16384)
    assert long.achieved_cents_at_hz(55.0) < r.achieved_cents_at_hz(55.0)
    assert long.achieved_cents_at_hz(1000.0) == r.achieved_cents_at_hz(1000.0)
    with pytest.raises(ValueError, match="together"):
        ResolutionReport(n_fft=2048, hop=512, sample_rate=44100, low_knee_hz=200.0)


def _field(**over):
    base = dict(freqs_hz=[100.0, 200.0, 300.0], times_s=[0.0, 0.1], magnitude=np.ones((3, 2)),
                origin="symbolic", resolution=ResolutionReport(2048, 512, 44100), fingerprint="fp")
    base.update(over)
    return SpectralField(**base)


def test_field_validates_axes_against_magnitude():
    f = _field()
    assert f.magnitude.shape == (3, 2)
    with pytest.raises(ValueError, match="n_freqs, n_times"):
        _field(magnitude=np.ones((2, 3)))
    with pytest.raises(ValueError, match="increasing"):
        _field(freqs_hz=[300.0, 200.0, 100.0])
    with pytest.raises(ValueError, match="non-negative"):
        _field(magnitude=-np.ones((3, 2)))
    with pytest.raises(ValueError, match="origin"):
        _field(origin="guessed")


def test_node_refs_take_exactly_four_shapes():
    assert validate_node_ref(("master",)) == ("master",)
    assert validate_node_ref(("minus", "t1")) == ("minus", "t1")
    for bad in [("master", "x"), ("track",), ("bus", "b1"), "track", ()]:
        with pytest.raises(ValueError):
            validate_node_ref(bad)


def test_schedule_orders_spans_and_refuses_overlap():
    s = ReferenceSchedule((
        ReferenceSpan(16.0, 32.0, (("track", "bass"),)),
        ReferenceSpan(0.0, 16.0, (("master",),)),
    ))
    assert s.start_beat == 0.0 and s.end_beat == 32.0
    assert s.nodes_at(20.0) == (("track", "bass"),)
    assert s.nodes_at(32.0) == ()
    with pytest.raises(ValueError, match="overlap"):
        ReferenceSchedule((
            ReferenceSpan(0.0, 16.0, (("master",),)),
            ReferenceSpan(8.0, 24.0, (("master",),)),
        ))
    with pytest.raises(ValueError, match="at least one node"):
        ReferenceSpan(0.0, 4.0, ())


def test_mask_params_are_bounded_and_may_vary_per_frame():
    p = MaskParams("carve", harmonic_depth=6, notch_width_cents=50.0, depth_db=18.0, smoothing_s=0.02)
    assert p.depth_db == 18.0
    per_frame = MaskParams("vocode", 4, notch_width_cents=np.array([30.0, 60.0]), depth_db=np.array([6.0, 12.0]))
    assert isinstance(per_frame.depth_db, np.ndarray)
    with pytest.raises(ValueError, match="depth_db"):
        MaskParams("carve", 4, 50.0, depth_db=MAX_DEPTH_DB + 1)
    with pytest.raises(ValueError, match="depth_db"):
        MaskParams("carve", 4, 50.0, depth_db=0.0)
    with pytest.raises(ValueError, match="polarity"):
        MaskParams("notch", 4, 50.0, 6.0)
    with pytest.raises(ValueError, match="harmonic_depth"):
        MaskParams("carve", 0, 50.0, 6.0)
