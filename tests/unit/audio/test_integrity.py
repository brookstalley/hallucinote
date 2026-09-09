"""Render-integrity lens — every detector fires on a synthetic defect and stays
silent on clean material.

The pairing is the contract: a detector that only ever fires proves nothing, and
one that never fires proves less. Each class below carries both halves for one
defect, using the shared synthetic fixtures so the "clean" material here is the
same material the rest of the audio suite calls clean.
"""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.audio.integrity import (
    ClipEvent,
    Discontinuity,
    Dropout,
    SurfaceIntegrity,
    measure_integrity,
)

from .fixtures import (
    SAMPLE_RATE,
    click,
    concat,
    kick_onset,
    onsets_at_beats,
    pink_noise,
    silence,
    sine,
)


def _measure(audio: np.ndarray, **kwargs: object) -> SurfaceIntegrity:
    """Measure at the fixture sample rate; every test uses one surface."""
    return measure_integrity(audio, sample_rate=SAMPLE_RATE, **kwargs)  # type: ignore[arg-type]


def _skip_tokens(result: SurfaceIntegrity) -> set[str]:
    """The stable token half of each ``"token: detail"`` skip reason."""
    return {reason.split(":", 1)[0] for reason in result.checks_skipped}


def _hard_clip(audio: np.ndarray, ceiling: float) -> np.ndarray:
    """Drive a signal into a hard ceiling — what a stem does on its way into an
    over-hot master bus."""
    return np.clip(audio * (1.0 / ceiling), -1.0, 1.0).astype(np.float32)


def _zero_run_at_crest(
    audio: np.ndarray, *, start_hint: int, length: int
) -> tuple[np.ndarray, int]:
    """Punch a bit-exact hole starting at the loudest sample near ``start_hint``.

    A dropout cuts the waveform wherever the buffer died, so the fixture has to
    cut at a crest rather than wherever a sine happens to cross zero — a hole
    starting at a zero crossing has no abrupt edge and is indistinguishable from
    a rest, which is the detector's documented limit and not what this fixture is
    for.
    """
    window = np.abs(audio[start_hint : start_hint + 240, 0])
    start = start_hint + int(np.argmax(window))
    out = audio.copy()
    out[start : start + length] = 0.0
    return out, start


class TestCleanMaterial:
    """A clean render says so — distinguishably from "could not check"."""

    @pytest.mark.parametrize(
        "name, audio",
        [
            ("sine", sine(220.0, 0.5)),
            ("pink_noise", pink_noise(0.5)),
            # Two kicks, each given room to decay to nothing before the next.
            # A kick spliced on before it finished would be a cut decay joined at
            # a step, which this lens is right to report — so the clean fixture
            # has to be genuinely clean, not merely percussive.
            (
                "kick",
                concat(
                    kick_onset(duration_s=0.3, decay_s=0.04),
                    kick_onset(duration_s=0.3, decay_s=0.04),
                ),
            ),
        ],
    )
    def test_no_defects_reported(self, name: str, audio: np.ndarray) -> None:
        result = _measure(audio, onset_samples=[])
        assert not result.silent, name
        assert result.clip_events == [], name
        assert result.clipped_sample_fraction == 0.0, name
        assert result.worst_clip_run_samples == 0, name
        assert result.dropouts == [], name
        assert result.discontinuities == [], name

    def test_clean_material_skips_nothing(self) -> None:
        # An empty event list means "looked and found nothing" only because an
        # empty skip list is the other half of the contract.
        #
        # Onsets are SUPPLIED here rather than left empty: an empty list
        # suppresses nothing, so it now names itself as a degraded reading (see
        # `test_an_empty_onset_list_names_itself_like_a_missing_one`). A clean
        # surface analysed the way the real caller analyses one skips nothing.
        result = _measure(sine(220.0, 0.5), onset_samples=[0])
        assert result.checks_skipped == []

    def test_dc_offset_of_a_symmetric_signal_is_negligible(self) -> None:
        result = _measure(sine(220.0, 0.5), onset_samples=[])
        assert result.dc_offset[0] == pytest.approx(0.0, abs=1e-3)
        assert result.dc_offset[1] == pytest.approx(0.0, abs=1e-3)
        assert result.dc_offset_dbfs < -50.0


