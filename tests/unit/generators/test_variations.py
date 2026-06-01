"""Tests for the canonical motivic variation ops (rulers).

Contract under test (`.prawduct/artifacts/arrangement-model.md`): six pure
transforms — transpose, invert, retrograde, augment, diminish, fragment — plus
the `shift` placement utility. Pure: inputs never mutated, tags carried through,
new dicts returned. Musical: each op does exactly the textbook transform.
"""
from __future__ import annotations

import pytest

from hallucinote.generators import variations as V


def _n(pitch, start, dur=1.0, vel=80, tags=None):
    return {
        "pitch": pitch,
        "start_beats": start,
        "duration_beats": dur,
        "velocity": vel,
        "tags": tags if tags is not None else ["motif"],
    }


# A tiny 3-note rising motif: E3, G3, B3 over beats 0,1,2.
MOTIF = [_n(52, 0.0), _n(55, 1.0), _n(59, 2.0)]


# --------------------------------------------------------------------------
# transpose
# --------------------------------------------------------------------------


def test_transpose_shifts_all_pitches_preserving_intervals():
    out = V.transpose(MOTIF, 12)
    assert [n["pitch"] for n in out] == [64, 67, 71]
    # intervals preserved
    assert [b["pitch"] - a["pitch"] for a, b in zip(out, out[1:])] == [3, 4]


def test_transpose_down():
    out = V.transpose(MOTIF, -5)
    assert [n["pitch"] for n in out] == [47, 50, 54]


def test_transpose_out_of_range_raises():
    with pytest.raises(ValueError, match="MIDI range"):
        V.transpose([_n(120, 0.0)], 12)
    with pytest.raises(ValueError, match="MIDI range"):
        V.transpose([_n(5, 0.0)], -12)


def test_transpose_is_pure():
    original = _n(52, 0.0)
    snapshot = dict(original)
    V.transpose([original], 7)
    assert original == snapshot  # input untouched


# --------------------------------------------------------------------------
# invert
# --------------------------------------------------------------------------


def test_invert_around_first_note_by_default():
    # axis = 52 (first pitch). 52->52, 55->49, 59->45.
    out = V.invert(MOTIF)
    assert [n["pitch"] for n in out] == [52, 49, 45]


def test_invert_explicit_axis():
    out = V.invert(MOTIF, axis_pitch=60)
    assert [n["pitch"] for n in out] == [68, 65, 61]


def test_invert_empty():
    assert V.invert([]) == []


def test_invert_out_of_range_raises():
    with pytest.raises(ValueError, match="MIDI range"):
        V.invert([_n(0, 0.0), _n(70, 1.0)])  # 2*0-70 = -70


# --------------------------------------------------------------------------
# retrograde
# --------------------------------------------------------------------------


def test_retrograde_reverses_time():
    # span = 3.0 (last release). onsets: 0->2, 1->1, 2->0.
    out = V.retrograde(MOTIF)
    by_pitch = {n["pitch"]: n["start_beats"] for n in out}
    assert by_pitch[52] == 2.0
    assert by_pitch[55] == 1.0
    assert by_pitch[59] == 0.0


def test_retrograde_explicit_span():
    out = V.retrograde(MOTIF, span_beats=4.0)
    by_pitch = {n["pitch"]: n["start_beats"] for n in out}
    assert by_pitch[59] == 1.0  # 4 - (2+1)
    assert by_pitch[52] == 3.0  # 4 - (0+1)


def test_retrograde_returns_sorted_by_onset():
    out = V.retrograde(MOTIF)
    onsets = [n["start_beats"] for n in out]
    assert onsets == sorted(onsets)


# --------------------------------------------------------------------------
# augment / diminish
# --------------------------------------------------------------------------


def test_augment_stretches_onset_and_duration():
    out = V.augment(MOTIF, 2.0)
    assert [n["start_beats"] for n in out] == [0.0, 2.0, 4.0]
    assert all(n["duration_beats"] == 2.0 for n in out)


def test_diminish_is_inverse_of_augment():
    out = V.diminish(MOTIF, 2.0)
    assert [n["start_beats"] for n in out] == [0.0, 0.5, 1.0]
    assert all(n["duration_beats"] == 0.5 for n in out)


def test_augment_diminish_round_trip():
    rt = V.diminish(V.augment(MOTIF, 3.0), 3.0)
    for a, b in zip(MOTIF, rt):
        assert a["start_beats"] == pytest.approx(b["start_beats"])
        assert a["duration_beats"] == pytest.approx(b["duration_beats"])


@pytest.mark.parametrize("op", [V.augment, V.diminish])
def test_augment_diminish_reject_nonpositive_factor(op):
    with pytest.raises(ValueError, match="factor must be > 0"):
        op(MOTIF, 0.0)


# --------------------------------------------------------------------------
# fragment
# --------------------------------------------------------------------------


def test_fragment_selects_window_and_rebases():
    # window [1,3): keeps G3@1, B3@2; rebased to 0,1.
    out = V.fragment(MOTIF, 1.0, 3.0)
    assert [n["pitch"] for n in out] == [55, 59]
    assert [n["start_beats"] for n in out] == [0.0, 1.0]


def test_fragment_no_rebase_keeps_absolute_onsets():
    out = V.fragment(MOTIF, 1.0, 3.0, rebase=False)
    assert [n["start_beats"] for n in out] == [1.0, 2.0]


def test_fragment_window_is_half_open():
    # [0,1): keeps only onset at exactly 0, excludes onset at 1.
    out = V.fragment(MOTIF, 0.0, 1.0)
    assert [n["pitch"] for n in out] == [52]


def test_fragment_bad_window_raises():
    with pytest.raises(ValueError, match="must be >"):
        V.fragment(MOTIF, 2.0, 2.0)


# --------------------------------------------------------------------------
# shift
# --------------------------------------------------------------------------


def test_shift_translates_onsets():
    out = V.shift(MOTIF, 8.0)
    assert [n["start_beats"] for n in out] == [8.0, 9.0, 10.0]
    # durations + pitches untouched
    assert [n["pitch"] for n in out] == [52, 55, 59]


def test_shift_allows_negative_result():
    # shift does not clamp; the mutator boundary owns the >= 0 reality check.
    out = V.shift([_n(52, 1.0)], -0.5)
    assert out[0]["start_beats"] == 0.5


# --------------------------------------------------------------------------
# cross-cutting: purity + tags + composition
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda: V.transpose(MOTIF, 5),
        lambda: V.invert(MOTIF),
        lambda: V.retrograde(MOTIF),
        lambda: V.augment(MOTIF, 2.0),
        lambda: V.diminish(MOTIF, 2.0),
        lambda: V.fragment(MOTIF, 0.0, 3.0),
        lambda: V.shift(MOTIF, 4.0),
    ],
)
def test_ops_preserve_tags_and_dont_mutate_input(call):
    before = [dict(n) for n in MOTIF]
    out = call()
    # input unchanged
    assert MOTIF == before
    # tags carried through and independent (new list objects)
    for n in out:
        assert n["tags"] == ["motif"]
    if out:
        out[0]["tags"].append("touched")
        assert all("touched" not in n["tags"] for n in MOTIF)


def test_ops_compose():
    # transpose up an octave then fragment the tail, then shift into place.
    chain = V.shift(V.fragment(V.transpose(MOTIF, 12), 1.0, 3.0), 16.0)
    assert [n["pitch"] for n in chain] == [67, 71]
    assert [n["start_beats"] for n in chain] == [16.0, 17.0]
