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
import pytest

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
    env = DeclaredEnvelope.from_pairs(
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
    env = DeclaredEnvelope.from_pairs(
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
    env = DeclaredEnvelope.from_pairs(
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
    env = DeclaredEnvelope.from_pairs(
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
    return DeclaredEnvelope.from_pairs(
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
    return DeclaredEnvelope.from_pairs(
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
    env = DeclaredEnvelope.from_pairs(
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
    env = DeclaredEnvelope.from_pairs(
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


# ---------------------------------------------------------------------------
# Dual-probe device-parameter verification (STR-4C8N A2).
#
# Spectral centroid alone is the wrong probe for an IMAGE effect. A flanger is a
# comb filter: it notches roughly symmetrically, so it barely moves the centroid
# however wet it gets. On `the-argument` that produced three `warning` findings
# ("no audible timbre shift ... 1% < 12%") against automation that provably DID
# land — the parameter read back its exact authored value mid-sweep, and the
# stereo appeared in the render. A device-parameter change is realized when it
# moves the timbre OR the image.
# ---------------------------------------------------------------------------


def _widened(mono_src: np.ndarray, *, shift_samples: int) -> np.ndarray:
    """Decorrelate a stereo pair by PHASE-shifting one channel.

    This is how a flanger with a non-zero Mod Phase actually creates width, and
    why it is invisible to a brightness probe: each channel keeps an identical
    magnitude spectrum, so no per-channel timbre changes at all — only the
    relationship between the channels does.

    (An earlier version of this fixture injected white noise as the side signal.
    That decorrelates too, but it genuinely brightens both channels, so it was
    modelling a change the centroid SHOULD see — it only looked right because a
    mono sum cancelled the noise away.)
    """
    out = mono_src.astype(np.float64).copy()
    out[:, 1] = np.roll(out[:, 1], shift_samples)
    return out


def test_device_parameter_image_shift_is_realized_without_a_timbre_shift():
    """The flanger case: the image opens, the centroid does not move."""
    half = 2.0
    tone = sine(440.0, half, amplitude=0.5)
    dry = tone                      # channels identical — bit-exact mono
    wet = _widened(sine(440.0, half, amplitude=0.5), shift_samples=27)
    audio = _two_half_audio(dry, wet)
    env = DeclaredEnvelope.from_pairs(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Dry/Wet",
        breakpoints=((0.0, 0.0), (8.0, 0.38)),
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(audio), master_audio=audio,
    )
    assert len(results) == 1
    v = results[0]
    assert v.measurable is True
    assert v.realized is True, (
        "an image change with no centroid change must count as realized — this "
        "is the false-positive class the dual probe exists to remove"
    )
    # The note must say WHICH probe fired, or a reader can't tell a timbre move
    # from an image move.
    assert "image" in v.note.lower()


def test_device_parameter_flat_image_and_flat_timbre_is_still_not_realized():
    """The regression that matters most: the dual probe must not become a
    rubber stamp. Nothing moved, so nothing is realized."""
    flat = sine(440.0, 4.0, amplitude=0.5)
    env = DeclaredEnvelope.from_pairs(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Dry/Wet",
        breakpoints=((0.0, 0.0), (8.0, 0.38)),
    )
    results = verify_envelope_realization(
        env, flat, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(flat), master_audio=flat,
    )
    assert len(results) == 1
    assert results[0].measurable is True
    assert results[0].realized is False


def test_wet_but_mono_flanger_is_still_not_realized():
    """The true positive the old code got right for the wrong reason.

    A flanger whose Mod Phase is 0° combs both channels identically: the stem
    stays bit-exact mono and the centroid barely shifts. Neither probe fires, so
    the reading stays 'not realized' — which is the correct diagnosis of a
    device that cannot do what was declared.
    """
    half = 2.0
    dry = sine(440.0, half, amplitude=0.5)
    # Same signal, marginally comb-filtered IN BOTH CHANNELS EQUALLY.
    combed = sine(440.0, half, amplitude=0.5) * 0.97
    audio = _two_half_audio(dry, combed)
    env = DeclaredEnvelope.from_pairs(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Dry/Wet",
        breakpoints=((0.0, 0.0), (8.0, 0.38)),
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(audio), master_audio=audio,
    )
    assert len(results) == 1
    assert results[0].realized is False


def test_timbre_shift_still_reported_as_timbre():
    """The existing centroid path keeps its own voice — a brightness flip must
    not start describing itself as an image move."""
    half = 2.0
    audio = _two_half_audio(
        sine(300.0, half, amplitude=0.5), sine(3500.0, half, amplitude=0.5)
    )
    env = DeclaredEnvelope.from_pairs(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Amp Type",
        breakpoints=((0.0, 0.0), (8.0, 1.0)),
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(audio), master_audio=audio,
    )
    v = results[0]
    assert v.realized is True
    assert "timbre" in v.note.lower()


def test_anti_phase_window_is_not_mistaken_for_silence():
    """The silence gate must read STEREO energy, not the mono sum.

    A near anti-phase window sums to almost nothing while the surface plays at
    full level. Gating on the mono sum called it "too quiet to characterise" and
    skipped the whole verification — including the image probe, for which
    anti-phase is the single most informative shape there is.
    """
    half = 2.0
    tone = sine(440.0, half, amplitude=0.5)
    mono_pair = tone                       # channels identical
    anti = tone.copy()
    anti[:, 1] = -anti[:, 1]               # sums to ~zero, still plainly audible
    audio = _two_half_audio(mono_pair, anti)
    env = DeclaredEnvelope.from_pairs(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Dry/Wet",
        breakpoints=((0.0, 0.0), (8.0, 1.0)),
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(audio), master_audio=audio,
    )
    assert len(results) == 1
    v = results[0]
    assert v.measurable is True, "an audible anti-phase window is not silence"
    assert v.realized is True
    assert "image" in v.note.lower()


def test_image_carried_verdict_names_its_probe():
    """`probe` makes the verdict's basis machine-readable.

    An image-carried verdict sits beside a near-unchanged centroid in
    `metric`/`before`/`after`, so a consumer that reads those as the evidence
    asserts a brightness change the audio does not support. `probe` says which
    probe fired without string-matching the note.
    """
    half = 2.0
    tone = sine(440.0, half, amplitude=0.5)
    anti = tone.copy()
    anti[:, 1] = -anti[:, 1]
    audio = _two_half_audio(tone, anti)
    env = DeclaredEnvelope.from_pairs(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Dry/Wet",
        breakpoints=((0.0, 0.0), (8.0, 1.0)),
    )
    v = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(audio), master_audio=audio,
    )[0]
    assert v.probe == "image"
    # The centroid pair is unchanged — which is exactly why it must not be read
    # as the evidence for this verdict.
    assert v.metric == "spectral_centroid_hz"
    assert abs(v.after - v.before) / v.before < 0.12

    # A genuine timbre move reports the other probe.
    bright = _two_half_audio(
        sine(300.0, half, amplitude=0.5), sine(3500.0, half, amplitude=0.5)
    )
    v2 = verify_envelope_realization(
        env, bright, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(bright), master_audio=bright,
    )[0]
    assert v2.probe == "timbre"


def test_send_level_is_graded_on_the_same_signal_the_gate_measures():
    """A decorrelated return must not be judged on two cancellation residues.

    The silence gate reads STEREO energy for every kind. If `_verify_level`
    graded the MONO SUM instead, a wide return — a ping-pong delay, a stereo
    reverb — would clear the gate at full level and then have its send step
    measured on near-silent residue, yielding a confident dB verdict from noise.
    Here the send is declared UP and the return genuinely gets louder while
    staying decorrelated throughout; the verdict must follow the audible level.
    """
    half = 2.0

    def _decorrelated(amplitude: float) -> np.ndarray:
        # L and R are different tones, so the mono sum is NOT a scaled copy of
        # the stereo signal — the two measurements genuinely disagree.
        left = sine(440.0, half, amplitude=amplitude)[:, 0]
        right = sine(441.7, half, amplitude=amplitude, phase=math.pi)[:, 0]
        return np.stack([left, right], axis=1).astype(np.float32)

    audio = _two_half_audio(_decorrelated(0.05), _decorrelated(0.5))
    env = DeclaredEnvelope.from_pairs(
        target_surface_id="return:1",
        target_kind="send_level",
        parameter_path=None,
        breakpoints=((0.0, 0.2), (8.0, 0.8)),  # declared UP at beat 8
    )
    v = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=_beat_map(audio), master_audio=audio,
    )[0]
    assert v.measurable is True
    assert v.realized is True, "a 20 dB rise on a wide return is a realized send step"
    # ~20 dB (0.05 → 0.5), which is the STEREO level move. Grading the mono sum
    # would read some unrelated residue delta here.
    assert 18.0 < (v.after - v.before) < 22.0


# ---------------------------------------------------------------------------
# Envelope-aware windowing: a RAMP is not a step (AUD-5K7T), and a staircase
# is one gesture, not N (the alien fixture).
#
# Both defects are the same mistake seen from two sides: the verifier assumed
# every change was instantaneous at its breakpoint, so a window clamped to the
# neighbouring breakpoint could land ON the move it was measuring. Where the
# preceding segment ramped, both windows sat on the ramp and a realized
# gesture read as unrealized; where the move was authored as 64 small steps,
# both windows collapsed to one step of the ramp and every step failed.
# ---------------------------------------------------------------------------


def _paint(audio: np.ndarray, span: tuple[float, float],
           from_beat: float, to_beat: float, fn) -> None:
    """Replace the sample span covering ``[from_beat, to_beat)`` in place."""
    start, stop = span
    n = audio.shape[0]
    a = int(round((from_beat - start) / (stop - start) * n))
    b = int(round((to_beat - start) / (stop - start) * n))
    audio[a:b] = fn(b - a)


def _tone_block(freq: float, amplitude: float):
    def build(n: int) -> np.ndarray:
        return sine(freq, n / SAMPLE_RATE, amplitude=amplitude)[:n]
    return build


def _wide_block(freq: float, amplitude: float, shift: int = 27):
    def build(n: int) -> np.ndarray:
        return _widened(sine(freq, n / SAMPLE_RATE, amplitude=amplitude)[:n],
                        shift_samples=shift)
    return build


# The chorus flanger arc from `the-argument` that filed AUD-5K7T: a 4-beat
# ramp OPEN, a 23-beat drift, then a 2-beat ramp back to dry. Every segment is
# `linear` — the DB default, and what the envelope generators emit.
_ARC = (
    (261.0, 0.0, "linear"),
    (265.0, 0.38, "linear"),
    (288.0, 0.42, "linear"),
    (290.0, 0.0, "linear"),
)
_ARC_SPAN = (255.0, 295.0)


def _arc_audio() -> np.ndarray:
    """Dry (bit-exact mono) until the ramp opens at 265, wide after it."""
    audio = sine(440.0, 8.0, amplitude=0.5).astype(np.float32)
    _paint(audio, _ARC_SPAN, 265.0, 295.0, _wide_block(440.0, 0.5))
    return audio


def _arc_results() -> list:
    audio = _arc_audio()
    env = DeclaredEnvelope(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Dry/Wet",
        breakpoints=_ARC,
    )
    return verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=BeatSampleMap(*_ARC_SPAN, audio.shape[0]),
        master_audio=audio,
    )


def test_ramped_gesture_reads_the_plateau_before_the_ramp():
    """The flanger opens over 4 beats and the verdict must be `realized`.

    Assuming a step at beat 265 clamps the before-window to 263 — halfway UP
    the ramp — so both windows contain the change, the measured delta collapses
    and a gesture that demonstrably happened reads as not realized. The
    before-window belongs on the dry plateau BEFORE the ramp starts.
    """
    v = _arc_results()[0]
    assert v.at_beat == 265.0
    assert v.through_beat == 265.0
    assert v.measurable is True
    assert v.realized is True, (
        "the ramp is fully realized in the audio — reading it as unrealized is "
        "the defect, and it comes from windowing a ramp as if it were a step"
    )


def test_far_side_ramp_is_unmeasurable_not_rubber_stamped():
    """The fix must not become a rubber stamp.

    The 0.38→0.42 drift at beat 288 is inaudible, and it is bracketed by ramps
    on both sides — the value never settles anywhere near it. A naive "anchor
    both windows on the transition" fix reports it realized off the ramp down
    to dry. The honest answer is that there is no window to judge it in.
    """
    v = _arc_results()[1]
    assert v.at_beat == 288.0
    assert v.measurable is False
    assert v.realized is False
    assert "ramp" in v.note, (
        "the note must name the ramping neighbour, or the reader can't tell "
        "'no settled window' from 'too quiet'"
    )
    assert math.isnan(v.before)


def test_hold_curve_windows_are_unchanged():
    """R5: a `hold` segment keeps the exact windows — and so the exact verdict.

    The audio steps twice on each side of the declared change, so the measured
    dB pair pins WHERE the windows sat, not merely that a verdict came out:
    only `[6, 8)` reads -29.0 dBFS and only `[8, 10)` reads -9.0.
    """
    audio = sine(220.0, 4.0, amplitude=0.02).astype(np.float32)
    span = (0.0, 16.0)
    _paint(audio, span, 5.5, 8.0, _tone_block(220.0, 0.05))
    _paint(audio, span, 8.0, 10.0, _tone_block(220.0, 0.5))
    _paint(audio, span, 10.0, 16.0, _tone_block(220.0, 0.1))
    env = DeclaredEnvelope(
        target_surface_id="return:1",
        target_kind="send_level",
        parameter_path=None,
        # A 8-beat HOLD segment — four times the window, the shape AUD-5K7T
        # would mis-window if it treated every long segment as a ramp.
        breakpoints=((0.0, 0.2, "hold"), (8.0, 0.8, "hold")),
    )
    v = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=BeatSampleMap(*span, audio.shape[0]), master_audio=audio,
    )[0]
    assert v.at_beat == 8.0
    assert v.steps == 1
    assert v.before == pytest.approx(20.0 * math.log10(0.05 / math.sqrt(2)), abs=0.05)
    assert v.after == pytest.approx(20.0 * math.log10(0.5 / math.sqrt(2)), abs=0.05)


def test_changes_closer_than_the_window_do_not_bleed():
    """Two opposite steps 0.3 beats apart have no room for a verdict.

    They must NOT join (opposite directions), and neither window may span the
    neighbouring change to find room — the honest answer is unmeasurable.
    """
    audio = sine(440.0, 4.0, amplitude=0.5).astype(np.float32)
    env = DeclaredEnvelope(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Dry/Wet",
        breakpoints=((4.0, 0.0, "hold"), (8.0, 0.5, "hold"), (8.3, 0.0, "hold")),
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=BeatSampleMap(0.0, 16.0, audio.shape[0]), master_audio=audio,
    )
    assert [v.at_beat for v in results] == [8.0, 8.3]
    assert [v.measurable for v in results] == [False, False]
    assert all("no settled window" in v.note for v in results)


def test_all_target_kinds_share_the_ramp_aware_window():
    """R7: one windowing, inherited by every kind — not four that can drift.

    Recording the spans each kind asks the surface for is the direct assertion:
    if any kind carried its own windowing, its bounds would differ here.
    """
    import hallucinote.audio.automation as automation_module

    seen: dict[str, list[tuple[float, float]]] = {}
    audio = _arc_audio()
    beat_map = BeatSampleMap(*_ARC_SPAN, audio.shape[0])
    real_mono = automation_module._mono_window

    for kind in ("device_parameter", "send_level", "mixer_volume", "mixer_pan"):
        calls: list[tuple[float, float]] = []

        def _recording(a, bm, lo, hi, _calls=calls):
            _calls.append((lo, hi))
            return real_mono(a, bm, lo, hi)

        automation_module._mono_window = _recording
        try:
            verify_envelope_realization(
                DeclaredEnvelope(
                    target_surface_id="track:3",
                    target_kind=kind,
                    parameter_path="Dry/Wet",
                    breakpoints=_ARC,
                ),
                audio, sample_rate=SAMPLE_RATE,
                beat_map=beat_map, master_audio=audio,
            )
        finally:
            automation_module._mono_window = real_mono
        # Keep only the SURFACE windows: the mixer kinds also window the
        # master with the same bounds, which would double every entry.
        seen[kind] = sorted(set(calls))

    bounds = list(seen.values())
    assert all(b == bounds[0] for b in bounds), seen
    # And they are the ramp-aware ones: the plateau BEFORE the 261→265 ramp,
    # and the settled span after it.
    assert (259.0, 261.0) in bounds[0]
    assert (265.0, 267.0) in bounds[0]


def _staircase(
    start_beat: float, end_beat: float, v_from: float, v_to: float, steps: int,
) -> tuple[tuple[float, float, str], ...]:
    """A ramp authored as `steps` equal small steps — the alien fixture shape."""
    dt = (end_beat - start_beat) / steps
    dv = (v_to - v_from) / steps
    return tuple(
        (start_beat + i * dt, v_from + i * dv, "linear")
        for i in range(steps + 1)
    )


def test_sixty_four_step_staircase_is_one_gesture():
    """A ramp authored as 64 small steps is ONE authored move.

    Graded per step, both windows collapse to ~1/16 beat OF THE RAMP and every
    step fails against a threshold sized for a whole move — so the finer,
    better-authored ramp produced 64 findings where a coarse one produced 1.
    """
    audio = sine(300.0, 4.0, amplitude=0.5).astype(np.float32)
    span = (0.0, 16.0)
    _paint(audio, span, 8.0, 16.0, _tone_block(3500.0, 0.5))
    env = DeclaredEnvelope(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Tone",
        breakpoints=_staircase(4.0, 8.0, 0.0, 1.0, 64),
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=BeatSampleMap(*span, audio.shape[0]), master_audio=audio,
    )
    assert len(results) == 1, "64 verdicts on one gesture is the defect"
    v = results[0]
    assert v.steps == 64
    assert v.at_beat == pytest.approx(4.0625)
    assert v.through_beat == pytest.approx(8.0)
    assert v.measurable is True
    assert v.realized is True
    assert "over 64 steps" in v.note


def test_independent_breakpoints_keep_per_step_verdicts():
    """R5 regression guard: the join must never eat separable moves.

    Three changes a full window apart are three authored moves, and they stay
    three verifications with one step each — the per-step path is the
    `steps == 1` case of the general one, not an approximation of it.
    """
    audio = sine(440.0, 4.0, amplitude=0.5).astype(np.float32)
    env = DeclaredEnvelope.from_pairs(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Tone",
        breakpoints=((0.0, 0.0), (8.0, 0.3), (16.0, 0.6), (24.0, 0.9)),
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=BeatSampleMap(0.0, 32.0, audio.shape[0]), master_audio=audio,
    )
    assert [v.at_beat for v in results] == [8.0, 16.0, 24.0]
    assert [v.through_beat for v in results] == [8.0, 16.0, 24.0]
    assert [v.steps for v in results] == [1, 1, 1]
    assert all("over" not in v.note for v in results)


def test_up_down_staircase_is_two_gestures_not_sixty_four():
    """A direction reversal splits the run — a rise and the fall after it are
    two moves, never one net no-op.

    With no plateau at the apex neither gesture has a settled window on the
    apex side, and saying so is the honest reading: the value is in motion
    right through the turn.
    """
    audio = sine(440.0, 4.0, amplitude=0.5).astype(np.float32)
    up = _staircase(4.0, 6.0, 0.0, 1.0, 32)
    down = _staircase(6.0, 8.0, 1.0, 0.0, 32)[1:]
    env = DeclaredEnvelope(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Tone",
        breakpoints=up + down,
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=BeatSampleMap(0.0, 16.0, audio.shape[0]), master_audio=audio,
    )
    assert len(results) == 2
    assert [v.steps for v in results] == [32, 32]
    assert results[0].through_beat == pytest.approx(6.0)
    assert results[1].at_beat == pytest.approx(6.0625)
    assert results[1].through_beat == pytest.approx(8.0)


def test_up_and_down_runs_are_graded_in_opposite_directions():
    """Given a plateau to settle on, the two runs read as opposite moves.

    The same 32-up/32-down shape with 4 beats held at the apex: two gestures,
    one declared UP and one declared DOWN, each graded end-to-end.
    """
    audio = sine(220.0, 6.0, amplitude=0.05).astype(np.float32)
    span = (0.0, 24.0)
    _paint(audio, span, 8.0, 14.0, _tone_block(220.0, 0.5))
    # HOLD the apex for four beats — the plateau both runs are read against.
    up = _staircase(4.0, 8.0, 0.0, 0.8, 32)[:-1] + ((8.0, 0.8, "hold"),)
    down = _staircase(12.0, 16.0, 0.8, 0.0, 32)
    env = DeclaredEnvelope(
        target_surface_id="return:1",
        target_kind="send_level",
        parameter_path=None,
        breakpoints=up + down,
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=BeatSampleMap(*span, audio.shape[0]), master_audio=audio,
    )
    assert len(results) == 2
    assert "declared up over 32 steps" in results[0].note
    assert "declared down over 32 steps" in results[1].note
    assert results[0].realized is True
    assert results[1].realized is True


def test_alternating_duck_envelope_is_one_verification_per_direction_change():
    """A sidechain duck (rest → duck → rest) is unchanged by the join.

    Every adjacent pair reverses direction, so nothing joins and the ledger of
    verdicts reads exactly as it did before gestures existed.
    """
    audio = sine(440.0, 4.0, amplitude=0.5).astype(np.float32)
    env = DeclaredEnvelope(
        target_surface_id="track:1",
        target_kind="mixer_volume",
        parameter_path=None,
        breakpoints=(
            (0.0, 1.0, "linear"), (4.0, 0.3, "linear"), (4.5, 1.0, "linear"),
            (8.0, 0.3, "linear"), (8.5, 1.0, "linear"),
        ),
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=BeatSampleMap(0.0, 16.0, audio.shape[0]), master_audio=audio,
    )
    assert len(results) == 4
    assert [v.steps for v in results] == [1, 1, 1, 1]


def test_a_plateau_longer_than_the_window_splits_a_monotonic_run():
    """Rise, hold four beats, rise = two moves.

    Same direction throughout, so only the gap says these are separable — and
    a gap that could hold a full analysis window is exactly what makes two
    per-move verdicts valid.
    """
    audio = sine(440.0, 4.0, amplitude=0.5).astype(np.float32)
    env = DeclaredEnvelope(
        target_surface_id="track:3",
        target_kind="device_parameter",
        parameter_path="Tone",
        breakpoints=(
            (0.0, 0.0, "linear"), (2.0, 0.5, "hold"),
            (6.0, 0.5, "linear"), (8.0, 1.0, "hold"),
        ),
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=BeatSampleMap(0.0, 16.0, audio.shape[0]), master_audio=audio,
    )
    assert [v.at_beat for v in results] == [2.0, 8.0]
    assert [v.steps for v in results] == [1, 1]


def test_staircase_send_ramp_is_realized_end_to_end():
    """The alien case: a send authored as 64 steps whose return really rises.

    Today that reported 64 × NOT realized; the whole traversal moves the
    return by well over the send threshold, which is one realized move.
    """
    audio = sine(220.0, 4.0, amplitude=0.25).astype(np.float32)
    span = (0.0, 16.0)
    _paint(audio, span, 8.0, 16.0, _tone_block(220.0, 0.5))  # +6.0 dB
    env = DeclaredEnvelope(
        target_surface_id="return:1",
        target_kind="send_level",
        parameter_path=None,
        breakpoints=_staircase(4.0, 8.0, 0.0, 0.8, 64),
    )
    results = verify_envelope_realization(
        env, audio, sample_rate=SAMPLE_RATE,
        beat_map=BeatSampleMap(*span, audio.shape[0]), master_audio=audio,
    )
    assert len(results) == 1
    v = results[0]
    assert v.steps == 64
    assert v.realized is True
    assert v.after - v.before == pytest.approx(6.02, abs=0.2)
