"""Kit lookup: canonical pad name → MIDI note via fuzzy chain-name match."""
from __future__ import annotations

import warnings

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.generators.kit import Kit


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "kit.db")
    yield c
    c.close()


@pytest.fixture
def device_with_mappings(conn):
    """A Drum Rack device whose pad mappings are persisted in the DB."""
    sid = M.create_song(conn, name="t", key="Dm")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="Drums", kind="midi")
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="DrumGroupDevice", display_name="Hot Rod Kit",
    )
    # Hot-Rod-Kit-like layout: crash on 51 instead of GM's 49.
    M.replace_drum_pad_mappings(conn, device_id=did, mappings=[
        {"chain_name": "Kick Drum", "midi_note": 36},
        {"chain_name": "Snare Top", "midi_note": 38},
        {"chain_name": "Closed Hat", "midi_note": 42},
        {"chain_name": "Open Hat", "midi_note": 46},
        {"chain_name": "Crash", "midi_note": 51},
    ])
    return did


# ---------- Kit.from_device ----------


def test_from_device_loads_mappings_from_db(conn, device_with_mappings):
    kit = Kit.from_device(conn, device_with_mappings, name="Hot Rod Kit")
    assert kit.name == "Hot Rod Kit"
    assert kit.device_id == device_with_mappings
    # All five chains accessible by their canonical names.
    assert kit.kick == 36
    assert kit.snare == 38
    assert kit.hat_closed == 42
    assert kit.hat_open == 46
    assert kit.crash == 51  # NOT GM's 49 — this kit puts crash at 51


def test_from_device_empty_mappings_falls_through_to_gm_silently(conn):
    """When the device has NO captured pad mappings, the Kit is empty and
    every lookup quietly returns the GM default — no warning, because
    'empty kit' is a clear pre-capture state, not a kit-vs-canonical
    mismatch."""
    sid = M.create_song(conn, name="t", key="Dm")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="D", kind="midi")
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="DrumGroupDevice", display_name="Pre-Capture Kit",
    )
    kit = Kit.from_device(conn, did)
    # No warnings expected: empty kit short-circuits to GM without the
    # "kit has no chain matching X" warning (that warning is for the
    # captured-but-incomplete-kit case).
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        assert kit.kick == 36
        assert kit.snare == 38
    user_warnings = [r for r in record if issubclass(r.category, UserWarning)]
    assert user_warnings == []


# ---------- Kit.from_dict ----------


def test_from_dict_round_trips_canonical_names():
    kit = Kit.from_dict({"kick": 35, "snare": 40})
    assert kit.kick == 35
    assert kit.snare == 40


# ---------- Kit.gm_default ----------


def test_gm_default_exposes_standard_pad_layout():
    kit = Kit.gm_default()
    assert kit.kick == 36
    assert kit.snare == 38
    assert kit.hat_closed == 42
    assert kit.hat_open == 46
    assert kit.crash == 49  # GM crash


# ---------- pitch_of: fuzzy chain-name matching ----------


@pytest.mark.parametrize(
    "chain_name, canonical, expected_note",
    [
        # Hi-hat closed/open disambiguation — the most-likely-to-break case.
        ("Closed Hat", "hat_closed", 50),
        ("Hi-Hat Closed", "hat_closed", 50),
        ("CHH", "hat_closed", 50),
        ("Open Hat", "hat_open", 50),
        ("Hi-Hat Open", "hat_open", 50),
        # Kick name variants.
        ("Kick Drum", "kick", 50),
        ("BD Big", "kick", 50),
        ("Bass Drum", "kick", 50),
        # Snare variants.
        ("Snare Top", "snare", 50),
        ("SD 03", "snare", 50),
        ("Sn 808", "snare", 50),
        # Multi-word canonical (ride_bell) — substring of chain name.
        ("Ride Bell", "ride_bell", 50),
    ],
)
def test_pitch_of_fuzzy_matches_chain_name_variants(
    chain_name, canonical, expected_note,
):
    kit = Kit(name="t", device_id=None, mappings_by_note={expected_note: chain_name})
    assert kit.pitch_of(canonical) == expected_note


def test_pitch_of_warns_and_falls_through_when_kit_lacks_canonical(conn):
    """A populated kit that doesn't include the requested canonical pad
    falls through to the GM default WITH a UserWarning so the composer
    sees the substitution."""
    sid = M.create_song(conn, name="t", key="Dm")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="D", kind="midi")
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="DrumGroupDevice", display_name="Minimal Kit",
    )
    M.replace_drum_pad_mappings(conn, device_id=did, mappings=[
        {"chain_name": "Kick", "midi_note": 36},  # only kick captured
    ])
    kit = Kit.from_device(conn, did, name="Minimal Kit")
    with pytest.warns(UserWarning, match="snare"):
        assert kit.snare == 38  # GM default


def test_pitch_of_raises_for_unknown_canonical_name():
    kit = Kit.gm_default()
    with pytest.raises(KeyError, match="unknown canonical"):
        kit.pitch_of("not_a_pad")


def test_pitch_of_picks_lowest_note_on_multiple_matches():
    """If two chains both look like 'kick' ('Kick A', 'Kick B'), the lower
    MIDI note wins — Drum Racks order pads bottom-up so the canonical pad
    is typically the lowest."""
    kit = Kit(
        name="t", device_id=None,
        mappings_by_note={36: "Kick A", 40: "Kick B"},
    )
    assert kit.kick == 36
