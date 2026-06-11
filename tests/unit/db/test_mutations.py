"""Mutator + event-emission round-trip tests."""
from __future__ import annotations

import json
import sqlite3

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.db import events as E


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def track(conn, song):
    return M.create_track(conn, song_id=song, track_index=1, name="Drums", instrument_uri="x")


@pytest.fixture
def clip(conn, track):
    return M.create_clip(conn, track_id=track, slot=1, length_beats=16.0, name="verse_drums")


def _events(conn):
    return conn.execute(
        "SELECT kind, payload_json, actor, reason, request_id FROM events ORDER BY seq"
    ).fetchall()


# ---------- creation chain ----------


def test_create_song_emits_event(conn):
    sid = M.create_song(conn, name="x", key="Dm")
    rows = _events(conn)
    assert len(rows) == 1
    assert rows[0]["kind"] == E.SONG_CREATED
    payload = json.loads(rows[0]["payload_json"])
    assert payload == {"name": "x", "title": None, "key": "Dm",
                       "timing_mode": "native"}
    # song id is a 32-char UUID hex
    assert isinstance(sid, str) and len(sid) == 32 and all(c in "0123456789abcdef" for c in sid)


def test_create_song_accepts_title(conn):
    sid = M.create_song(conn, name="x", title="The Display Name", key="Dm")
    row = Q.get_song(conn, sid)
    assert row["title"] == "The Display Name"
    assert row["name"] == "x"


def test_create_song_rejects_uppercase_slug(conn):
    with pytest.raises(ValueError, match=r"\[a-z0-9_-\]\+"):
        M.create_song(conn, name="HasUpper")


def test_create_song_rejects_spaces_in_slug(conn):
    with pytest.raises(ValueError, match=r"\[a-z0-9_-\]\+"):
        M.create_song(conn, name="has spaces")


def test_create_song_rejects_special_chars_in_slug(conn):
    with pytest.raises(ValueError, match=r"\[a-z0-9_-\]\+"):
        M.create_song(conn, name="has,comma")


def test_create_song_accepts_hyphen_and_underscore(conn):
    sid1 = M.create_song(conn, name="hyphen-slug")
    sid2 = M.create_song(conn, name="under_slug")
    assert Q.get_song(conn, sid1)["name"] == "hyphen-slug"
    assert Q.get_song(conn, sid2)["name"] == "under_slug"


def test_update_tempo_point_emits_update_event(conn, song):
    pid = M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=132.0)
    M.update_tempo_point(conn, point_id=pid, tempo_bpm=130.0)
    rows = Q.get_tempo_map(conn, song)
    assert len(rows) == 1
    assert rows[0]["tempo_bpm"] == pytest.approx(130.0)
    # Latest event should be TEMPO_POINT_UPDATED (not REMOVED + ADDED).
    ev = _events(conn)[-1]
    assert ev["kind"] == E.TEMPO_POINT_UPDATED


def test_update_tempo_point_rejects_unknown_field(conn, song):
    pid = M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=132.0)
    with pytest.raises(ValueError, match="unsupported fields"):
        M.update_tempo_point(conn, point_id=pid, start_bar=2.0)


def test_update_tempo_point_rejects_non_positive_bpm(conn, song):
    pid = M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=132.0)
    with pytest.raises(ValueError, match="must be positive"):
        M.update_tempo_point(conn, point_id=pid, tempo_bpm=-1)


def test_update_time_signature_point_emits_update_event(conn, song):
    pid = M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.update_time_signature_point(conn, point_id=pid, numerator=6, denominator=8)
    rows = Q.get_time_signature_map(conn, song)
    assert rows[0]["numerator"] == 6
    assert rows[0]["denominator"] == 8
    ev = _events(conn)[-1]
    assert ev["kind"] == E.TIME_SIGNATURE_POINT_UPDATED


def test_create_track_emits_event_and_links_to_song(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=2, name="Bass")
    ev = _events(conn)[-1]
    assert ev["kind"] == E.TRACK_CREATED
    payload = json.loads(ev["payload_json"])
    assert payload["track_id"] == tid
    assert payload["track_index"] == 2


def test_create_track_rejects_legacy_return_kind(conn, song):
    """'return' is no longer a valid `tracks.kind` — real returns live in
    the `returns` table. Both the Python TRACK_KINDS guard and the schema
    CHECK reject it; the mutator's pre-INSERT check fires first."""
    with pytest.raises(ValueError, match="invalid kind"):
        M.create_track(
            conn, song_id=song, track_index=99, name="LegacyReturn",
            kind="return",
        )


def test_update_clip_persists_name_and_length_and_emits_event(conn, track):
    cid = M.create_clip(
        conn, track_id=track, slot=1, length_beats=16.0, name="Old",
    )
    M.update_clip(
        conn, clip_id=cid, name="New", length_beats=8.0, actor="sync",
    )
    row = Q.get_clip(conn, cid)
    assert row["name"] == "New"
    assert row["length_beats"] == 8.0
    ev = _events(conn)[-1]
    assert ev["kind"] == E.CLIP_UPDATED
    payload = json.loads(ev["payload_json"])
    assert payload["clip_id"] == cid
    assert payload["track_id"] == track
    assert set(payload["changes"]) == {"name", "length_beats"}
    assert ev["actor"] == "sync"


def test_update_clip_rejects_unsupported_field(conn, track):
    cid = M.create_clip(conn, track_id=track, slot=1, length_beats=8.0)
    with pytest.raises(ValueError, match="unsupported fields"):
        M.update_clip(conn, clip_id=cid, slot=2)  # slot is not mutable here


def test_update_clip_no_changes_is_noop(conn, track):
    cid = M.create_clip(conn, track_id=track, slot=1, length_beats=8.0, name="A")
    before_count = len(_events(conn))
    M.update_clip(conn, clip_id=cid)
    # No write -> no event.
    assert len(_events(conn)) == before_count


def test_create_clip_with_generator_call(conn, track):
    cid = M.create_clip(
        conn,
        track_id=track,
        slot=1,
        length_beats=16.0,
        name="verse_drums",
        section_role="verse",
        generator_call={"fn": "trip_hop_drums", "kwargs": {"bars": 4}},
    )
    row = Q.get_clip(conn, cid)
    assert row["section_role"] == "verse"
    assert json.loads(row["generator_call_json"])["fn"] == "trip_hop_drums"
    ev = _events(conn)[-1]
    assert ev["kind"] == E.CLIP_CREATED


# ---------- audio clips (CLP-AUD1 wave 1) ----------


@pytest.fixture
def audio_track(conn, song):
    return M.create_track(
        conn, song_id=song, track_index=2, name="Stems", kind="audio"
    )


_AUDIO_CLIP_KWARGS = dict(
    slot=1,
    length_beats=16.0,
    audio_file="assets/guitar_take3.wav",
    name="gtr",
    gain=0.85,
    pitch_coarse=-2,
    pitch_fine=12.5,
    warping=1,
    warp_mode=M.WARP_MODES["complex_pro"],
    start_marker=0.0,
    end_marker=64.0,
)


def test_create_audio_clip_persists_wave1_fields_and_emits_event(conn, audio_track):
    cid = M.create_audio_clip(conn, track_id=audio_track, **_AUDIO_CLIP_KWARGS)
    row = Q.get_clip(conn, cid)
    assert row["kind"] == "audio"
    assert row["audio_file"] == "assets/guitar_take3.wav"
    assert row["audio_gain"] == pytest.approx(0.85)
    assert row["pitch_coarse"] == -2
    assert row["pitch_fine"] == pytest.approx(12.5)
    assert row["warping"] == 1
    assert row["warp_mode"] == M.WARP_MODES["complex_pro"]
    # Markers are beats here (warping=1); seconds when warping=0.
    assert row["start_marker"] == 0.0
    assert row["end_marker"] == 64.0
    assert row["length_beats"] == 16.0
    assert row["name"] == "gtr"
    ev = _events(conn)[-1]
    assert ev["kind"] == E.CLIP_CREATED
    payload = json.loads(ev["payload_json"])
    assert payload["clip_id"] == cid
    assert payload["track_id"] == audio_track
    assert payload["slot"] == 1
    assert payload["kind"] == "audio"
    assert payload["audio_file"] == "assets/guitar_take3.wav"
    assert payload["audio_gain"] == pytest.approx(0.85)
    assert payload["pitch_coarse"] == -2
    assert payload["pitch_fine"] == pytest.approx(12.5)
    assert payload["warping"] == 1
    assert payload["warp_mode"] == M.WARP_MODES["complex_pro"]
    assert payload["start_marker"] == 0.0
    assert payload["end_marker"] == 64.0


def test_create_audio_clip_refuses_non_audio_host_track(conn, track):
    # `track` is the default MIDI fixture — audio clips need kind='audio'.
    with pytest.raises(ValueError, match="kind='midi'"):
        M.create_audio_clip(conn, track_id=track, **_AUDIO_CLIP_KWARGS)
    # Refusal happens before any write: no clip row, no event.
    assert conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0] == 0


def test_create_audio_clip_requires_audio_file(conn, audio_track):
    kwargs = dict(_AUDIO_CLIP_KWARGS, audio_file="")
    with pytest.raises(ValueError, match="audio_file is required"):
        M.create_audio_clip(conn, track_id=audio_track, **kwargs)
    assert conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0] == 0


def test_create_audio_clip_is_idempotent_and_updates_in_place(conn, audio_track):
    cid = M.create_audio_clip(conn, track_id=audio_track, **_AUDIO_CLIP_KWARGS)
    assert cid.kind == "created"
    # Same inputs -> unchanged, no event (the create_clip rebuild contract).
    before = len(_events(conn))
    again = M.create_audio_clip(conn, track_id=audio_track, **_AUDIO_CLIP_KWARGS)
    assert again == cid and again.kind == "unchanged"
    assert len(_events(conn)) == before
    # Changed field -> in-place update + CLIP_UPDATED.
    changed = dict(_AUDIO_CLIP_KWARGS, gain=0.5)
    updated = M.create_audio_clip(conn, track_id=audio_track, **changed)
    assert updated == cid and updated.kind == "updated"
    assert Q.get_clip(conn, cid)["audio_gain"] == pytest.approx(0.5)
    ev = _events(conn)[-1]
    assert ev["kind"] == E.CLIP_UPDATED
    assert json.loads(ev["payload_json"])["changes"]["audio_gain"] == pytest.approx(0.5)


