"""MixReport schema round-trip + invariant tests.

The MixReport is the analysis pipeline's wire-format. Stability of
``schema_version`` and field shape matters more than the numbers — those
are pinned by the loudness / attribution / reverb tests. These tests
pin the *shape* the agent and any future consumers will see.
"""
from __future__ import annotations

import json

import pytest

from hallucinote.audio.report import (
    EnvelopeVerification,
    Finding,
    LoudnessMetrics,
    MasterOvershoot,
    MixReport,
    PartCrossRhythm,
    Polymeter,
    ReverbVerification,
    SectionMetrics,
    StemMetrics,
)


def _make_loudness(*, lufs_i: float = -23.0) -> LoudnessMetrics:
    return LoudnessMetrics(
        lufs_i=lufs_i,
        lufs_s_median=lufs_i + 0.2,
        lufs_m_peak=lufs_i + 2.0,
        true_peak_dbtp=-1.0,
    )


def _make_stem(track_id: str = "track:1") -> StemMetrics:
    return StemMetrics(
        track_id=track_id,
        surface_kind="track",
        surface_name="01 Drums",
        loudness=_make_loudness(),
    )


def test_schema_version_is_pinned():
    report = MixReport(
        song_slug="test-song",
        captures_dir="/tmp/x",
        captured_at="20260528T120000Z",
        analyzer_signature="hallucinote-analyzer-v1",
        stems=[_make_stem()],
        master=_make_stem(track_id="master"),
    )
    assert report.schema_version == "1"


def test_to_json_dict_round_trips_through_json():
    report = MixReport(
        song_slug="reggae-metal",
        captures_dir="/Users/x/songs/reggae-metal/captures/20260527T200614Z",
        captured_at="20260527T200657Z",
        analyzer_signature="hallucinote-analyzer-v1",
        stems=[_make_stem("track:1"), _make_stem("track:2")],
        returns=[_make_stem("return:1")],
        master=_make_stem("master"),
        overshoots=[
            MasterOvershoot(
                start_beat=32.0,
                end_beat=40.0,
                peak_dbtp=1.2,
                dominant_band="low_60_200",
                attribution=[("track:1", 0.41), ("track:2", 0.33)],
            )
        ],
        reverb_verifications=[
            ReverbVerification(
                return_track_id="return:1",
                declared_rt60_s=1.2,
                measured_rt60_s=1.18,
                within_tolerance=True,
                tolerance_s=0.15,
                tail_span_db=58.0,
                contributing_track_ids=("track:1", "track:4"),
            )
        ],
        automation_verifications=[
            EnvelopeVerification(
                target_surface_id="track:3",
                target_kind="device_parameter",
                parameter_path="Amp Type",
                at_beat=128.0,
                metric="spectral_centroid_hz",
                before=1240.0,
                after=1880.0,
                measurable=True,
                realized=True,
                note="timbre shift realized",
            )
        ],
        findings=[
            Finding(
                kind="master_overshoot",
                severity="warning",
                subject="master",
                metric="peak_dbtp",
                observed=1.2,
                expected=0.0,
                db_reference="cue:chorus-1",
            )
        ],
    )

    as_dict = report.to_json_dict()
    serialized = json.dumps(as_dict)
    deserialized = json.loads(serialized)

    assert deserialized["schema_version"] == "1"
    assert deserialized["song_slug"] == "reggae-metal"
    assert len(deserialized["stems"]) == 2
    assert deserialized["overshoots"][0]["attribution"][0] == ["track:1", 0.41]
    rv = deserialized["reverb_verifications"][0]
    assert rv["within_tolerance"] is True
    assert rv["return_track_id"] == "return:1"  # per-return, not per (dry,wet) pair
    assert rv["measurement_method"] == "decay_tail"
    assert rv["contributing_track_ids"] == ["track:1", "track:4"]
    assert rv["sufficient_tail"] is True
    av = deserialized["automation_verifications"][0]
    assert av["target_surface_id"] == "track:3"
    assert av["target_kind"] == "device_parameter"
    assert av["metric"] == "spectral_centroid_hz"
    assert av["measurable"] is True and av["realized"] is True
    assert deserialized["findings"][0]["kind"] == "master_overshoot"
    assert deserialized["compare_to"] is None  # reserved skeleton


def test_per_section_serializes_with_scoped_surfaces():
    """per_section mirrors the top-level master/stems/returns shape, scoped
    to a named beat window — round-trips through JSON as nested dicts."""
    report = MixReport(
        song_slug="s",
        captures_dir="/x",
        captured_at="20260528T120000Z",
        analyzer_signature="hallucinote-analyzer-v1",
        stems=[_make_stem("track:1")],
        master=_make_stem("master"),
        per_section=[
            SectionMetrics(
                section_name="chorus1",
                start_beat=32.0,
                end_beat=48.0,
                master=StemMetrics(
                    track_id="master",
                    surface_kind="master",
                    surface_name="Main",
                    loudness=_make_loudness(),
                ),
                stems=[_make_stem("track:1")],
                returns=[_make_stem("return:1")],
            )
        ],
    )
    out = report.to_json_dict()
    serialized = json.loads(json.dumps(out))
    section = serialized["per_section"][0]
    assert section["section_name"] == "chorus1"
    assert section["start_beat"] == 32.0
    assert section["end_beat"] == 48.0
    assert section["master"]["surface_kind"] == "master"
    assert section["stems"][0]["track_id"] == "track:1"
    assert section["returns"][0]["track_id"] == "return:1"


