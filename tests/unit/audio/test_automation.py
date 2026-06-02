"""Envelope-aware automation verification tests (AUD-8H2M).

Pins that the analyzer confirms authored time-varying automation was REALIZED
in the audio:
  - a device-parameter flip with a real timbre step is detected (directional);
  - a flat stem at a declared flip → honest "not realized";
  - a send-level step on the return is verified in the declared direction;
  - post-fader (mixer_volume/pan) is reported unverifiable, not falsely failed;
  - a near-silent window is reported unmeasurable, not misread.
"""
from __future__ import annotations

import math

import numpy as np

from hallucinote.audio.automation import (
    DeclaredEnvelope,
    verify_envelope_realization,
)
from hallucinote.audio.section import BeatSampleMap

from .fixtures import SAMPLE_RATE, concat, silence, sine

_TOTAL_BEATS = 16.0


def _beat_map(audio: np.ndarray) -> BeatSampleMap:
    # Constant-tempo: the 16-beat span maps linearly onto the audio.
    return BeatSampleMap(0.0, _TOTAL_BEATS, audio.shape[0])


def _two_half_audio(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Concatenate two equal-length halves; the boundary lands at beat 8."""
    return concat(first, second)


def test_device_parameter_timbre_shift_is_detected():
    """A dark→bright step at the declared breakpoint reads as a realized timbre
    shift (centroid rises)."""
    half = 2.0  # seconds per half
    dark = sine(300.0, half, amplitude=0.5)
    bright = sine(3500.0, half, amplitude=0.5)
    audio = _two_half_audio(dark, bright)
    env = DeclaredEnvelope(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Amp Type",
        breakpoints=((0.0, 0.0), (8.0, 1.0)),  # Clean→Heavy at beat 8
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE, beat_map=_beat_map(audio),
    )
    assert len(results) == 1
    v = results[0]
    assert v.measurable is True
    assert v.realized is True
    assert v.metric == "spectral_centroid_hz"
    assert v.after > v.before  # brighter after the flip
    assert v.at_beat == 8.0


def test_device_parameter_no_change_is_not_realized():
    """A flat stem at a declared flip → measurable but NOT realized (the
    authored change didn't happen in audio)."""
    flat = sine(440.0, 4.0, amplitude=0.5)  # same timbre throughout
    env = DeclaredEnvelope(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Amp Type",
        breakpoints=((0.0, 0.0), (8.0, 1.0)),
    )
    results = verify_envelope_realization(
        env, flat, sample_rate=SAMPLE_RATE, beat_map=_beat_map(flat),
    )
    assert len(results) == 1
    assert results[0].measurable is True
    assert results[0].realized is False


def test_send_level_step_realized_in_declared_direction():
    """A return that gets louder where the send is declared to rise → realized."""
    quiet = sine(220.0, 2.0, amplitude=0.05)
    loud = sine(220.0, 2.0, amplitude=0.5)
    audio = _two_half_audio(quiet, loud)
    env = DeclaredEnvelope(
        target_surface_id="return:1",
        target_kind="send_level",
        parameter_path=None,
        breakpoints=((0.0, 0.2), (8.0, 0.8)),  # send declared UP at beat 8
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE, beat_map=_beat_map(audio),
    )
    assert len(results) == 1
    v = results[0]
    assert v.measurable is True
    assert v.realized is True
    assert v.metric == "rms_db"
    assert v.after > v.before


def test_send_level_not_realized_when_level_flat():
    """Declared send rise but the return level didn't move → not realized."""
    flat = sine(220.0, 4.0, amplitude=0.3)
    env = DeclaredEnvelope(
        target_surface_id="return:1",
        target_kind="send_level",
        parameter_path=None,
        breakpoints=((0.0, 0.2), (8.0, 0.8)),
    )
    results = verify_envelope_realization(
        env, flat, sample_rate=SAMPLE_RATE, beat_map=_beat_map(flat),
    )
    assert results[0].measurable is True
    assert results[0].realized is False


def test_mixer_volume_is_reported_unverifiable():
    """Post-fader automation is invisible to the pre-fader stem — reported
    measurable=False, not falsely failed."""
    audio = _two_half_audio(sine(220.0, 2.0, amplitude=0.1),
                            sine(220.0, 2.0, amplitude=0.6))
    env = DeclaredEnvelope(
        target_surface_id="track:1",
        target_kind="mixer_volume",
        parameter_path=None,
        breakpoints=((0.0, 0.5), (8.0, 0.9)),
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE, beat_map=_beat_map(audio),
    )
    assert len(results) == 1
    assert results[0].measurable is False
    assert "post-fader" in results[0].note


def test_silent_window_is_unmeasurable_not_failed():
    """A near-silent surface around the breakpoint → measurable=False (can't
    confirm or refute), not a false 'not realized'."""
    audio = silence(4.0)
    env = DeclaredEnvelope(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Amp Type",
        breakpoints=((0.0, 0.0), (8.0, 1.0)),
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE, beat_map=_beat_map(audio),
    )
    assert len(results) == 1
    assert results[0].measurable is False
    assert math.isnan(results[0].before)


def test_no_value_change_yields_no_verification():
    """Breakpoints that never change value carry no gesture to verify."""
    audio = sine(440.0, 4.0, amplitude=0.5)
    env = DeclaredEnvelope(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Amp Type",
        breakpoints=((0.0, 1.0), (8.0, 1.0)),  # constant
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE, beat_map=_beat_map(audio),
    )
    assert results == []
