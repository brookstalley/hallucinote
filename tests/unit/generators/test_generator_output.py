"""Tests for the GeneratorOutput dataclass and as_generator_output normalizer."""
from __future__ import annotations

import pytest

from hallucinote.generators import (
    GeneratorOutput,
    as_generator_output,
)


def _note(pitch=60, start=0.0, dur=1.0, vel=80, tags=None):
    return {
        "pitch": pitch,
        "start_beats": start,
        "duration_beats": dur,
        "velocity": vel,
        "tags": tags or [],
    }


def _envelope(target_kind="mixer_volume", target_track_id="t1"):
    return {
        "target_kind": target_kind,
        "target_track_id": target_track_id,
        "breakpoints": [
            {"time_beats": 0.0, "value": 0.0, "curve_kind": "linear"},
            {"time_beats": 4.0, "value": 0.8, "curve_kind": "linear"},
        ],
    }


# --------------------------------------------------------------------------
# Dataclass shape
# --------------------------------------------------------------------------


def test_generator_output_defaults_empty():
    out = GeneratorOutput()
    assert out.notes == []
    assert out.envelopes == []


def test_generator_output_takes_notes_only():
    out = GeneratorOutput(notes=[_note(60), _note(62)])
    assert len(out.notes) == 2
    assert out.envelopes == []


def test_generator_output_takes_envelopes_only():
    out = GeneratorOutput(envelopes=[_envelope()])
    assert out.notes == []
    assert len(out.envelopes) == 1


def test_generator_output_takes_both():
    out = GeneratorOutput(notes=[_note(60)], envelopes=[_envelope()])
    assert len(out.notes) == 1
    assert len(out.envelopes) == 1


def test_each_instance_has_independent_lists():
    # Regression: dataclass default_factory not a shared mutable.
    a = GeneratorOutput()
    b = GeneratorOutput()
    a.notes.append(_note(60))
    assert b.notes == []


# --------------------------------------------------------------------------
# Concatenation via extend / +
# --------------------------------------------------------------------------


def test_extend_with_generator_output_merges_both_lists():
    a = GeneratorOutput(notes=[_note(60)], envelopes=[_envelope()])
    b = GeneratorOutput(notes=[_note(62)], envelopes=[_envelope(target_track_id="t2")])
    a.extend(b)
    assert len(a.notes) == 2
    assert len(a.envelopes) == 2
    # b should be unchanged
    assert len(b.notes) == 1


def test_extend_with_note_list_appends_notes_only():
    a = GeneratorOutput(notes=[_note(60)])
    a.extend([_note(62), _note(64)])
    assert len(a.notes) == 3
    assert a.envelopes == []


def test_add_returns_new_object():
    a = GeneratorOutput(notes=[_note(60)])
    b = GeneratorOutput(notes=[_note(62)])
    c = a + b
    assert len(c.notes) == 2
    # Originals untouched
    assert len(a.notes) == 1
    assert len(b.notes) == 1


def test_iadd_mutates_in_place():
    a = GeneratorOutput(notes=[_note(60)])
    a += GeneratorOutput(notes=[_note(62)])
    assert len(a.notes) == 2


def test_add_with_legacy_note_list_works():
    a = GeneratorOutput(notes=[_note(60)])
    c = a + [_note(62)]
    assert len(c.notes) == 2


# --------------------------------------------------------------------------
# Normalizer
# --------------------------------------------------------------------------


def test_as_generator_output_passes_through_generator_output():
    src = GeneratorOutput(notes=[_note(60)])
    out = as_generator_output(src)
    assert out is src  # passed through unchanged


def test_as_generator_output_wraps_note_list():
    out = as_generator_output([_note(60), _note(62)])
    assert isinstance(out, GeneratorOutput)
    assert len(out.notes) == 2
    assert out.envelopes == []


def test_as_generator_output_handles_empty_list():
    out = as_generator_output([])
    assert out.notes == []
    assert out.envelopes == []


def test_as_generator_output_handles_none():
    out = as_generator_output(None)
    assert out.notes == []
    assert out.envelopes == []


def test_as_generator_output_rejects_unknown_type():
    with pytest.raises(TypeError, match="cannot normalize"):
        as_generator_output("not a generator output")
    with pytest.raises(TypeError):
        as_generator_output({"pitch": 60})  # bare dict — not a list


# --------------------------------------------------------------------------
# Interop with existing legacy generators
# --------------------------------------------------------------------------


def test_normalizer_wraps_legacy_drum_generator_output():
    """Existing drum generators return list[NoteDict]; normalizer must wrap them."""
    from hallucinote.generators import drums

    legacy_return = drums.kick_stumble(4)
    out = as_generator_output(legacy_return)
    assert isinstance(out, GeneratorOutput)
    assert out.notes is legacy_return  # wrapper does not copy
    assert out.envelopes == []
