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
    Finding,
    LoudnessMetrics,
    MasterOvershoot,
    MixReport,
    ReverbVerification,
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
                dry_track_id="track:4",
                wet_return_track_id="return:1",
                declared_rt60_s=1.2,
                measured_rt60_s=1.18,
                within_tolerance=True,
                tolerance_s=0.15,
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
    assert deserialized["reverb_verifications"][0]["within_tolerance"] is True
    assert deserialized["findings"][0]["kind"] == "master_overshoot"
    assert deserialized["compare_to"] is None  # reserved skeleton


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
