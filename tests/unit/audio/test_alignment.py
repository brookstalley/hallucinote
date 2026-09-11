"""Capture trim-to-common-length alignment (AUD-1C7K).

The capture pipeline's per-surface sfrecord~ instances finalize at staggered
times, so the raw WAVs differ in length — but their content starts are
sample-aligned (a known-offset calibration capture recovered a 2-beat impulse
spacing to the exact sample). So the fix is to trim every surface to the common
(shortest) length; these pin that contract. The cross-surface passes
(attribution, masking) require equal-length surfaces; the capstone shows reverb
RT60 — now measured from a return's OWN ring-out (one surface, dry-source-free
per AUD-6R2M) — still recovers correctly from the trimmed return.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from hallucinote.audio.alignment import (
    measure_capture_span,
    trim_to_common_length,
)
from hallucinote.audio.io import CaptureSet, Surface
from hallucinote.audio.section import TempoSegment
from hallucinote.audio.reverb import REVERB_TOLERANCE_FLOOR_S, measure_return_rt60
from tests.unit.audio import fixtures

SR = fixtures.SAMPLE_RATE


def _surface(track_id: str, kind: str, audio: np.ndarray) -> Surface:
    return Surface(
        track_id=track_id,
        surface_kind=kind,  # type: ignore[arg-type]
        surface_name=track_id,
        audio=audio,
        sample_rate=SR,
    )


def _capture(master: Surface, stems=(), returns=()) -> CaptureSet:
    return CaptureSet(
        song_slug="trim-test",
        captured_at="20260602T000000Z",
        analyzer_signature="hallucinote-analyzer-v1",
        captures_dir=Path("/tmp/x"),
        manifest_path=Path("/tmp/x/manifest.json"),
        sample_rate=SR,
        start_at_beat=0.0,
        stop_at_beat=64.0,
        ring_out_beats=0.0,
        master=master,
        stems=list(stems),
        returns=list(returns),
    )


def test_trim_equalizes_lengths_and_preserves_heads():
    """Surfaces of different lengths are all trimmed to the shortest; the
    retained head of each is byte-identical to the original (only tails drop)."""
    base = fixtures.pink_noise(1.0)  # 48000 samples
    master = base[:47000]            # the shortest → defines the common length
    s1 = base[:48000]
    r1 = base[:47500]
    capture = _capture(
        master=_surface("master", "master", master),
        stems=[_surface("track:1", "track", s1)],
        returns=[_surface("return:1", "return", r1)],
    )

    aligned, report = trim_to_common_length(capture)

    lengths = {
        aligned.master.audio.shape[0],
        *(s.audio.shape[0] for s in aligned.stems),
        *(r.audio.shape[0] for r in aligned.returns),
    }
    assert lengths == {47000}
    assert report.common_length == 47000
    assert report.max_drift_samples == 1000  # 48000 - 47000
    # Heads preserved exactly (trim drops only the tail).
    np.testing.assert_array_equal(aligned.stems[0].audio, s1[:47000])
    np.testing.assert_array_equal(aligned.returns[0].audio, r1[:47000])
    # Report accounts every surface with its drop.
    by_id = {s.track_id: s for s in report.surfaces}
    assert by_id["track:1"].trimmed_samples == 1000
    assert by_id["return:1"].trimmed_samples == 500
    assert by_id["master"].trimmed_samples == 0


def test_trim_is_noop_when_already_equal_length():
    """Equal-length surfaces (synthetic fixtures) pass through untouched —
    drift 0, same arrays, so existing analysis tests aren't perturbed."""
    s1 = fixtures.pink_noise(0.5)
    s2 = fixtures.sine(220.0, 0.5)
    master = (s1 + s2).astype(np.float32)
    capture = _capture(
        master=_surface("master", "master", master),
        stems=[_surface("track:1", "track", s1), _surface("track:2", "track", s2)],
    )

    aligned, report = trim_to_common_length(capture)

    assert report.max_drift_samples == 0
    assert "already equal length" in report.human_summary
    np.testing.assert_array_equal(aligned.stems[0].audio, s1)
    np.testing.assert_array_equal(aligned.stems[1].audio, s2)


def test_human_summary_reports_drift_for_unequal_capture():
    capture = _capture(
        master=_surface("master", "master", fixtures.silence(1.0)),
        stems=[_surface("track:1", "track", fixtures.silence(1.1))],  # 100 ms longer
    )
    _, report = trim_to_common_length(capture)
    assert report.max_drift_samples == int(round(0.1 * SR))
    assert "100 ms" in report.human_summary


