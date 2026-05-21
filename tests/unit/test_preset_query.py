"""Tests for src/hallucinote/preset_query.py — Arc 3 / C2.

The path-shape parser is the syntactic-sugar layer for compose-time
preset selection. Everything below the mutator (push planner, MCP
loader, compat.check_song) sees only the canonical dict, so the parser's
job is narrow: accept the ergonomic string, reject malformed input
loud, normalize root to the MCP-canonical form.
"""
from __future__ import annotations

import pytest

from hallucinote.preset_query import (
    BROWSER_ROOTS,
    normalize,
    parse_path_shape,
)


def test_parse_path_shape_simple_root_pattern():
    """Two-segment input → root + pattern, no path_prefix."""
    out = parse_path_shape("Drums/Kit-Core 909")
    assert out == {"root": "drums", "pattern": "Kit-Core 909"}


def test_parse_path_shape_path_prefix_segments():
    """Middle segments become path_prefix; last segment is the pattern."""
    out = parse_path_shape("Instruments/Operator/Bass/Pluck-Sub")
    assert out == {
        "root": "instruments",
        "path_prefix": ["Operator", "Bass"],
        "pattern": "Pluck-Sub",
    }


def test_parse_path_shape_root_canonicalizes_case():
    """Root is case-insensitive — authors write 'Drums', browser
    canonical is 'drums'."""
    out = parse_path_shape("DRUMS/909")
    assert out["root"] == "drums"


def test_parse_path_shape_root_spaces_become_underscores():
    """'Audio Effects' ≡ 'audio_effects' — both are common spellings
    and the parser must accept either to match how authors actually
    write paths."""
    out = parse_path_shape("Audio Effects/Reverb/Hall")
    assert out["root"] == "audio_effects"
    assert out["path_prefix"] == ["Reverb"]
    assert out["pattern"] == "Hall"


def test_parse_path_shape_path_prefix_segments_preserved_verbatim():
    """Path-prefix and pattern segments are matched LITERALLY by Live's
    browser. Don't strip whitespace, lowercase, or otherwise mangle —
    'Kit-Core 909' is a different folder name from 'kit-core 909'."""
    out = parse_path_shape("Drums/Kit-Core/Kit-Core 909")
    assert out["path_prefix"] == ["Kit-Core"]
    assert out["pattern"] == "Kit-Core 909"


def test_parse_path_shape_rejects_single_segment():
    """Single segment is ambiguous: is 'drums' a root or a pattern?
    Refuse and name the valid roots so the author sees the right
    syntax."""
    with pytest.raises(ValueError, match="needs at least.*root.*pattern"):
        parse_path_shape("drums")


def test_parse_path_shape_rejects_empty_string():
    """Empty input → also single-segment (split('/') → ['']); same
    error path."""
    with pytest.raises(ValueError, match="needs at least"):
        parse_path_shape("")


def test_parse_path_shape_rejects_unknown_root():
    """Typo'd root — must name the valid set so the author can fix."""
    with pytest.raises(ValueError, match="not in valid roots"):
        parse_path_shape("effects/Hall")


def test_parse_path_shape_rejects_empty_pattern_segment():
    """Trailing slash → last segment is empty → no usable pattern."""
    with pytest.raises(ValueError, match="empty pattern"):
        parse_path_shape("drums/")


def test_parse_path_shape_rejects_whitespace_only_pattern():
    """Whitespace doesn't count as a pattern — Live's browser won't
    match anything against a blank string and we'd surface a noisy
    'no matches' error at push time."""
    with pytest.raises(ValueError, match="empty pattern"):
        parse_path_shape("drums/   ")


def test_parse_path_shape_rejects_non_string_input():
    """Defensive — callers should pass str, but a stray dict here would
    silently produce garbage path data through `.split('/')` on a
    coerced repr. Fail closed with a clear type message instead."""
    with pytest.raises(ValueError, match="must be a string"):
        parse_path_shape(["drums", "909"])  # type: ignore[arg-type]


def test_normalize_passes_through_dict():
    """A canonical dict is already in the right shape; passthrough."""
    pq = {"root": "drums", "pattern": "909"}
    assert normalize(pq) is pq