def test_create_audio_clip_refuses_existing_midi_clip_in_slot(conn, audio_track):
    # Seed a MIDI row via raw INSERT: chunk 02's create_clip host-kind
    # guard refuses authoring MIDI on an audio track, but legacy rows of
    # that shape can exist — the immutability doctrine holds regardless.
    conn.execute(
        """INSERT INTO clips (id, track_id, slot, length_beats, kind)
           VALUES ('legacy-midi', ?, 1, 4.0, 'midi')""",
        (audio_track,),
    )
    with pytest.raises(ValueError, match="kind is immutable"):
        M.create_audio_clip(conn, track_id=audio_track, **_AUDIO_CLIP_KWARGS)


def test_create_clip_writes_kind_midi_with_null_audio_fields(conn, track):
    cid = M.create_clip(conn, track_id=track, slot=1, length_beats=8.0)
    row = Q.get_clip(conn, cid)
    assert row["kind"] == "midi"
    for col in ("audio_file", "audio_gain", "pitch_coarse", "pitch_fine",
                "warping", "warp_mode", "start_marker", "end_marker"):
        assert row[col] is None
    payload = json.loads(_events(conn)[-1]["payload_json"])
    assert payload["kind"] == "midi"


def test_delete_audio_clip_emits_event_and_removes_row(conn, audio_track):
    cid = M.create_audio_clip(conn, track_id=audio_track, **_AUDIO_CLIP_KWARGS)
    M.delete_clip(conn, clip_id=cid)
    assert Q.get_clip(conn, cid) is None
    assert _events(conn)[-1]["kind"] == E.CLIP_DELETED


# ---------- kind-guards across MIDI-assuming surfaces (CLP-AUD1 C2) ----------


@pytest.fixture
def audio_clip(conn, audio_track):
    return M.create_audio_clip(conn, track_id=audio_track, **_AUDIO_CLIP_KWARGS)


def test_create_clip_refuses_audio_host_track(conn, audio_track):
    # Mirror of create_audio_clip's MIDI-host refusal: Live hosts MIDI
    # clips only on MIDI tracks.
    with pytest.raises(ValueError, match="create_audio_clip"):
        M.create_clip(conn, track_id=audio_track, slot=3, length_beats=4.0)
    assert conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0] == 0


def test_create_clip_refuses_existing_audio_clip_in_slot(conn, song, audio_clip):
    """The idempotent-rebuild path must never silently 'update' an audio
    row as MIDI (flagged in C1). Seed the collision via raw INSERT of an
    audio row on a MIDI track — the host-kind guard fires first on a real
    audio track, but kind immutability must hold independently of it."""
    midi_track = M.create_track(conn, song_id=song, track_index=5, name="Keys")
    conn.execute(
        """INSERT INTO clips (id, track_id, slot, length_beats, kind, audio_file)
           VALUES ('legacy-audio', ?, 1, 4.0, 'audio', 'assets/x.wav')""",
        (midi_track,),
    )
    before = len(_events(conn))
    with pytest.raises(ValueError, match="kind is immutable"):
        M.create_clip(conn, track_id=midi_track, slot=1, length_beats=4.0)
    # Refusal is write-free: the audio row is untouched, no event emitted.
    row = conn.execute(
        "SELECT kind, audio_file FROM clips WHERE id = 'legacy-audio'"
    ).fetchone()
    assert (row["kind"], row["audio_file"]) == ("audio", "assets/x.wav")
    assert len(_events(conn)) == before


def test_update_clip_audio_fields_on_audio_clip(conn, audio_clip):
    M.update_clip(
        conn, clip_id=audio_clip, audio_gain=0.5,
        warp_mode=M.WARP_MODES["beats"], warping=0,
        start_marker=0.25, end_marker=12.0,
    )
    row = Q.get_clip(conn, audio_clip)
    assert row["audio_gain"] == pytest.approx(0.5)
    assert row["warp_mode"] == M.WARP_MODES["beats"]
    assert row["warping"] == 0
    # Markers are seconds now (warping=0) — units travel with `warping`.
    assert row["start_marker"] == pytest.approx(0.25)
    assert row["end_marker"] == pytest.approx(12.0)
    ev = _events(conn)[-1]
    assert ev["kind"] == E.CLIP_UPDATED
    changes = json.loads(ev["payload_json"])["changes"]
    assert changes["audio_gain"] == pytest.approx(0.5)


def test_update_clip_common_fields_still_work_on_audio_clip(conn, audio_clip):
    """The kind-guard must not over-reach: name/length/section_role are
    both-kinds fields."""
    M.update_clip(conn, clip_id=audio_clip, name="gtr2", length_beats=32.0)
    row = Q.get_clip(conn, audio_clip)
    assert row["name"] == "gtr2"
    assert row["length_beats"] == 32.0


def test_update_clip_refuses_audio_fields_on_midi_clip(conn, clip):
    before = Q.get_clip(conn, clip)
    with pytest.raises(ValueError, match="kind='midi'"):
        M.update_clip(conn, clip_id=clip, audio_gain=0.5)
    with pytest.raises(ValueError, match="audio fields"):
        M.update_clip(conn, clip_id=clip, name="ok-too", audio_file="x.wav")
    # Refusal is atomic: the both-kinds field in the mixed call did not land.
    after = Q.get_clip(conn, clip)
    assert after["name"] == before["name"]
    assert after["audio_gain"] is None


def test_update_clip_refuses_kind_change_on_both_kinds(conn, clip, audio_clip):
    for cid in (clip, audio_clip):
        with pytest.raises(ValueError, match="immutable"):
            M.update_clip(conn, clip_id=cid, kind="audio")
    assert Q.get_clip(conn, clip)["kind"] == "midi"
    assert Q.get_clip(conn, audio_clip)["kind"] == "audio"


def test_update_clip_refuses_clearing_audio_file(conn, audio_clip):
    for empty in (None, ""):
        with pytest.raises(ValueError, match="audio_file cannot be cleared"):
            M.update_clip(conn, clip_id=audio_clip, audio_file=empty)
    assert Q.get_clip(conn, audio_clip)["audio_file"] == "assets/guitar_take3.wav"


def test_update_clip_can_repoint_audio_file(conn, audio_clip):
    M.update_clip(conn, clip_id=audio_clip, audio_file="assets/guitar_take4.wav")
    assert Q.get_clip(conn, audio_clip)["audio_file"] == "assets/guitar_take4.wav"


def test_insert_notes_refuses_audio_clip(conn, audio_clip):
    with pytest.raises(ValueError, match="kind='audio'"):
        M.insert_notes(conn, clip_id=audio_clip, notes=[_make_note()])
    assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0


def test_replace_clip_notes_refuses_audio_clip(conn, audio_clip):
    with pytest.raises(ValueError, match="notes live on MIDI clips only"):
        M.replace_clip_notes(conn, clip_id=audio_clip, notes=[_make_note()])
    # The empty-set form is refused too: "this clip's notes are now []"
    # is meaningless for an audio clip.
    with pytest.raises(ValueError, match="kind='audio'"):
        M.replace_clip_notes(conn, clip_id=audio_clip, notes=[])
    assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0


# ---------- notes ----------


def _make_note(pitch=36, start=0.0, dur=0.25, vel=100, tags=None):
    n = {"pitch": pitch, "start_beats": start, "duration_beats": dur, "velocity": vel}
    if tags:
        n["tags"] = tags
    return n


def test_insert_notes_returns_ids_and_emits_event(conn, clip):
    notes = [_make_note(start=0.0), _make_note(start=1.0, tags=["ghost"])]
    ids = M.insert_notes(conn, clip_id=clip, notes=notes)
    assert len(ids) == 2 and all(isinstance(i, str) and len(i) == 32 for i in ids)
    out = Q.get_notes_for_clip(conn, clip)
    assert len(out) == 2
    assert out[1]["tags"] == ["ghost"]
    ev = _events(conn)[-1]
    assert ev["kind"] == E.NOTES_INSERTED
    assert json.loads(ev["payload_json"])["count"] == 2


def test_replace_clip_notes_swaps_full_note_set(conn, clip):
    M.insert_notes(conn, clip_id=clip, notes=[_make_note() for _ in range(5)])
    new_ids = M.replace_clip_notes(
        conn, clip_id=clip, notes=[_make_note(pitch=38), _make_note(pitch=42)]
    )
    out = Q.get_notes_for_clip(conn, clip)
    assert len(out) == 2
    assert {n["pitch"] for n in out} == {38, 42}
    # Old ids gone
    assert all(n["id"] in new_ids for n in out)
    # Event records prev_count and new_count
    last = _events(conn)[-1]
    assert last["kind"] == E.CLIP_NOTES_REPLACED
    p = json.loads(last["payload_json"])
    assert p["prev_count"] == 5 and p["new_count"] == 2


def test_insert_notes_refuses_negative_start_beats(conn, clip):
    """Arc 6 / H4: `apply_feel({0.0: -0.02})` on bar-1's downbeat
    produces `start_beats=-0.02`. The math is correct in isolation
    but Live's MIDI clip has no negative-beat region — the wire layer
    can't represent it. Catch it at the mutator boundary with a
    teaching error pointing at the most common cause."""
    with pytest.raises(ValueError, match="start_beats=-0.02.*negative"):
        M.insert_notes(
            conn, clip_id=clip,
            notes=[_make_note(start=-0.02)],
        )
    # Mutator refusal is transactional — no notes landed.
    assert Q.get_notes_for_clip(conn, clip) == []


