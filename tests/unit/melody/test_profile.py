"""melody.profile — the declared MelodicProfile authoring object (phase 2b).

Covers the contract that mirrors the proven ``PerformanceProfile``:
``__post_init__`` validation (empty name, bad Literals, out-of-range numerics),
``to_dict()`` round-trip, an all-``None`` profile being legal — and the W3 deferral
pinned as a regression: the v1 field set is EXACTLY the nine declared fields and
does NOT include ``phrase_arch`` / ``motif_dna`` (no guaranteed read side this
plan). ``ContourIntent`` uses ``"level"`` (NOT ``"static"``) to match the read-side
``ContourShape`` exactly (W2) — pinned so it can't silently re-diverge.
"""
from __future__ import annotations

from dataclasses import fields

import pytest

from hallucinote.melody.contour import ContourShape
from hallucinote.melody.profile import (
    V1_FIELDS,
    MelodicProfile,
)


def test_all_none_profile_is_legal_and_grades_nothing():
    # A profile that declares only a name is valid — every gradable field is None,
    # so the line reads as unconstrained substrate (the 2a behavior, graceful).
    p = MelodicProfile(name="bare")
    assert p.name == "bare"
    assert p.contour_intent is None
    assert p.harmonic_freedom is None
    assert p.repetition_appetite is None


def test_post_init_rejects_empty_name():
    with pytest.raises(ValueError, match="name must be non-empty"):
        MelodicProfile(name="")


def test_post_init_rejects_bad_contour_intent_literal():
    with pytest.raises(ValueError, match="contour_intent"):
        MelodicProfile(name="x", contour_intent="static")  # type: ignore[arg-type]


@pytest.mark.parametrize("field_name", ["step_appetite", "harmonic_freedom", "repetition_appetite"])
def test_post_init_rejects_bad_appetite_literal(field_name):
    with pytest.raises(ValueError, match=field_name):
        MelodicProfile(name="x", **{field_name: "medium"})  # type: ignore[arg-type]


def test_post_init_rejects_apex_out_of_unit_range():
    with pytest.raises(ValueError, match="apex_position"):
        MelodicProfile(name="x", apex_position=1.5)
    with pytest.raises(ValueError, match="apex_position"):
        MelodicProfile(name="x", apex_position=-0.1)


def test_post_init_rejects_inverted_ambitus_band():
    with pytest.raises(ValueError, match="ambitus_min"):
        MelodicProfile(name="x", ambitus_min=12, ambitus_max=7)


def test_post_init_rejects_negative_ambitus():
    with pytest.raises(ValueError, match="ambitus_max"):
        MelodicProfile(name="x", ambitus_max=-1)


def test_to_dict_round_trips_every_field():
    p = MelodicProfile(
        name="reggae-hook",
        idiom="singable-pop-hook",
        contour_intent="arch",
        apex_position=0.5,
        ambitus_min=5,
        ambitus_max=12,
        step_appetite="moderate",
        harmonic_freedom="low",
        repetition_appetite="high",
    )
    d = p.to_dict()
    assert MelodicProfile(**d) == p
    assert set(d) == set(V1_FIELDS)


def test_v1_field_set_is_exactly_nine_and_excludes_deferred():
    """W3 deferral made semantic (learnings: pin the convention with a test naming
    what now FAILS). ``phrase_arch`` / ``motif_dna`` have no guaranteed read side
    this plan, so they MUST NOT be on the v1 profile — they enter when their read
    side ships."""
    actual = tuple(f.name for f in fields(MelodicProfile))
    assert actual == V1_FIELDS
    assert len(actual) == 9
    assert "phrase_arch" not in actual
    assert "motif_dna" not in actual


def test_contour_intent_uses_level_not_static_and_aligns_with_contourshape():
    """W2: ContourIntent's shared members are byte-identical to the read-side
    ContourShape (minus ``insufficient-data``, plus ``free``) so a declared intent
    compares to a measured shape by string equality — no translation table.
    ``"level"`` (not ``"static"``) is the shared member; pinned against regression."""
    # "level" is accepted; "static" is rejected (it would silently no-op the contour
    # grading by never equalling any measured ContourShape).
    MelodicProfile(name="x", contour_intent="level")
    with pytest.raises(ValueError):
        MelodicProfile(name="x", contour_intent="static")  # type: ignore[arg-type]
    # Every ContourIntent member except "free" is a real ContourShape member.
    contourshape_members = set(ContourShape.__args__)
    intent_members = {"arch", "ascending", "descending", "valley", "level", "free"}
    assert (intent_members - {"free"}).issubset(contourshape_members)
    assert "static" not in contourshape_members  # the measured shape is "level"
    # The two intentionally-asymmetric members: read-only / intent-only.
    assert "insufficient-data" in contourshape_members
    assert "insufficient-data" not in intent_members
    assert "free" not in contourshape_members
