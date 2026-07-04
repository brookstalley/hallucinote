"""EVT-6H9R chunk 3: fold-events-to-state replay smoke test.

Builds a small but representative song through the normal mutator API, then
folds its event log into a fresh DB and asserts convergence with the
materialized state. This is the thin seed-health slice, NOT the EVT-4K8H
replay/merge tooling: the fold lives here in the test, covers the FOLDED
kinds below, and every event kind must be classified as FOLDED or
NOT_YET_FOLDED (with a reason) so a new kind cannot ship unclassified and
silently escape the smoke test.

The fold applies event payloads with direct SQL. That is deliberate, not a
mutator-discipline violation: reconstructing state FROM events is the
read-model builder's job — mutators can't be reused because they mint fresh
ids and re-emit events, while the fold must reproduce the exact ids the
payloads carry.

Known payload gap surfaced by this test (the point of doing it now): the
notes events (`notes_inserted`, `clip_notes_replaced`, ...) carry note ids
and counts but NOT the note content (pitch/start/duration/velocity), so the
`notes` table cannot be rebuilt from the log. EVT-4K8H must enrich those
payloads (or change the fold contract) before the event-store flip.
"""
from __future__ import annotations

import json

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.db import events as E


# ---------------------------------------------------------------------------
# Classification: every event kind is FOLDED or NOT_YET_FOLDED. Exhaustiveness
# over hallucinote.db.events is asserted in test_every_event_kind_is_classified.
# ---------------------------------------------------------------------------

FOLDED: frozenset[str] = frozenset({
    E.SONG_CREATED, E.SONG_UPDATED, E.SONG_TIMING_MODE_SET, E.SONG_TUNING_SET,
    E.TRACK_CREATED, E.TRACK_UPDATED, E.TRACK_DELETED,
    E.TRACK_MIXER_SET, E.TRACK_ROUTING_SET,
    E.CLIP_CREATED, E.CLIP_UPDATED, E.CLIP_DELETED,
    E.SECTION_CREATED, E.SECTION_UPDATED, E.SECTION_DELETED,
    E.TEMPO_POINT_ADDED, E.TIME_SIGNATURE_POINT_ADDED,
    E.RETURN_CREATED, E.SEND_SET,
    E.ARRANGEMENT_CLIP_ADDED, E.ARRANGEMENT_CLIP_REMOVED,
    E.DEVICE_CHAIN_CREATED, E.DEVICE_CREATED, E.DEVICE_DELETED,
    E.DEVICE_PARAMETER_SET, E.DEVICE_PARAMETER_REMOVED,
})

# kind -> why it is not folded by this smoke slice. Two distinct flavors:
# "payload gap" = the log does NOT carry enough to rebuild state (a real
# event-store blocker, EVT-4K8H's problem); "outside slice" = payload looks
# sufficient but the fold handler is deferred (writing untested handlers for
# unexercised kinds would be worse than an honest list).
NOT_YET_FOLDED: dict[str, str] = {
    # --- payload gaps (EVT-4K8H must enrich before the flip) ---
    E.NOTES_INSERTED: "payload gap: note ids + count only, no note content",
    E.CLIP_NOTES_REPLACED: "payload gap: counts + new ids only, no note content",
    E.NOTE_UPDATED: "payload gap: changes only; base note content never logged",
    E.NOTES_DELETED: "payload gap: ids only (delete would fold, but the notes "
                     "table can't converge while inserts don't fold)",
    E.NOTES_BULK_UPDATED: "payload gap: matched ids + velocity delta only",
    E.REQUEST_CREATED: "payload gap: prompt_text / metadata_json / ts not in "
                       "payload — requests provenance can't fully rebuild",
    E.REQUEST_CLOSED: "payload gap: see request_created",
    E.SONG_CONTENT_RESET: "payload gap: per-table delete counts only; folding "
                          "the wipe means re-executing the scoped deletes",
    # --- audit-only by design (nothing to fold) ---
    E.MARKDOWN_REF_RECORDED: "audit-only: markdown_refs is a projection "
                             "rebuilt from disk, never from events",
    E.AUTOMATION_PERFORMED: "sync-state fingerprint (performed_automation is "
                            "disposable, rebuilt by the next push)",
    # --- outside this smoke slice (payloads look fold-sufficient) ---
    E.RETURN_UPDATED: "outside slice",
    E.RETURN_DELETED: "outside slice",
    E.SEND_REMOVED: "outside slice",
    E.SEND_INTENT_SET: "outside slice",
    E.TEMPO_POINT_UPDATED: "outside slice",
    E.TEMPO_POINT_REMOVED: "outside slice",
    E.TIME_SIGNATURE_POINT_UPDATED: "outside slice",
    E.TIME_SIGNATURE_POINT_REMOVED: "outside slice",
    E.CUE_POINT_ADDED: "outside slice",
    E.CUE_POINT_REMOVED: "outside slice",
    E.DEVICE_CHAIN_DELETED: "outside slice",
    E.DEVICE_CHAIN_PROPS_SET: "outside slice",
    E.DEVICE_SIDECHAIN_SET: "outside slice",
    E.DRUM_PAD_MAPPINGS_REPLACED: "outside slice",
    E.DEVICE_PARAM_OVERRIDES_REPLACED: "outside slice",
    E.ENVELOPE_CREATED: "outside slice",
    E.ENVELOPE_DELETED: "outside slice",
    E.BREAKPOINT_ADDED: "outside slice",
    E.BREAKPOINT_REMOVED: "outside slice",
    E.BREAKPOINTS_REPLACED: "outside slice",
    E.ABLETON_SESSION_CREATED: "outside slice (sync projection)",
    E.ABLETON_LINK_SET: "outside slice (sync projection)",
    E.ABLETON_LINK_REMOVED: "outside slice (sync projection)",
}