def test_reverb_rt60_measured_from_trimmed_return_ringout():
    """The AUD-1C7K capstone, post-AUD-6R2M. RT60 is now measured from the
    return's OWN ring-out (one surface, dry-source-free), so capture length
    drift across surfaces no longer couples into the deconvolution math — but
    the return surface itself is still trimmed by the AUD-1C7K pass. A return
    whose tail finalized later than its siblings is trimmed to the common
    length; because the trimmed-off region is trailing post-decay silence, the
    ring-out survives and ``measure_return_rt60`` recovers the declared RT60."""
    # The return surface IS a ring-out: an impulse-excited IR decaying into
    # silence (0.6 s RT60, well decayed within the 3 s buffer).
    ir = fixtures.synthetic_ir(0.6, duration_s=3.0)
    impulse = fixtures.silence(3.0)
    impulse[0, 0] = 1.0
    impulse[0, 1] = 1.0
    ring_out = fixtures.convolve(impulse, ir)

    # Stop drift: the return's sfrecord~ finalized later → its WAV is longer by
    # the per-surface stop offset (trailing post-decay silence), heads aligned.
    drifted_return = np.concatenate([ring_out, fixtures.silence(0.05)], axis=0)
    master = ring_out  # shortest → defines the common length
    assert drifted_return.shape[0] != master.shape[0]

    capture = _capture(
        master=_surface("master", "master", master),
        returns=[_surface("return:1", "return", drifted_return)],
    )
    aligned, _ = trim_to_common_length(capture)
    return_a = aligned.returns[0].audio
    assert return_a.shape[0] == master.shape[0]  # trimmed to common length

    # Decay onset is the impulse at sample 0; integrate the decay from there.
    result = measure_return_rt60(
        return_a,
        sample_rate=SR,
        decay_onset_sample=0,
        declared_rt60_s=0.6,
        return_track_id="return:1",
    )
    assert result.sufficient_tail
    assert np.isfinite(result.measured_rt60_s)
    assert abs(result.measured_rt60_s - 0.6) <= REVERB_TOLERANCE_FLOOR_S
    assert result.within_tolerance


# --- capture span: is the audio as long as the manifest declares? (#491) ------
#
# The numbers below are measurements, not invented fixtures. Three real captures
# of `songs/alien` (124 BPM, 48 kHz) were measured on 2026-09-09: the capture the
# incoming report named ran 1.06 beats past its declared span, and the two
# healthy ones sat inside 0.05 beats. Both ends of that separation are pinned
# here, because a threshold justified by a measurement is only honest while the
# measurement is still in the test.

ALIEN_BPM = 124.0


def _span_capture(
    *,
    declared_beats: float,
    captured_seconds: float,
    sample_rate: int = SR,
) -> CaptureSet:
    """A capture whose master holds exactly ``captured_seconds`` of audio while
    the manifest declares ``declared_beats``."""
    frames = int(round(captured_seconds * sample_rate))
    master = Surface(
        track_id="master",
        surface_kind="master",  # type: ignore[arg-type]
        surface_name="master",
        audio=np.zeros((frames, 2), dtype=np.float32),
        sample_rate=sample_rate,
    )
    return CaptureSet(
        song_slug="alien",
        captured_at="20260908T233753Z",
        analyzer_signature="hallucinote-analyzer-v1",
        captures_dir=Path("/tmp/x"),
        manifest_path=Path("/tmp/x/manifest.json"),
        sample_rate=sample_rate,
        start_at_beat=0.0,
        stop_at_beat=declared_beats,
        ring_out_beats=0.0,
        master=master,
        stems=[],
        returns=[],
    )


def test_span_reproduces_the_reported_defective_capture():
    """20260908T233753Z: 515 declared beats at 124 BPM is 249.19 s; the master
    held 11985920 frames = 249.71 s. That is the excess the report saw as a ~1.1-beat shift, and
    it must land outside tolerance."""
    capture = _span_capture(declared_beats=515.0, captured_seconds=11985920 / SR)
    span, skip = measure_capture_span(capture, [TempoSegment(0.0, ALIEN_BPM)])
    assert span is not None
    assert span.excess_beats == pytest.approx(1.06, abs=0.005)
    assert not span.within_tolerance


def test_span_accepts_the_two_healthy_captures():
    """20260909T041123Z and 20260909T043509Z: 523 declared beats = 253.06 s
    against 12146688 and 12146176 frames. Both sit inside a twentieth of a beat,
    which is what makes a quarter-beat tolerance a bright line and not a knob."""
    for frames in (12146688, 12146176):
        capture = _span_capture(declared_beats=523.0, captured_seconds=frames / SR)
        span, skip = measure_capture_span(capture, [TempoSegment(0.0, ALIEN_BPM)])
        assert span is not None
        assert abs(span.excess_beats) < 0.05
        assert span.within_tolerance