class TestClipping:
    def test_flat_topped_stem_reports_runs_and_a_fraction(self) -> None:
        clipped = _hard_clip(sine(220.0, 0.5, amplitude=0.5), ceiling=0.25)
        result = _measure(clipped, onset_samples=[])

        assert result.clip_events, "a stem driven 6 dB into the ceiling must clip"
        assert all(isinstance(e, ClipEvent) for e in result.clip_events)
        assert result.worst_clip_run_samples >= 3
        assert 0.0 < result.clipped_sample_fraction < 1.0
        # Both channels of a stereo stem clip; the events say which.
        assert {e.channel for e in result.clip_events} == {0, 1}

    def test_clip_runs_land_where_the_waveform_is_flat(self) -> None:
        clipped = _hard_clip(sine(100.0, 0.2, amplitude=0.5), ceiling=0.25)
        result = _measure(clipped, onset_samples=[])
        event = result.clip_events[0]
        run = clipped[event.start_sample : event.start_sample + event.length_samples,
                      event.channel]
        assert np.all(np.abs(run) >= 0.999)
        # The samples on each side of the run are not at the ceiling — the run is
        # the whole excursion, not a fragment of it.
        if event.start_sample > 0:
            assert abs(clipped[event.start_sample - 1, event.channel]) < 0.999

    def test_headroom_leaves_the_detector_silent(self) -> None:
        # -6 dBFS peak: nothing to flat-top against.
        result = _measure(sine(220.0, 0.5, amplitude=0.5), onset_samples=[])
        assert result.clip_events == []
        assert result.clipped_sample_fraction == 0.0

    def test_a_single_sample_at_full_scale_is_not_a_clip(self) -> None:
        # One sample touching the ceiling is what a correctly normalized peak
        # does. Only a held ceiling is damage.
        audio = sine(220.0, 0.2, amplitude=0.5).copy()
        audio[5000, 0] = 1.0
        result = _measure(audio, onset_samples=[5000])
        assert result.clip_events == []


class TestDcOffset:
    def test_offset_is_reported_per_channel_and_in_dbfs(self) -> None:
        audio = sine(220.0, 0.5, amplitude=0.4).copy()
        audio[:, 0] += 0.05  # only the left channel misbehaves
        result = _measure(audio, onset_samples=[])

        assert result.dc_offset[0] == pytest.approx(0.05, abs=1e-3)
        assert result.dc_offset[1] == pytest.approx(0.0, abs=1e-3)
        # The dBFS reading is the WORST channel — 20*log10(0.05) = -26.0.
        assert result.dc_offset_dbfs == pytest.approx(-26.0, abs=0.5)

    def test_a_negative_offset_reads_the_same_magnitude(self) -> None:
        audio = sine(220.0, 0.5, amplitude=0.4) - 0.05
        result = _measure(audio, onset_samples=[])
        assert result.dc_offset[0] == pytest.approx(-0.05, abs=1e-3)
        assert result.dc_offset_dbfs == pytest.approx(-26.0, abs=0.5)