# Tables whose state the FOLDED kinds fully determine. `notes` is the known
# absentee (see module docstring). events/requests/markdown_refs/ableton_*
# are audit/provenance/projection surfaces, not folded state.
FOLDED_TABLES = (
    "songs", "sections", "tempo_map", "time_signature_map",
    "tracks", "clips", "arrangement_clips",
    "returns", "sends",
    "device_chains", "devices", "device_parameters",
)

_TS_COLUMNS = {"created_at", "updated_at"}  # wall-clock, not event-carried


def _compact(obj) -> str | None:
    """Match the mutators' compact json.dumps for *_json state columns."""
    return json.dumps(obj, separators=(",", ":")) if obj else None


def _fold_event(conn, kind: str, payload: dict, song_id, clip_id) -> None:
    p = payload
    if kind == E.SONG_CREATED:
        conn.execute(
            "INSERT INTO songs (id, name, title, key, timing_mode) "
            "VALUES (?, ?, ?, ?, ?)",
            (song_id, p["name"], p["title"], p["key"], p["timing_mode"]),
        )
    elif kind == E.SONG_UPDATED:
        conn.execute(
            "UPDATE songs SET title = ?, key = ?, timing_mode = ? WHERE id = ?",
            (p["title"], p["key"], p["timing_mode"], song_id),
        )
    elif kind == E.SONG_TIMING_MODE_SET:
        conn.execute(
            "UPDATE songs SET timing_mode = ? WHERE id = ?",
            (p["timing_mode"], song_id),
        )
    elif kind == E.SONG_TUNING_SET:
        conn.execute(
            "UPDATE songs SET tuning_ref = ?, tuning_data = ? WHERE id = ?",
            (p["tuning_ref"], p["tuning_data"], song_id),
        )
    elif kind == E.TRACK_CREATED:
        conn.execute(
            "INSERT INTO tracks (id, song_id, track_index, name, "
            "instrument_uri, kind) VALUES (?, ?, ?, ?, ?, ?)",
            (p["track_id"], song_id, p["track_index"], p["name"],
             p["instrument_uri"], p["kind"]),
        )
    elif kind == E.TRACK_UPDATED:
        conn.execute(
            "UPDATE tracks SET name = ?, instrument_uri = ?, kind = ? "
            "WHERE id = ?",
            (p["name"], p["instrument_uri"], p["kind"], p["track_id"]),
        )
    elif kind == E.TRACK_DELETED:
        conn.execute("DELETE FROM tracks WHERE id = ?", (p["track_id"],))
    elif kind in (E.TRACK_MIXER_SET, E.TRACK_ROUTING_SET):
        sets = ", ".join(f"{k} = ?" for k in p["changes"])
        conn.execute(
            f"UPDATE tracks SET {sets} WHERE id = ?",
            (*p["changes"].values(), p["track_id"]),
        )
    elif kind == E.CLIP_CREATED:
        if p["kind"] == "midi":
            conn.execute(
                "INSERT INTO clips (id, track_id, slot, length_beats, name, "
                "section_role, generator_call_json, kind) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'midi')",
                (p["clip_id"], p["track_id"], p["slot"], p["length_beats"],
                 p["name"], p["section_role"], _compact(p["generator_call"])),
            )
        else:
            conn.execute(
                "INSERT INTO clips (id, track_id, slot, kind, length_beats, "
                "name, audio_file, audio_gain, pitch_coarse, pitch_fine, "
                "warping, warp_mode, start_marker, end_marker, reverse) "
                "VALUES (?, ?, ?, 'audio', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (p["clip_id"], p["track_id"], p["slot"], p["length_beats"],
                 p["name"], p["audio_file"], p["audio_gain"],
                 p["pitch_coarse"], p["pitch_fine"], p["warping"],
                 p["warp_mode"], p["start_marker"], p["end_marker"],
                 p["reverse"]),
            )
    elif kind == E.CLIP_UPDATED:
        changes = dict(p["changes"])
        if "generator_call" in changes:
            changes["generator_call_json"] = _compact(
                changes.pop("generator_call")
            )
        sets = ", ".join(f"{k} = ?" for k in changes)
        conn.execute(
            f"UPDATE clips SET {sets} WHERE id = ?",
            (*changes.values(), p["clip_id"]),
        )
    elif kind == E.CLIP_DELETED:
        conn.execute("DELETE FROM clips WHERE id = ?", (p["clip_id"],))
    elif kind == E.SECTION_CREATED:
        conn.execute(
            "INSERT INTO sections (id, song_id, name, start_bar, end_bar, "
            "color, notes_md, energy) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (p["section_id"], song_id, p["name"], p["start_bar"],
             p["end_bar"], p["color"], p["notes_md"], p["energy"]),
        )
    elif kind == E.SECTION_UPDATED:
        sets = ", ".join(f"{k} = ?" for k in p["changes"])
        conn.execute(
            f"UPDATE sections SET {sets} WHERE id = ?",
            (*p["changes"].values(), p["section_id"]),
        )
    elif kind == E.SECTION_DELETED:
        conn.execute("DELETE FROM sections WHERE id = ?", (p["section_id"],))
    elif kind == E.TEMPO_POINT_ADDED:
        conn.execute(
            "INSERT INTO tempo_map (id, song_id, start_bar, tempo_bpm, ramp) "
            "VALUES (?, ?, ?, ?, ?)",
            (p["point_id"], song_id, p["start_bar"], p["tempo_bpm"], p["ramp"]),
        )
    elif kind == E.TIME_SIGNATURE_POINT_ADDED:
        conn.execute(
            "INSERT INTO time_signature_map "
            "(id, song_id, start_bar, numerator, denominator) "
            "VALUES (?, ?, ?, ?, ?)",
            (p["point_id"], song_id, p["start_bar"], p["numerator"],
             p["denominator"]),
        )
    elif kind == E.RETURN_CREATED:
        conn.execute(
            "INSERT INTO returns (id, song_id, name, position, volume, pan, "
            "color) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (p["return_id"], song_id, p["name"], p["position"], p["volume"],
             p["pan"], p["color"]),
        )
    elif kind == E.SEND_SET:
        conn.execute(
            "INSERT INTO sends (from_track_id, to_return_id, level) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(from_track_id, to_return_id) "
            "DO UPDATE SET level = excluded.level",
            (p["from_track_id"], p["to_return_id"], p["level"]),
        )
    elif kind == E.ARRANGEMENT_CLIP_ADDED:
        conn.execute(
            "INSERT INTO arrangement_clips "
            "(id, song_id, track_id, clip_id, start_bar, end_bar) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET end_bar = excluded.end_bar",
            (p["arrangement_clip_id"], song_id, p["track_id"], p["clip_id"],
             p["start_bar"], p["end_bar"]),
        )
    elif kind == E.ARRANGEMENT_CLIP_REMOVED:
        conn.execute(
            "DELETE FROM arrangement_clips WHERE id = ?",
            (p["arrangement_clip_id"],),
        )
    elif kind == E.DEVICE_CHAIN_CREATED:
        conn.execute(
            "INSERT INTO device_chains (id, parent_track_id, parent_return_id, "
            "parent_rack_device_id, position) VALUES (?, ?, ?, ?, ?)",
            (p["chain_id"], p["parent_track_id"], p["parent_return_id"],
             p["parent_rack_device_id"], p["position"]),
        )
    elif kind == E.DEVICE_CREATED:
        # One payload shape covers create + idempotent-update (result_kind).
        conn.execute(
            "INSERT OR REPLACE INTO devices (id, chain_id, position, kind, "
            "display_name, class_name, preset_uri, preset_query, "
            "browser_path_json, audio_file) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (p["device_id"], p["chain_id"], p["position"], p["kind"],
             p["display_name"], p["class_name"], p["preset_uri"],
             json.dumps(p["preset_query"], sort_keys=True)
             if p["preset_query"] is not None else None,
             json.dumps(p["browser_path"])
             if p["browser_path"] is not None else None,
             p["audio_file"]),
        )
    elif kind == E.DEVICE_DELETED:
        conn.execute("DELETE FROM devices WHERE id = ?", (p["device_id"],))
    elif kind == E.DEVICE_PARAMETER_SET:
        conn.execute(
            "INSERT OR REPLACE INTO device_parameters (id, device_id, name, "
            "value_display, value_normalized, value_items_json, value_raw) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (p["parameter_id"], p["device_id"], p["name"], p["value_display"],
             p["value_normalized"], p["value_items_json"], p["value_raw"]),
        )
    elif kind == E.DEVICE_PARAMETER_REMOVED:
        conn.execute(
            "DELETE FROM device_parameters WHERE device_id = ? AND name = ?",
            (p["device_id"], p["name"]),
        )
    else:  # pragma: no cover — classification test keeps this unreachable
        raise AssertionError(f"fold handler missing for FOLDED kind {kind!r}")