def test_insert_notes_accepts_zero_start_beats(conn, clip):
    """Regression guard for H4: start_beats=0.0 is the canonical bar-
    boundary value and must not be falsely rejected by the < 0
    check."""
    ids = M.insert_notes(conn, clip_id=clip, notes=[_make_note(start=0.0)])
    assert len(ids) == 1


def test_replace_clip_notes_refuses_negative_start_beats(conn, clip):
    """The negative-beat refusal is enforced at `_normalize_note` —
    the chokepoint every note-write path passes through. This test
    pins the contract at the `replace_clip_notes` entry point so a
    future refactor that bypasses the chokepoint surfaces here, not
    in a song that suddenly ships invalid clips."""
    M.insert_notes(conn, clip_id=clip, notes=[_make_note(pitch=40)])
    with pytest.raises(ValueError, match="negative"):
        M.replace_clip_notes(
            conn, clip_id=clip,
            notes=[_make_note(pitch=50, start=-0.05)],
        )
    # Original note survives — replace was atomic.
    out = Q.get_notes_for_clip(conn, clip)
    assert len(out) == 1
    assert out[0]["pitch"] == 40


def test_replace_clip_notes_rolls_back_on_failure(conn, clip):
    """Mid-batch validation error must leave the prior notes intact and emit no event.

    Regression for the "with conn:" no-op (autocommit mode) — previously the
    DELETE committed before the INSERT raised, leaving the clip empty.
    """
    original = M.insert_notes(
        conn, clip_id=clip, notes=[_make_note(pitch=40), _make_note(pitch=41)],
    )
    pre_event_count = len(_events(conn))
    # Second note is malformed — `_normalize_note` will raise.
    with pytest.raises(KeyError):
        M.replace_clip_notes(
            conn, clip_id=clip,
            notes=[_make_note(pitch=50), {"start_beats": 0, "duration_beats": 1, "velocity": 80}],
        )
    # Original notes survive intact.
    out = Q.get_notes_for_clip(conn, clip)
    assert len(out) == 2
    assert {n["id"] for n in out} == set(original)
    assert {n["pitch"] for n in out} == {40, 41}
    # No CLIP_NOTES_REPLACED event emitted for the failed call.
    assert len(_events(conn)) == pre_event_count


def test_update_note_partial(conn, clip):
    [nid] = M.insert_notes(conn, clip_id=clip, notes=[_make_note(vel=50)])
    M.update_note(conn, note_id=nid, velocity=110)
    [out] = Q.get_notes_for_clip(conn, clip)
    assert out["velocity"] == 110
    assert out["pitch"] == 36  # unchanged
    ev = _events(conn)[-1]
    assert ev["kind"] == E.NOTE_UPDATED
    assert json.loads(ev["payload_json"])["changes"] == {"velocity": 110}


def test_update_note_rejects_unknown_fields(conn, clip):
    [nid] = M.insert_notes(conn, clip_id=clip, notes=[_make_note()])
    with pytest.raises(ValueError, match="unsupported"):
        M.update_note(conn, note_id=nid, foo="bar")


def test_update_note_tags_serialization(conn, clip):
    [nid] = M.insert_notes(conn, clip_id=clip, notes=[_make_note(tags=["old"])])
    M.update_note(conn, note_id=nid, tags=["new", "ghost"])
    [out] = Q.get_notes_for_clip(conn, clip)
    assert out["tags"] == ["new", "ghost"]


def test_delete_notes(conn, clip):
    ids = M.insert_notes(conn, clip_id=clip, notes=[_make_note(start=i) for i in range(3)])
    M.delete_notes(conn, note_ids=ids[:2])
    out = Q.get_notes_for_clip(conn, clip)
    assert len(out) == 1 and out[0]["id"] == ids[2]
    ev = _events(conn)[-1]
    assert ev["kind"] == E.NOTES_DELETED


def test_delete_notes_sets_event_clip_id(conn, clip):
    """Single-clip delete tags `events.clip_id` so `_latest_actor_for(row_kind='clip')`
    sees the delete as a touch on that clip. Without this, a build-owned clip
    whose only LLM-touch was `delete_notes` falsely tombstone-eligible.
    """
    ids = M.insert_notes(conn, clip_id=clip, notes=[_make_note(start=i) for i in range(2)])
    M.delete_notes(conn, note_ids=ids, actor="llm")
    row = conn.execute(
        "SELECT clip_id, actor FROM events WHERE kind = ? ORDER BY seq DESC LIMIT 1",
        (E.NOTES_DELETED,),
    ).fetchone()
    assert row["clip_id"] == clip
    assert row["actor"] == "llm"
    # Latest-actor lookup (the tombstone-protection path) sees the LLM touch.
    assert M._latest_actor_for(conn, row_kind="clip", row_id=clip) == "llm"


def test_delete_notes_multi_clip_emits_event_per_clip(conn, track):
    """Multi-clip delete emits one NOTES_DELETED event per affected clip so
    every event carries a specific clip_id — the column drives clip-touch
    lookups and would lose granularity if a single event spanned multiple clips.
    """
    clip_a = M.create_clip(conn, track_id=track, slot=1, length_beats=16.0, name="a")
    clip_b = M.create_clip(conn, track_id=track, slot=2, length_beats=16.0, name="b")
    a_ids = M.insert_notes(conn, clip_id=clip_a, notes=[_make_note(start=0)])
    b_ids = M.insert_notes(conn, clip_id=clip_b, notes=[_make_note(start=0)])
    M.delete_notes(conn, note_ids=[*a_ids, *b_ids], actor="llm")
    rows = conn.execute(
        "SELECT clip_id, payload_json FROM events WHERE kind = ? ORDER BY seq",
        (E.NOTES_DELETED,),
    ).fetchall()
    assert len(rows) == 2
    by_clip = {r["clip_id"]: json.loads(r["payload_json"]) for r in rows}
    assert set(by_clip.keys()) == {clip_a, clip_b}
    assert by_clip[clip_a]["note_ids"] == a_ids
    assert by_clip[clip_b]["note_ids"] == b_ids
    assert by_clip[clip_a]["affected_clips"] == [clip_a]
    assert by_clip[clip_b]["affected_clips"] == [clip_b]


def test_update_notes_by_tag_velocity_delta(conn, clip):
    M.insert_notes(
        conn,
        clip_id=clip,
        notes=[
            _make_note(start=0.0, vel=40, tags=["ghost"]),
            _make_note(start=1.0, vel=100),  # no tag
            _make_note(start=2.0, vel=50, tags=["ghost"]),
        ],
    )
    n = M.update_notes_by_tag(conn, clip_id=clip, tag="ghost", velocity_delta=5)
    assert n == 2
    notes = Q.get_notes_for_clip(conn, clip)
    by_start = {round(x["start_beats"], 2): x for x in notes}
    assert by_start[0.0]["velocity"] == 45
    assert by_start[1.0]["velocity"] == 100  # unchanged
    assert by_start[2.0]["velocity"] == 55
    ev = _events(conn)[-1]
    assert ev["kind"] == E.NOTES_BULK_UPDATED


def test_update_notes_by_tag_clamps_velocity(conn, clip):
    M.insert_notes(conn, clip_id=clip, notes=[_make_note(vel=125, tags=["loud"])])
    M.update_notes_by_tag(conn, clip_id=clip, tag="loud", velocity_delta=20)
    [out] = Q.get_notes_for_clip(conn, clip)
    assert out["velocity"] == 127


def test_update_notes_by_tag_requires_one_arg(conn, clip):
    with pytest.raises(ValueError):
        M.update_notes_by_tag(conn, clip_id=clip, tag="x")
    with pytest.raises(ValueError):
        M.update_notes_by_tag(conn, clip_id=clip, tag="x", velocity_delta=1, velocity_set=2)


# ---------- arrangement clips ----------


def test_arrangement_clip_lifecycle(conn, song, track, clip):
    aid = M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1, end_bar=16
    )
    rows = Q.get_arrangement_for_song(conn, song)
    assert len(rows) == 1 and rows[0]["id"] == aid

    M.remove_arrangement_clip(conn, arrangement_clip_id=aid)
    assert Q.get_arrangement_for_song(conn, song) == []
    kinds = [r["kind"] for r in _events(conn)]
    assert kinds[-2:] == [E.ARRANGEMENT_CLIP_ADDED, E.ARRANGEMENT_CLIP_REMOVED]


def test_get_arrangement_for_track_scopes_by_track(conn, song, track, clip):
    """Per-track query returns only this track's rows and includes the
    joined `clip_name`. Used by the pull-side apply path to avoid
    scanning the whole song's arrangement on each call."""
    # Second track on the same song with its own clip + placement.
    other_track = M.create_track(conn, song_id=song, track_index=2, name="Other")
    other_clip = M.create_clip(
        conn, track_id=other_track, slot=1, length_beats=16.0, name="Other Clip"
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=1.0, end_bar=3.0,
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=other_track, clip_id=other_clip,
        start_bar=5.0, end_bar=7.0,
    )

    rows = Q.get_arrangement_for_track(conn, track)
    assert len(rows) == 1
    assert rows[0]["track_id"] == track
    assert rows[0]["clip_id"] == clip
    # Join exposes the clip name so the pull-layer breadcrumb can use it
    # without a second query.
    assert "clip_name" in rows[0].keys()


# ---------- foreign keys / cascades ----------


def test_clip_delete_cascades_to_notes(conn, track):
    cid = M.create_clip(conn, track_id=track, slot=1, length_beats=4.0)
    M.insert_notes(conn, clip_id=cid, notes=[_make_note() for _ in range(3)])
    assert len(Q.get_notes_for_clip(conn, cid)) == 3
    M.delete_clip(conn, clip_id=cid)
    assert Q.get_notes_for_clip(conn, cid) == []