class TestDropouts:
    def test_a_bit_exact_hole_mid_signal_is_a_zero_run(self) -> None:
        hole_len = int(0.010 * SAMPLE_RATE)
        audio, start = _zero_run_at_crest(
            sine(220.0, 0.5), start_hint=20_000, length=hole_len
        )
        result = _measure(audio, onset_samples=[])

        zero_runs = [d for d in result.dropouts if d.kind == "zero_run"]
        assert len(zero_runs) == 1
        assert isinstance(zero_runs[0], Dropout)
        assert zero_runs[0].start_sample == start
        assert zero_runs[0].length_samples == hole_len

    def test_leading_and_trailing_silence_are_not_dropouts(self) -> None:
        audio = concat(silence(0.2), sine(220.0, 0.3), silence(0.2))
        result = _measure(audio, onset_samples=[])
        assert result.dropouts == []

    def test_a_hole_shorter_than_a_buffer_is_below_the_floor(self) -> None:
        # 1 ms is shorter than the minimum a dropped audio buffer can be.
        audio, _ = _zero_run_at_crest(
            sine(220.0, 0.5), start_hint=20_000, length=int(0.001 * SAMPLE_RATE)
        )
        result = _measure(audio, onset_samples=[])
        assert [d for d in result.dropouts if d.kind == "zero_run"] == []

    def test_a_non_zero_level_collapse_is_an_rms_collapse(self) -> None:
        audio = pink_noise(0.5).copy()
        # 20 ms at -60 dB: the samples are still non-zero, so only the level test
        # can see this one.
        lo, hi = int(0.10 * SAMPLE_RATE), int(0.12 * SAMPLE_RATE)
        audio[lo:hi, :] *= 1e-3
        result = _measure(audio, onset_samples=[])

        collapses = [d for d in result.dropouts if d.kind == "rms_collapse"]
        assert len(collapses) == 1
        assert collapses[0].start_sample == pytest.approx(lo, abs=240)
        assert collapses[0].length_samples == pytest.approx(hi - lo, abs=480)

    def test_a_stuttering_buffer_reports_every_hole(self) -> None:
        # Holes back to back are what a buffer under sustained load produces; the
        # second must not be swallowed by the first one's recovery.
        audio = pink_noise(0.5).copy()
        holes = [(0.10, 0.12), (0.13, 0.15)]
        for start_s, end_s in holes:
            audio[int(start_s * SAMPLE_RATE) : int(end_s * SAMPLE_RATE), :] *= 1e-3
        result = _measure(audio, onset_samples=[])

        collapses = [d for d in result.dropouts if d.kind == "rms_collapse"]
        assert len(collapses) == 2
        assert [c.start_sample for c in collapses] == sorted(
            c.start_sample for c in collapses
        )

    def test_a_decay_is_not_a_collapse(self) -> None:
        # A kick falls tens of dB, monotonically, and never climbs back out.
        # The two-sided flanking test is what keeps it off this list.
        audio = concat(kick_onset(duration_s=0.4), kick_onset(duration_s=0.4))
        result = _measure(audio, onset_samples=[])
        assert [d for d in result.dropouts if d.kind == "rms_collapse"] == []

    def test_a_hole_is_reported_once_under_one_kind(self) -> None:
        hole_len = int(0.020 * SAMPLE_RATE)
        audio, _ = _zero_run_at_crest(
            pink_noise(0.5), start_hint=20_000, length=hole_len
        )
        result = _measure(audio, onset_samples=[])
        # Bit-exact silence satisfies the level test too; the same hole must not
        # arrive twice wearing two names.
        assert len(result.dropouts) == 1
        assert result.dropouts[0].kind == "zero_run"