def _fold_log(source_conn, target_conn) -> set[str]:
    """Fold source's event log into target. Returns the set of kinds seen."""
    seen: set[str] = set()
    for ev in source_conn.execute(
        "SELECT kind, payload_json, song_id, clip_id FROM events ORDER BY seq"
    ).fetchall():
        kind = ev["kind"]
        seen.add(kind)
        if kind in FOLDED:
            _fold_event(
                target_conn, kind, json.loads(ev["payload_json"]),
                ev["song_id"], ev["clip_id"],
            )
        else:
            assert kind in NOT_YET_FOLDED, (
                f"event kind {kind!r} is neither FOLDED nor NOT_YET_FOLDED — "
                "classify it (and teach the fold, or record why not)"
            )
    return seen


# ---------------------------------------------------------------------------
# Fixture: a small but representative song, built through the mutator API,
# deliberately emitting EVERY folded kind (creates, updates, deletes).
# ---------------------------------------------------------------------------


def _build_representative_song(conn) -> None:
    sid = M.create_song(conn, name="replay-smoke", title="Replay Smoke",
                        key="Dm")
    M.create_song(conn, name="replay-smoke", title="Replay Smoke", key="Em")
    M.set_song_timing_mode(conn, song_id=sid, timing_mode="grid")
    M.set_song_timing_mode(conn, song_id=sid, timing_mode="native")
    M.set_song_tuning(conn, song_id=sid, tuning_ref="tunings/gamma.ascl",
                      tuning_data='{"reference_note":60}')

    M.add_tempo_point(conn, song_id=sid, start_bar=1.0, tempo_bpm=122.0)
    M.add_time_signature_point(conn, song_id=sid, start_bar=1.0,
                               numerator=4, denominator=4)

    s1 = M.create_section(conn, song_id=sid, name="verse", start_bar=1.0,
                          end_bar=9.0, energy=0.4)
    s2 = M.create_section(conn, song_id=sid, name="chorus", start_bar=9.0,
                          end_bar=17.0)
    M.update_section(conn, section_id=s2, energy=0.9, color=0xFF8800)
    M.delete_section(conn, section_id=s1)

    t1 = M.create_track(conn, song_id=sid, track_index=1, name="Drums",
                        instrument_uri="hallucinote://kit/909")
    M.create_track(conn, song_id=sid, track_index=1, name="Drums 909",
                   instrument_uri="hallucinote://kit/909")  # -> track_updated
    t2 = M.create_track(conn, song_id=sid, track_index=2, name="Texture",
                        kind="audio")
    t3 = M.create_track(conn, song_id=sid, track_index=3, name="Doomed")
    M.set_track_mixer(conn, track_id=t1, volume=0.8, pan=-0.1)
    M.set_track_routing(conn, track_id=t1, output_routing_kind="master")

    c1 = M.create_clip(conn, track_id=t1, slot=1, length_beats=16.0,
                       name="verse_drums",
                       generator_call={"helper": "drum_pattern",
                                       "args": {"style": "punk"}})
    M.create_clip(conn, track_id=t1, slot=1, length_beats=32.0,
                  name="verse_drums",
                  generator_call={"helper": "drum_pattern",
                                  "args": {"style": "punk"}})  # -> clip_updated
    c2 = M.create_audio_clip(conn, track_id=t2, slot=1, length_beats=16.0,
                             audio_file="assets/texture.wav", gain=0.7,
                             warping=1, warp_mode=4)
    c3 = M.create_clip(conn, track_id=t1, slot=2, length_beats=8.0)
    M.insert_notes(
        conn, clip_id=c1,
        notes=[{"pitch": 36, "start_beats": 0.0, "duration_beats": 0.25,
                "velocity": 110},
               {"pitch": 38, "start_beats": 1.0, "duration_beats": 0.25,
                "velocity": 96, "tags": ["backbeat"]}],
    )
    M.replace_clip_notes(
        conn, clip_id=c1,
        notes=[{"pitch": 36, "start_beats": 0.0, "duration_beats": 0.25,
                "velocity": 118}],
    )

    a1 = M.add_arrangement_clip(conn, song_id=sid, track_id=t1, clip_id=c1,
                                start_bar=1.0, end_bar=5.0)
    a2 = M.add_arrangement_clip(conn, song_id=sid, track_id=t2, clip_id=c2,
                                start_bar=1.0, end_bar=5.0)
    M.add_arrangement_clip(conn, song_id=sid, track_id=t1, clip_id=c1,
                           start_bar=1.0, end_bar=9.0)  # -> updated variant
    M.remove_arrangement_clip(conn, arrangement_clip_id=a2)
    assert a1  # silence unused warning; a1 stays placed

    r1 = M.create_return(conn, song_id=sid, name="room", position=1,
                         volume=0.85)
    M.set_send_level(conn, from_track_id=t1, to_return_id=r1, level=0.25)
    M.set_send_level(conn, from_track_id=t1, to_return_id=r1, level=0.3)

    ch = M.create_device_chain(conn, parent_track_id=t1, position=0)
    d1 = M.create_device(conn, chain_id=ch, position=1, kind="Drum Rack",
                         display_name="909 Core",
                         class_name="DrumGroupDevice",
                         browser_path=["drums", "Drum Rack", "909 Core"])
    M.set_device_parameter(conn, device_id=d1, name="Volume",
                           value_display="-8 dB", value_normalized=0.7)
    M.set_device_parameter(conn, device_id=d1, name="Volume",
                           value_display="-6 dB", value_normalized=0.75)
    M.set_device_parameter(conn, device_id=d1, name="Filter Type",
                           value_display="Lowpass",
                           value_items=["Lowpass", "Highpass"])
    M.set_device_parameter(conn, device_id=d1, name="Doomed Param",
                           value_display="on")
    M.remove_device_parameter(conn, device_id=d1, name="Doomed Param")
    d2 = M.create_device(conn, chain_id=ch, position=2, kind="Saturator",
                         display_name="Saturator")
    M.delete_device(conn, device_id=d2)

    # Deletes last so lineage paths (stable event ids, chunk 2) are exercised
    # against rows that HAVE prior events.
    M.delete_clip(conn, clip_id=c3)
    M._delete_track(conn, track_id=t3)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _all_event_kind_constants() -> set[str]:
    return {
        value
        for name, value in vars(E).items()
        if name.isupper() and isinstance(value, str)
    }


