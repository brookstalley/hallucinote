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


# ---------- W23-B: song annotations ----------


def test_add_annotation_song_scoped(conn, song):
    aid = M.add_annotation(
        conn, song_id=song, kind="stylistic",
        body="track is glitchy lo-fi throughout",
    )
    row = conn.execute("SELECT * FROM annotations WHERE id=?", (aid,)).fetchone()
    assert row["kind"] == "stylistic"
    assert row["body"] == "track is glitchy lo-fi throughout"
    assert row["track_id"] is None
    assert row["start_bar"] is None
    assert row["end_bar"] is None
    last = _events(conn)[-1]
    assert last["kind"] == E.ANNOTATION_ADDED


def test_add_annotation_time_scoped(conn, song):
    aid = M.add_annotation(
        conn, song_id=song, kind="intent",
        body="verse feels like weight getting worse",
        start_bar=17.0, end_bar=33.0,
    )
    row = conn.execute("SELECT * FROM annotations WHERE id=?", (aid,)).fetchone()
    assert row["start_bar"] == 17.0
    assert row["end_bar"] == 33.0
    assert row["track_id"] is None


def test_add_annotation_track_scoped(conn, song, track):
    aid = M.add_annotation(
        conn, song_id=song, track_id=track, kind="todo",
        body="don't sidechain bass on the bridge",
    )
    row = conn.execute("SELECT * FROM annotations WHERE id=?", (aid,)).fetchone()
    assert row["track_id"] == track


def test_add_annotation_open_ended_forward_range(conn, song):
    """end_bar NULL with start_bar set means "active from start_bar onward."""
    aid = M.add_annotation(
        conn, song_id=song, kind="reference",
        body="bass weaves at 95 BPM from here on",
        start_bar=49.0,
    )
    row = conn.execute("SELECT * FROM annotations WHERE id=?", (aid,)).fetchone()
    assert row["start_bar"] == 49.0
    assert row["end_bar"] is None


def test_add_annotation_rejects_invalid_kind(conn, song):
    with pytest.raises(ValueError, match="invalid annotation kind"):
        M.add_annotation(conn, song_id=song, kind="bogus", body="x")


def test_add_annotation_rejects_end_without_start(conn, song):
    with pytest.raises(ValueError, match="end_bar requires start_bar"):
        M.add_annotation(conn, song_id=song, kind="intent", body="x", end_bar=8.0)


def test_add_annotation_rejects_end_le_start(conn, song):
    with pytest.raises(ValueError, match="must be greater than start_bar"):
        M.add_annotation(
            conn, song_id=song, kind="intent", body="x",
            start_bar=8.0, end_bar=8.0,
        )


def test_update_annotation_changes_body_and_kind(conn, song):
    aid = M.add_annotation(conn, song_id=song, kind="todo", body="old")
    M.update_annotation(conn, annotation_id=aid, body="new", kind="intent")
    row = conn.execute("SELECT * FROM annotations WHERE id=?", (aid,)).fetchone()
    assert row["body"] == "new"
    assert row["kind"] == "intent"
    assert _events(conn)[-1]["kind"] == E.ANNOTATION_UPDATED


def test_update_annotation_partial_leaves_others(conn, song, track):
    aid = M.add_annotation(
        conn, song_id=song, track_id=track, kind="intent",
        body="original", start_bar=8.0, end_bar=16.0,
    )
    M.update_annotation(conn, annotation_id=aid, body="revised")
    row = conn.execute("SELECT * FROM annotations WHERE id=?", (aid,)).fetchone()
    assert row["body"] == "revised"
    assert row["kind"] == "intent"
    assert row["start_bar"] == 8.0
    assert row["end_bar"] == 16.0
    assert row["track_id"] == track


def test_update_annotation_rejects_missing(conn):
    with pytest.raises(ValueError, match="not found"):
        M.update_annotation(conn, annotation_id="deadbeef" * 4, body="x")


def test_delete_annotation_removes_row_and_emits(conn, song):
    aid = M.add_annotation(conn, song_id=song, kind="todo", body="ephemeral")
    M.delete_annotation(conn, annotation_id=aid)
    assert conn.execute("SELECT * FROM annotations WHERE id=?", (aid,)).fetchone() is None
    assert _events(conn)[-1]["kind"] == E.ANNOTATION_REMOVED


def test_delete_annotation_missing_is_noop(conn, song):
    """Already-deleted is silent — agent races shouldn't double-emit."""
    pre_count = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    M.delete_annotation(conn, annotation_id="deadbeef" * 4)
    post_count = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    assert post_count == pre_count