# ---------- ableton sync wiring (sessions + links projection) ----------


def test_link_db_to_ableton_records_in_session(conn, song, track, clip):
    sess = M.create_ableton_session(conn, song_id=song, name="draft")
    M.link_db_to_ableton(
        conn, session_id=sess, db_kind="track", db_id=track, ableton_index=3
    )
    M.link_db_to_ableton(
        conn, session_id=sess, db_kind="clip", db_id=clip, ableton_index=2
    )

    assert Q.get_ableton_link(conn, session_id=sess, db_kind="track", db_id=track) == 3
    assert Q.get_ableton_link(conn, session_id=sess, db_kind="clip", db_id=clip) == 2

    # Core rows are untouched — projection separation
    track_cols = [r[1] for r in conn.execute("PRAGMA table_info(tracks)").fetchall()]
    clip_cols = [r[1] for r in conn.execute("PRAGMA table_info(clips)").fetchall()]
    assert "ableton_track_index" not in track_cols
    assert "ableton_clip_index" not in clip_cols

    kinds = [r["kind"] for r in _events(conn)]
    assert kinds.count(E.ABLETON_LINK_SET) == 2
    assert E.ABLETON_SESSION_CREATED in kinds


def test_link_db_to_ableton_upserts_existing(conn, song, track):
    sess = M.create_ableton_session(conn, song_id=song)
    M.link_db_to_ableton(conn, session_id=sess, db_kind="track", db_id=track, ableton_index=1)
    M.link_db_to_ableton(conn, session_id=sess, db_kind="track", db_id=track, ableton_index=7)
    # Single row, updated value
    rows = conn.execute(
        "SELECT ableton_index FROM ableton_links WHERE session_id=? AND db_kind='track' AND db_id=?",
        (sess, track),
    ).fetchall()
    assert [r["ableton_index"] for r in rows] == [7]


def test_link_db_to_ableton_rejects_unknown_kind(conn, song, track):
    sess = M.create_ableton_session(conn, song_id=song)
    with pytest.raises(ValueError, match="db_kind"):
        M.link_db_to_ableton(
            conn, session_id=sess, db_kind="bogus", db_id=track, ableton_index=0
        )


def test_two_sessions_isolate_bindings(conn, song, track):
    """Same db row, two sessions, two independent ableton indices."""
    s1 = M.create_ableton_session(conn, song_id=song, name="draft")
    s2 = M.create_ableton_session(conn, song_id=song, name="render")
    M.link_db_to_ableton(conn, session_id=s1, db_kind="track", db_id=track, ableton_index=2)
    M.link_db_to_ableton(conn, session_id=s2, db_kind="track", db_id=track, ableton_index=9)
    assert Q.get_ableton_link(conn, session_id=s1, db_kind="track", db_id=track) == 2
    assert Q.get_ableton_link(conn, session_id=s2, db_kind="track", db_id=track) == 9


# ---------- requests + provenance ----------


def test_create_request_returns_uuid_and_emits_event(conn, song):
    rid = M.create_request(
        conn,
        actor="llm",
        intent="add a chorus",
        payload={"section": "chorus"},
        song_id=song,
    )
    assert isinstance(rid, str) and len(rid) == 32
    row = conn.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    assert row["actor"] == "llm" and row["intent"] == "add a chorus"
    ev = _events(conn)[-1]
    assert ev["kind"] == E.REQUEST_CREATED
    assert ev["actor"] == "llm"
    assert ev["request_id"] == rid


def test_create_request_rejects_invalid_actor(conn):
    with pytest.raises(ValueError, match="invalid actor"):
        M.create_request(conn, actor="alien", intent="x")


# ---------- Arc 2 / B3: prompt_text + parent_id + metadata_json ----------


def test_create_request_persists_prompt_text(conn, song):
    rid = M.create_request(
        conn,
        actor="user",
        intent="compose verse",
        kind="compose",
        song_id=song,
        prompt_text="make me a moody verse in Dm",
    )
    row = conn.execute("SELECT prompt_text FROM requests WHERE id=?", (rid,)).fetchone()
    assert row["prompt_text"] == "make me a moody verse in Dm"


def test_create_request_persists_metadata_as_json(conn, song):
    rid = M.create_request(
        conn,
        actor="user",
        intent="push v1",
        kind="push",
        song_id=song,
        metadata={
            "model": "claude-opus-4-7",
            "git_sha": "abcd1234",
            "branch": "feat/arc-2",
        },
    )
    row = conn.execute(
        "SELECT metadata_json FROM requests WHERE id=?", (rid,)
    ).fetchone()
    import json
    parsed = json.loads(row["metadata_json"])
    assert parsed == {
        "model": "claude-opus-4-7",
        "git_sha": "abcd1234",
        "branch": "feat/arc-2",
    }


def test_create_request_threads_parent_id(conn, song):
    """A compose-parent threading a push-child: the agent compose-cycle
    contains a push-cycle, and reading the push back must reveal its parent."""
    compose_rid = M.create_request(
        conn,
        actor="user",
        intent="compose first pass",
        kind="compose",
        song_id=song,
    )
    push_rid = M.create_request(
        conn,
        actor="user",
        intent="push to live",
        kind="push",
        song_id=song,
        parent_id=compose_rid,
    )
    row = conn.execute(
        "SELECT parent_id FROM requests WHERE id=?", (push_rid,)
    ).fetchone()
    assert row["parent_id"] == compose_rid


def test_create_request_rejects_unknown_parent_id(conn, song):
    """Unknown parent_id is a contract violation — fail loudly instead of
    silently writing a dangling FK that breaks audit-trail walks later."""
    with pytest.raises(ValueError, match="invalid parent_id"):
        M.create_request(
            conn,
            actor="user",
            intent="orphan",
            kind="mutate",
            song_id=song,
            parent_id="0" * 32,
        )


def test_create_request_omits_new_columns_when_unset(conn, song):
    """Backwards-compat: callers that don't pass the new fields get NULL
    on all three. Required for pre-Arc-2 callers + the default mutator
    metadata path (M.create_request without explicit provenance args)."""
    rid = M.create_request(conn, actor="user", intent="bare", song_id=song)
    row = conn.execute(
        "SELECT prompt_text, parent_id, metadata_json FROM requests WHERE id=?",
        (rid,),
    ).fetchone()
    assert row["prompt_text"] is None
    assert row["parent_id"] is None
    assert row["metadata_json"] is None


def test_request_context_manager_propagates_new_fields(conn, song):
    """The ergonomic `M.request(...)` context manager must thread the new
    fields through to `create_request` — otherwise compose drivers can't
    use the context-manager surface (which they will in Chunk 3)."""
    compose_rid = M.create_request(
        conn, actor="user", intent="parent", kind="compose", song_id=song
    )
    captured_rid: list[str] = []
    with M.request(
        conn,
        actor="user",
        intent="child cycle",
        kind="mutate",
        song_id=song,
        prompt_text="user typed this",
        parent_id=compose_rid,
        metadata={"model": "test"},
    ) as rid:
        captured_rid.append(rid)
    assert len(captured_rid) == 1
    row = conn.execute(
        """SELECT prompt_text, parent_id, metadata_json, outcome
           FROM requests WHERE id=?""",
        (captured_rid[0],),
    ).fetchone()
    assert row["prompt_text"] == "user typed this"
    assert row["parent_id"] == compose_rid
    import json
    assert json.loads(row["metadata_json"]) == {"model": "test"}
    assert row["outcome"] == "ok"


def test_provenance_metadata_captures_standard_signals():
    """The auto-captured metadata helper must produce a dict with the
    expected keys when the environment supports them. git_sha + branch
    + hostname all hit best-effort probes; a non-git environment drops
    git_sha/branch silently."""
    meta = M.provenance_metadata()
    # Hostname should always succeed.
    assert "hostname" in meta
    # In this repo (we're running tests from a git checkout), git_sha
    # and branch should be present.
    assert "git_sha" in meta
    assert "branch" in meta
    assert isinstance(meta["git_sha"], str) and len(meta["git_sha"]) > 0
    assert isinstance(meta["branch"], str) and len(meta["branch"]) > 0


def test_provenance_metadata_merges_extras():
    meta = M.provenance_metadata(
        model="claude-opus-4-7",
        extra={"driver": "push_cli", "session_id": "abc"},
    )
    assert meta["model"] == "claude-opus-4-7"
    assert meta["driver"] == "push_cli"
    assert meta["session_id"] == "abc"


def test_build_session_auto_captures_metadata(conn):
    """Every compose cycle should get the standard platform context for
    free — without this, build.py callers would have to remember to opt
    in to provenance and most wouldn't."""
    import json

    with M.build_session(conn, song_name="provenance-test") as bs:
        # Drive at least one mutator so the song row exists for tombstone.
        M.create_song(conn, name="provenance-test")
    row = conn.execute(
        "SELECT metadata_json, kind, prompt_text FROM requests WHERE id=?",
        (bs.request_id,),
    ).fetchone()
    assert row is not None
    assert row["kind"] == "compose"
    assert row["metadata_json"] is not None
    meta = json.loads(row["metadata_json"])
    assert "hostname" in meta
    # In CI / git checkout, git fields are present.
    assert "git_sha" in meta or "branch" in meta


def test_build_session_propagates_prompt_text_and_parent(conn):
    """A build session running inside an outer compose cycle should chain
    via parent_id and carry the user's seed prompt."""
    import json

    outer_rid = M.create_request(
        conn,
        actor="user",
        intent="outer compose",
        kind="compose",
    )
    with M.build_session(
        conn,
        song_name="inner-build",
        prompt_text="make me an experimental jazz piece",
        parent_id=outer_rid,
        metadata={"model": "claude-opus-4-7"},
    ) as bs:
        M.create_song(conn, name="inner-build")
    row = conn.execute(
        """SELECT prompt_text, parent_id, metadata_json
           FROM requests WHERE id=?""",
        (bs.request_id,),
    ).fetchone()
    assert row["prompt_text"] == "make me an experimental jazz piece"
    assert row["parent_id"] == outer_rid
    meta = json.loads(row["metadata_json"])
    # Caller-provided model rides through.
    assert meta["model"] == "claude-opus-4-7"
    # And auto-captured fields still present.
    assert "hostname" in meta


