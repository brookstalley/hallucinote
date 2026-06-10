"""Envelope-aware automation verification tests (AUD-8H2M).

Pins that the analyzer confirms authored time-varying automation was REALIZED
in the audio:
  - a device-parameter flip with a real timbre step is detected (directional);
  - a flat stem at a declared flip → honest "not realized";
  - a send-level step on the return is verified in the declared direction;
  - mixer_volume is verified on the MASTER via the fader-calibrated
    prediction model (AUD-3F8M); diluted/quiet cases honestly unmeasurable;
  - mixer_pan is verified on the master's L-R balance (constant-power
    prediction scaled by the stem's static fader gain);
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
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(audio), master_audio=audio,
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
        env, flat, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(flat), master_audio=flat,
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
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(audio), master_audio=audio,
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
        env, flat, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(flat), master_audio=flat,
    )
    assert results[0].measurable is True
    assert results[0].realized is False


def _mixer_volume_env(v_before: float, v_after: float) -> DeclaredEnvelope:
    return DeclaredEnvelope(
        target_surface_id="track:1",
        target_kind="mixer_volume",
        parameter_path=None,
        breakpoints=((0.0, v_before), (8.0, v_after)),
    )


def _master_from(stem_half: np.ndarray, rest_half: np.ndarray,
                 g_before: float, g_after: float) -> np.ndarray:
    """Synthesize a master: rest-of-mix + the stem at its post-fader gain,
    per half (the fader move lands at the half boundary, beat 8)."""
    return concat(rest_half + stem_half * g_before,
                  rest_half + stem_half * g_after)


def test_mixer_volume_swell_realized_on_master():
    """AUD-3F8M verifiable signal: a declared mixer_volume swell whose level
    step IS in the master reports measurable=True + realized=True from
    master-bus windowing — not the old post-fader skip."""
    from hallucinote.audio.levels import live_fader_gain

    stem_half = sine(220.0, 2.0, amplitude=0.4)   # pre-fader stem, constant
    rest_half = sine(660.0, 2.0, amplitude=0.3)   # the rest of the mix
    stem = concat(stem_half, stem_half)
    v1, v2 = 0.5, 0.85  # fader swell: ~-14 dB -> unity
    master = _master_from(
        stem_half, rest_half, live_fader_gain(v1), live_fader_gain(v2),
    )
    env = _mixer_volume_env(v1, v2)
    results = verify_envelope_realization(
        env, stem, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(stem), master_audio=master,
    )
    assert len(results) == 1
    v = results[0]
    assert v.measurable is True
    assert v.realized is True
    assert v.metric == "master_rms_db"
    assert v.after > v.before  # master got louder where the fader rose
    assert "realized" in v.note
    assert "post-fader" not in v.note  # the old teaching note is gone


def test_mixer_volume_declared_but_master_flat_is_not_realized():
    """The fader move is declared and predictable, but the master never
    moves -> measurable=True, realized=False (finding-worthy)."""
    stem_half = sine(220.0, 2.0, amplitude=0.4)
    rest_half = sine(660.0, 2.0, amplitude=0.3)
    stem = concat(stem_half, stem_half)
    # Master stays at the BEFORE gain on both halves — move never happened.
    flat_master = _master_from(stem_half, rest_half, 0.2, 0.2)
    env = _mixer_volume_env(0.5, 0.85)
    results = verify_envelope_realization(
        env, stem, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(stem), master_audio=flat_master,
    )
    assert len(results) == 1
    assert results[0].measurable is True
    assert results[0].realized is False
    assert "NOT realized" in results[0].note


def test_mixer_volume_diluted_stem_is_unmeasurable_not_guessed():
    """A stem far below the mix can't move the master detectably — the
    prediction gate reports measurable=False with the dilution note, never
    a false verdict."""
    stem_half = sine(220.0, 2.0, amplitude=0.005)  # tiny in the mix
    rest_half = sine(660.0, 2.0, amplitude=0.5)
    stem = concat(stem_half, stem_half)
    master = _master_from(stem_half, rest_half, 0.2, 1.0)
    env = _mixer_volume_env(0.5, 0.85)
    results = verify_envelope_realization(
        env, stem, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(stem), master_audio=master,
    )
    assert len(results) == 1
    assert results[0].measurable is False
    assert "too diluted" in results[0].note


def test_mixer_volume_quiet_master_is_unmeasurable():
    """A near-silent master window can't be characterised — honest skip."""
    stem = concat(sine(220.0, 2.0, amplitude=0.4),
                  sine(220.0, 2.0, amplitude=0.4))
    master = silence(4.0)
    env = _mixer_volume_env(0.5, 0.85)
    results = verify_envelope_realization(
        env, stem, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(stem), master_audio=master,
    )
    assert len(results) == 1
    assert results[0].measurable is False
    assert "too quiet" in results[0].note


def _mixer_pan_env(p_before: float, p_after: float) -> DeclaredEnvelope:
    return DeclaredEnvelope(
        target_surface_id="track:1",
        target_kind="mixer_pan",
        parameter_path=None,
        breakpoints=((0.0, p_before), (8.0, p_after)),
    )


def _panned_master(stem_half: np.ndarray, rest_half: np.ndarray,
                   pan_before: float, pan_after: float,
                   gain: float = 1.0) -> np.ndarray:
    """Synthesize a master with the stem constant-power panned per half."""
    from hallucinote.audio.automation import _pan_gains

    def half(pan):
        gl, gr = _pan_gains(pan)
        out = rest_half.copy().astype(np.float64)
        out[:, 0] += stem_half[:, 0] * gain * gl
        out[:, 1] += stem_half[:, 1] * gain * gr
        return out.astype(np.float32)

    return concat(half(pan_before), half(pan_after))