def test_every_event_kind_is_classified():
    """New event kinds cannot silently escape the smoke test: every constant
    in hallucinote.db.events must be FOLDED xor NOT_YET_FOLDED."""
    all_kinds = _all_event_kind_constants()
    classified = FOLDED | set(NOT_YET_FOLDED)
    assert FOLDED.isdisjoint(NOT_YET_FOLDED)
    missing = all_kinds - classified
    assert not missing, (
        f"unclassified event kind(s) {sorted(missing)}: add a fold handler "
        "to test_event_replay_smoke or record why the kind can't fold yet"
    )
    stale = classified - all_kinds
    assert not stale, f"classified kinds no longer exist: {sorted(stale)}"


@pytest.fixture
def folded(tmp_path):
    """(materialized_conn, folded_conn) after building + folding the song."""
    mat = init_db(tmp_path / "materialized.db")
    _build_representative_song(mat)
    fold = init_db(tmp_path / "folded.db")
    seen = _fold_log(mat, fold)
    yield mat, fold, seen
    mat.close()
    fold.close()


def test_fixture_exercises_every_folded_kind(folded):
    """Every fold handler runs against a real emission — no dead handlers."""
    _mat, _fold, seen = folded
    unexercised = FOLDED - seen
    assert not unexercised, (
        f"FOLDED kind(s) never emitted by the fixture: {sorted(unexercised)}"
    )


