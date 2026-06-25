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
    BedMasking,
    EnergyInversion,
    EnergyRealization,
    EnvelopeVerification,
    Finding,
    LoudnessMetrics,
    MaskingPair,
    MasterOvershoot,
    MixReport,
    PartCrossRhythm,
    Polymeter,
    ReverbVerification,
    SectionEnergy,
    SectionMetrics,
    StemMetrics,
    TimbreMetrics,
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
    assert deserialized["compare_to"] is None  # no baseline requested


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
    # No section_id supplied (hand-built fixture) → serializes as null, not absent.
    assert section["section_id"] is None
    assert section["start_beat"] == 32.0
    assert section["end_beat"] == 48.0
    assert section["master"]["surface_kind"] == "master"
    assert section["stems"][0]["track_id"] == "track:1"
    assert section["returns"][0]["track_id"] == "return:1"


def test_masking_entries_carry_resolved_surface_names_and_section_id():
    """AUD-2N6K: masking / bed_masking entries serialize resolved display names
    beside the raw track ids (joined from the report's surfaces), and a
    DB-identified section carries its ``section_id`` through to JSON."""
    drums = StemMetrics(
        track_id="track:4", surface_kind="track",
        surface_name="04 Drums", loudness=_make_loudness(),
    )
    bass = StemMetrics(
        track_id="track:9", surface_kind="track",
        surface_name="09 Bass", loudness=_make_loudness(),
    )
    report = MixReport(
        song_slug="s",
        captures_dir="/x",
        captured_at="20260528T120000Z",
        analyzer_signature="hallucinote-analyzer-v1",
        stems=[drums, bass],
        master=_make_stem("master"),
        per_section=[
            SectionMetrics(
                section_name="breathe1",
                section_id="sec-7f3a",
                start_beat=32.0,
                end_beat=165.0,
                master=_make_stem("master"),
                stems=[drums, bass],
                masking=[
                    MaskingPair(
                        masker_track_id="track:4",
                        maskee_track_id="track:9",
                        masked_fraction=0.893,
                        dominant_band="mud (250-500)",
                        dominant_region_hz=(200.0, 300.0),
                    )
                ],
                bed_masking=[
                    BedMasking(
                        maskee_track_id="track:9",
                        masked_fraction=0.61,
                        dominant_band="lows",
                        dominant_region_hz=(80.0, 250.0),
                    )
                ],
            )
        ],
    )
    section = json.loads(json.dumps(report.to_json_dict()))["per_section"][0]

    assert section["section_id"] == "sec-7f3a"

    m = section["masking"][0]
    # Raw ids preserved (programmatic use) ...
    assert m["masker_track_id"] == "track:4"
    assert m["maskee_track_id"] == "track:9"
    # ... and resolved names added beside them (narrative use, no manual join).
    assert m["masker_surface_name"] == "04 Drums"
    assert m["maskee_surface_name"] == "09 Bass"

    b = section["bed_masking"][0]
    assert b["maskee_track_id"] == "track:9"
    assert b["maskee_surface_name"] == "09 Bass"


def test_masking_surface_name_is_none_for_unknown_track():
    """A masking id that isn't a captured surface resolves to None (honest) —
    the raw id is still present, so a consumer can fall back to it."""
    report = MixReport(
        song_slug="s",
        captures_dir="/x",
        captured_at="20260528T120000Z",
        analyzer_signature="hallucinote-analyzer-v1",
        stems=[_make_stem("track:1")],
        master=_make_stem("master"),
        per_section=[
            SectionMetrics(
                section_name="verse",
                start_beat=0.0,
                end_beat=16.0,
                master=_make_stem("master"),
                stems=[_make_stem("track:1")],
                masking=[
                    MaskingPair(
                        masker_track_id="track:1",
                        maskee_track_id="track:404",  # not in surfaces
                        masked_fraction=0.5,
                        dominant_band="body",
                        dominant_region_hz=(400.0, 800.0),
                    )
                ],
            )
        ],
    )
    m = report.to_json_dict()["per_section"][0]["masking"][0]
    assert m["masker_surface_name"] == "01 Drums"  # track:1 via _make_stem
    assert m["maskee_surface_name"] is None
    assert m["maskee_track_id"] == "track:404"


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


def test_energy_realization_defaults_to_none():
    """A report constructed without an energy read serializes energy_realization
    as null (the field defaults None) — synthetic-fixture callers unaffected."""
    report = MixReport(
        song_slug="x", captures_dir="/tmp/x", captured_at="20260528T120000Z",
        analyzer_signature="sig", stems=[_make_stem()],
        master=_make_stem(track_id="master"),
    )
    out = report.to_json_dict()
    assert "energy_realization" in out
    assert out["energy_realization"] is None
    # Round-trips through strict JSON (allow_nan=False) — the B1 backstop.
    json.loads(json.dumps(out, allow_nan=False))