def test_mixer_pan_move_realized_on_master_balance():
    """AUD-3F8M: a declared left->right pan move whose balance shift IS in
    the master reports measurable=True + realized=True."""
    stem_half = sine(220.0, 2.0, amplitude=0.4)
    rest_half = sine(660.0, 2.0, amplitude=0.3)
    stem = concat(stem_half, stem_half)
    master = _panned_master(stem_half, rest_half, -0.5, 0.5)
    env = _mixer_pan_env(-0.5, 0.5)
    results = verify_envelope_realization(
        env, stem, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(stem), master_audio=master,
    )
    assert len(results) == 1
    v = results[0]
    assert v.measurable is True
    assert v.realized is True
    assert v.metric == "master_balance_db"
    assert v.after < v.before  # balance tilted right (L-R fell)
    assert "post-fader" not in v.note


def test_mixer_pan_declared_but_master_balance_flat_is_not_realized():
    """Pan declared, prediction detectable, but the master image never moved
    -> measurable=True, realized=False (finding-worthy)."""
    stem_half = sine(220.0, 2.0, amplitude=0.4)
    rest_half = sine(660.0, 2.0, amplitude=0.3)
    stem = concat(stem_half, stem_half)
    flat_master = _panned_master(stem_half, rest_half, -0.5, -0.5)
    env = _mixer_pan_env(-0.5, 0.5)
    results = verify_envelope_realization(
        env, stem, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(stem), master_audio=flat_master,
    )
    assert len(results) == 1
    assert results[0].measurable is True
    assert results[0].realized is False
    assert "NOT realized" in results[0].note


def test_mixer_pan_diluted_stem_is_unmeasurable():
    """A stem far below the mix can't move the master image detectably."""
    stem_half = sine(220.0, 2.0, amplitude=0.005)
    rest_half = sine(660.0, 2.0, amplitude=0.5)
    stem = concat(stem_half, stem_half)
    master = _panned_master(stem_half, rest_half, -0.5, 0.5)
    env = _mixer_pan_env(-0.5, 0.5)
    results = verify_envelope_realization(
        env, stem, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(stem), master_audio=master,
    )
    assert len(results) == 1
    assert results[0].measurable is False
    assert "too diluted" in results[0].note


def test_mixer_pan_respects_stem_gain_in_prediction():
    """A hot pre-fader stem pulled way down by its fader can't move the
    master image — stem_gain scales the prediction, gating honestly."""
    stem_half = sine(220.0, 2.0, amplitude=0.6)   # hot pre-fader
    rest_half = sine(660.0, 2.0, amplitude=0.5)
    stem = concat(stem_half, stem_half)
    tiny_gain = 0.01  # fader nearly silent
    master = _panned_master(stem_half, rest_half, -0.5, 0.5, gain=tiny_gain)
    env = _mixer_pan_env(-0.5, 0.5)
    results = verify_envelope_realization(
        env, stem, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(stem), master_audio=master,
        stem_gain=tiny_gain,
    )
    assert len(results) == 1
    assert results[0].measurable is False
    assert "too diluted" in results[0].note


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
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(audio), master_audio=audio,
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
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(audio), master_audio=audio,
    )
    assert results == []


def test_mixer_volume_model_breakdown_is_unmeasurable_not_false_verdict():
    """Hot stem + heavily limited master + fader-down: the uncorrelated model
    predicts non-positive after-power. That is model breakdown — honest
    measurable=False, never a manufactured 'NOT realized'."""
    # Pre-fader stem far hotter than the (limited) master it feeds.
    stem_half = sine(220.0, 2.0, amplitude=0.8)
    stem = concat(stem_half, stem_half)
    master = concat(sine(220.0, 2.0, amplitude=0.2),
                    sine(220.0, 2.0, amplitude=0.2))
    # Fader down from unity (0.85 -> 0.5): p_stem*g1^2 exceeds master power.
    env = _mixer_volume_env(0.85, 0.5)
    results = verify_envelope_realization(
        env, stem, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(stem), master_audio=master,
    )
    assert len(results) == 1
    assert results[0].measurable is False
    assert "breaks down" in results[0].note


def test_mixer_pan_quiet_master_is_unmeasurable():
    """A near-silent master window can't be characterised for balance —
    honest skip, mirroring the volume guard."""
    stem = concat(sine(220.0, 2.0, amplitude=0.4),
                  sine(220.0, 2.0, amplitude=0.4))
    master = silence(4.0)
    env = _mixer_pan_env(-0.5, 0.5)
    results = verify_envelope_realization(
        env, stem, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(stem), master_audio=master,
    )
    assert len(results) == 1
    assert results[0].measurable is False
    assert "too quiet" in results[0].note


def test_mixer_pan_model_breakdown_is_unmeasurable_not_false_verdict():
    """Hot stem at unity gain + heavily limited master: the per-channel
    prediction goes non-positive — model breakdown is an honest skip,
    never a manufactured 'NOT realized' (mirrors the volume guard)."""
    stem_half = sine(220.0, 2.0, amplitude=0.8)
    stem = concat(stem_half, stem_half)
    master = concat(sine(220.0, 2.0, amplitude=0.1),
                    sine(220.0, 2.0, amplitude=0.1))
    # Move away from where the stem currently sits: at gL(-0.9)≈hard left,
    # the stem-at-gain accounts for far more left-channel power than the
    # limited master shows.
    env = _mixer_pan_env(-0.9, 0.9)
    results = verify_envelope_realization(
        env, stem, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(stem), master_audio=master,
    )
    assert len(results) == 1
    assert results[0].measurable is False
    assert "breaks down" in results[0].note
