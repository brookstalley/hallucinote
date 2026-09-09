"""The second front door: any file in, ``(n, 2)`` float32 out.

Every case writes its own file to ``tmp_path`` from a synthesized signal —
no audio is committed — and asserts the normalization contract: mono is
duplicated, wide files fold at equal power, resampling keeps the pitch, and
the capture loader's refusals are not this loader's business.
"""
from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from hallucinote.audio.sample_io import as_mono, fold_to_stereo, load_sample, resample
from tests.unit.audio.fixtures import sine


def _zero_crossing_hz(mono: np.ndarray, sr: int) -> float:
    crossings = np.count_nonzero(np.diff(np.signbit(mono)))
    return crossings / 2.0 / (mono.shape[0] / sr)


def test_22k_mono_file_loads_as_44k1_stereo(tmp_path):
    src_sr = 22_050
    mono = sine(440.0, 1.0, sr=src_sr)[:, 0]
    path = tmp_path / "line.wav"
    sf.write(path, mono, src_sr, subtype="PCM_16")

    sample = load_sample(path, target_sr=44_100)

    assert sample.audio.shape == (44_100, 2)
    assert sample.audio.dtype == np.float32
    assert sample.sr == 44_100
    assert sample.source_sr == src_sr
    assert sample.source_channels == 1
    assert sample.duration_s == pytest.approx(1.0)
    np.testing.assert_array_equal(sample.audio[:, 0], sample.audio[:, 1])
    assert _zero_crossing_hz(sample.audio[:, 0], sample.sr) == pytest.approx(440.0, rel=0.01)


def test_native_rate_is_kept_when_no_target_given(tmp_path):
    path = tmp_path / "stereo.wav"
    sf.write(path, sine(220.0, 0.5, sr=48_000), 48_000, subtype="FLOAT")

    sample = load_sample(path)

    assert sample.sr == 48_000
    assert sample.source_channels == 2
    assert sample.audio.shape == (24_000, 2)
    assert sample.path == path


def test_wide_file_folds_to_stereo_at_equal_power(tmp_path):
    sr = 48_000
    rng = np.random.default_rng(3)
    four = (0.2 * rng.standard_normal((sr, 4))).astype(np.float32)
    path = tmp_path / "quad.wav"
    sf.write(path, four, sr, subtype="FLOAT")

    sample = load_sample(path)

    assert sample.source_channels == 4
    assert sample.audio.shape == (sr, 2)
    expected = four.sum(axis=1) / 2.0  # 1/sqrt(4)
    np.testing.assert_allclose(sample.audio[:, 0], expected, atol=1e-6)
    # Equal-power: the fold's RMS matches one channel's, not four times it.
    assert np.sqrt(np.mean(sample.audio[:, 0] ** 2)) == pytest.approx(
        np.sqrt(np.mean(four[:, 0] ** 2)), rel=0.05
    )


def test_downsampling_preserves_pitch():
    sr = 96_000
    tone = sine(1000.0, 1.0, sr=sr)
    out = resample(tone, sr, 44_100)
    assert out.shape == (44_100, 2)
    assert out.dtype == np.float32
    assert _zero_crossing_hz(out[:, 0], 44_100) == pytest.approx(1000.0, rel=0.005)


def test_fold_to_stereo_shapes():
    mono = np.ones((10,), dtype=np.float32)
    assert fold_to_stereo(mono).shape == (10, 2)
    assert fold_to_stereo(mono[:, None]).shape == (10, 2)
    stereo = np.zeros((10, 2), dtype=np.float32)
    assert fold_to_stereo(stereo) is not None and fold_to_stereo(stereo).shape == (10, 2)
    with pytest.raises(ValueError, match="at least one channel"):
        fold_to_stereo(np.zeros((10, 0), dtype=np.float32))


def test_as_mono_matches_duplicated_mono_and_accepts_shapes():
    m = sine(300.0, 0.1)[:, 0]
    np.testing.assert_allclose(as_mono(np.stack([m, m], axis=1)), m, atol=1e-7)
    np.testing.assert_allclose(as_mono(m[:, None]), m, atol=1e-7)
    assert as_mono(m).dtype == np.float64
    with pytest.raises(ValueError, match="n_samples, n_channels"):
        as_mono(np.zeros((2, 2, 2)))


def test_missing_file_teaches(tmp_path):
    with pytest.raises(FileNotFoundError, match="libsndfile reads"):
        load_sample(tmp_path / "nope.wav")


def test_non_audio_file_is_refused_with_a_hint(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("this is not audio")
    with pytest.raises(ValueError, match="not an audio file"):
        load_sample(path)


def test_empty_file_is_refused(tmp_path):
    path = tmp_path / "empty.wav"
    sf.write(path, np.zeros((0, 1), dtype=np.float32), 48_000, subtype="FLOAT")
    with pytest.raises(ValueError, match="no samples"):
        load_sample(path)


def test_bad_target_sr_is_refused(tmp_path):
    path = tmp_path / "x.wav"
    sf.write(path, sine(220.0, 0.1)[:, 0], 48_000, subtype="FLOAT")
    with pytest.raises(ValueError, match="target_sr must be a positive"):
        load_sample(path, target_sr=0)
