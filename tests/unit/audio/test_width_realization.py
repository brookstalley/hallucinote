"""Declared width controls joined against measured image (STR-4C8N A3).

The join is the point: catching a width control that does nothing needs BOTH the
declaration and the rendered audio, which is why no DAW reports it.
"""
from __future__ import annotations

from hallucinote.audio.analyze import DeclaredWidthControl, _realize_widths
from hallucinote.audio.report import LoudnessMetrics, StemMetrics, StereoMetrics


def _stem(track_id: str, name: str, corr: float, loss: float) -> StemMetrics:
    return StemMetrics(
        track_id=track_id,
        surface_kind="track",
        surface_name=name,
        loudness=LoudnessMetrics(
            lufs_i=-20.0, lufs_s_median=-20.0, lufs_m_peak=-18.0, true_peak_dbtp=-3.0
        ),
        stereo=StereoMetrics(correlation=corr, mono_sum_loss_db=loss),
    )


def _control(surface: str, declared: str) -> DeclaredWidthControl:
    return DeclaredWidthControl(
        surface_id=surface,
        device_name="Utility",
        parameter_name="Stereo Width",
        declared_display=declared,
    )


def test_no_op_and_real_width_are_both_representable():
    """The two rows that made the case on the-argument: the most aggressive
    declared setting producing the least effect, beside a milder one doing real
    work. No threshold is applied — the PAIRING is the evidence."""
    stems = [
        _stem("track:9", "Drone", 0.896, -0.23),
        _stem("track:6", "Brass Section", 0.035, -2.86),
    ]
    declared = [_control("track:9", "165 %"), _control("track:6", "125 %")]

    realizations, skipped = _realize_widths(declared, stems)

    assert skipped == []
    by_name = {r.surface_name: r for r in realizations}
    # The no-op: highest declared value, lowest measured effect.
    assert by_name["Drone"].declared_display == "165 %"
    assert by_name["Drone"].mono_sum_loss_db > -1.0
    # Real width, from a lower declared setting.
    assert by_name["Brass Section"].declared_display == "125 %"
    assert by_name["Brass Section"].mono_sum_loss_db < -2.0


def test_no_declared_controls_is_recorded_not_silently_absent():
    realizations, skipped = _realize_widths([], [_stem("track:1", "Drums", 0.8, -0.5)])
    assert realizations == []
    assert len(skipped) == 1
    assert skipped[0]["kind"] == "width_realization"
    assert "no declared width controls" in skipped[0]["reason"]


def test_declared_control_on_an_uncaptured_surface_is_reported_not_dropped():
    """A declaration we cannot check must say so — silently omitting it would
    read as 'nothing declared', which is a different and wrong statement."""
    realizations, skipped = _realize_widths(
        [_control("track:42", "150 %")], [_stem("track:1", "Drums", 0.8, -0.5)]
    )
    assert realizations == []
    assert len(skipped) == 1
    assert "track:42" in skipped[0]["reason"]


def test_stem_without_measured_stereo_is_skipped_not_guessed():
    stem = StemMetrics(
        track_id="track:1",
        surface_kind="track",
        surface_name="Drums",
        loudness=LoudnessMetrics(
            lufs_i=-20.0, lufs_s_median=-20.0, lufs_m_peak=-18.0, true_peak_dbtp=-3.0
        ),
        stereo=None,
    )
    realizations, skipped = _realize_widths([_control("track:1", "150 %")], [stem])
    assert realizations == []
    assert len(skipped) == 1