def test_energy_realization_serializes_with_none_rho_and_inversion():
    """A populated energy_realization (one None ρ + one inversion + ranked
    curve) round-trips through json.dumps(allow_nan=False) — None → null, never
    nan; the inversion carries start_beats."""
    er = EnergyRealization(
        correlate_rho={"loudness": -0.5, "onset_density": None},
        inversions=[EnergyInversion(
            higher_energy_start_beat=32.0, higher_energy_section="Chorus",
            lower_energy_start_beat=16.0, lower_energy_section="Verse",
            declared_energy_delta=0.3, correlate="loudness",
            measured_higher=-14.0, measured_lower=-10.0, measured_delta=-4.0,
        )],
        sections_ranked=[
            SectionEnergy(start_beat=16.0, name="Verse", energy=0.6),
            SectionEnergy(start_beat=32.0, name="Chorus", energy=0.9),
        ],
        skipped=["onset_density ρ undefined: measured values tied/constant"],
    )
    report = MixReport(
        song_slug="x", captures_dir="/tmp/x", captured_at="20260528T120000Z",
        analyzer_signature="sig", stems=[_make_stem()],
        master=_make_stem(track_id="master"), energy_realization=er,
    )
    out = json.loads(json.dumps(report.to_json_dict(), allow_nan=False))
    e = out["energy_realization"]
    assert e["correlate_rho"] == {"loudness": -0.5, "onset_density": None}
    assert e["inversions"][0]["higher_energy_start_beat"] == 32.0
    assert e["inversions"][0]["measured_delta"] == -4.0
    assert [s["energy"] for s in e["sections_ranked"]] == [0.6, 0.9]
    assert e["skipped"] == [
        "onset_density ρ undefined: measured values tied/constant"
    ]


def test_nonfinite_sentinels_serialize_as_null_under_allow_nan_false():
    """The B1 backstop's structural completion: the report's deliberate
    non-finite SENTINELS — an insufficient-tail RT60 (NaN), an unmeasurable
    automation change (NaN), a silent-stem -inf LUFS — serialize as JSON null,
    so the whole report is valid JSON under json.dumps(allow_nan=False). A bare
    NaN/Infinity token would crash strict consumers (the bug B1 surfaced)."""
    silent = LoudnessMetrics(
        lufs_i=float("-inf"), lufs_s_median=float("-inf"),
        lufs_m_peak=float("-inf"), true_peak_dbtp=float("-inf"),
    )
    report = MixReport(
        song_slug="x", captures_dir="/tmp/x", captured_at="20260528T120000Z",
        analyzer_signature="sig",
        stems=[StemMetrics("track:1", "track", "Silent", silent)],
        master=_make_stem(track_id="master"),
        reverb_verifications=[ReverbVerification(
            return_track_id="return:1", declared_rt60_s=0.8,
            measured_rt60_s=float("nan"), within_tolerance=False,
            tolerance_s=0.1, sufficient_tail=False,
        )],
        automation_verifications=[EnvelopeVerification(
            target_surface_id="track:1", target_kind="mixer_volume",
            parameter_path=None, at_beat=4.0, metric="rms_db",
            before=float("nan"), after=float("nan"),
            measurable=False, realized=False, note="post-fader, unverifiable",
        )],
    )
    # MUST NOT raise — every non-finite field went through _finite_or_none.
    parsed = json.loads(json.dumps(report.to_json_dict(), allow_nan=False))
    assert parsed["stems"][0]["loudness"]["lufs_i"] is None
    assert parsed["reverb_verifications"][0]["measured_rt60_s"] is None
    assert parsed["automation_verifications"][0]["before"] is None
    assert parsed["automation_verifications"][0]["after"] is None


def test_timbre_serializes_when_present_and_is_null_when_absent():
    """AUD-8T3K: a populated stem carries the timbre object; a stem without a
    measured timbre (the default-None fixture path) serializes ``timbre: null``."""
    with_timbre = StemMetrics(
        "track:1", "track", "Drums", _make_loudness(),
        timbre=TimbreMetrics(
            spectral_centroid_hz=1820.0, spectral_flatness=0.42,
            spectral_rolloff_hz=4100.0,
        ),
    )
    without = StemMetrics("track:2", "track", "Pad", _make_loudness())  # timbre defaults None
    report = MixReport(
        song_slug="x", captures_dir="/tmp/x", captured_at="20260528T120000Z",
        analyzer_signature="sig",
        stems=[with_timbre, without], master=_make_stem(track_id="master"),
    )
    parsed = json.loads(json.dumps(report.to_json_dict(), allow_nan=False))
    t = parsed["stems"][0]["timbre"]
    assert t == {
        "spectral_centroid_hz": 1820.0,
        "spectral_flatness": 0.42,
        "spectral_rolloff_hz": 4100.0,
    }
    assert parsed["stems"][1]["timbre"] is None


