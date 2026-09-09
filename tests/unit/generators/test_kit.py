"""Kit lookup: canonical pad name → MIDI note via fuzzy chain-name match."""
from __future__ import annotations

import os
import warnings
from pathlib import Path

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
        kind="Drum Rack", display_name="Hot Rod Kit",
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
        kind="Drum Rack", display_name="Pre-Capture Kit",
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
        kind="Drum Rack", display_name="Minimal Kit",
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


# ---------- pitch_of: wrong-sound case (Hot Rod Kit cautionary tale) ----------


def test_pitch_of_raises_when_gm_default_collides_with_different_chain():
    """The Hot Rod Kit case: kit has captured pads, none match the requested
    canonical, AND the GM-default note for that canonical is already taken
    by a differently-named chain. Falling through would play the wrong
    sound (cowbell instead of ride). Refuse.
    """
    # Hot Rod Kit shape (simplified) — pad 51 is cowbell, not ride.
    kit = Kit(
        name="Hot Rod Kit",
        device_id=None,
        mappings_by_note={
            36: "Kick Drum",
            38: "Snare Top",
            42: "Closed Hat",
            46: "Buttery",  # second closed hat — kit has no open hat
            49: "Crash",
            51: "Cowbell Fenk Chick",  # GM-default "ride" slot
        },
    )
    with pytest.raises(KeyError, match=r"Cowbell.*Fenk.*Chick"):
        kit.pitch_of("ride")


def test_pitch_of_raises_message_names_try_pitch_of_alternative():
    """The wrong-sound exception message points the caller at `try_pitch_of`
    so the recovery path is discoverable from the error itself."""
    kit = Kit(
        name="Hot Rod Kit",
        device_id=None,
        mappings_by_note={51: "Cowbell Fenk Chick"},
    )
    with pytest.raises(KeyError, match="try_pitch_of"):
        kit.pitch_of("ride")


def test_pitch_of_still_warns_and_falls_through_when_gm_slot_empty():
    """The 'empty slot' fall-through case stays exactly as before — GM-default
    note is NOT taken on this kit, so the substitution plays silence (the
    pad is empty), not a different sound. Warn-and-return-GM keeps the
    composer aware while letting the build flow."""
    # Minimal kit: only kick captured. GM[shaker]=70 is NOT in mappings.
    kit = Kit(
        name="Minimal Kit",
        device_id=None,
        mappings_by_note={36: "Kick Drum"},
    )
    with pytest.warns(UserWarning, match="empty pad on this kit"):
        assert kit.pitch_of("shaker") == 70


# ---------- try_pitch_of ----------


def test_try_pitch_of_returns_note_on_match():
    """When a chain matches the canonical, try_pitch_of returns the note
    just like pitch_of."""
    kit = Kit(
        name="t", device_id=None,
        mappings_by_note={37: "Kick Drum", 39: "Snare Top"},
    )
    assert kit.try_pitch_of("kick") == 37
    assert kit.try_pitch_of("snare") == 39


def test_try_pitch_of_returns_none_for_missing_canonical_on_populated_kit():
    """When the kit has captured chains but none match, try_pitch_of returns
    None — including the wrong-sound case that pitch_of raises on. Callers
    that want to react to absence get a clean signal without exception
    handling."""
    # Wrong-sound case (Hot Rod Kit ride).
    hot_rod = Kit(
        name="Hot Rod Kit", device_id=None,
        mappings_by_note={51: "Cowbell Fenk Chick"},
    )
    assert hot_rod.try_pitch_of("ride") is None
    # Empty-slot case (Minimal Kit shaker).
    minimal = Kit(
        name="Minimal Kit", device_id=None,
        mappings_by_note={36: "Kick Drum"},
    )
    assert minimal.try_pitch_of("shaker") is None


def test_try_pitch_of_returns_gm_default_on_empty_kit():
    """Empty mappings (pre-capture state) → GM default. Symmetric with
    pitch_of: an uncharacterized kit gets the GM best-guess."""
    kit = Kit(name="Pre-Capture", device_id=None, mappings_by_note={})
    assert kit.try_pitch_of("kick") == 36  # GM kick
    assert kit.try_pitch_of("ride") == 51  # GM ride


def test_try_pitch_of_raises_for_unknown_canonical():
    """Pad-name typos remain programming errors, not absence cases."""
    kit = Kit.gm_default()
    with pytest.raises(KeyError, match="unknown canonical"):
        kit.try_pitch_of("not_a_pad")


# ---------- assert_has ----------


def test_assert_has_passes_when_all_pads_resolve():
    kit = Kit(
        name="Full Kit", device_id=None,
        mappings_by_note={
            36: "Kick Drum", 38: "Snare", 42: "Closed Hat",
            46: "Open Hat", 49: "Crash", 51: "Ride Cymbal",
        },
    )
    kit.assert_has("kick", "snare", "hat_closed", "hat_open", "crash", "ride")
    # No exception = pass.


def test_assert_has_raises_listing_missing_pads():
    """A metal section that needs ride + crash but the loaded kit has
    neither — fail at composition start, not in audio playback."""
    kit = Kit(
        name="Hot Rod Kit",
        device_id=None,
        mappings_by_note={36: "Kick", 38: "Snare", 51: "Cowbell Fenk Chick"},
    )
    with pytest.raises(KeyError, match=r"\['ride', 'crash'\]"):
        kit.assert_has("kick", "snare", "ride", "crash")


