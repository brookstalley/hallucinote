"""Unit tests for ``compare.diff_reports`` — MixReport baseline diffs.

Pure-dict tests: both sides are ``to_json_dict()``-shaped dicts built by
hand, because the JSON schema (not the dataclass) is the diff contract.
Thresholds are imported from the module — they are the single source of
truth the calibration evidence froze (see compare.py docstring).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hallucinote.audio.compare import (
    SIGNIFICANCE_DB,
    SIGNIFICANCE_DEFAULT_DB,
    SIGNIFICANCE_SHORT_TERM_DB,
    diff_reports,
)


def _loudness(
    lufs_i: float | None = -14.0,
    lufs_s_median: float | None = -13.0,
    lufs_m_peak: float | None = -10.0,
    true_peak_dbtp: float | None = -1.2,
) -> dict:
    return {
        "lufs_i": lufs_i,
        "lufs_s_median": lufs_s_median,
        "lufs_m_peak": lufs_m_peak,
        "true_peak_dbtp": true_peak_dbtp,
    }


def _timbre(
    spectral_centroid_hz: float | None = 1500.0,
    spectral_flatness: float | None = 0.1,
    spectral_rolloff_hz: float | None = 3000.0,
    sharpness_acum: float | None = 1.5,
) -> dict:
    return {
        "spectral_centroid_hz": spectral_centroid_hz,
        "spectral_flatness": spectral_flatness,
        "spectral_rolloff_hz": spectral_rolloff_hz,
        "sharpness_acum": sharpness_acum,
    }


def _stereo(
    correlation: float | None = 0.5,
    mono_sum_loss_db: float | None = -1.0,
) -> dict:
    return {
        "correlation": correlation,
        "mono_sum_loss_db": mono_sum_loss_db,
    }


_DEFAULT_TIMBRE = object()
_DEFAULT_STEREO = object()


def _surface(
    track_id: str,
    kind: str = "track",
    name: str = "x",
    *,
    timbre: object = _DEFAULT_TIMBRE,
    stereo: object = _DEFAULT_STEREO,
    **loudness,
) -> dict:
    return {
        "track_id": track_id,
        "surface_kind": kind,
        "surface_name": name,
        "loudness": _loudness(**loudness),
        # ``timbre=None`` models a silent stem (null) or a pre-timbre baseline.
        "timbre": _timbre() if timbre is _DEFAULT_TIMBRE else timbre,
        # ``stereo=None`` likewise models an unmeasurable stem or a pre-stereo
        # baseline — the diff must yield a null delta there, never a fabricated 0.
        "stereo": _stereo() if stereo is _DEFAULT_STEREO else stereo,
    }


def _report(
    *,
    stems: list[dict] | None = None,
    returns: list[dict] | None = None,
    master: dict | None = None,
    overshoots: list | None = None,
    song_slug: str = "test-song",
    schema_version: str = "1",
) -> dict:
    return {
        "schema_version": schema_version,
        "song_slug": song_slug,
        "captured_at": "20260610T120000Z",
        "analyzer_signature": "hallucinote-analyzer-v1",
        "master": master or _surface("master", "master", "Main"),
        "stems": stems if stems is not None else [],
        "returns": returns if returns is not None else [],
        "overshoots": overshoots if overshoots is not None else [],
    }


def test_identical_reports_diff_to_zero_and_insignificant():
    a = _report(stems=[_surface("track:1")])
    b = _report(stems=[_surface("track:1")])
    out = diff_reports(a, b)
    assert out["added_surfaces"] == [] and out["missing_surfaces"] == []
    assert out["overshoot_count"] == {
        "before": 0, "after": 0, "delta": 0, "significant": False,
    }
    # master + track:1, each with 4 loudness + 4 timbre + 2 stereo metrics
    assert len(out["deltas"]) == 20
    for row in out["deltas"]:
        assert row["delta"] == 0.0
        assert row["significant"] is False
    # Loudness deltas are calibrated; timbre and stereo deltas are provisional.
    by_metric = {r["metric"]: r for r in out["deltas"]}
    assert by_metric["lufs_i"]["provisional"] is False
    assert by_metric["mono_sum_loss_db"]["provisional"] is True
    assert by_metric["spectral_centroid_hz"]["provisional"] is True


def test_significant_master_move_is_flagged_with_correct_sign():
    baseline = _report()
    current = _report(master=_surface("master", "master", "Main", lufs_i=-14.6))
    row = _find(diff_reports(current, baseline), "master", "lufs_i")
    assert row["before"] == -14.0 and row["after"] == -14.6
    assert row["delta"] == pytest.approx(-0.6)
    assert row["significant"] is True


def test_sub_threshold_move_is_insignificant():
    baseline = _report()
    current = _report(master=_surface("master", "master", "Main", lufs_i=-14.1))
    row = _find(diff_reports(current, baseline), "master", "lufs_i")
    assert row["delta"] == pytest.approx(-0.1)
    assert row["significant"] is False


def test_short_term_median_carries_its_own_calibrated_threshold():
    """lufs_s_median wobbles ~0.6 dB between re-captures of the same mix
    (calibration evidence in compare.py) — 0.6 must NOT flag, 1.2 must."""
    assert SIGNIFICANCE_DB["lufs_s_median"] == SIGNIFICANCE_SHORT_TERM_DB
    assert SIGNIFICANCE_SHORT_TERM_DB > SIGNIFICANCE_DEFAULT_DB
    baseline = _report()
    wobble = _report(master=_surface("master", "master", "Main", lufs_s_median=-13.6))
    real = _report(master=_surface("master", "master", "Main", lufs_s_median=-14.2))
    assert _find(diff_reports(wobble, baseline), "master", "lufs_s_median")["significant"] is False
    assert _find(diff_reports(real, baseline), "master", "lufs_s_median")["significant"] is True


def test_added_and_missing_surfaces_never_misalign():
    baseline = _report(stems=[_surface("track:1"), _surface("track:2")])
    current = _report(stems=[_surface("track:1"), _surface("track:3")])
    out = diff_reports(current, baseline)
    assert out["added_surfaces"] == ["track:3"]
    assert out["missing_surfaces"] == ["track:2"]
    diffed_ids = {r["track_id"] for r in out["deltas"]}
    assert diffed_ids == {"master", "track:1"}


def test_returns_are_diffed_too():
    baseline = _report(returns=[_surface("return:1", "return", "A Reverb")])
    current = _report(
        returns=[_surface("return:1", "return", "A Reverb", true_peak_dbtp=-0.2)]
    )
    row = _find(diff_reports(current, baseline), "return:1", "true_peak_dbtp")
    assert row["surface_kind"] == "return"
    assert row["delta"] == pytest.approx(1.0)
    assert row["significant"] is True


def test_null_metric_on_either_side_yields_null_delta_never_a_crash():
    """The non-finite sentinel serializes as null (silent stem → -inf LUFS).
    A diff against it is honestly unmeasured, not a fabricated number."""
    baseline = _report(stems=[_surface("track:1", lufs_i=None)])
    current = _report(stems=[_surface("track:1")])
    row = _find(diff_reports(current, baseline), "track:1", "lufs_i")
    assert row["before"] is None
    assert row["delta"] is None
    assert row["significant"] is False


def test_timbre_move_beyond_provisional_floor_is_flagged_provisional():
    from hallucinote.audio.compare import SIGNIFICANCE_TIMBRE
    baseline = _report()
    current = _report(
        master=_surface(
            "master", "master", "Main",
            timbre=_timbre(spectral_centroid_hz=1700.0),  # +200 Hz > 50 Hz floor
        )
    )
    row = _find(diff_reports(current, baseline), "master", "spectral_centroid_hz")
    assert row["delta"] == pytest.approx(200.0)
    assert abs(row["delta"]) >= SIGNIFICANCE_TIMBRE["spectral_centroid_hz"]
    assert row["significant"] is True
    assert row["provisional"] is True   # never read as a calibrated verdict


def test_timbre_null_on_either_side_yields_null_delta():
    # A silent stem (timbre null) or a pre-timbre baseline diffs to an honest
    # null timbre delta — never a fabricated number, like the loudness path.
    baseline = _report(stems=[_surface("track:1", timbre=None)])
    current = _report(stems=[_surface("track:1")])
    row = _find(diff_reports(current, baseline), "track:1", "spectral_flatness")
    assert row["before"] is None
    assert row["delta"] is None
    assert row["significant"] is False


def test_stereo_null_on_either_side_yields_null_delta():
    # An unmeasurable stem (stereo null) or a PRE-STEREO baseline diffs to an
    # honest null — never a fabricated 0.0, which would read as "the image did
    # not change" when the truth is "one side never measured it".
    baseline = _report(stems=[_surface("track:1", stereo=None)])
    current = _report(stems=[_surface("track:1")])
    row = _find(diff_reports(current, baseline), "track:1", "mono_sum_loss_db")
    assert row["before"] is None
    assert row["delta"] is None
    assert row["significant"] is False


def test_stereo_move_is_flagged_provisional():
    # Reducing an over-wide element moved a real stem ~1 dB in mono-sum loss;
    # the diff must see it, and must mark it provisional (no jitter calibration).
    baseline = _report(stems=[_surface("track:1", stereo=_stereo(mono_sum_loss_db=-3.84))])
    current = _report(stems=[_surface("track:1", stereo=_stereo(mono_sum_loss_db=-2.86))])
    row = _find(diff_reports(current, baseline), "track:1", "mono_sum_loss_db")
    assert row["delta"] == pytest.approx(0.98)
    assert row["significant"] is True
    assert row["provisional"] is True


def test_overshoot_count_change_is_significant():
    baseline = _report(overshoots=[{"peak_dbtp": 0.4}])
    current = _report()
    out = diff_reports(current, baseline)
    assert out["overshoot_count"] == {
        "before": 1, "after": 0, "delta": -1, "significant": True,
    }


def test_schema_version_mismatch_refuses():
    with pytest.raises(ValueError, match="schema_version"):
        diff_reports(_report(), _report(schema_version="2"))


def test_cross_song_baseline_refuses():
    with pytest.raises(ValueError, match="cross-song"):
        diff_reports(_report(), _report(song_slug="other-song"))


def test_baseline_provenance_is_carried():
    out = diff_reports(_report(), _report(), baseline_ref="/songs/x/analysis/a.json")
    assert out["baseline"]["ref"] == "/songs/x/analysis/a.json"
    assert out["baseline"]["captured_at"] == "20260610T120000Z"
    assert out["baseline"]["analyzer_signature"] == "hallucinote-analyzer-v1"
    assert out["baseline"]["schema_version"] == "1"


def _find(out: dict, track_id: str, metric: str) -> dict:
    matches = [
        r for r in out["deltas"]
        if r["track_id"] == track_id and r["metric"] == metric
    ]
    assert len(matches) == 1, f"expected one row for {track_id}/{metric}"
    return matches[0]


# ---------------------------------------------------------------------------
# resolve_baseline — seq → analysis-JSON resolution
# ---------------------------------------------------------------------------


def _write_analysis(dir_: "Path", name: str, *, db_seq: int | None) -> "Path":
    import json
    dir_.mkdir(parents=True, exist_ok=True)
    payload = _report()
    payload["db_seq"] = db_seq
    path = dir_ / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_resolve_baseline_matches_seq(tmp_path):
    from hallucinote.audio.compare import resolve_baseline
    _write_analysis(tmp_path, "20260601T010000Z.json", db_seq=10)
    target = _write_analysis(tmp_path, "20260602T010000Z.json", db_seq=20)
    assert resolve_baseline(tmp_path, 20) == target


def test_resolve_baseline_tie_breaks_to_latest(tmp_path):
    """Same seq on several reports (re-analyses of one capture) → the
    newest wins; ISO filenames make lex order chronological."""
    from hallucinote.audio.compare import resolve_baseline
    _write_analysis(tmp_path, "20260601T010000Z.json", db_seq=10)
    latest = _write_analysis(tmp_path, "20260603T010000Z.json", db_seq=10)
    assert resolve_baseline(tmp_path, 10) == latest


def test_resolve_baseline_no_match_teaches_available_seqs(tmp_path):
    from hallucinote.audio.compare import resolve_baseline
    _write_analysis(tmp_path, "a.json", db_seq=10)
    _write_analysis(tmp_path, "b.json", db_seq=20)
    with pytest.raises(ValueError, match=r"db_seq=15.*\[10, 20\]"):
        resolve_baseline(tmp_path, 15)


def test_resolve_baseline_skips_pre_tagging_reports(tmp_path):
    """Reports with db_seq=null (pre-tagging) are never seq-matched —
    the teaching error points at the explicit-path fallback."""
    from hallucinote.audio.compare import resolve_baseline
    _write_analysis(tmp_path, "old.json", db_seq=None)
    with pytest.raises(ValueError, match="predate seq tagging"):
        resolve_baseline(tmp_path, 10)


def test_resolve_baseline_empty_dir_refuses(tmp_path):
    from hallucinote.audio.compare import resolve_baseline
    with pytest.raises(ValueError, match="no analysis reports"):
        resolve_baseline(tmp_path / "missing", 10)


def test_resolve_baseline_skips_corrupt_json(tmp_path):
    """An unreadable report can't be a baseline — the scan continues past
    it to a valid match instead of crashing."""
    from hallucinote.audio.compare import resolve_baseline
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "corrupt.json").write_text("{not json", encoding="utf-8")
    target = _write_analysis(tmp_path, "20260601T010000Z.json", db_seq=10)
    assert resolve_baseline(tmp_path, 10) == target


def test_resolve_baseline_skips_non_int_db_seq(tmp_path):
    """A malformed/hand-edited db_seq (string, bool) is never a seq key —
    skipped like None, not coerced (True must not match seq=1)."""
    from hallucinote.audio.compare import resolve_baseline
    _write_analysis(tmp_path, "stringseq.json", db_seq="10")
    _write_analysis(tmp_path, "boolseq.json", db_seq=True)
    target = _write_analysis(tmp_path, "20260601T010000Z.json", db_seq=10)
    assert resolve_baseline(tmp_path, 10) == target
    with pytest.raises(ValueError, match=r"db_seq=1;"):
        resolve_baseline(tmp_path, 1)


def _section(name, stems, transients=(), *, master=None, returns=()):
    sec = {"section_name": name, "stems": stems, "transients": list(transients),
           "returns": list(returns)}
    if master is not None:
        sec["master"] = master
    return sec


def _transient(track_id, **over):
    base = {"track_id": track_id, "hit_count": 16, "rise_ms": 16.0, "t20_ms": 164.0,
            "censored_rise_hits": 0, "censored_t20_hits": 0, "censored_attack_hits": 0,
            "attack_sub_40_100_db": -10.8, "attack_low_100_250_db": -6.9,
            "attack_lowmid_250_600_db": -19.2, "attack_click_2k_6k_db": -33.7,
            "click_minus_sub_db": -22.9, "low_minus_sub_db": 3.9}
    base.update(over)
    return base


def test_section_deltas_carry_per_section_timbre_and_transient_rows():
    base_sec = _section("chorus3", [_surface("track:4", timbre=_timbre(sharpness_acum=2.51))],
                        [_transient("track:1")])
    cur_sec = _section("chorus3", [_surface("track:4", timbre=_timbre(sharpness_acum=2.36))],
                       [_transient("track:1", click_minus_sub_db=-15.9, rise_ms=17.0)])
    baseline = _report()
    baseline["per_section"] = [base_sec]
    current = _report()
    current["per_section"] = [cur_sec]
    out = diff_reports(current, baseline)
    rows = {(r["section"], r["track_id"], r["metric"]): r for r in out["section_deltas"]}
    sharp = rows[("chorus3", "track:4", "sharpness_acum")]
    assert sharp["delta"] == pytest.approx(-0.15) and sharp["significant"] is True
    assert sharp["provisional"] is True
    click = rows[("chorus3", "track:1", "click_minus_sub_db")]
    assert click["delta"] == pytest.approx(7.0) and click["significant"] is True
    rise = rows[("chorus3", "track:1", "rise_ms")]
    assert rise["delta"] == pytest.approx(1.0) and rise["significant"] is False


def test_section_deltas_cover_the_master_and_returns_not_just_stems():
    """The per-section MASTER is the whole-mix read a de-shrill edit is judged
    on, and a return's timbre is how the send bus moved — both are measured per
    section, so both get an A/B row. Iterating stems alone left the surfaces
    carrying the section's summary with no row at all."""
    base_sec = _section(
        "chorus3", [_surface("track:4", timbre=_timbre(sharpness_acum=2.51))],
        master=_surface("master", timbre=_timbre(sharpness_acum=1.78)),
        returns=[_surface("return:1", timbre=_timbre(sharpness_acum=1.20))])
    cur_sec = _section(
        "chorus3", [_surface("track:4", timbre=_timbre(sharpness_acum=2.36))],
        master=_surface("master", timbre=_timbre(sharpness_acum=1.66)),
        returns=[_surface("return:1", timbre=_timbre(sharpness_acum=1.05))])
    baseline = _report()
    baseline["per_section"] = [base_sec]
    current = _report()
    current["per_section"] = [cur_sec]
    out = diff_reports(current, baseline)
    rows = {(r["section"], r["track_id"], r["metric"]): r for r in out["section_deltas"]}
    assert rows[("chorus3", "master", "sharpness_acum")]["delta"] == pytest.approx(-0.12)
    assert rows[("chorus3", "return:1", "sharpness_acum")]["delta"] == pytest.approx(-0.15)
    assert rows[("chorus3", "track:4", "sharpness_acum")]["delta"] == pytest.approx(-0.15)