def test_added_columns_migration_idempotent_with_existing_db(tmp_path):
    """Run init_db twice — the second call must NOT raise (the ALTER
    is guarded by PRAGMA table_info). This guards against a future
    edit that drops the guard and breaks existing-DB upgrades."""
    from hallucinote.db.connection import init_db

    db_path = tmp_path / "test.db"
    conn1 = init_db(db_path)
    conn1.close()
    # Re-open and re-init — the second init must be a no-op on the schema.
    conn2 = init_db(db_path)
    # Sanity: the new columns are present and queryable.
    rows = conn2.execute("PRAGMA table_info(requests)").fetchall()
    cols = {r["name"] for r in rows}
    assert {"prompt_text", "parent_id", "metadata_json"} <= cols
    conn2.close()


def test_mutator_kwarg_defaults_actor_system_no_request(conn, song):
    """Mutators without explicit metadata default to actor='system' / no request."""
    M.create_track(conn, song_id=song, track_index=2, name="Bass")
    last = _events(conn)[-1]
    assert last["actor"] == "system"
    assert last["request_id"] is None
    assert last["reason"] is None


def test_mutator_metadata_kwargs_propagate_to_event(conn, song):
    rid = M.create_request(conn, actor="user", intent="add bass track", song_id=song)
    M.create_track(
        conn,
        song_id=song,
        track_index=2,
        name="Bass",
        actor="user",
        request_id=rid,
        reason="user asked for a bassline",
    )
    last = _events(conn)[-1]
    assert last["kind"] == E.TRACK_CREATED
    assert last["actor"] == "user"
    assert last["request_id"] == rid
    assert last["reason"] == "user asked for a bassline"


def test_emit_rejects_invalid_actor(conn, song):
    with pytest.raises(ValueError, match="invalid actor"):
        M.create_track(conn, song_id=song, track_index=2, name="x", actor="bogus")


# ---------- W23-A: provenance read surface ----------


def test_list_requests_for_song_orders_most_recent_first(conn, song):
    """Ordering by ts DESC; agent reads the most recent cycle first."""
    rid1 = M.create_request(conn, actor="user", intent="first", song_id=song)
    rid2 = M.create_request(conn, actor="user", intent="second", song_id=song)
    rid3 = M.create_request(conn, actor="user", intent="third", song_id=song)
    rows = Q.list_requests_for_song(conn, song)
    assert [r["id"] for r in rows] == [rid3, rid2, rid1]


def test_list_requests_for_song_filters_by_kind(conn, song):
    """`kind='push'` returns only push-kind requests; other kinds skipped."""
    M.create_request(conn, actor="user", intent="compose v1", kind="compose", song_id=song)
    rid_push = M.create_request(conn, actor="user", intent="push v1", kind="push", song_id=song)
    M.create_request(conn, actor="user", intent="capture", kind="capture", song_id=song)
    rows = Q.list_requests_for_song(conn, song, kind="push")
    assert [r["id"] for r in rows] == [rid_push]


def test_list_requests_for_song_respects_limit(conn, song):
    for i in range(5):
        M.create_request(conn, actor="user", intent=f"r{i}", song_id=song)
    rows = Q.list_requests_for_song(conn, song, limit=2)
    assert len(rows) == 2


def test_list_requests_for_song_scopes_to_song(conn, song):
    """Another song's requests don't bleed in."""
    other_song = M.create_song(conn, name="other", key="Em")
    M.create_request(conn, actor="user", intent="other", song_id=other_song)
    M.create_request(conn, actor="user", intent="mine", song_id=song)
    rows = Q.list_requests_for_song(conn, song)
    assert [r["intent"] for r in rows] == ["mine"]


def test_get_latest_request_for_song_returns_most_recent(conn, song):
    M.create_request(conn, actor="user", intent="old", song_id=song)
    rid_new = M.create_request(conn, actor="user", intent="new", song_id=song)
    latest = Q.get_latest_request_for_song(conn, song)
    assert latest["id"] == rid_new


def test_get_latest_request_for_song_filters_by_kind(conn, song):
    M.create_request(conn, actor="user", intent="compose", kind="compose", song_id=song)
    rid_push = M.create_request(conn, actor="user", intent="push", kind="push", song_id=song)
    M.create_request(conn, actor="user", intent="compose2", kind="compose", song_id=song)
    latest_push = Q.get_latest_request_for_song(conn, song, kind="push")
    assert latest_push["id"] == rid_push


def test_get_latest_request_for_song_returns_none_when_empty(conn, song):
    assert Q.get_latest_request_for_song(conn, song) is None
    assert Q.get_latest_request_for_song(conn, song, kind="push") is None


def test_get_events_for_request_returns_in_seq_order(conn, song):
    """Oldest first — agent reads the cycle's events as a timeline."""
    rid = M.create_request(conn, actor="user", intent="add tracks", song_id=song)
    M.create_track(
        conn, song_id=song, track_index=2, name="Bass",
        actor="user", request_id=rid,
    )
    M.create_track(
        conn, song_id=song, track_index=3, name="Lead",
        actor="user", request_id=rid,
    )
    rows = Q.get_events_for_request(conn, rid)
    seqs = [r["seq"] for r in rows]
    assert seqs == sorted(seqs)


def test_get_events_for_request_excludes_other_requests(conn, song):
    rid1 = M.create_request(conn, actor="user", intent="r1", song_id=song)
    rid2 = M.create_request(conn, actor="user", intent="r2", song_id=song)
    M.create_track(conn, song_id=song, track_index=2, name="A",
                   actor="user", request_id=rid1)
    M.create_track(conn, song_id=song, track_index=3, name="B",
                   actor="user", request_id=rid2)
    rid1_events = Q.get_events_for_request(conn, rid1)
    assert all(e["request_id"] == rid1 for e in rid1_events)
    # rid1's REQUEST_CREATED + the track_created for "A" (2 events).
    assert len(rid1_events) == 2


def test_get_request_event_summary_counts_by_kind(conn, song):
    rid = M.create_request(conn, actor="user", intent="bulk", song_id=song)
    M.create_track(conn, song_id=song, track_index=2, name="A",
                   actor="user", request_id=rid)
    M.create_track(conn, song_id=song, track_index=3, name="B",
                   actor="user", request_id=rid)
    M.create_track(conn, song_id=song, track_index=4, name="C",
                   actor="user", request_id=rid)
    summary = Q.get_request_event_summary(conn, rid)
    assert summary[E.TRACK_CREATED] == 3
    assert summary[E.REQUEST_CREATED] == 1


def test_get_request_event_summary_empty_for_unknown_request(conn):
    """No matching events → empty dict (not an error)."""
    assert Q.get_request_event_summary(conn, "deadbeef" * 4) == {}


# ---------- events.seq ordering ----------


def test_events_seq_is_monotonic(conn, song, track):
    M.create_clip(conn, track_id=track, slot=1, length_beats=4.0)
    M.create_clip(conn, track_id=track, slot=2, length_beats=4.0)
    seqs = [r["seq"] for r in conn.execute("SELECT seq FROM events ORDER BY seq").fetchall()]
    assert seqs == sorted(seqs)
    assert seqs == list(range(1, len(seqs) + 1))


def test_event_id_is_uuid_hex(conn):
    M.create_song(conn, name="x")
    eid = conn.execute("SELECT id FROM events").fetchone()["id"]
    assert isinstance(eid, str) and len(eid) == 32


# ---------- M+1-4: returns mute/solo ----------


def test_create_return_defaults_mute_solo_to_null(conn, song):
    """Schema doesn't supply a DEFAULT for mute/solo (nullable, like
    tracks.mute/solo/arm). Brand-new return rows are NULL until the user
    explicitly sets the field."""
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    row = Q.get_return(conn, rid)
    assert row["mute"] is None
    assert row["solo"] is None


def test_update_return_accepts_mute_solo_and_persists(conn, song):
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    M.update_return(conn, return_id=rid, mute=1, solo=0)
    row = Q.get_return(conn, rid)
    assert row["mute"] == 1
    assert row["solo"] == 0


def test_update_return_mute_solo_emits_return_updated_event(conn, song):
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    M.update_return(conn, return_id=rid, mute=1, reason="test")
    payload = json.loads(_events(conn)[-1]["payload_json"])
    assert payload["changes"] == {"mute": 1}


def test_returns_schema_check_rejects_out_of_range_mute(conn, song):
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE returns SET mute = 2 WHERE id = ?", (rid,))


# ---------- Arc 7 / P7: mutator-level letter-prefix strip ----------


def test_create_return_strips_live_letter_prefix_from_name(conn, song):
    """Arc 7 / P7: `M.create_return` normalizes Live's `<letter>-` slot
    prefix off the name before insert, so a hand-authored snapshot or a
    build.py call passing the prefixed form (e.g. 'A-Reverb') can't
    poison the DB — push then re-emits the suffix and Live re-adds its
    own slot prefix. Idempotent for already-stripped names."""
    rid_a = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    rid_b = M.create_return(conn, song_id=song, name="Delay", position=2)
    rows = {Q.get_return(conn, r)["name"] for r in (rid_a, rid_b)}
    assert rows == {"Reverb", "Delay"}  # both stored without the prefix


def test_update_return_strips_letter_prefix_when_renaming(conn, song):
    """`M.update_return` mirrors create — passing `name='B-Delay'` lands
    'Delay' in the DB. Guards against build.py code paths that round-trip
    a name through Live first."""
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    M.update_return(conn, return_id=rid, name="B-Delay")
    assert Q.get_return(conn, rid)["name"] == "Delay"