class TestDiscontinuities:
    def test_a_clip_starting_off_a_zero_crossing_is_a_pop(self) -> None:
        # The failure this project makes in its own output: a programmatically
        # placed clip whose first sample is nowhere near zero.
        audio = concat(silence(0.1), sine(220.0, 0.4, amplitude=0.5, phase=np.pi / 2))
        result = _measure(audio, onset_samples=[])

        assert result.discontinuities
        assert all(isinstance(d, Discontinuity) for d in result.discontinuities)
        splice = int(0.1 * SAMPLE_RATE)
        assert {d.sample for d in result.discontinuities} == {splice}
        assert {d.channel for d in result.discontinuities} == {0, 1}
        assert result.discontinuities[0].magnitude == pytest.approx(0.5, abs=0.01)

    def test_a_smooth_signal_has_none(self) -> None:
        result = _measure(sine(220.0, 0.5), onset_samples=[])
        assert result.discontinuities == []

    def test_the_threshold_scales_with_the_material(self) -> None:
        # The same step relative to the signal must read the same way at any
        # level — an absolute constant would flag the loud take and miss the
        # quiet one.
        loud = concat(silence(0.1), sine(220.0, 0.4, amplitude=0.5, phase=np.pi / 2))
        quiet = loud * 0.01
        loud_result = _measure(loud, onset_samples=[])
        quiet_result = _measure(quiet, onset_samples=[])
        assert [d.sample for d in quiet_result.discontinuities] == [
            d.sample for d in loud_result.discontinuities
        ]

    def test_known_onsets_suppress_their_own_attacks(self) -> None:
        beats = [0.0, 1.0, 2.0, 3.0]
        audio = onsets_at_beats(beats, bpm=120.0, total_beats=4.0)
        samples_per_beat = SAMPLE_RATE * 60.0 / 120.0
        onsets = [int(round(b * samples_per_beat)) for b in beats]

        unsuppressed = _measure(audio, onset_samples=None)
        suppressed = _measure(audio, onset_samples=onsets)

        # A click IS a discontinuity — that is exactly why the caller has to say
        # where the music's attacks are.
        assert unsuppressed.discontinuities
        assert suppressed.discontinuities == []

    def test_no_onsets_supplied_is_named_not_silently_assumed(self) -> None:
        result = _measure(sine(220.0, 0.2), onset_samples=None)
        assert "discontinuities_unsuppressed" in _skip_tokens(result)

    def test_a_pop_next_to_an_onset_is_still_suppressed_only_near_it(self) -> None:
        # Suppression is a window around a known attack, not a blanket amnesty:
        # a pop far from every onset survives it.
        audio = sine(220.0, 0.5, amplitude=0.4).copy()
        attack = click()
        audio[: attack.shape[0], :] += attack  # a real musical attack at sample 0
        pop_at = int(0.3 * SAMPLE_RATE)
        audio[pop_at:, :] += 0.3  # a splice in the middle of the note
        result = _measure(audio, onset_samples=[0])
        assert {d.sample for d in result.discontinuities} == {pop_at}


class TestTruncatedDecay:
    def test_signal_at_the_final_samples_reads_a_loud_tail(self) -> None:
        result = _measure(sine(220.0, 0.5, amplitude=0.5), onset_samples=[])
        assert result.tail_level_dbfs is not None
        # A 0.5-amplitude sine is -9 dBFS RMS; the capture stopped mid-note.
        assert result.tail_level_dbfs == pytest.approx(-9.0, abs=1.0)

    def test_a_decay_that_finished_reads_a_quiet_tail(self) -> None:
        result = _measure(
            concat(sine(220.0, 0.3), silence(0.2)), onset_samples=[]
        )
        assert result.tail_level_dbfs is not None
        assert result.tail_level_dbfs < -100.0
        # Far below the peak, which is what "the decay had room to finish" means.
        assert result.tail_level_dbfs < result.peak_dbfs - 60.0

    def test_a_surface_shorter_than_the_tail_window_says_so(self) -> None:
        result = _measure(sine(220.0, 0.005), onset_samples=[])
        assert result.tail_level_dbfs is None
        assert "tail_window_too_short" in _skip_tokens(result)


class TestSilence:
    def test_an_all_silent_surface_is_a_fact_not_a_pile_of_nans(self) -> None:
        result = _measure(silence(0.5))
        assert result.silent is True
        assert not np.isnan(result.peak_dbfs)
        assert result.peak_dbfs <= -180.0
        assert result.dc_offset == (0.0, 0.0)
        assert result.clip_events == []
        assert result.dropouts == []
        assert result.discontinuities == []
        assert result.tail_level_dbfs is None
        assert "silent_surface" in _skip_tokens(result)

    def test_an_empty_surface_names_itself(self) -> None:
        result = _measure(np.zeros((0, 2), dtype=np.float32))
        assert result.silent is True
        assert "empty_surface" in _skip_tokens(result)

    def test_audible_material_is_not_silent(self) -> None:
        result = _measure(sine(220.0, 0.2, amplitude=1e-4), onset_samples=[])
        assert result.silent is False
        assert "silent_surface" not in _skip_tokens(result)


