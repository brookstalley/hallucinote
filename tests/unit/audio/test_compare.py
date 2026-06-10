"""Unit tests for ``compare.diff_reports`` — MixReport baseline diffs.

Pure-dict tests: both sides are ``to_json_dict()``-shaped dicts built by
hand, because the JSON schema (not the dataclass) is the diff contract.
Thresholds are imported from the module — they are the single source of
truth the calibration evidence froze (see compare.py docstring).
"""
from __future__ import annotations

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


def _surface(track_id: str, kind: str = "track", name: str = "x", **loudness) -> dict:
    return {
        "track_id": track_id,
        "surface_kind": kind,
        "surface_name": name,
        "loudness": _loudness(**loudness),
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
    # master (4 metrics) + track:1 (4 metrics)
    assert len(out["deltas"]) == 8
    for row in out["deltas"]:
        assert row["delta"] == 0.0
        assert row["significant"] is False


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