def test_update_return_passthrough_when_name_already_stripped(conn, song):
    """Idempotent: a stripped name passes through unchanged. No false
    positives even if a name happens to look prefix-shaped after the
    first character (e.g. 'M-Pad', kept because the regex matches a
    single uppercase letter + hyphen — 'M-Pad' is stripped to 'Pad').
    This test pins the canonical behavior, not the edge."""
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    M.update_return(conn, return_id=rid, name="Reverb")  # no-op rename
    assert Q.get_return(conn, rid)["name"] == "Reverb"


def test_returns_schema_check_rejects_out_of_range_solo(conn, song):
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE returns SET solo = -1 WHERE id = ?", (rid,))


# ---------------------------------------------------------------------------
# W10-F: envelope-target track-kind refusals (D2 master / D3 audio / group)
# ---------------------------------------------------------------------------


def test_create_envelope_mixer_volume_refuses_master_target(conn, song):
    """D2: mixer_volume on the master track has no LOM path (master can't
    host clips). The mutator refuses with a teaching error pointing at the
    sub-bus workaround."""
    master = M.create_track(conn, song_id=song, track_index=0, name="Master",
                            kind="master")
    with pytest.raises(ValueError) as excinfo:
        M.create_envelope(
            conn, song_id=song, target_kind="mixer_volume",
            target_track_id=master,
        )
    msg = str(excinfo.value)
    assert "master" in msg
    assert "sub-bus" in msg
    assert "guides/gaps" in msg


def test_create_envelope_mixer_pan_refuses_master_target(conn, song):
    master = M.create_track(conn, song_id=song, track_index=0, name="Master",
                            kind="master")
    with pytest.raises(ValueError) as excinfo:
        M.create_envelope(
            conn, song_id=song, target_kind="mixer_pan",
            target_track_id=master,
        )
    assert "master" in str(excinfo.value)


def test_create_envelope_mixer_volume_refuses_audio_target(conn, song):
    """D3: audio tracks can't host MIDI session clips in v1, so the routing
    surface for mixer_volume envelopes is unreachable."""
    audio = M.create_track(conn, song_id=song, track_index=3, name="Guitar",
                           kind="audio")
    with pytest.raises(ValueError) as excinfo:
        M.create_envelope(
            conn, song_id=song, target_kind="mixer_volume",
            target_track_id=audio,
        )
    msg = str(excinfo.value)
    assert "audio" in msg
    assert "sub-bus" in msg


def test_create_envelope_send_level_refuses_audio_target(conn, song):
    audio = M.create_track(conn, song_id=song, track_index=3, name="Guitar",
                           kind="audio")
    ret = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    with pytest.raises(ValueError) as excinfo:
        M.create_envelope(
            conn, song_id=song, target_kind="send_level",
            target_track_id=audio, target_send_return_id=ret,
        )
    assert "audio" in str(excinfo.value)


def test_create_envelope_refuses_group_track_target(conn, song):
    """Group tracks in Live are routing-only and host no clips of any kind
    — same failure mode as D3, different teaching message."""
    group = M.create_track(conn, song_id=song, track_index=2, name="Bus",
                           kind="group")
    with pytest.raises(ValueError) as excinfo:
        M.create_envelope(
            conn, song_id=song, target_kind="mixer_volume",
            target_track_id=group,
        )
    assert "group" in str(excinfo.value)


def test_create_envelope_device_parameter_refuses_master_device(conn, song):
    """device_parameter on a device in the master's chain is also D2:
    the routing path through a Clip is unreachable."""
    master = M.create_track(conn, song_id=song, track_index=0, name="Master",
                            kind="master")
    chain = M.create_device_chain(conn, parent_track_id=master, position=0)
    device = M.create_device(
        conn, chain_id=chain, position=1, kind="Compressor",
        display_name="Compressor",
    )
    with pytest.raises(ValueError) as excinfo:
        M.create_envelope(
            conn, song_id=song, target_kind="device_parameter",
            target_device_id=device, parameter_path="Threshold",
        )
    assert "master" in str(excinfo.value)


def test_create_envelope_device_parameter_accepts_midi_track_device(conn, song, track):
    """Positive control: device_parameter on a device whose chain belongs
    to a kind='midi' track is accepted by the mutator (the `track` fixture
    creates kind='midi' by default)."""
    chain = M.create_device_chain(conn, parent_track_id=track, position=0)
    device = M.create_device(
        conn, chain_id=chain, position=1, kind="Operator",
        display_name="Operator",
    )
    env_id = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=device, parameter_path="Volume",
    )
    assert env_id


def test_create_envelope_mixer_volume_accepts_midi_track(conn, song, track):
    """Positive control: kind='midi' is the host kind the v1 routing path
    supports."""
    env_id = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=track,
    )
    assert env_id


def test_create_envelope_clip_cc_unaffected_by_track_kind_check(conn, song, clip):
    """Sanity: clip_cc envelopes target a Clip (not a track), so the W10-F
    track-kind check should NOT fire for them — they're separately blocked
    by the LOM gap at push time, not by D2/D3 at DB time."""
    env_id = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=clip, parameter_path="64",
    )
    assert env_id


# ---------- W18-C reset_song_content (soft reset) ----------


def test_reset_song_content_preserves_tracks_and_returns(conn, song):
    """The whole point: track / return UUIDs survive, so ableton_links
    pointing at them remain valid across the iterate-loop reset."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)

    M.reset_song_content(conn, song_id=song)

    assert Q.get_track(conn, tid)["id"] == tid
    returns_rows = list(Q.get_returns_for_song(conn, song))
    assert any(r["id"] == rid for r in returns_rows)


def test_reset_song_content_preserves_ableton_sessions_and_links(conn, song):
    """The W18-C goal: session_id presented as a durable handle survives
    a soft reset, so the natural compose-iterate loop doesn't break push."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    sess = M.create_ableton_session(conn, song_id=song, name="draft")
    M.link_db_to_ableton(
        conn, session_id=sess, db_kind="track", db_id=tid, ableton_index=5,
    )

    M.reset_song_content(conn, song_id=song)

    assert Q.get_ableton_session(conn, sess) is not None
    assert Q.get_ableton_link(
        conn, session_id=sess, db_kind="track", db_id=tid,
    ) == 5


def test_reset_song_content_wipes_clips_notes_and_arrangement(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=4.0, name="c")
    M.insert_notes(
        conn, clip_id=cid,
        notes=[{"pitch": 36, "start_beats": 0.0,
                "duration_beats": 0.25, "velocity": 100}],
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=tid, clip_id=cid,
        start_bar=1.0, end_bar=2.0,
    )

    counts = M.reset_song_content(conn, song_id=song)

    assert counts["clips"] >= 1
    assert counts["notes"] >= 1
    assert counts["arrangement_clips"] >= 1
    assert conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM arrangement_clips"
    ).fetchone()[0] == 0


def test_reset_song_content_wipes_score_half(conn, song):
    M.create_section(conn, song_id=song, name="verse", start_bar=1.0, end_bar=5.0)
    M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=120.0)
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    M.add_cue_point(conn, song_id=song, position_bar=1.0, name="start")

    counts = M.reset_song_content(conn, song_id=song)

    assert counts["sections"] == 1
    assert counts["tempo_map"] == 1
    assert counts["time_signature_map"] == 1
    assert counts["cue_points"] == 1
    assert conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0] == 0


def test_reset_song_content_emits_event(conn, song):
    """Audit-log invariant: the soft reset emits one song_content_reset
    event with table counts in the payload."""
    M.create_section(conn, song_id=song, name="verse", start_bar=1.0, end_bar=5.0)

    M.reset_song_content(conn, song_id=song, actor="build", reason="test")

    last = conn.execute(
        "SELECT kind, actor, reason, payload_json FROM events "
        "ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert last["kind"] == "song_content_reset"
    assert last["actor"] == "build"
    assert last["reason"] == "test"
    payload = json.loads(last["payload_json"])
    assert payload["counts"]["sections"] == 1


def test_reset_song_content_scoped_to_one_song(conn):
    """Wiping song A's content must not touch song B's."""
    a = M.create_song(conn, name="a", key="C")
    b = M.create_song(conn, name="b", key="G")
    M.create_section(conn, song_id=a, name="A-verse", start_bar=1.0, end_bar=5.0)
    M.create_section(conn, song_id=b, name="B-verse", start_bar=1.0, end_bar=5.0)

    M.reset_song_content(conn, song_id=a)

    b_sections = conn.execute(
        "SELECT name FROM sections WHERE song_id = ?", (b,)
    ).fetchall()
    assert len(b_sections) == 1
    assert b_sections[0]["name"] == "B-verse"


def test_reset_song_content_round_trips_punk_fate_scenario(conn, song):
    """The exact W18-C repro: probe-and-link writes a track link, then
    --reset, then build re-creates the track (same UUID via upsert), then
    a fresh push observes the link is still pointing at a valid track.

    This is the "session_id presented as durable handle must survive the
    iterate-loop" guarantee made by W18-C."""
    # First build pass.
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    sess = M.create_ableton_session(conn, song_id=song, name="draft")
    M.link_db_to_ableton(
        conn, session_id=sess, db_kind="track", db_id=tid, ableton_index=5,
    )

    # User edits build.py and runs --reset.
    M.reset_song_content(conn, song_id=song)

    # Build re-runs create_track with same (song_id, track_index) → upsert
    # path returns the SAME tid.
    tid_again = M.create_track(
        conn, song_id=song, track_index=1, name="Drums", kind="midi",
    )
    # MutatorResult is comparable with == to the string UUID for the
    # tid_again, but the test ergonomic is to compare the raw IDs.
    assert str(tid_again) == str(tid)

    # The ableton_links row survived AND still points at the same valid
    # track UUID. Push planner would skip the create.
    assert Q.get_ableton_link(
        conn, session_id=sess, db_kind="track", db_id=tid,
    ) == 5


def test_reset_song_content_preserves_markdown_refs(conn, song):
    """Decisions / annotations are author-managed, not rebuilt by
    build.py. A soft reset must not wipe them."""
    conn.execute(
        """INSERT INTO markdown_refs
               (path, kind, scope, song_id, content_hash)
           VALUES (?, ?, ?, ?, ?)""",
        ("songs/t/decisions/01-foo.md", "decision", "song", song, "abc123"),
    )
    M.reset_song_content(conn, song_id=song)
    n = conn.execute(
        "SELECT COUNT(*) FROM markdown_refs WHERE song_id = ?", (song,)
    ).fetchone()[0]
    assert n == 1


# ---------- M1-C replace_drum_pad_mappings ----------


@pytest.fixture
def drum_device(conn, song):
    """A Drum Rack device on a midi track, ready for pad-mapping inserts."""
    tid = M.create_track(
        conn, song_id=song, track_index=1, name="Drums", kind="midi",
    )
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    return M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="Drum Rack", display_name="Late Nite Kit",
    )