def test_assert_has_passes_on_empty_kit_via_gm_fallback():
    """Pre-capture state: every canonical is 'present' via GM fall-through.
    assert_has catches kit-incompleteness, not pre-capture state — for
    pre-capture, the snapshot+capture flow is the right safety net."""
    kit = Kit(name="Pre-Capture", device_id=None, mappings_by_note={})
    kit.assert_has("kick", "snare", "ride", "crash")
    # No exception = pass.


def test_assert_has_raises_for_unknown_canonical_in_args():
    """Typo in the args list (e.g., 'rde' instead of 'ride') surfaces as
    a KeyError from try_pitch_of, propagated by assert_has."""
    kit = Kit.gm_default()
    with pytest.raises(KeyError, match="unknown canonical"):
        kit.assert_has("kick", "rde")  # rde is a typo


def test_assert_has_strict_refuses_empty_kit():
    """Arc 6 / H3: strict mode catches the pre-capture state that the
    default mode lets slide via GM fall-through. Documented design
    choice from Arc 1 / A3: a build.py that calls assert_has() before
    the first capture would silently pass, then surface the wrong-
    sound case on the NEXT session once drum_pad_mappings is
    populated. Strict mode refuses pre-capture explicitly."""
    kit = Kit(name="Pre-Capture", device_id=None, mappings_by_note={})
    with pytest.raises(KeyError, match="no captured pad mappings yet"):
        kit.assert_has("kick", "snare", strict=True)


def test_assert_has_strict_passes_when_kit_is_captured_and_complete():
    """Regression guard for strict mode: when the kit IS captured and
    has every canonical, strict=True still passes (it only adds the
    pre-capture check, doesn't replace the pad-presence check)."""
    kit = Kit.from_dict({
        "kick": 36, "snare": 38, "hat_closed": 42, "hat_open": 46,
        "crash": 49, "ride": 51,
    }, name="Complete Kit")
    kit.assert_has("kick", "snare", "ride", "crash", strict=True)
    # No exception = pass.


def test_assert_has_strict_still_catches_missing_pads_after_capture():
    """A captured kit missing pads — strict mode surfaces the same
    teaching error as default mode (the missing-pad path runs after
    the empty-mappings check, unchanged)."""
    kit = Kit.from_dict({"kick": 36, "snare": 38}, name="Sparse Captured")
    with pytest.raises(KeyError, match="missing canonical pad"):
        kit.assert_has("kick", "ride", strict=True)


# ---------- purity (JANITOR-2026-09 R2) ----------


def test_from_rows_needs_no_database():
    """A Kit is buildable from rows alone — the purity norm's actual guarantee.

    `kit.py` imported `hallucinote.db.queries` for one call, which made the
    norm ("generators stay pure — no DB imports under generators/") false at
    exactly the point it was supposed to buy something: you could not build a
    Kit without the DB layer imported. Rows in, Kit out, no connection.
    """
    kit = Kit.from_rows(
        [{"midi_note": 36, "chain_name": "Kick Drum"},
         {"midi_note": 51, "chain_name": "Cowbell"}],
        name="Hot Rod Kit",
        device_id="dev-abc12345",
    )
    assert kit.pitch_of("kick") == 36
    assert kit.name == "Hot Rod Kit"
    assert kit.device_id == "dev-abc12345"


def test_generators_package_imports_no_database_code():
    """Import-graph lock: nothing under `generators/` may pull in `db` or MCP.

    Enforcing the norm on the import GRAPH rather than on the source text is
    what makes it hold — a lazily-imported `db` would pass a grep for
    module-level imports while still coupling the packages at run time. The
    one legitimate DB path (`Kit.from_device`) is an alias whose import is
    function-local, so it does not appear here.
    """
    import subprocess
    import sys

    # EVERY generator module, not just kit. Importing one proves nothing about
    # its six siblings, and the norm is about the package.
    probe = (
        "import importlib, pkgutil, sys;"
        "import hallucinote.generators as g;"
        "[importlib.import_module(m.name) for m in pkgutil.iter_modules(g.__path__, g.__name__ + '.')];"
        "leaked = sorted(m for m in sys.modules"
        " if m.startswith('hallucinote.db') or m.startswith('hallucinote_mcp'));"
        "print(','.join(leaked))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, check=True,
        cwd=str(Path(__file__).resolve().parents[3]),
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert out.stdout.strip() == "", (
        "importing the generators package pulled in DB or MCP modules: "
        f"{out.stdout.strip()}"
    )


def test_load_kit_reads_mappings_from_the_database(conn, device_with_mappings):
    """`hallucinote.kits.load_kit` directly — not through the alias.

    `Kit.from_device` is deprecated for removal in 2.0. Testing the loader only
    through it would mean the surviving surface loses its coverage on the day
    the alias goes, which is the wrong day to discover that.
    """
    from hallucinote.kits import load_kit

    kit = load_kit(conn, device_with_mappings, name="Hot Rod Kit")
    assert kit.name == "Hot Rod Kit"
    assert kit.device_id == device_with_mappings
    assert kit.pitch_of("kick") == Kit.from_device(
        conn, device_with_mappings
    ).pitch_of("kick")


def test_from_rows_name_default_covers_both_branches():
    """Both default branches, and the empty-name fall-through.

    The extraction briefly changed `name or <stub>` into `name is None`, which
    silently preserved an empty name where the pre-split `from_device` produced
    a stub. Nothing caught it because neither branch had a test.
    """
    assert Kit.from_rows([], device_id="abcdef1234").name == "device:abcdef12"
    assert Kit.from_rows([]).name == "rows"
    assert Kit.from_rows([], name="", device_id="abcdef1234").name == "device:abcdef12"
    assert Kit.from_rows([], name="Explicit").name == "Explicit"