def test_section_deltas_tolerate_a_section_with_no_master_or_returns():
    """Older reports (and any section the analyzer measured stems-only) carry
    neither key — the surface sweep must not invent a row or raise."""
    base_sec = _section("verse1", [_surface("track:1", timbre=_timbre(sharpness_acum=1.4))])
    cur_sec = _section("verse1", [_surface("track:1", timbre=_timbre(sharpness_acum=1.4))])
    base_sec.pop("returns")
    cur_sec.pop("returns")
    baseline = _report()
    baseline["per_section"] = [base_sec]
    current = _report()
    current["per_section"] = [cur_sec]
    out = diff_reports(current, baseline)
    assert {r["track_id"] for r in out["section_deltas"]} == {"track:1"}


def test_section_deltas_skip_unmatched_sections_and_null_sides():
    baseline = _report()
    baseline["per_section"] = [
        _section("verse", [], [_transient("track:1", t20_ms=None)])]
    current = _report()
    current["per_section"] = [
        _section("verse", [], [_transient("track:1")]),
        _section("outro", [], [_transient("track:1")])]
    out = diff_reports(current, baseline)
    sections = {r["section"] for r in out["section_deltas"]}
    assert sections == {"verse"}                       # outro has no baseline
    t20 = next(r for r in out["section_deltas"] if r["metric"] == "t20_ms")
    assert t20["delta"] is None and t20["significant"] is False


def test_reports_without_sections_yield_no_section_deltas():
    out = diff_reports(_report(), _report())
    assert out["section_deltas"] == []