def test_span_refuses_without_tempo_evidence():
    """No tempo map means no answer. Returning a 120-BPM-derived duration here
    would manufacture a finding on every song not at 120 — the whole reason
    declared_span_seconds refuses rather than reusing BeatSampleMap's fallback."""
    capture = _span_capture(declared_beats=515.0, captured_seconds=249.19)
    for segments in ([], [TempoSegment(0.0, 0.0)]):
        span, skip = measure_capture_span(capture, segments)
        assert span is None
        assert skip is not None
        assert "no tempo_map rows" in skip


def test_span_refuses_when_the_capture_predates_the_first_tempo_point():
    """A span reaching back before the first tempo point has no evidence for its
    leading beats. Refusing is the honest answer; integrating them at a default
    would compare real audio against a partly-invented duration.

    Nothing requires a song's first tempo row to be at bar 1, so this is a
    reachable state and not a theoretical one — and it must NOT be reported as a
    missing tempo map, because the map is present and usable."""
    capture = _span_capture(declared_beats=515.0, captured_seconds=249.19)
    span, skip = measure_capture_span(capture, [TempoSegment(16.0, ALIEN_BPM)])
    assert span is None
    assert skip is not None
    assert "before the song's first tempo point" in skip
    assert "no tempo_map rows" not in skip


def test_span_refuses_on_a_malformed_manifest_and_says_so():
    """A manifest declaring stop <= start has no duration to check against. That
    is a broken manifest, not a missing tempo map, and an operator sent to look
    for the wrong one loses the trail."""
    capture = _span_capture(declared_beats=515.0, captured_seconds=249.19)
    capture = dataclasses.replace(capture, start_at_beat=600.0, stop_at_beat=500.0)
    span, skip = measure_capture_span(capture, [TempoSegment(0.0, ALIEN_BPM)])
    assert span is None
    assert skip is not None
    assert "non-positive span" in skip


def test_span_decline_reasons_are_all_distinct():
    """Four declines, four messages. The entry exists to end a silence; naming
    one cause for four different problems would replace it with a wrong answer,
    which is worse."""
    ok = _span_capture(declared_beats=515.0, captured_seconds=249.19)
    malformed = dataclasses.replace(ok, start_at_beat=600.0, stop_at_beat=500.0)
    reasons = {
        measure_capture_span(malformed, [TempoSegment(0.0, ALIEN_BPM)])[1],
        measure_capture_span(ok, [])[1],
        measure_capture_span(ok, [TempoSegment(16.0, ALIEN_BPM)])[1],
        measure_capture_span(
            ok, [TempoSegment(0.0, 120.0), TempoSegment(60.0, 60.0)]
        )[1],
    }
    assert len(reasons) == 4
    assert None not in reasons


def test_span_declines_when_the_song_declares_a_tempo_change():
    """The comparison is against the DECLARED tempo, and push materializes only
    the bar-1 tempo today — so on a song declaring a change, declared duration
    and rendered audio disagree for a reason that is not a capture defect.
    Declining names the push gap instead of reporting it as a bad capture.

    (The integrator itself IS variable-tempo accurate; that is pinned in
    test_section.py, where it is the integrator's contract rather than this
    check's.)"""
    capture = _span_capture(declared_beats=120.0, captured_seconds=90.0)
    span, skip = measure_capture_span(
        capture, [TempoSegment(0.0, 120.0), TempoSegment(60.0, 60.0)]
    )
    assert span is None
    assert skip is not None
    assert "push materializes only the bar-1 row" in skip


def test_span_declines_on_a_declared_tempo_ramp():
    """A linear ramp is a tempo change even with no second point inside the span."""
    capture = _span_capture(declared_beats=120.0, captured_seconds=90.0)
    span, skip = measure_capture_span(
        capture,
        [TempoSegment(0.0, 120.0, "linear"), TempoSegment(200.0, 60.0)],
    )
    assert span is None
    assert skip is not None


def test_span_runs_when_a_later_tempo_point_sits_outside_the_span():
    """A tempo change after the capture ends does not make the captured span
    variable — declining there would silence the check on any song with a tempo
    move later in the arrangement than the render window."""
    capture = _span_capture(declared_beats=40.0, captured_seconds=40 * 60 / ALIEN_BPM)
    span, skip = measure_capture_span(
        capture, [TempoSegment(0.0, ALIEN_BPM), TempoSegment(400.0, 90.0)]
    )
    assert skip is None
    assert span is not None
    assert span.within_tolerance


def test_span_measures_the_master_not_the_longest_surface():
    """Returns finalize up to a third of a beat after the master on a HEALTHY
    capture (the stop-length ramp above). Measuring anything but the common
    length would flag every capture ever made."""
    capture = _span_capture(declared_beats=523.0, captured_seconds=12146176 / SR)
    late_return = _surface(
        "return-01", "return",
        np.zeros((12154880, 2), dtype=np.float32),  # +0.34 beats, real number
    )
    capture = dataclasses.replace(capture, returns=[late_return])
    span, skip = measure_capture_span(capture, [TempoSegment(0.0, ALIEN_BPM)])
    assert span is not None
    assert span.within_tolerance


