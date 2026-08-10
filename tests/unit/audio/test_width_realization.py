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


def test_width_control_on_a_return_is_joined_not_reported_unmeasurable():
    """A width control on a reverb/delay bus is an ordinary move.

    The join receives tracks AND returns; a version that saw only tracks would
    report such a control as unmeasurable when its audio was captured all along.
    """
    surfaces = [
        _stem("track:1", "Drums", 0.8, -0.5),
        StemMetrics(
            track_id="return:2",
            surface_kind="return",
            surface_name="B-Room",
            loudness=LoudnessMetrics(
                lufs_i=-30.0, lufs_s_median=-30.0, lufs_m_peak=-28.0,
                true_peak_dbtp=-12.0,
            ),
            stereo=StereoMetrics(correlation=0.407, mono_sum_loss_db=-1.9),
        ),
    ]
    realizations, skipped = _realize_widths(
        [_control("return:2", "140 %")], surfaces
    )
    assert skipped == []
    assert len(realizations) == 1
    assert realizations[0].surface_name == "B-Room"
    assert realizations[0].mono_sum_loss_db == -1.9


# ---------------------------------------------------------------------------
# Serialization. The handler dumps with allow_nan=False, so an un-collapsed NaN
# is a hard failure at write time rather than a bad number in the file — and the
# populated branch of both new blocks was previously unexercised.
# ---------------------------------------------------------------------------


def test_stereo_and_width_blocks_serialize_and_survive_allow_nan_false():
    import json

    from hallucinote.audio.report import MixReport, WidthRealization

    report = MixReport(
        song_slug="s",
        captures_dir="captures/x",
        captured_at="20260810T000000Z",
        analyzer_signature="sig",
        master=_stem("master", "Main", 0.5, -1.2),
        stems=[
            _stem("track:1", "Wide", 0.2, -2.5),
            # NaN is the unmeasurable sentinel — it MUST collapse to null.
            _stem("track:2", "Silent", float("nan"), float("nan")),
        ],
        width_realizations=[
            WidthRealization(
                surface_id="track:1",
                surface_name="Wide",
                device_name="Utility",
                parameter_name="Stereo Width",
                declared_display="150 %",
                correlation=0.2,
                mono_sum_loss_db=-2.5,
            ),
            WidthRealization(
                surface_id="track:2",
                surface_name="Silent",
                device_name="Utility",
                parameter_name="Stereo Width",
                declared_display="150 %",
                correlation=float("nan"),
                mono_sum_loss_db=float("nan"),
            ),
        ],
    )

    payload = report.to_json_dict()
    # The whole point of the sentinel contract: this raises on a stray NaN.
    text = json.dumps(payload, allow_nan=False)
    round_tripped = json.loads(text)

    wide, silent = round_tripped["stems"]
    assert wide["stereo"] == {"correlation": 0.2, "mono_sum_loss_db": -2.5}
    assert silent["stereo"] == {"correlation": None, "mono_sum_loss_db": None}

    w_wide, w_silent = round_tripped["width_realizations"]
    assert w_wide["declared_display"] == "150 %"
    assert w_wide["mono_sum_loss_db"] == -2.5
    assert w_silent["correlation"] is None
    assert w_silent["mono_sum_loss_db"] is None


def test_stem_without_stereo_serializes_as_null_block():
    """Hand-built fixtures and pre-stereo baselines must stay valid."""
    from hallucinote.audio.report import LoudnessMetrics as _L
    from hallucinote.audio.report import MixReport, StemMetrics as _S

    stem = _S(
        track_id="track:1",
        surface_kind="track",
        surface_name="Drums",
        loudness=_L(
            lufs_i=-20.0, lufs_s_median=-20.0, lufs_m_peak=-18.0, true_peak_dbtp=-3.0
        ),
    )
    report = MixReport(
        song_slug="s",
        captures_dir="captures/x",
        captured_at="20260810T000000Z",
        analyzer_signature="sig",
        master=stem,
        stems=[stem],
    )
    payload = report.to_json_dict()
    assert payload["stems"][0]["stereo"] is None
    assert payload["width_realizations"] == []