class TestEventCaps:
    def test_the_cap_bounds_every_list_and_says_what_it_dropped(self) -> None:
        clipped = _hard_clip(sine(200.0, 1.0, amplitude=0.5), ceiling=0.25)
        result = _measure(clipped, onset_samples=[], max_events=4)

        assert len(result.clip_events) == 4
        truncation = [
            r for r in result.checks_skipped if r.startswith("clip_events_truncated")
        ]
        assert len(truncation) == 1
        # The detail carries both numbers, so a reader can see how much was hidden.
        assert "4 reported" in truncation[0]

    def test_the_counts_are_computed_over_everything_found(self) -> None:
        clipped = _hard_clip(sine(200.0, 1.0, amplitude=0.5), ceiling=0.25)
        capped = _measure(clipped, onset_samples=[], max_events=4)
        uncapped = _measure(clipped, onset_samples=[], max_events=100_000)

        assert len(uncapped.clip_events) > 4
        # The cap hides rows, never the measurement.
        assert capped.clipped_sample_fraction == uncapped.clipped_sample_fraction
        assert capped.worst_clip_run_samples == uncapped.worst_clip_run_samples


class TestInputContract:
    def test_a_mono_array_is_refused(self) -> None:
        with pytest.raises(ValueError, match="stereo"):
            measure_integrity(np.zeros(4800, dtype=np.float32), sample_rate=SAMPLE_RATE)

    def test_a_non_positive_sample_rate_is_refused(self) -> None:
        with pytest.raises(ValueError, match="sample rate"):
            measure_integrity(silence(0.1), sample_rate=0)

    def test_the_input_buffer_is_not_modified(self) -> None:
        audio = sine(220.0, 0.2)
        before = audio.copy()
        _measure(audio, onset_samples=[])
        assert np.array_equal(audio, before)


class TestLoudIsNotClipped:
    """A pre-fader stem may peak far above 0 dBFS and be perfectly undamaged.

    Captured stems are float32 and pre-fader: the mixer applies the fader
    afterwards, so a healthy part routinely runs hot and float has no ceiling for
    it to hit. A real render exposed the failure this pins — a stem peaking at
    +6.3 dBFS drew thousands of clip runs from an amplitude-threshold rule,
    because a waveform that loud spends most of every cycle above full scale
    without ever going flat. Clipping is a flat top; loudness is not damage.
    """

    def test_a_stem_peaking_above_full_scale_is_not_clipped(self) -> None:
        # +6 dBFS, curving through every peak — nothing is pinned.
        hot = (sine(100.0, 0.5, amplitude=0.5) * 4.0).astype(np.float32)
        result = _measure(hot, onset_samples=[])
        assert result.peak_dbfs > 6.0
        assert result.clip_events == []
        assert result.clipped_sample_fraction == 0.0
        assert result.worst_clip_run_samples == 0

    def test_a_hot_stem_that_IS_flat_topped_still_reports(self) -> None:
        # Same level, but genuinely squared off — the flat top is the defect, and
        # it must survive being far above full scale.
        hot = (sine(100.0, 0.5, amplitude=0.5) * 4.0).astype(np.float32)
        squared = np.clip(hot, -1.5, 1.5).astype(np.float32)
        result = _measure(squared, onset_samples=[])
        assert result.clip_events, "a flat top above full scale is still a flat top"
        assert result.worst_clip_run_samples >= 3

    def test_a_low_frequency_peak_is_not_mistaken_for_a_plateau(self) -> None:
        # 20 Hz is the flattest a musical waveform gets near its peak; normalized
        # to exactly full scale it is the hardest honest signal to tell from a
        # clip, and it must still read clean.
        slow = sine(20.0, 0.5, amplitude=1.0).astype(np.float32)
        result = _measure(slow, onset_samples=[])
        assert result.clip_events == []