def test_normalize_passes_through_none():
    """None → None — the no-preset_query case threads cleanly through
    the mutator."""
    assert normalize(None) is None


def test_normalize_parses_string():
    """String input flows through the path-shape parser."""
    out = normalize("Drums/Kit-Core 909")
    assert out == {"root": "drums", "pattern": "Kit-Core 909"}


def test_normalize_rejects_other_types():
    """Lists/ints/etc. → ValueError naming the type."""
    with pytest.raises(ValueError, match="dict, str, or None"):
        normalize(42)  # type: ignore[arg-type]


def test_browser_roots_matches_mcp_side():
    """The set of valid browser roots here MUST agree with the MCP
    server's ``_ROOTS`` enum. The compat module's lock-test pins this
    same identity at the compat layer; this asserts the path-shape
    parser uses the same canonical set."""
    from hallucinote_mcp.actions.browser import _ROOTS as MCP_ROOTS
    assert BROWSER_ROOTS == frozenset(MCP_ROOTS)


# ---------------------------------------------------------------------------
# Integration through M.create_device — DB stores canonical structured form
# ---------------------------------------------------------------------------


import json
import sqlite3
from pathlib import Path

from hallucinote.db import init_db, mutations as M


@pytest.fixture
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    conn = init_db(tmp_path / "song.db")
    yield conn
    conn.close()


@pytest.fixture
def song_chain(db_conn) -> str:
    song_id = M.create_song(db_conn, name="t", title="T", key="C")
    track_id = M.create_track(db_conn, song_id=song_id, track_index=1, name="Lead")
    return M.create_device_chain(db_conn, parent_track_id=track_id)


def test_create_device_accepts_path_shape_string(db_conn, song_chain):
    """A snapshot author writes the path-shape string; the DB stores
    the canonical dict (JSON-serialized) so downstream consumers see
    a single shape."""
    M.create_device(
        db_conn, chain_id=song_chain, position=1,
        kind="Operator", display_name="Operator",
        preset_query="Instruments/Operator/Bass/Pluck-Sub",
    )
    db_conn.commit()
    row = db_conn.execute(
        "SELECT preset_query FROM devices WHERE chain_id = ?", (song_chain,),
    ).fetchone()
    stored = json.loads(row["preset_query"])
    assert stored == {
        "root": "instruments",
        "path_prefix": ["Operator", "Bass"],
        "pattern": "Pluck-Sub",
    }


def test_create_device_dict_form_unchanged(db_conn, song_chain):
    """Existing dict-form callers must keep working — passthrough."""
    M.create_device(
        db_conn, chain_id=song_chain, position=1,
        kind="Reverb", display_name="Reverb",
        preset_query={"root": "audio_effects", "pattern": "Hall"},
    )
    db_conn.commit()
    row = db_conn.execute(
        "SELECT preset_query FROM devices WHERE chain_id = ?", (song_chain,),
    ).fetchone()
    stored = json.loads(row["preset_query"])
    assert stored == {"root": "audio_effects", "pattern": "Hall"}


def test_create_device_path_shape_with_invalid_root_raises_loud(db_conn, song_chain):
    """Bad path-shape → ValueError at the mutator, not silently
    persisted as garbage that a later push would refuse opaquely."""
    with pytest.raises(ValueError, match="not in valid roots"):
        M.create_device(
            db_conn, chain_id=song_chain, position=1,
            kind="Reverb", display_name="Reverb",
            preset_query="effects/Hall",
        )


def test_create_device_normalized_preset_query_is_idempotent(db_conn, song_chain):
    """Calling create_device twice with the equivalent path-shape +
    dict forms should converge to the same row, not produce a noisy
    'updated' result with churning JSON. Tests that the normalized
    form is what compares against ``existing`` for idempotency."""
    sid_1 = M.create_device(
        db_conn, chain_id=song_chain, position=1,
        kind="Operator", display_name="Operator",
        preset_query="Instruments/Bass",
    )
    sid_2 = M.create_device(
        db_conn, chain_id=song_chain, position=1,
        kind="Operator", display_name="Operator",
        preset_query={"root": "instruments", "pattern": "Bass"},
    )
    # Same device_id, second call detected as unchanged.
    assert str(sid_1) == str(sid_2)
    assert sid_2.kind == "unchanged"