def test_span_human_summary_states_what_it_cannot_know():
    """The summary must not claim the capture 'started early' — length alone
    cannot tell a head offset from a tail overrun."""
    capture = _span_capture(declared_beats=515.0, captured_seconds=11985920 / SR)
    span, skip = measure_capture_span(capture, [TempoSegment(0.0, ALIEN_BPM)])
    assert span is not None
    summary = span.human_summary
    assert "1.06 beats longer" in summary
    assert "head or the tail" in summary


def test_span_declines_when_the_span_would_be_read_at_a_tempo_push_never_played():
    """The case that makes this a RENDER question, not a score question.

    A song declaring 90 bpm at bar 1 and 124 from beat 8, rendered from beat 16,
    has a declared tempo that is perfectly constant across the captured span —
    124. But push sets Live's one global tempo from the bar-1 row and skips the
    rest, so the audio was played at 90 throughout. Integrating at 124 would
    compare real audio against a duration nobody performed and hand the operator
    a `capture_span_mismatch` — in the one lens the mix-review skill instructs
    the reader never to hedge.

    An earlier predicate asked only whether the DECLARED tempo was constant and
    accepted exactly this."""
    declared = 40.0
    capture = _span_capture(
        declared_beats=declared, captured_seconds=declared * 60 / 90.0
    )
    capture = dataclasses.replace(
        capture, start_at_beat=16.0, stop_at_beat=16.0 + declared
    )
    span, skip = measure_capture_span(
        capture, [TempoSegment(0.0, 90.0), TempoSegment(8.0, 124.0)]
    )
    assert span is None
    assert skip is not None
    assert "bar-1 tempo (90 bpm)" in skip


def test_span_runs_when_an_earlier_row_restates_the_same_tempo():
    """The safe half of the same shape: a tempo row before the span that does not
    CHANGE the tempo leaves the render and the score agreeing, so the check still
    answers. Declining here would silence it on any song rendered from a later
    section than bar 1."""
    declared = 40.0
    capture = _span_capture(
        declared_beats=declared, captured_seconds=declared * 60 / ALIEN_BPM
    )
    capture = dataclasses.replace(
        capture, start_at_beat=16.0, stop_at_beat=16.0 + declared
    )
    span, skip = measure_capture_span(
        capture, [TempoSegment(0.0, ALIEN_BPM), TempoSegment(8.0, ALIEN_BPM)]
    )
    assert skip is None
    assert span is not None
    assert span.within_tolerance


def test_span_declines_when_no_row_sits_at_bar_one():
    """With no bar-1 row push sets no global tempo at all and says so in a warn,
    so what Live played is genuinely unknown — not assumable from the earliest
    row that happens to exist."""
    declared = 40.0
    capture = _span_capture(
        declared_beats=declared, captured_seconds=declared * 60 / ALIEN_BPM
    )
    capture = dataclasses.replace(
        capture, start_at_beat=8.0, stop_at_beat=8.0 + declared
    )
    span, skip = measure_capture_span(capture, [TempoSegment(4.0, ALIEN_BPM)])
    assert span is None
    assert skip is not None
    assert "no bar-1 row" in skip


def test_span_runs_on_a_trailing_linear_segment():
    """A `linear` ramp on the LAST segment has no successor to glide toward, so
    it holds — the same reading BeatSampleMap documents."""
    declared = 40.0
    capture = _span_capture(
        declared_beats=declared, captured_seconds=declared * 60 / ALIEN_BPM
    )
    span, skip = measure_capture_span(
        capture, [TempoSegment(0.0, ALIEN_BPM, "linear")]
    )
    assert skip is None
    assert span is not None
    assert span.within_tolerance


def test_span_flags_a_capture_SHORTER_than_its_declared_span():
    """A truncated render is the same defect from the other end, and at least as
    likely as an overrun. `excess_beats` is signed and the tolerance symmetric,
    so this path exists — but a sign or wording inversion would reach an operator
    as a summary naming the wrong direction while the numbers say the opposite."""
    declared = 515.0
    short_s = declared * 60 / ALIEN_BPM - 60 / ALIEN_BPM  # one beat short
    capture = _span_capture(declared_beats=declared, captured_seconds=short_s)
    span, skip = measure_capture_span(capture, [TempoSegment(0.0, ALIEN_BPM)])
    assert skip is None
    assert span is not None
    assert span.excess_beats == pytest.approx(-1.0, abs=0.01)
    assert not span.within_tolerance
    assert "1.00 beats shorter than" in span.human_summary