def test_replace_drum_pad_mappings_inserts_rows_and_emits_event(conn, song, drum_device):
    ids = M.replace_drum_pad_mappings(
        conn, device_id=drum_device, mappings=[
            {"chain_name": "Kick Drum", "midi_note": 36},
            {"chain_name": "Snare", "midi_note": 38},
            {"chain_name": "Closed Hat", "midi_note": 42},
        ],
    )
    assert len(ids) == 3
    rows = Q.get_drum_pad_mappings(conn, drum_device)
    assert [(r["chain_name"], r["midi_note"]) for r in rows] == [
        ("Kick Drum", 36), ("Snare", 38), ("Closed Hat", 42),
    ]
    events = [e for e in _events(conn) if e["kind"] == E.DRUM_PAD_MAPPINGS_REPLACED]
    assert len(events) == 1
    payload = json.loads(events[0]["payload_json"])
    assert payload["device_id"] == drum_device
    assert payload["prev_count"] == 0
    assert payload["new_count"] == 3


def test_replace_drum_pad_mappings_idempotent_no_event(conn, drum_device):
    """Re-replacing with identical content is a no-op — no second event."""
    M.replace_drum_pad_mappings(
        conn, device_id=drum_device, mappings=[
            {"chain_name": "Kick", "midi_note": 36},
        ],
    )
    n_before = len([e for e in _events(conn) if e["kind"] == E.DRUM_PAD_MAPPINGS_REPLACED])
    M.replace_drum_pad_mappings(
        conn, device_id=drum_device, mappings=[
            {"chain_name": "Kick", "midi_note": 36},
        ],
    )
    n_after = len([e for e in _events(conn) if e["kind"] == E.DRUM_PAD_MAPPINGS_REPLACED])
    assert n_after == n_before


def test_replace_drum_pad_mappings_replaces_existing_rows_atomically(conn, drum_device):
    M.replace_drum_pad_mappings(
        conn, device_id=drum_device, mappings=[
            {"chain_name": "Old Kick", "midi_note": 36},
        ],
    )
    M.replace_drum_pad_mappings(
        conn, device_id=drum_device, mappings=[
            {"chain_name": "New Kick", "midi_note": 36},
            {"chain_name": "New Snare", "midi_note": 40},
        ],
    )
    rows = Q.get_drum_pad_mappings(conn, drum_device)
    assert [(r["chain_name"], r["midi_note"]) for r in rows] == [
        ("New Kick", 36), ("New Snare", 40),
    ]


def test_replace_drum_pad_mappings_rejects_out_of_range_midi(conn, drum_device):
    with pytest.raises(ValueError, match="MIDI range"):
        M.replace_drum_pad_mappings(
            conn, device_id=drum_device, mappings=[
                {"chain_name": "Bad Pad", "midi_note": 128},
            ],
        )


def test_replace_drum_pad_mappings_rejects_empty_chain_name(conn, drum_device):
    with pytest.raises(ValueError, match="chain_name"):
        M.replace_drum_pad_mappings(
            conn, device_id=drum_device, mappings=[
                {"chain_name": "", "midi_note": 36},
            ],
        )


def test_replace_drum_pad_mappings_cascade_on_device_delete(conn, drum_device):
    """FK ON DELETE CASCADE: deleting the device wipes its pad mappings."""
    M.replace_drum_pad_mappings(
        conn, device_id=drum_device, mappings=[
            {"chain_name": "Kick", "midi_note": 36},
        ],
    )
    # Manual delete to test the FK behavior — production code goes through
    # device-cascade paths that the schema already exercises.
    conn.execute("DELETE FROM devices WHERE id = ?", (drum_device,))
    conn.commit()
    rows = Q.get_drum_pad_mappings(conn, drum_device)
    assert rows == []


# ---------- E3: devices.browser_path_json + W13-A v1.0 fallback identity ----------


def test_create_device_persists_browser_path_json(conn, song, track):
    """E3 (W13-A v1.0): browser_path is JSON-encoded into the new column.
    The path captures vendor / pack scope at original-load time so the push
    planner can fall back to a path-scoped search when the per-machine
    preset_uri doesn't resolve on a different machine."""
    chain_id = M.create_device_chain(conn, parent_track_id=track, position=0)
    dev_id = M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="Massive X", display_name="FatBass",
        preset_uri="query:Plugin#FileId_9999",
        browser_path=["plug-ins", "Native Instruments", "Massive X", "FatBass"],
    )
    row = Q.get_device(conn, dev_id)
    stored = row["browser_path_json"]
    assert stored is not None
    assert json.loads(stored) == [
        "plug-ins", "Native Instruments", "Massive X", "FatBass",
    ]


def test_create_device_browser_path_round_trips_in_event(conn, song, track):
    """The DEVICE_CREATED event surfaces browser_path so request-replay
    consumers can reconstruct the snapshot's fallback identity."""
    chain_id = M.create_device_chain(conn, parent_track_id=track, position=0)
    M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="Operator", display_name="Operator",
        browser_path=["instruments", "Operator", "Bass", "Sub Bass"],
    )
    rows = [e for e in _events(conn) if e["kind"] == E.DEVICE_CREATED]
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["browser_path"] == [
        "instruments", "Operator", "Bass", "Sub Bass",
    ]


def test_create_device_browser_path_idempotent_no_event(conn, song, track):
    """Re-create with identical browser_path is a no-op — the idempotency
    tuple includes browser_path_json so no spurious second event."""
    chain_id = M.create_device_chain(conn, parent_track_id=track, position=0)
    M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator",
        display_name="Operator",
        browser_path=["instruments", "Operator", "Bass", "Sub Bass"],
    )
    n_before = len([e for e in _events(conn) if e["kind"] == E.DEVICE_CREATED])
    M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator",
        display_name="Operator",
        browser_path=["instruments", "Operator", "Bass", "Sub Bass"],
    )
    n_after = len([e for e in _events(conn) if e["kind"] == E.DEVICE_CREATED])
    assert n_after == n_before


def test_create_device_browser_path_change_emits_update_event(conn, song, track):
    """Replaying with a different browser_path triggers a DEVICE_CREATED
    update event — the column participates in change detection."""
    chain_id = M.create_device_chain(conn, parent_track_id=track, position=0)
    M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator",
        display_name="Operator",
        browser_path=["instruments", "Operator", "Bass", "Sub Bass"],
    )
    M.create_device(
        conn, chain_id=chain_id, position=1, kind="Operator",
        display_name="Operator",
        browser_path=["instruments", "Operator", "Lead", "Bell Lead"],
    )
    rows = [e for e in _events(conn) if e["kind"] == E.DEVICE_CREATED]
    assert len(rows) == 2
    p2 = json.loads(rows[1]["payload_json"])
    assert p2["browser_path"] == [
        "instruments", "Operator", "Lead", "Bell Lead",
    ]
    assert p2["result_kind"] == "updated"


def test_create_device_rejects_bad_browser_path_shapes(conn, song, track):
    """Bad shapes raise ValueError — empty list, non-list, non-string elements."""
    chain_id = M.create_device_chain(conn, parent_track_id=track, position=0)
    with pytest.raises(ValueError, match="browser_path"):
        M.create_device(
            conn, chain_id=chain_id, position=1, kind="Op",
            display_name="Op", browser_path=[],
        )
    with pytest.raises(ValueError, match="browser_path"):
        M.create_device(
            conn, chain_id=chain_id, position=1, kind="Op",
            display_name="Op", browser_path=["a", ""],
        )
    with pytest.raises(ValueError, match="browser_path"):
        M.create_device(
            conn, chain_id=chain_id, position=1, kind="Op",
            display_name="Op", browser_path=[1, 2, 3],  # type: ignore[list-item]
        )


# ---------- E1: value_items capture + create_enum_envelope ----------


_AMP_TYPE_ITEMS = (
    "Clean", "Boost", "Blues", "Heavy", "Smith", "Lead", "Bass",
)


@pytest.fixture
def amp_device(conn, song):
    """Amp-shaped device on a midi track, ready for enum-envelope authoring."""
    tid = M.create_track(
        conn, song_id=song, track_index=1, name="Guitar", kind="midi",
    )
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    return M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="Amp", display_name="Amp",
    )


def test_set_device_parameter_persists_value_items_json(conn, amp_device):
    """E1 schema lift: value_items round-trips through the mutator."""
    M.set_device_parameter(
        conn, device_id=amp_device, name="Amp Type",
        value_display="Clean", value_normalized=None,
        value_items=_AMP_TYPE_ITEMS,
    )
    row = conn.execute(
        "SELECT value_items_json FROM device_parameters "
        "WHERE device_id = ? AND name = ?",
        (amp_device, "Amp Type"),
    ).fetchone()
    assert row is not None
    items = json.loads(row["value_items_json"])
    assert items == list(_AMP_TYPE_ITEMS)