def test_timbre_nan_sentinel_serializes_as_null():
    """A silent surface measures an all-NaN TimbreMetrics; each field collapses
    to JSON null via _finite_or_none, like the loudness -inf sentinel."""
    nan = float("nan")
    report = MixReport(
        song_slug="x", captures_dir="/tmp/x", captured_at="20260528T120000Z",
        analyzer_signature="sig",
        stems=[StemMetrics(
            "track:1", "track", "Silent", _make_loudness(),
            timbre=TimbreMetrics(nan, nan, nan),
        )],
        master=_make_stem(track_id="master"),
    )
    parsed = json.loads(json.dumps(report.to_json_dict(), allow_nan=False))
    assert parsed["stems"][0]["timbre"] == {
        "spectral_centroid_hz": None,
        "spectral_flatness": None,
        "spectral_rolloff_hz": None,
    }


def test_master_fader_fields_default_none_and_serialize():
    """MASTER-PREFADER-TP: the delivered (post-fader) true-peak fields default to
    None (master block = pre-fader bus only) and round-trip when populated."""
    report = MixReport(
        song_slug="x", captures_dir="/tmp/x", captured_at="20260528T120000Z",
        analyzer_signature="sig",
        stems=[_make_stem()],
        master=_make_stem(track_id="master"),
    )
    default = report.to_json_dict()
    assert default["master_fader_volume"] is None
    assert default["master_fader_db"] is None
    assert default["delivered_true_peak_dbtp"] is None

    populated = MixReport(
        song_slug="x", captures_dir="/tmp/x", captured_at="20260528T120000Z",
        analyzer_signature="sig",
        stems=[_make_stem()],
        master=_make_stem(track_id="master"),
        master_fader_volume=0.70,
        master_fader_db=-3.5,
        delivered_true_peak_dbtp=-4.5,
    )
    out = json.loads(json.dumps(populated.to_json_dict(), allow_nan=False))
    assert out["master_fader_volume"] == 0.70
    assert out["master_fader_db"] == -3.5
    assert out["delivered_true_peak_dbtp"] == -4.5


def test_muted_master_fader_db_serializes_as_null():
    """A muted master (volume 0) gives master_fader_db = -inf and a delivered
    peak of -inf; both must serialize as null, not crash allow_nan=False."""
    report = MixReport(
        song_slug="x", captures_dir="/tmp/x", captured_at="20260528T120000Z",
        analyzer_signature="sig",
        stems=[_make_stem()],
        master=_make_stem(track_id="master"),
        master_fader_volume=0.0,
        master_fader_db=float("-inf"),
        delivered_true_peak_dbtp=float("-inf"),
    )
    parsed = json.loads(json.dumps(report.to_json_dict(), allow_nan=False))
    assert parsed["master_fader_volume"] == 0.0
    assert parsed["master_fader_db"] is None
    assert parsed["delivered_true_peak_dbtp"] is None


def test_compare_to_defaults_none_and_serializes_when_populated():
    """``compare_to`` is None when no baseline was requested, and passes
    through serialization verbatim when ``analyze_mix(compare_to=...)``
    populated it (the payload is built by ``compare.diff_reports``, which
    is already JSON-shaped — no re-encoding at this boundary)."""
    report = MixReport(
        song_slug="s",
        captures_dir="/x",
        captured_at="20260528T120000Z",
        analyzer_signature="hallucinote-analyzer-v1",
        stems=[],
        master=_make_stem("master"),
    )
    assert report.compare_to is None
    assert report.to_json_dict()["compare_to"] is None

    report.compare_to = {
        "baseline": {"ref": "/songs/s/analysis/a.json"},
        "deltas": [],
        "overshoot_count": {"before": 0, "after": 0, "delta": 0,
                            "significant": False},
        "added_surfaces": [],
        "missing_surfaces": [],
    }
    out = json.loads(json.dumps(report.to_json_dict(), allow_nan=False))
    assert out["compare_to"]["baseline"]["ref"] == "/songs/s/analysis/a.json"


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


def test_db_seq_serializes_and_defaults_none():
    """db_seq (the capture's audit-log provenance, AUD-4W7K) rides the
    report verbatim; None for pre-tagging captures."""
    report = MixReport(
        song_slug="s",
        captures_dir="/x",
        captured_at="20260528T120000Z",
        analyzer_signature="hallucinote-analyzer-v1",
        stems=[],
        master=_make_stem("master"),
    )
    assert report.to_json_dict()["db_seq"] is None
    report.db_seq = 4823
    assert report.to_json_dict()["db_seq"] == 4823