class TestQuietLowFrequencyIsNotClipped:
    """The flatness tolerance is RELATIVE, so it holds at every level.

    A crest's flatness scales with amplitude, so an absolute tolerance becomes a
    false positive as material gets quieter — a clean 20 Hz sine at -12 dBFS,
    which is exactly where a sub or an 808 tail lives, drew 32 phantom clip runs.
    That is the same failure as the loud one this detector was already fixed for,
    at the other end of the range.
    """

    @pytest.mark.parametrize("freq", [20.0, 40.0, 60.0])
    @pytest.mark.parametrize("amplitude", [0.5, 0.125, 0.02])
    def test_a_clean_low_sine_reads_clean_at_any_level(
        self, freq: float, amplitude: float
    ) -> None:
        result = _measure(sine(freq, 0.5, amplitude=amplitude), onset_samples=[])
        assert result.clip_events == []

    def test_a_clipped_channel_is_not_hidden_by_a_louder_sibling(self) -> None:
        # The ceiling is per CHANNEL: an asymmetric pan or M/S-processed stem
        # routinely leaves one side quieter, and a surface-wide peak would let
        # the louder side mask the damaged one entirely.
        n = SAMPLE_RATE // 2
        t = np.arange(n) / SAMPLE_RATE
        left = (1.4 * np.sin(2 * np.pi * 100 * t)).astype(np.float32)
        right = np.clip(2.0 * np.sin(2 * np.pi * 100 * t), -0.5, 0.5).astype(np.float32)
        result = _measure(np.stack([left, right], axis=1), onset_samples=[])
        assert result.clip_events, "the quiet channel is hard-clipped"
        assert {c.channel for c in result.clip_events} == {1}


class TestDiscontinuityThresholdIsLocal:
    """A single global sigma cannot work on music, which is non-stationary.

    A surface with a wide envelope range has its median derivative set by its
    quiet majority, so every loud moment reads as a huge outlier. Measured on
    synthetic drum-like material before this was made local: 32,752
    "discontinuities" against 31 real onsets.
    """

    @staticmethod
    def _bursts(period_s: float, seed: int = 5) -> np.ndarray:
        rng = np.random.default_rng(seed)
        n = SAMPLE_RATE * 2
        out = np.zeros(n)
        step = int(SAMPLE_RATE * period_s)
        for start in range(0, n - step, step):
            length = min(step, int(SAMPLE_RATE * 0.25))
            out[start:start + length] += (
                rng.normal(0, 0.3, length) * np.exp(-np.linspace(0, 8, length))
            )
        return np.stack([out, out], axis=1).astype(np.float32)

    @pytest.mark.parametrize("period_s", [0.125, 0.25, 0.5])
    def test_undamaged_percussive_material_reports_nothing(
        self, period_s: float
    ) -> None:
        audio = self._bursts(period_s)
        result = _measure(audio, onset_samples=[])
        assert result.discontinuities == []

    def test_a_planted_splice_is_still_found(self) -> None:
        audio = self._bursts(0.25)
        at = int(SAMPLE_RATE * 0.9)
        audio[at] = 0.9
        audio[at + 1] = -0.9
        result = _measure(audio, onset_samples=[])
        assert result.discontinuities, "a one-sample splice is the whole point"
        assert min(abs(d.sample - at) for d in result.discontinuities) <= 2

    def test_a_splice_is_not_hidden_by_the_onset_it_creates(self) -> None:
        # The onsets come from the same audio, so a click loud enough to register
        # as a spectral-flux event manufactures the very onset that would hide it.
        # A defect that conceals itself in proportion to its severity is the worst
        # failure this detector can have.
        audio = self._bursts(0.25)
        at = int(SAMPLE_RATE * 0.9)
        audio[at] = 0.9
        audio[at + 1] = -0.9
        result = _measure(audio, onset_samples=[at - 200])
        assert result.discontinuities, "the guard must not swallow an impossible step"