def test_set_device_parameter_value_items_unchanged_is_no_op(conn, amp_device):
    """Idempotency: re-setting the same (display, normalized, items)
    triple yields kind='unchanged' and emits no second event."""
    M.set_device_parameter(
        conn, device_id=amp_device, name="Amp Type",
        value_display="Clean", value_items=_AMP_TYPE_ITEMS,
    )
    before = len([
        e for e in _events(conn) if e["kind"] == E.DEVICE_PARAMETER_SET
    ])
    result = M.set_device_parameter(
        conn, device_id=amp_device, name="Amp Type",
        value_display="Clean", value_items=_AMP_TYPE_ITEMS,
    )
    after = len([
        e for e in _events(conn) if e["kind"] == E.DEVICE_PARAMETER_SET
    ])
    assert after == before
    assert result.kind == "unchanged"


def test_set_device_parameter_value_items_change_updates(conn, amp_device):
    """Updating just the value_items (display + normalized unchanged)
    still triggers an update — the cardinality is part of the row's
    state, not metadata."""
    M.set_device_parameter(
        conn, device_id=amp_device, name="Amp Type",
        value_display="Clean", value_items=("Clean", "Heavy"),
    )
    result = M.set_device_parameter(
        conn, device_id=amp_device, name="Amp Type",
        value_display="Clean", value_items=_AMP_TYPE_ITEMS,
    )
    assert result.kind == "updated"


def test_set_device_parameter_omits_value_items_for_continuous(conn, amp_device):
    """Continuous params get value_items=None — column stays NULL."""
    M.set_device_parameter(
        conn, device_id=amp_device, name="Bass",
        value_display="0.7", value_normalized=0.7,
    )
    row = conn.execute(
        "SELECT value_items_json FROM device_parameters "
        "WHERE device_id = ? AND name = ?",
        (amp_device, "Bass"),
    ).fetchone()
    assert row["value_items_json"] is None


def test_set_device_parameter_rejects_empty_value_items(conn, amp_device):
    """E1 Critic paper-cut: empty value_items=[] used to silently coerce
    to NULL, asymmetric with M.create_enum_envelope's kwarg path which
    raises on []. Both paths now raise — callers must pass None for
    continuous params or a non-empty list for enum params.
    """
    with pytest.raises(ValueError) as exc:
        M.set_device_parameter(
            conn, device_id=amp_device, name="Amp Type",
            value_display="Clean", value_items=[],
        )
    assert "value_items=[]" in str(exc.value)
    assert "non-empty" in str(exc.value)


def test_create_enum_envelope_resolves_via_snapshot(conn, amp_device):
    """Primary path: helper looks up value_items from the captured
    device-parameter snapshot. Author writes enum names; helper stores
    numeric indices."""
    M.set_device_parameter(
        conn, device_id=amp_device, name="Amp Type",
        value_display="Clean", value_items=_AMP_TYPE_ITEMS,
    )
    env_id = M.create_enum_envelope(
        conn,
        device_id=amp_device,
        parameter_name="Amp Type",
        breakpoints=[
            {"time_beats": 0.0, "value": "Clean"},
            {"time_beats": 32.0, "value": "Heavy"},
        ],
    )
    rows = conn.execute(
        """SELECT time_beats, value, curve_kind FROM automation_breakpoints
           WHERE envelope_id = ? ORDER BY time_beats""",
        (env_id,),
    ).fetchall()
    assert [(r["time_beats"], r["value"], r["curve_kind"]) for r in rows] == [
        (0.0, 0.0, "hold"),     # Clean = index 0
        (32.0, 3.0, "hold"),    # Heavy = index 3
    ]


def test_create_enum_envelope_escape_hatch_via_kwarg(conn, amp_device):
    """Escape hatch: when the snapshot lacks value_items (param not
    captured yet), the helper accepts an explicit kwarg."""
    env_id = M.create_enum_envelope(
        conn,
        device_id=amp_device,
        parameter_name="Amp Type",
        breakpoints=[{"time_beats": 0.0, "value": "Heavy"}],
        value_items=_AMP_TYPE_ITEMS,
    )
    rows = conn.execute(
        "SELECT value FROM automation_breakpoints WHERE envelope_id = ?",
        (env_id,),
    ).fetchall()
    assert [r["value"] for r in rows] == [3.0]


def test_create_enum_envelope_refuses_uncaptured_param(conn, amp_device):
    """No snapshot row + no kwarg → teaching error pointing at pull /
    escape hatch."""
    with pytest.raises(ValueError, match="not captured"):
        M.create_enum_envelope(
            conn,
            device_id=amp_device,
            parameter_name="Amp Type",
            breakpoints=[{"time_beats": 0.0, "value": "Clean"}],
        )


def test_create_enum_envelope_refuses_non_enum_snapshot(conn, amp_device):
    """Snapshot row exists but value_items_json is NULL — distinguished
    from "not captured" (per the 'enumerate every state' learning).
    Surfaces a teaching error mentioning both possibilities (not enum,
    or pre-E1 capture) so the agent can pick the right remedy."""
    M.set_device_parameter(
        conn, device_id=amp_device, name="Bass",
        value_display="0.5", value_normalized=0.5,
    )
    with pytest.raises(ValueError, match="value_items"):
        M.create_enum_envelope(
            conn,
            device_id=amp_device,
            parameter_name="Bass",
            breakpoints=[{"time_beats": 0.0, "value": "Loud"}],
        )


def test_create_enum_envelope_refuses_unknown_enum_name(conn, amp_device):
    M.set_device_parameter(
        conn, device_id=amp_device, name="Amp Type",
        value_display="Clean", value_items=_AMP_TYPE_ITEMS,
    )
    with pytest.raises(ValueError, match="Distortion"):
        M.create_enum_envelope(
            conn,
            device_id=amp_device,
            parameter_name="Amp Type",
            breakpoints=[{"time_beats": 0.0, "value": "Distortion"}],
        )


def test_create_enum_envelope_refuses_numeric_value(conn, amp_device):
    """The helper is a compose-time string→numeric resolver; numeric
    values must go through create_envelope + replace_breakpoints
    directly."""
    M.set_device_parameter(
        conn, device_id=amp_device, name="Amp Type",
        value_display="Clean", value_items=_AMP_TYPE_ITEMS,
    )
    with pytest.raises(ValueError, match="enum names"):
        M.create_enum_envelope(
            conn,
            device_id=amp_device,
            parameter_name="Amp Type",
            breakpoints=[{"time_beats": 0.0, "value": 3.0}],
        )


def test_create_enum_envelope_emits_envelope_and_breakpoint_events(
    conn, amp_device,
):
    """Mutator discipline: every state change emits a paired event. The
    helper composes create_envelope + replace_breakpoints, so both
    events should appear in the audit trail."""
    M.set_device_parameter(
        conn, device_id=amp_device, name="Amp Type",
        value_display="Clean", value_items=_AMP_TYPE_ITEMS,
    )
    M.create_enum_envelope(
        conn,
        device_id=amp_device,
        parameter_name="Amp Type",
        breakpoints=[
            {"time_beats": 0.0, "value": "Clean"},
            {"time_beats": 16.0, "value": "Heavy"},
        ],
    )
    kinds = [e["kind"] for e in _events(conn)]
    assert E.ENVELOPE_CREATED in kinds
    assert E.BREAKPOINTS_REPLACED in kinds


def test_create_enum_envelope_idempotent_on_replay(conn, amp_device):
    """Re-running with the same breakpoints is a no-op on the breakpoint
    side (replace_breakpoints' idempotency), and the envelope create
    returns the existing id (create_envelope's identity check)."""
    M.set_device_parameter(
        conn, device_id=amp_device, name="Amp Type",
        value_display="Clean", value_items=_AMP_TYPE_ITEMS,
    )
    first = M.create_enum_envelope(
        conn, device_id=amp_device, parameter_name="Amp Type",
        breakpoints=[
            {"time_beats": 0.0, "value": "Clean"},
            {"time_beats": 16.0, "value": "Heavy"},
        ],
    )
    second = M.create_enum_envelope(
        conn, device_id=amp_device, parameter_name="Amp Type",
        breakpoints=[
            {"time_beats": 0.0, "value": "Clean"},
            {"time_beats": 16.0, "value": "Heavy"},
        ],
    )
    assert first == second


def test_audio_field_domains_validated_at_authoring_time(conn):
    """CLP-AUD1 cumulative-Critic W3: LOM value domains teach at the mutator,
    not at CLP-AUD2 push time inside Live."""
    sid = M.create_song(conn, name="s")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="Vox",
                         kind="audio")

    def make(**kw):
        return M.create_audio_clip(
            conn, track_id=tid, slot=1, length_beats=4.0,
            audio_file="assets/a.wav", **kw,
        )

    with pytest.raises(ValueError, match="LINEAR"):
        make(gain=1.5)
    with pytest.raises(ValueError, match="semitones"):
        make(pitch_coarse=60)
    with pytest.raises(ValueError, match="cents"):
        make(pitch_fine=-51.0)
    with pytest.raises(ValueError, match="warping"):
        make(warping=2)
    with pytest.raises(ValueError, match="not a Live warp mode"):
        make(warp_mode=99)
    # No row, no event leaked from the refusals.
    assert conn.execute("SELECT COUNT(*) AS n FROM clips").fetchone()["n"] == 0

    # Boundary values pass; update_clip validates the same domains.
    cid = make(gain=1.0, pitch_coarse=-48, pitch_fine=50.0, warping=1,
               warp_mode=M.WARP_MODES["complex_pro"])
    with pytest.raises(ValueError, match="not a Live warp mode"):
        M.update_clip(conn, clip_id=cid, warp_mode=42)
    M.update_clip(conn, clip_id=cid, audio_gain=0.0)
    row = conn.execute("SELECT audio_gain FROM clips WHERE id = ?",
                       (cid,)).fetchone()
    assert row["audio_gain"] == 0.0