def test_additive_grouping_and_polymeter_serialize():
    """The C8c fields — an `additive` cross-rhythm's `grouping` /
    `cycle_length_beats` and a `Polymeter` pair — round-trip through JSON.
    Locks the new wire contract (the agent/mix-review read these keys)."""
    report = MixReport(
        song_slug="s",
        captures_dir="/x",
        captured_at="20260528T120000Z",
        analyzer_signature="hallucinote-analyzer-v1",
        stems=[_make_stem("track:1")],
        master=_make_stem("master"),
        per_section=[
            SectionMetrics(
                section_name="A",
                start_beat=0.0,
                end_beat=16.0,
                master=_make_stem("master"),
                cross_rhythm=[
                    PartCrossRhythm(
                        track_id="track:1",
                        pulse_ratio=None,
                        against_meter=True,
                        base_period_beats=1.5,
                        occupancy=1.0,
                        confidence=0.9,
                        verdict="additive",
                        grouping=(3, 3, 2),
                        cycle_length_beats=4.0,
                    )
                ],
                polymeter=[
                    Polymeter(
                        track_a="track:1",
                        track_b="track:2",
                        cycle_a_beats=4.0,
                        cycle_b_beats=3.0,
                        realign_beats=12.0,
                        confidence=0.7,
                    )
                ],
            )
        ],
    )
    section = json.loads(json.dumps(report.to_json_dict()))["per_section"][0]
    cr = section["cross_rhythm"][0]
    assert cr["verdict"] == "additive"
    assert cr["grouping"] == [3, 3, 2]  # tuple → list through JSON
    assert cr["cycle_length_beats"] == 4.0
    pm = section["polymeter"][0]
    assert pm["cycle_a_beats"] == 4.0 and pm["cycle_b_beats"] == 3.0
    assert pm["realign_beats"] == 12.0


def test_non_additive_cross_rhythm_has_null_grouping():
    """A plain subdivision serializes grouping/cycle_length_beats as null."""
    cr = PartCrossRhythm(
        track_id="track:1", pulse_ratio="2/beat", against_meter=False,
        base_period_beats=0.5, occupancy=1.0, confidence=0.95,
        verdict="subdivision",
    )
    from hallucinote.audio.report import _part_cross_rhythm_to_dict
    d = json.loads(json.dumps(_part_cross_rhythm_to_dict(cr)))
    assert d["grouping"] is None
    assert d["cycle_length_beats"] is None


def test_per_section_defaults_empty():
    report = MixReport(
        song_slug="s",
        captures_dir="/x",
        captured_at="20260528T120000Z",
        analyzer_signature="hallucinote-analyzer-v1",
        stems=[],
        master=_make_stem("master"),
    )
    assert report.per_section == []
    assert report.to_json_dict()["per_section"] == []


def test_compare_to_field_is_reserved_skeleton():
    report = MixReport(
        song_slug="s",
        captures_dir="/x",
        captured_at="20260528T120000Z",
        analyzer_signature="hallucinote-analyzer-v1",
        stems=[],
        master=_make_stem("master"),
    )
    # Reserved per spike §9 — implementation deferred to P2 backlog.
    assert report.compare_to is None
    assert "compare_to" in report.to_json_dict()


def test_skipped_analyses_records_dropped_work():
    """Per CLAUDE.md "Never silently drop a requirement" — when a declared
    requirement (e.g. reverb verification on a song with no declared decay
    times) can't be evaluated, the report carries an explicit skip record
    rather than emitting an empty section."""
    report = MixReport(
        song_slug="s",
        captures_dir="/x",
        captured_at="20260528T120000Z",
        analyzer_signature="hallucinote-analyzer-v1",
        stems=[],
        master=_make_stem("master"),
        skipped_analyses=[
            {"kind": "reverb_verification",
             "reason": "no declared decay times in song DB"},
        ],
    )
    out = report.to_json_dict()
    assert out["skipped_analyses"][0]["kind"] == "reverb_verification"


def test_finding_severity_is_validated():
    with pytest.raises(ValueError, match="severity"):
        Finding(
            kind="x",
            severity="catastrophe",  # not a real severity
            subject="master",
            metric="peak",
            observed=1.0,
            expected=0.0,
        )


def test_stem_metrics_surface_kind_is_validated():
    with pytest.raises(ValueError, match="surface_kind"):
        StemMetrics(
            track_id="x:1",
            surface_kind="bogus",  # only track | return | master
            surface_name="X",
            loudness=_make_loudness(),
        )