class TestRestsAreNotDropouts:
    """A gap that merely ENDS in an attack is ordinary music.

    In Live a track outputs bit-exact zeros whenever nothing is sounding, so
    accepting either edge turned every rest into a dropout. What makes a dropout
    a dropout is that the audio was CUT while it was still running — its LEADING
    edge is the abrupt one.
    """

    @staticmethod
    def _gated_hits() -> np.ndarray:
        audio = np.zeros((SAMPLE_RATE * 2, 2), dtype=np.float32)
        one = kick_onset()
        for i in range(8):
            start = i * SAMPLE_RATE // 4
            audio[start:start + one.shape[0]] += one
        return audio

    def test_bit_exact_rests_between_hits_are_not_dropouts(self) -> None:
        result = _measure(self._gated_hits(), onset_samples=[])
        assert [d for d in result.dropouts if d.kind == "zero_run"] == []

    def test_a_cut_mid_decay_still_reports(self) -> None:
        audio = self._gated_hits()
        cut = SAMPLE_RATE // 4 + 400
        audio[cut:cut + int(SAMPLE_RATE * 0.02)] = 0.0
        result = _measure(audio, onset_samples=[])
        assert [d for d in result.dropouts if d.kind == "zero_run"]


def test_an_empty_onset_list_names_itself_like_a_missing_one() -> None:
    """An empty list suppresses nothing, exactly like no list at all.

    It is also what the real caller produces when the onset front end finds
    nothing, so without this the one degradation token is unreachable in
    production and a degraded reading arrives looking authoritative.
    """
    audio = sine(440.0, 0.5, amplitude=0.3)
    for onsets in (None, []):
        result = _measure(audio, onset_samples=onsets)
        tokens = [entry.split(":")[0] for entry in result.checks_skipped]
        assert "discontinuities_unsuppressed" in tokens


class TestStepBurstsCollapseToRegions:
    """A burst of step-rich material is one region, not one defect per sample.

    Measured on a finished song: a heavily-processed vocal produced 42,578
    flagged steps inside 660 windows — about 65 per window, which is very nearly
    every sample in those spans. Counting that per sample turns a processed
    passage into a catastrophe in the report.
    """

    def test_a_dense_burst_reports_far_fewer_events_than_stepping_samples(
        self,
    ) -> None:
        rng = np.random.default_rng(4)
        audio = sine(220.0, 1.0, amplitude=0.3).copy()
        # A 30 ms span where every sample jumps: what a bitcrusher or a granular
        # burst actually produces.
        start = SAMPLE_RATE // 2
        span = int(SAMPLE_RATE * 0.03)
        audio[start:start + span] = rng.choice(
            np.array([-0.6, 0.6], dtype=np.float32), size=(span, 2)
        )
        result = _measure(audio, onset_samples=[])
        assert result.discontinuities, "the burst is real and must be reported"
        # One or two windows' worth per channel, not hundreds of samples.
        assert len(result.discontinuities) <= 8, len(result.discontinuities)

    def test_two_separated_splices_stay_two_events(self) -> None:
        # Collapsing must not merge genuinely distinct defects.
        audio = sine(220.0, 1.0, amplitude=0.3).copy()
        for at in (int(SAMPLE_RATE * 0.25), int(SAMPLE_RATE * 0.75)):
            audio[at] = 0.95
            audio[at + 1] = -0.95
        result = _measure(audio, onset_samples=[])
        positions = sorted({d.sample for d in result.discontinuities})
        assert len(positions) >= 2, positions