def test_song_delete_cascades_annotations(conn, song):
    M.add_annotation(conn, song_id=song, kind="intent", body="x")
    M.add_annotation(conn, song_id=song, kind="todo", body="y")
    conn.execute("DELETE FROM songs WHERE id = ?", (song,))
    n = conn.execute("SELECT COUNT(*) AS n FROM annotations").fetchone()["n"]
    assert n == 0


def test_track_delete_cascades_track_scoped_annotations(conn, song, track):
    """Track-scoped annotations follow the track; song-scoped survive."""
    M.add_annotation(conn, song_id=song, track_id=track, kind="todo", body="track")
    M.add_annotation(conn, song_id=song, kind="intent", body="song")
    conn.execute("DELETE FROM tracks WHERE id = ?", (track,))
    rows = conn.execute("SELECT body FROM annotations").fetchall()
    assert {r["body"] for r in rows} == {"song"}


# ---------- W23-B: annotation queries ----------


def test_get_annotations_for_song_returns_all_scopes(conn, song, track):
    M.add_annotation(conn, song_id=song, kind="intent", body="song-scoped")
    M.add_annotation(conn, song_id=song, kind="intent", body="time-scoped",
                     start_bar=17.0, end_bar=33.0)
    M.add_annotation(conn, song_id=song, track_id=track, kind="todo", body="track-scoped")
    rows = Q.get_annotations_for_song(conn, song)
    bodies = [r["body"] for r in rows]
    # track_id-NULL first, then by start_bar, then created_at.
    assert bodies == ["song-scoped", "time-scoped", "track-scoped"]


def test_get_annotations_for_song_filters_by_kind(conn, song):
    M.add_annotation(conn, song_id=song, kind="intent", body="a")
    M.add_annotation(conn, song_id=song, kind="todo", body="b")
    rows = Q.get_annotations_for_song(conn, song, kind="todo")
    assert [r["body"] for r in rows] == ["b"]


def test_get_annotations_for_track_excludes_song_scoped(conn, song, track):
    M.add_annotation(conn, song_id=song, kind="intent", body="song")
    M.add_annotation(conn, song_id=song, track_id=track, kind="todo", body="track")
    rows = Q.get_annotations_for_track(conn, track)
    assert [r["body"] for r in rows] == ["track"]


def test_get_annotations_at_bar_includes_song_scoped(conn, song):
    """Song-scoped (start_bar NULL) annotations are active at every bar."""
    M.add_annotation(conn, song_id=song, kind="stylistic", body="lo-fi vibe")
    rows = Q.get_annotations_at_bar(conn, song, 17.0)
    assert [r["body"] for r in rows] == ["lo-fi vibe"]


def test_get_annotations_at_bar_half_open_range(conn, song):
    """Range [17, 33) means active at bar 17 inclusive, bar 33 exclusive."""
    M.add_annotation(conn, song_id=song, kind="intent", body="verse",
                     start_bar=17.0, end_bar=33.0)
    assert [r["body"] for r in Q.get_annotations_at_bar(conn, song, 17.0)] == ["verse"]
    assert [r["body"] for r in Q.get_annotations_at_bar(conn, song, 32.99)] == ["verse"]
    assert Q.get_annotations_at_bar(conn, song, 33.0) == []
    assert Q.get_annotations_at_bar(conn, song, 16.99) == []


def test_get_annotations_at_bar_open_ended_forward(conn, song):
    """end_bar NULL = active for every bar ≥ start_bar."""
    M.add_annotation(conn, song_id=song, kind="reference",
                     body="from here on", start_bar=49.0)
    assert [r["body"] for r in Q.get_annotations_at_bar(conn, song, 49.0)] == ["from here on"]
    assert [r["body"] for r in Q.get_annotations_at_bar(conn, song, 100.0)] == ["from here on"]
    assert Q.get_annotations_at_bar(conn, song, 48.99) == []


def test_get_annotations_at_bar_scopes_by_song(conn, song):
    """Another song's annotations don't surface."""
    other_song = M.create_song(conn, name="other", key="Em")
    M.add_annotation(conn, song_id=other_song, kind="intent", body="other")
    M.add_annotation(conn, song_id=song, kind="intent", body="mine")
    rows = Q.get_annotations_at_bar(conn, song, 1.0)
    assert [r["body"] for r in rows] == ["mine"]


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