def test_fold_converges_with_materialized_state(folded):
    mat, fold, _seen = folded
    for table in FOLDED_TABLES:
        cols = [
            r["name"]
            for r in mat.execute(f"PRAGMA table_info({table})").fetchall()
            if r["name"] not in _TS_COLUMNS
        ]
        col_sql = ", ".join(cols)
        mat_rows = sorted(
            tuple(r) for r in mat.execute(
                f"SELECT {col_sql} FROM {table}"
            ).fetchall()
        )
        fold_rows = sorted(
            tuple(r) for r in fold.execute(
                f"SELECT {col_sql} FROM {table}"
            ).fetchall()
        )
        assert mat_rows == fold_rows, (
            f"table {table!r} diverged between the materialized DB and the "
            f"event fold:\n materialized={mat_rows}\n folded={fold_rows}"
        )
        assert mat_rows, f"fixture left table {table!r} empty — not representative"


def test_deletes_converged(folded):
    """The delete/lineage paths: deleted rows are absent from BOTH sides,
    while their events (with stable ids) drove the fold."""
    mat, fold, _seen = folded
    for conn in (mat, fold):
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM tracks WHERE name = 'Doomed'"
        ).fetchone()["n"] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM clips WHERE slot = 2"
        ).fetchone()["n"] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM devices WHERE kind = 'Saturator'"
        ).fetchone()["n"] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM sections WHERE name = 'verse'"
        ).fetchone()["n"] == 0


def test_notes_gap_is_real_not_stale(folded):
    """Honesty check on the documented payload gap: the materialized DB HAS
    notes the fold cannot rebuild. If this ever fails because the fold DB
    gained notes, the payloads got enriched — promote the notes kinds to
    FOLDED and extend the fold."""
    mat, fold, _seen = folded
    assert mat.execute("SELECT COUNT(*) AS n FROM notes").fetchone()["n"] > 0
    assert fold.execute("SELECT COUNT(*) AS n FROM notes").fetchone()["n"] == 0


def test_emit_rejects_unknown_kind(tmp_path):
    """The emit-site half of the exhaustiveness guarantee: `_emit` refuses a
    kind that isn't an events.py constant, so an inline-string kind can't
    even reach the log (the classification tests above guard the constants;
    this guards the wire into them)."""
    conn = init_db(tmp_path / "kinds.db")
    try:
        from hallucinote.db.mutations._core import _emit
        with pytest.raises(ValueError, match="unknown event kind"):
            _emit(conn, "totally_new_kind", {"x": 1})
        # Sanity: E.KINDS is the derived closed set and covers a known kind.
        assert E.SONG_CREATED in E.KINDS
        assert "totally_new_kind" not in E.KINDS
    finally:
        conn.close()
