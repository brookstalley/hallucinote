"""Each transform records its parameters exactly and does to audio what its name says."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hallucinote.assets.transforms import (
    STRETCH_AB_COMMAND,
    chop_at_onsets,
    fade,
    normalize,
    pitch_shift,
    reverse,
    stretch_to_bars,
    trim,
)
from hallucinote.assets.types import Source, Transform, TransformContext
from tests.unit.audio.fixtures import SAMPLE_RATE, sine

_SHA = "b" * 64
SR = SAMPLE_RATE


def _ctx(tmp_path: Path, name: str = "line") -> TransformContext:
    source = Source(
        name=name, path=Path("assets/sources") / f"{name}.wav", checksum=_SHA,
        sample_rate=SR, channels=2, duration_s=2.0,
    )
    return TransformContext(song_dir=tmp_path, source=source)


def _pulsed_tone(n_pulses: int, *, lead_s: float = 0.3, period_s: float = 0.5,
                 burst_s: float = 0.1, sr: int = SR) -> np.ndarray:
    """Tone bursts with a decaying tail, stereo (n, 2) — one clear attack per pulse."""
    total = int(sr * (lead_s + period_s * n_pulses))
    buf = np.zeros((total, 2), dtype=np.float32)
    for k in range(n_pulses):
        start = int(sr * (lead_s + period_s * k))
        n = int(sr * burst_s)
        t = np.arange(n) / sr
        burst = (0.6 * np.sin(2 * np.pi * 440 * t) * np.exp(-t / (burst_s / 4))).astype(np.float32)
        buf[start:start + n, 0] = burst
        buf[start:start + n, 1] = burst
    return buf


def _dominant_hz(mono: np.ndarray, sr: int) -> float:
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(mono.shape[0])))
    return float(np.fft.rfftfreq(mono.shape[0], 1.0 / sr)[int(np.argmax(spectrum))])


ALL_TRANSFORMS = [
    trim(0.1, 0.5), fade(0.01, 0.02), normalize(), reverse(),
    pitch_shift(3.0), stretch_to_bars(1, 120), chop_at_onsets(0.2),
]


@pytest.mark.parametrize("transform", ALL_TRANSFORMS, ids=lambda t: t.kind)
def test_every_transform_satisfies_the_protocol_with_json_safe_params(transform):
    assert isinstance(transform, Transform)
    assert transform.kind and transform.kind == type(transform).__name__
    assert "kind" not in transform.params()
    json.dumps(transform.params(), allow_nan=False)


def test_params_are_exactly_the_constructor_arguments():
    assert trim(0.4, 2.1).params() == {"start_s": 0.4, "end_s": 2.1}
    assert trim(0.4).params() == {"start_s": 0.4, "end_s": None}
    assert fade(0.5).params() == {"in_s": 0.5, "out_s": 0.0}
    assert normalize(peak_dbfs=-3.0).params() == {"peak_dbfs": -3.0}
    assert reverse().params() == {}
    assert pitch_shift(-2).params() == {"semitones": -2.0, "formant_preserve": False}
    assert stretch_to_bars(2, 90, beats_per_bar=3).params() == {
        "bars": 2.0, "bpm": 90.0, "beats_per_bar": 3, "formant_preserve": False,
    }
    assert chop_at_onsets(0.05).params() == {"min_gap_s": 0.05}


def test_transforms_are_values_equal_by_parameters():
    assert trim(0.4, 2.1) == trim(0.4, 2.1)
    assert trim(0.4, 2.1) != trim(0.4, 2.2)
    assert hash(reverse()) == hash(reverse())


# --- trim ------------------------------------------------------------------


def test_trim_keeps_the_window_and_clamps_an_end_past_the_file(tmp_path):
    audio = sine(220.0, 2.0)
    kept = trim(0.5, 1.0).apply(audio, SR, _ctx(tmp_path))
    assert kept.shape == (SR // 2, 2)
    np.testing.assert_array_equal(kept, audio[SR // 2: SR])
    tail = trim(1.5, 9.0).apply(audio, SR, _ctx(tmp_path))
    assert tail.shape[0] == SR // 2
    to_end = trim(1.5).apply(audio, SR, _ctx(tmp_path))
    np.testing.assert_array_equal(tail, to_end)


def test_trim_refuses_a_start_past_the_file_and_malformed_windows(tmp_path):
    with pytest.raises(ValueError, match="past the end"):
        trim(3.0).apply(sine(220.0, 2.0), SR, _ctx(tmp_path))
    with pytest.raises(ValueError, match="start_s"):
        trim(-0.1)
    with pytest.raises(ValueError, match="after start_s"):
        trim(1.0, 1.0)


# --- fade ------------------------------------------------------------------


def test_fade_ramps_the_ends_and_leaves_the_middle(tmp_path):
    audio = np.ones((SR, 2), dtype=np.float32)
    out = fade(0.1, 0.2).apply(audio, SR, _ctx(tmp_path))
    assert out[0, 0] == 0.0
    assert out[SR // 2, 0] == 1.0
    assert out[-1, 0] < 0.001
    assert out[int(0.05 * SR), 0] == pytest.approx(0.5, abs=0.01)
    assert out.dtype == np.float32
    np.testing.assert_array_equal(audio, np.ones((SR, 2), dtype=np.float32))


def test_fade_refuses_overlapping_ramps_and_negative_lengths(tmp_path):
    with pytest.raises(ValueError, match="overlap"):
        fade(0.6, 0.6).apply(np.ones((SR, 2), dtype=np.float32), SR, _ctx(tmp_path))
    with pytest.raises(ValueError, match=">= 0"):
        fade(-1.0)


# --- normalize -------------------------------------------------------------


def test_normalize_lands_the_peak_and_passes_silence_through(tmp_path):
    out = normalize(peak_dbfs=-6.0).apply(sine(220.0, 0.5, amplitude=0.1), SR, _ctx(tmp_path))
    assert float(np.max(np.abs(out))) == pytest.approx(10 ** (-6.0 / 20.0), rel=1e-4)
    silent = np.zeros((SR, 2), dtype=np.float32)
    np.testing.assert_array_equal(normalize().apply(silent, SR, _ctx(tmp_path)), silent)
    with pytest.raises(ValueError, match="<= 0"):
        normalize(peak_dbfs=1.0)


# --- reverse ---------------------------------------------------------------


def test_reverse_of_reverse_is_the_source(tmp_path):
    audio = sine(220.0, 0.5) * np.linspace(0, 1, SR // 2, dtype=np.float32)[:, None]
    once = reverse().apply(audio, SR, _ctx(tmp_path))
    assert not np.array_equal(once, audio)
    np.testing.assert_array_equal(reverse().apply(once, SR, _ctx(tmp_path)), audio)


# --- pitch_shift -----------------------------------------------------------


@pytest.mark.parametrize("channels", [1, 2])
def test_pitch_shift_moves_the_pitch_and_keeps_the_length(tmp_path, channels):
    audio = sine(220.0, 1.0)[:, :channels]
    out = pitch_shift(12.0).apply(audio, SR, _ctx(tmp_path))
    assert out.shape == audio.shape and out.dtype == np.float32
    assert _dominant_hz(out[:, 0], SR) == pytest.approx(440.0, abs=3.0)


def test_pitch_shift_of_zero_is_the_identity(tmp_path):
    audio = sine(220.0, 0.5)
    np.testing.assert_array_equal(pitch_shift(0).apply(audio, SR, _ctx(tmp_path)), audio)


def test_formant_preserve_refuses_naming_the_listening_harness():
    with pytest.raises(ValueError, match=STRETCH_AB_COMMAND):
        pitch_shift(2.0, formant_preserve=True)
    with pytest.raises(ValueError, match=STRETCH_AB_COMMAND):
        stretch_to_bars(1, 120, formant_preserve=True)
    with pytest.raises(ValueError, match="finite"):
        pitch_shift(float("nan"))


# --- stretch_to_bars -------------------------------------------------------


@pytest.mark.parametrize("bars,bpm,beats_per_bar", [(1, 120, 4), (2, 90, 3), (0.5, 140, 4)])
def test_stretch_to_bars_lands_on_exactly_the_bars_asked(tmp_path, bars, bpm, beats_per_bar):
    audio = sine(220.0, 1.3)
    t = stretch_to_bars(bars, bpm, beats_per_bar=beats_per_bar)
    out = t.apply(audio, SR, _ctx(tmp_path))
    assert out.shape == (int(round(t.target_seconds() * SR)), 2)
    assert out.dtype == np.float32
    assert _dominant_hz(out[:, 0], SR) == pytest.approx(220.0, abs=3.0)


def test_stretch_to_bars_refuses_nonsense():
    with pytest.raises(ValueError, match="bars"):
        stretch_to_bars(0, 120)
    with pytest.raises(ValueError, match="bpm"):
        stretch_to_bars(1, 0)
    with pytest.raises(ValueError, match="beats_per_bar"):
        stretch_to_bars(1, 120, beats_per_bar=0)


# --- chop_at_onsets --------------------------------------------------------


def test_chop_at_onsets_yields_one_piece_per_pulse(tmp_path):
    audio = _pulsed_tone(4)
    pieces = chop_at_onsets(0.2).apply(audio, SR, _ctx(tmp_path))
    assert isinstance(pieces, list) and len(pieces) == 4
    for piece in pieces:
        assert piece.ndim == 2 and piece.shape[1] == 2
        assert float(np.max(np.abs(piece[: SR // 20]))) > 0.3  # the attack opens each piece
    assert sum(p.shape[0] for p in pieces) == audio.shape[0] - chop_at_onsets(0.2).onset_samples(audio, SR)[0]


def test_chop_min_gap_folds_offsets_and_double_triggers(tmp_path):
    audio = _pulsed_tone(3)
    assert len(chop_at_onsets(0.2).onset_samples(audio, SR)) == 3
    assert len(chop_at_onsets(0.0).onset_samples(audio, SR)) >= 3


def test_chop_at_onsets_refuses_material_with_no_attacks(tmp_path):
    with pytest.raises(ValueError, match="no onsets"):
        chop_at_onsets(0.1).apply(np.zeros((SR, 2), dtype=np.float32), SR, _ctx(tmp_path))
    with pytest.raises(ValueError, match="min_gap_s"):
        chop_at_onsets(-0.1)
