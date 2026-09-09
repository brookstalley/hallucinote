"""Tests for ``push_cli`` (CLI bridge) + ``probe_and_link`` (Python helper).

The CLI tests invoke ``push_cli.main(argv)`` directly and capture
stdout via ``capsys`` — avoids subprocess + Python import overhead.
The probe-and-link tests exercise the Python helper directly.

End-to-end CLI drive simulates the skill's flow: probe-and-link →
enumerate phases → for each phase emit a plan + synthesize results +
apply. Exercises the full fourteen-phase loop through the CLI surface.
"""
from __future__ import annotations

import json

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push, push_cli


_LINK_FIELDS: dict[str, str] = {
    "track": "track_index",
    "return": "return_index",
    "clip": "clip_index",
    "device": "device_index",
    "arrangement_clip": "arrangement_clip_index",
    "envelope": "envelope_index",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "psong.db"


@pytest.fixture
def conn(db_path):
    c = init_db(db_path)
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


def _synthesize_results(plan: push.PushPlan, counters: dict[str, int]) -> list[dict]:
    """Mirror of test_push_song's fake-apply: build synthetic ok results
    with monotonic indexes per link-kind."""
    results = []
    for call in plan.calls:
        kind = call.key.partition(":")[0]
        body: dict = {}
        if kind in _LINK_FIELDS:
            counters[kind] = counters.get(kind, 0) + 1
            body[_LINK_FIELDS[kind]] = counters[kind]
        results.append({
            "key": call.key, "ok": True, "tool": call.tool, "result": body,
        })
    return results


# ---------------------------------------------------------------------------
# probe_and_link (Python helper)
# ---------------------------------------------------------------------------


def test_probe_and_link_matches_track_by_name(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    live_tracks = [{"track_index": 3, "name": "Drums", "kind": "midi"}]
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=live_tracks, live_returns=[],
    )
    assert result.matched_tracks == [
        {"db_id": tid, "name": "Drums", "ableton_index": 3},
    ]
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=tid,
    ) == 3


def test_probe_and_link_skips_master_tracks(conn, song, session):
    """Live's ableton_track(action='list') never includes master. The
    DB's master row gets no link — master mixer state is reached via
    ableton_session(set_master_property), not by track index."""
    M.create_track(conn, song_id=song, track_index=0, name="Master", kind="master")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Master", "kind": "audio"}],
        live_returns=[],
    )
    assert result.matched_tracks == []
    assert result.unmatched_db_tracks == []


def test_probe_and_link_unmatched_db_track_listed(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Bass", "kind": "midi"}],
        live_returns=[],
    )
    assert result.matched_tracks == []
    assert result.unmatched_db_tracks == [{"db_id": tid, "name": "Drums"}]
    assert result.unmatched_live_tracks == [{"track_index": 1, "name": "Bass"}]


def test_probe_and_link_strips_return_slot_prefix(conn, song, session):
    """W4-C: DB stores suffix-only return names ('Reverb'); Live's
    list emits the slot-prefixed form ('A-Reverb'). Strip before matching."""
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[],
        live_returns=[{"return_index": 1, "name": "A-Reverb"}],
    )
    assert result.matched_returns == [
        {"db_id": rid, "name": "Reverb", "ableton_index": 1},
    ]
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="return", db_id=rid,
    ) == 1


def test_probe_and_link_strips_render_analyzer_suffix_on_returns(conn, song, session):
    """SYN-RENDER-RELINK: `ableton_render`'s analyzer auto-load renames RETURN
    tracks (appends ` | HallucinoteAnalyzer`), which defeated probe-and-link's name
    match and silently broke DB↔Live return relink after any render. The live-return
    normalizer must strip that render-appended suffix (and the slot prefix) so the
    return still matches its DB row."""
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[],
        live_returns=[{"return_index": 1, "name": "A-Reverb | HallucinoteAnalyzer"}],
    )
    assert result.matched_returns == [
        {"db_id": rid, "name": "Reverb", "ableton_index": 1},
    ]
    assert result.unmatched_db_returns == []
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="return", db_id=rid,
    ) == 1


def test_probe_and_link_warns_on_duplicate_live_track_names(conn, song, session):
    """Two Live tracks with the same name → link to the first, note
    the ambiguity so the user can rename."""
    M.create_track(conn, song_id=song, track_index=1, name="FX", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[
            {"track_index": 1, "name": "FX", "kind": "midi"},
            {"track_index": 2, "name": "FX", "kind": "midi"},
        ],
        live_returns=[],
    )
    assert result.matched_tracks[0]["ableton_index"] == 1
    assert any("FX" in n and "match" in n for n in result.notes), result.notes


def test_probe_and_link_notes_kind_mismatch(conn, song, session):
    """DB midi vs Live audio with same name: link is still written
    (name match wins) but a kind-mismatch note surfaces. Push will
    still create+populate notes happily; if Live's audio track
    rejects MIDI clip writes, that's the next step's problem."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Drums", "kind": "audio"}],
        live_returns=[],
    )
    assert result.matched_tracks  # link still written
    assert any("kind" in n for n in result.notes), result.notes


def test_probe_and_link_flags_case_near_match_for_tracks(conn, song, session):
    """W5-B: DB 'Drums' vs Live 'drums' both end up unmatched (the
    probe doesn't auto-link case-variants); a note surfaces so the
    user spots the rename drift before phase 3 creates a duplicate."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 7, "name": "drums", "kind": "midi"}],
        live_returns=[],
    )
    assert result.matched_tracks == []
    assert result.unmatched_db_tracks == [
        {"db_id": result.unmatched_db_tracks[0]["db_id"], "name": "Drums"},
    ]
    assert result.unmatched_live_tracks == [{"track_index": 7, "name": "drums"}]
    assert any(
        "Drums" in n and "drums" in n and "case differs" in n
        for n in result.notes
    ), result.notes


def test_probe_and_link_no_near_match_note_when_exact_match(conn, song, session):
    """Exact case match → matched, no near-match note."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Drums", "kind": "midi"}],
        live_returns=[],
    )
    assert result.matched_tracks
    assert not any("case differs" in n for n in result.notes)


def test_probe_and_link_no_near_match_note_when_names_unrelated(conn, song, session):
    """Different names with no case-insensitive overlap → no
    near-match note (avoid false-positive noise)."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Bass", "kind": "midi"}],
        live_returns=[],
    )
    assert not any("case differs" in n for n in result.notes)


def test_probe_and_link_flags_multiple_case_near_matches(conn, song, session):
    """Multiple unmatched-on-both-sides case-variant pairs each get
    their own note — agent sees the full list, not just the first."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.create_track(conn, song_id=song, track_index=2, name="Bass", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[
            {"track_index": 1, "name": "drums", "kind": "midi"},
            {"track_index": 2, "name": "BASS", "kind": "midi"},
        ],
        live_returns=[],
    )
    assert result.matched_tracks == []
    near_match_notes = [n for n in result.notes if "case differs" in n]
    assert len(near_match_notes) == 2
    assert any("Drums" in n and "drums" in n for n in near_match_notes)
    assert any("Bass" in n and "BASS" in n for n in near_match_notes)


def test_probe_and_link_flags_case_near_match_for_returns(conn, song, session):
    """W5-B for returns: DB 'Reverb' vs Live 'A-reverb' (after slot
    strip → 'reverb') near-matches. Both stay unmatched; note surfaces."""
    M.create_return(conn, song_id=song, name="Reverb", position=1)
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[],
        live_returns=[{"return_index": 1, "name": "A-reverb"}],
    )
    assert result.matched_returns == []
    assert result.unmatched_db_returns
    assert result.unmatched_live_returns
    assert any(
        "Reverb" in n and "A-reverb" in n and "case differs" in n
        for n in result.notes
    ), result.notes


def test_probe_and_link_is_idempotent(conn, song, session):
    """Second invocation with the same inputs no-ops (upsert by
    (session, db_kind, db_id))."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    live = [{"track_index": 5, "name": "Drums", "kind": "midi"}]
    push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=live, live_returns=[],
    )
    push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=live, live_returns=[],
    )
    rows = conn.execute(
        "SELECT COUNT(*) AS n FROM ableton_links WHERE session_id=? AND db_kind='track'",
        (session,),
    ).fetchone()
    assert rows["n"] == 1


# ---------------------------------------------------------------------------
# W18-B: strict link reconciliation
# ---------------------------------------------------------------------------


def test_probe_and_link_unlinks_stale_track_link(conn, song, session):
    """User deleted a Live track that was previously linked → re-probing
    drops the now-orphaned link row instead of silently leaving it (which
    would make the next push dispatch clip-creates at a dead index)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5,
    )
    # Fresh probe — index 5 is gone. The DB track 'Drums' isn't matched by
    # name in the new probe either (different track at index 1).
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Bass", "kind": "midi"}],
        live_returns=[],
    )
    assert result.unlinked_stale_tracks == [{"db_id": tid, "ableton_index": 5}]
    # The link row is gone.
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=tid,
    ) is None


def test_probe_and_link_unlinks_stale_return_link(conn, song, session):
    """Same shape for returns: deleted Live return → stale link cleared."""
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=rid, ableton_index=3,
    )
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[],
        live_returns=[{"return_index": 1, "name": "A-Delay"}],
    )
    assert result.unlinked_stale_returns == [{"db_id": rid, "ableton_index": 3}]
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="return", db_id=rid,
    ) is None


def test_probe_and_link_cascades_stale_clip_link_when_parent_track_dropped(
    conn, song, session,
):
    """SYN-3C8K: a Live-set swap that reuses the session drops the parent
    track link (its index is gone) but the clip link survives — and a dangling
    clip link makes the clips planner emit replace_notes against an empty slot,
    halting the clips phase. Reconciliation must cascade: when the parent track
    link is dropped, drop its clip links too."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=4.0, name="Drums A")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=cid, ableton_index=0,
    )
    # Fresh default set: index 5 is gone and 'Drums' isn't matched by name.
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "1-MIDI", "kind": "midi"}],
        live_returns=[],
    )
    assert result.unlinked_stale_tracks == [{"db_id": tid, "ableton_index": 5}]
    assert result.unlinked_stale_clips == [{"db_id": cid, "ableton_index": 0}]
    # Both link rows are gone — the next push will re-create + re-link the clip.
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="clip", db_id=cid,
    ) is None


def test_probe_and_link_unlinks_stale_clip_link_when_clip_row_deleted(
    conn, song, session,
):
    """FK-GUARD regression for the reported probe-and-link crash: a `build.py
    --reset` rebuild (or a Live-set swap that reuses the session) regenerates
    clips under new ids, leaving a clip link whose clip row is GONE from the DB.
    The SYN-3C8K cascade drops that link via unlink_db_from_ableton — which used
    to stamp the audit event's clip_id with the now-dangling id, violating
    events.clip_id's FK on INSERT (sqlite3.IntegrityError: FOREIGN KEY constraint
    failed) and crashing the whole reconcile. It must now reconcile cleanly.

    The track stays present (matched by name), so ONLY the clip-row-gone
    condition drives the cascade — isolating the exact FK trigger."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=4.0, name="Drums A")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=cid, ableton_index=0,
    )
    # The clip row vanishes (rebuild regenerated it under a new id); the clip LINK
    # lingers — ableton_links.db_id has no FK to clips.
    conn.execute("DELETE FROM clips WHERE id = ?", (cid,))
    assert Q.get_clip(conn, cid) is None

    # Pre-fix: this call raised sqlite3.IntegrityError mid-reconcile.
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Drums", "kind": "midi"}],
        live_returns=[],
    )
    assert result.unlinked_stale_clips == [{"db_id": cid, "ableton_index": 0}]
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="clip", db_id=cid,
    ) is None


def test_probe_and_link_keeps_clip_link_when_parent_track_survives(
    conn, song, session,
):
    """The cascade must NOT over-drop: when the parent track survives the probe
    (matched by name, link rewritten to its new index), its clip link is still
    valid and must be left intact."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=4.0, name="Drums A")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=cid, ableton_index=0,
    )
    # 'Drums' still present (shifted to index 1) → track link rewritten, kept.
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Drums", "kind": "midi"}],
        live_returns=[],
    )
    assert result.unlinked_stale_clips == []
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="clip", db_id=cid,
    ) is not None


def test_clips_planner_emits_create_after_stale_clip_link_cascade(
    conn, song, session,
):
    """End-to-end payoff (SYN-3C8K): after reconciliation cascades the stale
    clip-link drop and the tracks phase re-links the track at its new index,
    the clips planner emits `create` (not the empty-slot `replace_notes` that
    raised IndexError on every clip), so the clips phase completes."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=4.0, name="Drums A")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=cid, ableton_index=0,
    )
    # Set-swap reconciliation drops the stale track + clip links.
    push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "1-MIDI", "kind": "midi"}],
        live_returns=[],
    )
    # Tracks phase re-creates + re-links the track at its new index.
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=2,
    )
    plan = push.plan_push_clip(conn, clip_id=cid, session_id=session)
    actions = [c.args["action"] for c in plan.calls]
    assert actions == ["create"], (
        "after the stale clip link is cascaded away, the planner must re-create "
        "the clip, not replace_notes into an empty slot"
    )


# ---------------------------------------------------------------------------
# SYN-SCAFFOLD-MISLINK: set-swap rebind onto a fresh default scaffold
# ---------------------------------------------------------------------------


def test_probe_and_link_drops_mislinked_track_link_on_scaffold_set_swap(
    conn, song, session,
):
    """The reported bug: reusing a session bound to a now-discarded set and
    re-pushing onto a fresh DEFAULT set rebinds the surviving track links by
    bare index onto the scaffold tracks (1-MIDI..4-Audio). The link to index 1
    SURVIVES the W18-B bare-index sweep (index 1 still exists), so the tracks
    phase reads the DB track as "linked" and never re-creates it. Reconciliation
    must drop a link whose index is now occupied by a canonical default-scaffold
    track, so the DB track falls into unmatched_db_tracks and gets re-created."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1,
    )
    # Fresh default set: 1-MIDI..4-Audio. Index 1 STILL EXISTS (now a scaffold
    # track), so the pre-fix sweep kept the mislinked link.
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[
            {"track_index": 1, "name": "1-MIDI", "kind": "midi"},
            {"track_index": 2, "name": "2-MIDI", "kind": "midi"},
            {"track_index": 3, "name": "3-Audio", "kind": "audio"},
            {"track_index": 4, "name": "4-Audio", "kind": "audio"},
        ],
        live_returns=[],
    )
    assert result.unlinked_stale_tracks == [{"db_id": tid, "ableton_index": 1}]
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=tid,
    ) is None
    # The DB track is now unmatched → the tracks phase will re-create it.
    assert [t["db_id"] for t in result.unmatched_db_tracks] == [tid]
    # Scaffold detection still fires (it keys the "delete defaults?" prompt).
    assert {t["name"] for t in result.default_scaffold_unmatched_tracks} == {
        "1-MIDI", "2-MIDI", "3-Audio", "4-Audio",
    }


def test_probe_and_link_cascades_device_link_when_parent_track_mislinked(
    conn, song, session,
):
    """SYN-SCAFFOLD-MISLINK device cascade: when the mislinked parent track link
    is dropped, its top-level device links must cascade away too — else
    _emit_device_calls reads them as present and SKIPS the load, leaving the
    re-created track device-less (the clip-cascade failure moved one phase
    later)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    chain = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain, position=1, kind="Operator", display_name="Operator",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=1,
    )
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "1-MIDI", "kind": "midi"}],
        live_returns=[],
    )
    assert result.unlinked_stale_tracks == [{"db_id": tid, "ableton_index": 1}]
    assert result.unlinked_stale_devices == [{"db_id": did, "ableton_index": 1}]
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="device", db_id=did,
    ) is None


def test_probe_and_link_unlinks_device_when_its_index_vanished_from_live(
    conn, song, session,
):
    """A surviving PARENT does not make a device link valid — the index has to
    still exist.

    This is the fresh-set path, and Live's own defaults are what make it
    routine. Every new Live set ships `A-Reverb` / `B-Delay`, and DB return
    names are stored slot-prefix-stripped, so a song return called `Delay`
    matches Live's stock `B-Delay` — a return that already holds a factory
    device at index 1. The authored device loads at index 2 and the link
    records 2. Reopen a FRESH set and that return is factory-fresh again: the
    parent still matches by name, so the parent-scoped sweep keeps the link,
    but index 2 is gone. `_emit_device_calls` then reads the link as present,
    SKIPS the load, and every parameter write addresses the missing index —
    the devices phase halts on IndexError and never converges, because nothing
    emits the load that would create index 2.
    """
    rid = M.create_return(conn, song_id=song, name="Delay", position=1)
    device_id = _make_chain_with_device(
        conn, parent_return_id=rid, position=1, kind="Echo",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=rid, ableton_index=2,
    )
    # Recorded when the authored Echo loaded behind Live's factory Delay.
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=device_id,
        ableton_index=2,
    )
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[],
        # The parent still matches by name, so it is NOT dropped...
        live_returns=[{"return_index": 2, "name": "B-Delay"}],
        # ...but the fresh set carries only the factory device at index 1.
        live_devices_by_parent={
            ("return", 2): [
                {"device_index": 1, "name": "Delay", "class_name": "Delay"},
            ],
        },
    )
    assert result.unlinked_stale_devices == [
        {"db_id": device_id, "ableton_index": 2}
    ]
    # Unlinked is the whole point: it is what makes the devices planner emit the
    # load instead of writing parameters into a hole.
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="device", db_id=device_id,
    ) is None
    # The parent itself must survive — dropping it would re-create a duplicate
    # return rather than reusing Live's.
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="return", db_id=rid,
    ) == 2


def test_probe_and_link_keeps_device_link_when_index_still_present(
    conn, song, session,
):
    """The mirror of the vanished-index case: do not over-drop.

    A device still sitting at its recorded index is the ordinary re-push, and
    dropping its link would make the planner load a SECOND copy of the device.
    Guards the fix above from being written as an unconditional drop.
    """
    rid = M.create_return(conn, song_id=song, name="Delay", position=1)
    device_id = _make_chain_with_device(
        conn, parent_return_id=rid, position=1, kind="Echo",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=rid, ableton_index=2,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=device_id,
        ableton_index=2,
    )
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[],
        live_returns=[{"return_index": 2, "name": "B-Delay"}],
        live_devices_by_parent={
            ("return", 2): [
                {"device_index": 1, "name": "Delay", "class_name": "Delay"},
                {"device_index": 2, "name": "Echo", "class_name": "Echo"},
            ],
        },
    )
    assert result.unlinked_stale_devices == []
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="device", db_id=device_id,
    ) == 2


def test_probe_and_link_keeps_device_link_when_parent_not_probed(
    conn, song, session,
):
    """Absence of evidence is not evidence of absence.

    On the snapshot-fallback path no device data is probed at all. Treating an
    unprobed parent as "index missing" would drop every good device link and
    force a full reload on a push that merely skipped the device probe.
    """
    rid = M.create_return(conn, song_id=song, name="Delay", position=1)
    device_id = _make_chain_with_device(
        conn, parent_return_id=rid, position=1, kind="Echo",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=rid, ableton_index=2,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=device_id,
        ableton_index=2,
    )
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[],
        live_returns=[{"return_index": 2, "name": "B-Delay"}],
        # No live_devices_by_parent at all — the device probe did not run.
    )
    assert result.unlinked_stale_devices == []
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="device", db_id=device_id,
    ) == 2


def test_probe_and_link_keeps_track_link_when_renamed_not_scaffold(
    conn, song, session,
):
    """The scaffold gate must NOT over-drop. A track RENAMED in Live (its index
    survives, its new name is non-canonical) is still the same track — its link
    must stay so the next push updates it in place rather than creating a
    duplicate. Only a CANONICAL default-scaffold name proves the index is a
    fresh scaffold track; a renamed real track is not."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1,
    )
    # Live track at index 1 was renamed "Drumz" (non-canonical) — NOT a scaffold.
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Drumz", "kind": "midi"}],
        live_returns=[],
    )
    assert result.unlinked_stale_tracks == []
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=tid,
    ) is not None


def test_check_coherence_flags_mislinked_scaffold_track_link(
    conn, song, session,
):
    """check_coherence shares the bare-index blind spot: defense-in-depth must
    also refuse execute when a track link points at an index now occupied by a
    canonical default-scaffold track (the set-swap signature)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1,
    )
    result = push.check_coherence(
        conn, session_id=session,
        live_tracks=[{"track_index": 1, "name": "1-MIDI", "kind": "midi"}],
        live_returns=[],
    )
    assert not result.ok
    assert any(
        e["kind"] == "mislinked_scaffold_track_links" for e in result.errors
    )


def test_check_coherence_ok_when_track_link_matches_real_track(
    conn, song, session,
):
    """The coherence scaffold check must not false-positive: a link to an index
    occupied by the real (non-scaffold-named) track is coherent."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1,
    )
    result = push.check_coherence(
        conn, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Drums", "kind": "midi"}],
        live_returns=[],
    )
    assert result.ok


def test_probe_and_link_reconciles_to_new_index_on_shifted_match(conn, song, session):
    """Live track survives but at a new index (e.g., earlier track was
    deleted, this one shifted down). Name still matches → link rewritten
    to the new index; no stale-link entry surfaces (the upsert handled it)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5,
    )
    # 'Drums' now lives at index 1 (the four defaults that used to sit
    # ahead of it were deleted).
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Drums", "kind": "midi"}],
        live_returns=[],
    )
    assert result.matched_tracks == [
        {"db_id": tid, "name": "Drums", "ableton_index": 1},
    ]
    assert result.unlinked_stale_tracks == []
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=tid,
    ) == 1


def test_probe_and_link_cascade_covers_clip_and_device_on_stale_parent(
    conn, song, session,
):
    """SYN-SCAFFOLD-MISLINK extended the stale-parent cascade from clip-only to
    clip AND top-level device links. (Previously this boundary was deliberately
    clip-scoped — but a device link left dangling under a dropped parent makes
    _emit_device_calls read it as present and SKIP the load, leaving the
    re-created track device-less. The cascade now covers it.) A device link
    whose device ROW is also gone — a `build.py --reset` rebuild or set-swap
    regenerated it under a new id — drops here too, the device analog of the
    SYN-3C8K clip-row-gone cascade. envelope/note aren't persisted as
    ableton_links; they re-establish via the next push's own create-call path."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=4.0)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=cid, ableton_index=0,
    )
    # A device link whose device row doesn't exist (regenerated under a new id),
    # parented to the same now-stale track.
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id="dev-synthetic",
        ableton_index=0,
    )
    push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[],  # parent at index 5 gone
        live_returns=[],
    )
    # Parent track link cleared; clip link cascaded away (SYN-3C8K)...
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=tid,
    ) is None
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="clip", db_id=cid,
    ) is None
    # ...and the orphaned device link now cascades too (SYN-SCAFFOLD-MISLINK).
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="device", db_id="dev-synthetic",
    ) is None


def test_probe_and_link_emits_link_removed_event_on_stale_unlink(
    conn, song, session,
):
    """Strict reconciliation goes through the mutator so the event log
    records the removal (audit-trail seed for the future event-store flip)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5,
    )
    push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[], live_returns=[],
    )
    events = conn.execute(
        "SELECT kind, payload_json FROM events WHERE kind = 'ableton_link_removed'"
    ).fetchall()
    assert len(events) == 1
    body = json.loads(events[0]["payload_json"])
    assert body["db_kind"] == "track"
    assert body["db_id"] == tid
    assert body["ableton_index"] == 5


# ---------------------------------------------------------------------------
# ARR-PROJ: projection planner subsumes SYN-4R7P (no probe-and-link reconcile)
# ---------------------------------------------------------------------------


def test_arrangement_planner_rematerializes_after_live_side_delete(
    conn, song, session,
):
    """ARR-PROJ subsumes SYN-4R7P: after the user deletes an arrangement clip in
    Live (the lane goes empty), the projection planner re-materializes it via
    create+fill from the DB — no stale-link IndexError, no replace_notes into a
    dead index, no reconcile step required. The probe (empty lane) means no
    clear is needed; the placement is simply (re)created."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1,
    )
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0, name="A")
    aid = M.add_arrangement_clip(
        conn, song_id=song, track_id=tid, clip_id=cid, start_bar=1.0, end_bar=5.0,
    )
    # User deleted the arrangement clip in Live → the probe shows an empty lane.
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={1: []},
    )
    actions = [c.args["action"] for c in plan.calls]
    assert actions == ["create"], (
        "after a Live-side delete the projection planner re-materializes via "
        f"create+fill (no reconcile, no duplicate), got: {actions}"
    )
    assert plan.calls[0].key == f"arrangement_clip:{aid}"


def test_probe_and_link_no_longer_reconciles_arrangement_clip_links(
    conn, song, session,
):
    """ARR-PROJ removed the SYN-4R7P arrangement reconcile. Even in the case that
    used to cascade-drop an arrangement_clip link — the parent track link is
    dropped as stale — probe_and_link now leaves the arrangement_clip link
    untouched. With clear+create+fill as the sole materialization path, a stale
    positional link is harmless: the next push clears Live by probe and rebuilds,
    so there is nothing to reconcile. (probe_and_link also no longer accepts a
    live_arrangement_clips_by_track argument, and ProbeAndLinkResult no longer
    carries the arrangement-reconcile fields.)"""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5,
    )
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0, name="A")
    aid = M.add_arrangement_clip(
        conn, song_id=song, track_id=tid, clip_id=cid, start_bar=1.0, end_bar=5.0,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="arrangement_clip", db_id=aid,
        ableton_index=0,
    )
    # 'Drums'@5 is gone (a default scaffold sits at index 1) -> the track link is
    # dropped as stale (W18-B). Pre-ARR-PROJ this cascade-dropped the
    # arrangement_clip link too; now it must survive.
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "1-MIDI", "kind": "midi"}],
        live_returns=[],
    )
    # The stale track link still drops (unchanged W18-B behavior)...
    assert result.unlinked_stale_tracks == [{"db_id": tid, "ableton_index": 5}]
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=tid,
    ) is None
    # ...but the arrangement_clip link is left intact -- no reconcile happens.
    assert not hasattr(result, "unlinked_stale_arrangement_clips")
    assert not hasattr(result, "rebound_arrangement_clips")
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="arrangement_clip", db_id=aid,
    ) == 0


# ---------------------------------------------------------------------------
# W18-D: canonical default-scaffold detection
# ---------------------------------------------------------------------------


def test_probe_and_link_detects_default_scaffold_on_auto_session(conn, song, session):
    """Auto-session + all unmatched Live tracks are canonical defaults →
    populate default_scaffold_unmatched_tracks so the skill can offer to
    clean up. Strategy (b) from backlog #59: push first (creates song
    tracks), then delete the now-safe defaults."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[
            {"track_index": 1, "name": "1-MIDI", "kind": "midi"},
            {"track_index": 2, "name": "2-MIDI", "kind": "midi"},
            {"track_index": 3, "name": "3-Audio", "kind": "audio"},
            {"track_index": 4, "name": "4-Audio", "kind": "audio"},
        ],
        live_returns=[],
    )
    assert len(result.default_scaffold_unmatched_tracks) == 4
    assert {t["track_index"] for t in result.default_scaffold_unmatched_tracks} == {1, 2, 3, 4}


def test_probe_and_link_detects_partial_default_scaffold(conn, song, session):
    """Subset of the canonical set still qualifies — the user may have
    already deleted some of the defaults manually."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "1-MIDI", "kind": "midi"}],
        live_returns=[],
    )
    assert result.default_scaffold_unmatched_tracks == [
        {"track_index": 1, "name": "1-MIDI"},
    ]


def test_probe_and_link_default_scaffold_classified_on_session_reuse(conn, song, session):
    """SYN-3C8K: classify a default scaffold even when the session is REUSED
    (auto_session_created=False). The set-swap case — a reused session pushed
    onto a freshly-opened default set — has the identical canonical scaffold to
    clean up, and degrading it to the generic unmatched-Live confirm was a
    dogfood friction. The canonical-name signature is the real discriminator
    (an exact, case-sensitive '1-MIDI'/.../'4-Audio' set is what Live
    auto-generates, the names users rename AWAY from — not a plausible
    coincidental rename), so the fresh-vs-reused distinction only cost the
    missed cleanup. (Earlier W18-D gated this on auto_session_created=True.)"""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "1-MIDI", "kind": "midi"}],
        live_returns=[],
    )
    assert result.default_scaffold_unmatched_tracks == [
        {"track_index": 1, "name": "1-MIDI"},
    ]


def test_probe_and_link_no_default_scaffold_when_extras_present(conn, song, session):
    """If even one unmatched Live track has a non-canonical name, the set
    isn't a fresh scaffold (could be someone else's song with the defaults
    still alongside). Fall back to the generic unmatched-Live confirmation."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[
            {"track_index": 1, "name": "1-MIDI", "kind": "midi"},
            {"track_index": 2, "name": "SomeoneElsesTrack", "kind": "midi"},
        ],
        live_returns=[],
    )
    assert result.default_scaffold_unmatched_tracks == []


def test_probe_and_link_no_default_scaffold_when_nothing_unmatched(conn, song, session):
    """User opened a known Live set with their song's actual tracks already
    present — nothing unmatched, no detection. (auto_session_created=True
    only signals "this run minted the session," not "this is a fresh Live
    set.")"""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Drums", "kind": "midi"}],
        live_returns=[],
    )
    assert result.matched_tracks
    assert result.default_scaffold_unmatched_tracks == []


def test_probe_and_link_default_scaffold_is_case_sensitive(conn, song, session):
    """Live's defaults are exact-cased ('1-MIDI'); a renamed track in the
    same shape ('1-midi') is not a default. The user may have intentionally
    customised, so don't auto-suggest deletion."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "1-midi", "kind": "midi"}],
        live_returns=[],
    )
    assert result.default_scaffold_unmatched_tracks == []


# ---------------------------------------------------------------------------
# W20-A: device matching by (parent, position, class_name)
# ---------------------------------------------------------------------------


def _make_chain_with_device(conn, *, parent_track_id=None, parent_return_id=None,
                            position=1, kind, display_name=None):
    """Build the minimal device-chain + device shape so probe_and_link has
    something to match. Mirrors what capture.replay_capture would produce on
    a real song."""
    chain_id = M.create_device_chain(
        conn,
        parent_track_id=parent_track_id,
        parent_return_id=parent_return_id,
        position=0,
    )
    device_id = M.create_device(
        conn,
        chain_id=chain_id,
        position=position,
        kind=kind,
        display_name=display_name or kind,
    )
    return device_id


def test_probe_and_link_binds_device_by_position_and_class(conn, song, session):
    """The W20-A drift case: Live already has a Reverb at position 1 of the
    A-Reverb return; the DB also has a Reverb there. Without W20-A, no link
    exists → next push's _emit_device_calls loads a duplicate Reverb.
    With W20-A: probe-and-link binds the existing pairing."""
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    device_id = _make_chain_with_device(
        conn, parent_return_id=rid, position=1, kind="Reverb",
    )
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[],
        live_returns=[{"return_index": 1, "name": "A-Reverb"}],
        live_devices_by_parent={
            ("return", 1): [
                {"device_index": 1, "name": "Reverb", "class_name": "Reverb"},
            ],
        },
    )
    assert result.matched_devices == [{
        "db_id": device_id,
        "parent_kind": "return",
        "parent_index": 1,
        "position": 1,
        "class_name": "Reverb",
    }]
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="device", db_id=device_id,
    ) == 1


def test_probe_and_link_binds_track_device(conn, song, session):
    """Track-side mirror of the return case."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    _make_chain_with_device(
        conn, parent_track_id=tid, position=1, kind="Drum Rack",
    )
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 4, "name": "Drums", "kind": "midi"}],
        live_returns=[],
        live_devices_by_parent={
            ("track", 4): [
                {"device_index": 1, "name": "Kit", "class_name": "Drum Rack"},
            ],
        },
    )
    assert len(result.matched_devices) == 1
    assert result.matched_devices[0]["parent_index"] == 4
    assert result.matched_devices[0]["class_name"] == "Drum Rack"


def test_probe_and_link_ignores_analyzer_at_authored_slot(conn, song, session):
    """BUG1A: a render leaves a HallucinoteAnalyzer in the chain; a newly authored
    DB device whose position lands on the analyzer's live slot must NOT be compared
    against the analyzer — which produced a false 'device drift' note + skipped link,
    forcing manual analyzer deletion before a re-push. The analyzer is excluded
    before position-matching, so the already-present authored device still links and
    the new one is left for push to load, with no false drift."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Bass", kind="midi")
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    eq_id = M.create_device(
        conn, chain_id=chain_id, position=1, kind="EQ Eight", display_name="EQ Eight",
    )
    comp_id = M.create_device(
        conn, chain_id=chain_id, position=2, kind="Compressor", display_name="Compressor",
    )
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 2, "name": "Bass", "kind": "midi"}],
        live_returns=[],
        live_devices_by_parent={
            ("track", 2): [
                {"device_index": 1, "name": "EQ Eight",
                 "class_name": "Eq8", "class_display_name": "EQ Eight"},
                # the analyzer sits where the newly-authored Compressor (DB pos 2) wants to be
                {"device_index": 2, "name": "HallucinoteAnalyzer",
                 "class_name": "MxDeviceAudioEffect",
                 "class_display_name": "Max Audio Effect"},
            ],
        },
    )
    linked = {m["db_id"] for m in result.matched_devices}
    assert linked == {eq_id}          # EQ links; Compressor left for push to load
    assert comp_id not in linked
    assert not [n for n in result.notes if "drift" in n.lower()]


def test_probe_and_link_matches_via_class_display_name(conn, song, session):
    """Arc 4 / D4: DB stores `kind` as the post-rename display name
    (`EQ Eight`, `Compressor`, `Drum Rack`). The MCP probe surfaces BOTH
    `class_display_name` (display) AND `class_name` (internal, e.g. `Eq8`,
    `Compressor2`, `InstrumentGroupDevice`). The comparator must read
    `class_display_name` to match the DB's storage convention — otherwise
    every re-probe after push emits noisy false drift notes for the
    common case where Live's internal name differs from the display.
    Reproduces the 2026-05-22 sun-zone-done post-push false-drift spam.
    """
    tid = M.create_track(conn, song_id=song, track_index=1, name="Bass", kind="midi")
    device_id = _make_chain_with_device(
        conn, parent_track_id=tid, position=1, kind="EQ Eight",
    )
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 2, "name": "Bass", "kind": "midi"}],
        live_returns=[],
        live_devices_by_parent={
            ("track", 2): [
                {
                    "device_index": 1,
                    "name": "EQ",
                    "class_name": "Eq8",
                    "class_display_name": "EQ Eight",
                },
            ],
        },
    )
    assert result.matched_devices == [{
        "db_id": device_id,
        "parent_kind": "track",
        "parent_index": 2,
        "position": 1,
        "class_name": "EQ Eight",
    }]
    # No drift note — display names agree even though class_name differs.
    assert not any("device drift" in n for n in result.notes), result.notes


def test_probe_and_link_falls_back_to_class_name_when_display_absent(
    conn, song, session,
):
    """Older probe responses (pre-`class_display_name`) only surface
    `class_name`. The comparator must still match in that case — the
    fallback keeps existing fixtures and real-world older snapshots
    working without churn."""
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    device_id = _make_chain_with_device(
        conn, parent_return_id=rid, position=1, kind="Reverb",
    )
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[],
        live_returns=[{"return_index": 1, "name": "A-Reverb"}],
        live_devices_by_parent={
            ("return", 1): [
                # No class_display_name key — older probe shape.
                {"device_index": 1, "name": "Reverb", "class_name": "Reverb"},
            ],
        },
    )
    assert len(result.matched_devices) == 1
    assert result.matched_devices[0]["db_id"] == device_id
    assert not any("device drift" in n for n in result.notes), result.notes


def test_probe_and_link_skips_class_mismatch_at_same_position(conn, song, session):
    """DB has Reverb at position 1; Live has a Delay there. Don't link
    (push will load the DB's Reverb over Live's Delay) and surface a note
    so the user sees the drift."""
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    _make_chain_with_device(
        conn, parent_return_id=rid, position=1, kind="Reverb",
    )
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[],
        live_returns=[{"return_index": 1, "name": "A-Reverb"}],
        live_devices_by_parent={
            ("return", 1): [
                {"device_index": 1, "name": "Delay", "class_name": "Delay"},
            ],
        },
    )
    assert result.matched_devices == []
    assert any(
        "device drift" in n and "Reverb" in n and "Delay" in n
        for n in result.notes
    ), result.notes


def test_probe_and_link_partial_chain_match(conn, song, session):
    """DB has 2 devices on the track; Live's chain has 1. Match what
    overlaps (position 1) and leave the rest for push to create."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead", kind="midi")
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    M.create_device(conn, chain_id=chain_id, position=1, kind="Operator",
                    display_name="Operator")
    pos2_id = M.create_device(conn, chain_id=chain_id, position=2, kind="Reverb",
                              display_name="Reverb")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Lead", "kind": "midi"}],
        live_returns=[],
        live_devices_by_parent={
            ("track", 1): [
                {"device_index": 1, "name": "Operator", "class_name": "Operator"},
            ],
        },
    )
    assert len(result.matched_devices) == 1
    assert result.matched_devices[0]["position"] == 1
    # Position 2 unmatched — no link for Reverb yet; push creates it.
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="device", db_id=pos2_id,
    ) is None


def test_probe_and_link_no_devices_when_arg_omitted(conn, song, session):
    """Back-compat: omitting live_devices_by_parent is a no-op for the
    device side (existing callers see the same behaviour as before W20-A)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead", kind="midi")
    _make_chain_with_device(
        conn, parent_track_id=tid, position=1, kind="Operator",
    )
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Lead", "kind": "midi"}],
        live_returns=[],
        # live_devices_by_parent omitted
    )
    assert result.matched_devices == []


def test_probe_and_link_skips_devices_on_unlinked_parent(conn, song, session):
    """Live has devices on track 1 but DB's "Lead" doesn't match (Live has
    "Bass" there). The devices probe entry exists but probe-and-link
    only matches devices on linked parents."""
    M.create_track(conn, song_id=song, track_index=1, name="Lead", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Bass", "kind": "midi"}],
        live_returns=[],
        live_devices_by_parent={
            ("track", 1): [
                {"device_index": 1, "name": "Compressor", "class_name": "Compressor2"},
            ],
        },
    )
    assert result.matched_devices == []


# ---------------------------------------------------------------------------
# ANALYZER-INDEX: master device-chain reconciliation (analyzer-aware)
# ---------------------------------------------------------------------------


def test_probe_and_link_reconciles_master_device_after_analyzer_shift(
    conn, song, session,
):
    """The reported bug: a master device link froze at first-load and was never
    re-bound, so once a render's analyzer shifted the master chain, a param
    re-push targeted the stale index (the master Limiter's Ceiling hit the
    analyzer) and hard-halted the devices phase.

    With the master in device reconciliation: the analyzer is excluded, the
    Limiter is re-matched to its real authored slot, and the stale link is
    corrected — so the next param re-push addresses the Limiter, not the
    analyzer."""
    mid = M.create_track(conn, song_id=song, track_index=0, name="Master", kind="master")
    limiter_id = _make_chain_with_device(
        conn, parent_track_id=mid, position=1, kind="Limiter",
    )
    # The frozen first-load index: it points at slot 2 — where the analyzer now
    # sits after the render repositioned it terminal.
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=limiter_id,
        ableton_index=2, actor="sync", reason="stale first-load master index",
    )
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[], live_returns=[],
        live_devices_by_parent={
            ("master", 0): [
                {"device_index": 1, "name": "Limiter", "class_name": "Limiter"},
                {"device_index": 2, "name": "HallucinoteAnalyzer",
                 "class_name": "MxDeviceAudioEffect"},
            ],
        },
    )
    # Stale 2 (the analyzer slot) reconciled to 1 (the Limiter's real slot).
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="device", db_id=limiter_id,
    ) == 1
    master_matches = [m for m in result.matched_devices if m["parent_kind"] == "master"]
    assert len(master_matches) == 1
    assert master_matches[0]["db_id"] == limiter_id
    assert master_matches[0]["position"] == 1
    # No false drift note for the analyzer-occupied slot.
    assert not [n for n in result.notes if "drift" in n.lower()]


def test_probe_and_link_master_reconcile_is_noop_when_master_not_probed(
    conn, song, session,
):
    """Graceful when the master chain wasn't probed (e.g. a transient master
    probe failure dropped the ("master", 0) key): no master matched_devices,
    no crash — the rest of the reconciliation is unaffected."""
    mid = M.create_track(conn, song_id=song, track_index=0, name="Master", kind="master")
    _make_chain_with_device(conn, parent_track_id=mid, position=1, kind="Limiter")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[], live_returns=[],
        # master key absent; a non-master entry keeps live_devices_by_parent truthy
        live_devices_by_parent={("track", 1): []},
    )
    assert [m for m in result.matched_devices if m["parent_kind"] == "master"] == []


# ---------------------------------------------------------------------------
# SNP-8R4K chunk 4: stale-set detection through the probe-and-link seam
# ---------------------------------------------------------------------------
#
# The probe data shape is the same `live_devices_by_parent` map the device
# matcher consumes — `{(parent_kind, index): [ordered probe entries]}` from
# `_probe_live_devices_via_mcp`, which does NOT filter the analyzer out (it
# forwards the raw `ableton_device(action='list')` output, so the analyzer
# entry with name=="HallucinoteAnalyzer" reaches the detector). The guidance
# is surfaced through the existing `result.notes` channel (non-fatal — same
# channel device-drift uses), never a hard halt.

_ANALYZER_PROBE = {
    "device_index": 2,
    "name": "HallucinoteAnalyzer",
    "class_name": "MxDeviceAudioEffect",
}


def test_probe_and_link_flags_stale_set_with_device_after_analyzer(
    conn, song, session,
):
    """A surface whose chain has an authored device AFTER the analyzer emits
    the rebuild guidance note, naming the stale surface + the device."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 4, "name": "Drums", "kind": "midi"}],
        live_returns=[],
        live_devices_by_parent={
            ("track", 4): [
                {"device_index": 1, "name": "Operator", "class_name": "Operator"},
                {**_ANALYZER_PROBE, "device_index": 2},
                {"device_index": 3, "name": "Saturator", "class_name": "Saturator"},
            ],
        },
    )
    stale_notes = [n for n in result.notes if "STALE SET (SNP-8R4K)" in n]
    assert len(stale_notes) == 1, result.notes
    note = stale_notes[0]
    assert "track #4" in note
    assert "Saturator" in note
    assert "rebuild the set from source".upper() in note.upper()


def test_probe_and_link_flags_stale_set_on_master_chain(conn, song, session):
    """ANALYZER-INDEX: probing the master chain into live_devices_by_parent also
    feeds the stale-set detector, so a master surface with an authored device
    after the analyzer now surfaces the rebuild guidance too (previously the
    master was never probed, so master staleness went undetected)."""
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[], live_returns=[],
        live_devices_by_parent={
            ("master", 0): [
                {"device_index": 1, "name": "Glue Compressor",
                 "class_name": "GlueCompressor"},
                {**_ANALYZER_PROBE, "device_index": 2},
                {"device_index": 3, "name": "Limiter", "class_name": "Limiter"},
            ],
        },
    )
    stale_notes = [n for n in result.notes if "STALE SET (SNP-8R4K)" in n]
    assert len(stale_notes) == 1, result.notes
    # Singleton label: "master", never "master #0".
    assert "master: Limiter after the analyzer" in stale_notes[0]
    assert "master #" not in stale_notes[0]
    # No master DB track here, so the reconciliation half is a graceful no-op
    # (probed key present, no DB master row) — stale-set detection still fires.
    assert [m for m in result.matched_devices if m["parent_kind"] == "master"] == []


def test_probe_and_link_silent_on_clean_set_analyzer_last(conn, song, session):
    """Analyzer terminal on every surface → no stale note (a clean/rebuilt set
    is silent — the condition is the version key)."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.create_return(conn, song_id=song, name="Reverb", position=1)
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 4, "name": "Drums", "kind": "midi"}],
        live_returns=[{"return_index": 1, "name": "A-Reverb"}],
        live_devices_by_parent={
            ("track", 4): [
                {"device_index": 1, "name": "Operator", "class_name": "Operator"},
                {**_ANALYZER_PROBE, "device_index": 2},
            ],
            ("return", 1): [
                {"device_index": 1, "name": "Reverb", "class_name": "Reverb"},
                {**_ANALYZER_PROBE, "device_index": 2},
            ],
        },
    )
    assert not any("STALE SET" in n for n in result.notes), result.notes


def test_probe_and_link_silent_when_no_analyzer_in_chain(conn, song, session):
    """A set the render never tapped (no analyzer) → not stale; the render
    loads the analyzer terminal at the next capture (chunk 3)."""
    M.create_track(conn, song_id=song, track_index=1, name="Lead", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Lead", "kind": "midi"}],
        live_returns=[],
        live_devices_by_parent={
            ("track", 1): [
                {"device_index": 1, "name": "Operator", "class_name": "Operator"},
                {"device_index": 2, "name": "Reverb", "class_name": "Reverb"},
            ],
        },
    )
    assert not any("STALE SET" in n for n in result.notes), result.notes


def test_probe_and_link_no_stale_note_when_devices_arg_omitted(
    conn, song, session,
):
    """No probe device data → no detection runs (nothing to flag)."""
    M.create_track(conn, song_id=song, track_index=1, name="Lead", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 1, "name": "Lead", "kind": "midi"}],
        live_returns=[],
        # live_devices_by_parent omitted
    )
    assert not any("STALE SET" in n for n in result.notes), result.notes


def test_probe_and_link_flags_stale_set_on_unlinked_parent(conn, song, session):
    """Staleness is a property of the PROBED SET, independent of DB linkage:
    a surface that doesn't match any DB track still surfaces under-measurement
    guidance (the operator's set is stale regardless of what this song binds)."""
    M.create_track(conn, song_id=song, track_index=1, name="Lead", kind="midi")
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        # Live has "Bass" at index 1; DB's "Lead" doesn't match it.
        live_tracks=[{"track_index": 1, "name": "Bass", "kind": "midi"}],
        live_returns=[],
        live_devices_by_parent={
            ("track", 1): [
                {**_ANALYZER_PROBE, "device_index": 1},
                {"device_index": 2, "name": "Limiter", "class_name": "Limiter"},
            ],
        },
    )
    assert result.matched_devices == []  # parent unlinked → no device binding
    stale_notes = [n for n in result.notes if "STALE SET (SNP-8R4K)" in n]
    assert len(stale_notes) == 1, result.notes
    assert "Limiter" in stale_notes[0]


# ---------------------------------------------------------------------------
# push_cli — argument plumbing
# ---------------------------------------------------------------------------


def test_cli_phases_emits_fourteen_phase_metadata(conn, song, session, db_path, capsys):
    push_cli.main([
        "phases", session, "--db", str(db_path),
    ])
    out = json.loads(capsys.readouterr().out)
    assert out["song_id"] == song
    assert out["session_id"] == session
    assert [p["name"] for p in out["phases"]] == [
        "tempo_map", "time_signature_map", "tracks", "returns",
        "scenes", "clips", "mix", "devices", "routing", "device_sidechain",
        "envelopes", "performed_automation", "arrangement", "cues",
    ]
    for p in out["phases"]:
        assert p["description"], f"phase {p['name']!r} has empty description"


def test_cli_plan_emits_named_phase_plan(conn, song, session, db_path, capsys):
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    push_cli.main([
        "plan", "tracks", session, "--db", str(db_path),
    ])
    out = json.loads(capsys.readouterr().out)
    assert out["phase"] == "tracks"
    assert out["song_id"] == song
    assert out["session_id"] == session
    assert len(out["calls"]) == 1
    assert out["calls"][0]["tool"] == "ableton_track"
    assert out["calls"][0]["args"]["action"] == "create"


def test_cli_plan_rejects_unknown_phase(conn, song, session, db_path):
    with pytest.raises(SystemExit, match="unknown phase 'bogus'"):
        push_cli.main([
            "plan", "bogus", session, "--db", str(db_path),
        ])


def _seed_master_perform_arc(conn, song):
    master = M.create_track(conn, song_id=song, track_index=0, name="Master",
                            kind="master")
    eid = M.create_envelope(conn, song_id=song, target_kind="mixer_volume",
                            target_track_id=master)
    M.replace_breakpoints(conn, envelope_id=eid, breakpoints=[
        {"time_beats": 0.0, "value": 0.85},
        {"time_beats": 16.0, "value": 0.4},
    ])


def test_cli_plan_performed_automation_honors_perform_slowdown(
    conn, song, session, db_path, capsys,
):
    """ENV-2T9K: the --perform-slowdown operator flag threads through to the
    performed_automation phase plan (the agent-driven push path)."""
    _seed_master_perform_arc(conn, song)
    push_cli.main([
        "plan", "performed_automation", session,
        "--db", str(db_path), "--perform-slowdown", "4",
    ])
    out = json.loads(capsys.readouterr().out)
    call = next(
        c for c in out["calls"] if c["args"].get("action") == "perform_batch"
    )
    assert call["args"]["slowdown_factor"] == 4.0


def test_cli_plan_rejects_perform_slowdown_below_one_at_parse_time(
    conn, song, session, db_path,
):
    """ENV-2T9K: an out-of-range --perform-slowdown is rejected at the argparse
    boundary (SystemExit) — fail fast, BEFORE any phase dispatches against Live
    (the old deferred-into-phase-10 check died 9 phases into a push)."""
    with pytest.raises(SystemExit):
        push_cli.main([
            "plan", "performed_automation", session,
            "--db", str(db_path), "--perform-slowdown", "0.5",
        ])


def test_cli_plan_performed_automation_default_has_no_slowdown(
    conn, song, session, db_path, capsys,
):
    """Without the flag the plan carries no slowdown override (off by default)."""
    _seed_master_perform_arc(conn, song)
    push_cli.main([
        "plan", "performed_automation", session, "--db", str(db_path),
    ])
    out = json.loads(capsys.readouterr().out)
    call = next(
        c for c in out["calls"] if c["args"].get("action") == "perform_batch"
    )
    assert "slowdown_factor" not in call["args"]


def test_cli_apply_writes_link_from_result(conn, song, session, db_path, tmp_path, capsys):
    tid = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    results = [{
        "key": f"track:{tid}", "ok": True, "tool": "ableton_track",
        "result": {"track_index": 7},
    }]
    rpath = tmp_path / "r.json"
    rpath.write_text(json.dumps(results))
    push_cli.main([
        "apply", session, "--db", str(db_path), "--results", str(rpath),
    ])
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "applied": 1, "failed": 0, "details": [], "apply_warnings": [],
        "apply_notes": [],
    }
    # Re-open for fresh connection so the apply's transaction is visible.
    fresh = init_db(db_path)
    try:
        assert Q.get_ableton_link(
            fresh, session_id=session, db_kind="track", db_id=tid,
        ) == 7
    finally:
        fresh.close()


def test_cli_apply_skips_link_when_result_lacks_index(
    conn, song, session, db_path, tmp_path, capsys,
):
    """`ableton_clip(action='replace_notes')` keys are `clip:<id>` but the
    response carries no `clip_index` (the clip already exists; no new
    link to record). apply_push_results must SKIP the link write rather
    than raise. Pin the silent-skip path so a future apply-side refactor
    that drops it surfaces loudly."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1,
    )
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=4.0, name="loop")
    # No prior clip link — apply should not invent one.
    results = [{
        "key": f"clip:{cid}", "ok": True, "tool": "ableton_clip",
        "result": {},  # replace_notes returns no clip_index
    }]
    rpath = tmp_path / "r.json"
    rpath.write_text(json.dumps(results))
    push_cli.main([
        "apply", session, "--db", str(db_path), "--results", str(rpath),
    ])
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "applied": 1, "failed": 0, "details": [], "apply_warnings": [],
        "apply_notes": [],
    }
    fresh = init_db(db_path)
    try:
        assert Q.get_ableton_link(
            fresh, session_id=session, db_kind="clip", db_id=cid,
        ) is None  # No link written — replace_notes carried no index.
    finally:
        fresh.close()


def test_cli_apply_reports_failed_calls(
    conn, song, session, db_path, tmp_path, capsys,
):
    tid = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    results = [{
        "key": f"track:{tid}", "ok": False, "tool": "ableton_track",
        "error": "boom",
    }]
    rpath = tmp_path / "r.json"
    rpath.write_text(json.dumps(results))
    push_cli.main([
        "apply", session, "--db", str(db_path), "--results", str(rpath),
    ])
    summary = json.loads(capsys.readouterr().out)
    assert summary["applied"] == 0
    assert summary["failed"] == 1
    assert summary["details"][0]["error"] == "boom"


def test_cli_probe_and_link_via_snapshot_file(
    conn, song, session, db_path, tmp_path, capsys,
):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    snap = {
        "tracks": [{"track_index": 4, "name": "Drums", "kind": "midi"}],
        "returns": [{"return_index": 2, "name": "A-Reverb"}],
    }
    spath = tmp_path / "snap.json"
    spath.write_text(json.dumps(snap))
    push_cli.main([
        "probe-and-link", session, "--db", str(db_path), "--snapshot", str(spath),
    ])
    out = json.loads(capsys.readouterr().out)
    assert out["matched_tracks"][0]["ableton_index"] == 4
    assert out["matched_returns"][0]["ableton_index"] == 2
    fresh = init_db(db_path)
    try:
        assert Q.get_ableton_link(
            fresh, session_id=session, db_kind="track", db_id=tid,
        ) == 4
        assert Q.get_ableton_link(
            fresh, session_id=session, db_kind="return", db_id=rid,
        ) == 2
    finally:
        fresh.close()


# ---------------------------------------------------------------------------
# check-coherence (W18-A)
# ---------------------------------------------------------------------------


def test_cli_check_coherence_exits_zero_on_match(
    conn, song, session, db_path, tmp_path, capsys,
):
    """Coherent state → exit 0, ok=true in JSON output."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=4,
    )
    conn.commit()

    snap = {"tracks": [{"track_index": 4, "name": "Drums"}], "returns": []}
    spath = tmp_path / "snap.json"
    spath.write_text(json.dumps(snap))

    rc = push_cli.main([
        "check-coherence", session, "--db", str(db_path), "--snapshot", str(spath),
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["ok"] is True
    assert out["errors"] == []


def test_cli_check_coherence_exits_nonzero_on_stale_link(
    conn, song, session, db_path, tmp_path, capsys,
):
    """Stale link → exit non-zero with stale_track_links in JSON output."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5,
    )
    conn.commit()

    # Snapshot omits index 5 (user deleted that track in Live).
    snap = {"tracks": [{"track_index": 1, "name": "1-MIDI"}], "returns": []}
    spath = tmp_path / "snap.json"
    spath.write_text(json.dumps(snap))

    rc = push_cli.main([
        "check-coherence", session, "--db", str(db_path), "--snapshot", str(spath),
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc != 0
    assert out["ok"] is False
    assert any(e["kind"] == "stale_track_links" for e in out["errors"])


def test_cli_check_coherence_refuses_missing_session(db_path, tmp_path, conn, capsys):
    """Session row absent → exit non-zero with session_missing."""
    snap = {"tracks": [], "returns": []}
    spath = tmp_path / "snap.json"
    spath.write_text(json.dumps(snap))

    rc = push_cli.main([
        "check-coherence", "definitely-not-a-real-id",
        "--db", str(db_path), "--snapshot", str(spath),
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc != 0
    assert out["errors"][0]["kind"] == "session_missing"


def test_cli_check_coherence_rejects_malformed_snapshot(
    db_path, tmp_path, conn, session,
):
    """Snapshot file not shaped like {tracks, returns} → SystemExit with
    same teaching text probe-and-link uses."""
    spath = tmp_path / "bad.json"
    spath.write_text(json.dumps([1, 2, 3]))
    with pytest.raises(SystemExit, match="must be a JSON object"):
        push_cli.main([
            "check-coherence", session, "--db", str(db_path),
            "--snapshot", str(spath),
        ])


def test_cli_song_slug_resolves_to_canonical_path(tmp_path, monkeypatch, capsys):
    """``--song <slug>`` resolves to ``songs/<slug>/<slug>.db``. Verify
    by chdir'ing into a tmp dir with that layout."""
    songs_dir = tmp_path / "songs" / "demo"
    songs_dir.mkdir(parents=True)
    db_path = songs_dir / "demo.db"
    conn = init_db(db_path)
    try:
        song = M.create_song(conn, name="t", key="Dm")
        session = M.create_ableton_session(conn, song_id=song, name="draft")
    finally:
        conn.close()
    monkeypatch.chdir(tmp_path)
    push_cli.main(["phases", session, "--song", "demo"])
    out = json.loads(capsys.readouterr().out)
    assert out["session_id"] == session


def test_cli_missing_db_raises_actionable_error(tmp_path):
    with pytest.raises(SystemExit, match="DB not found"):
        push_cli.main([
            "phases", "fake-session-id", "--db", str(tmp_path / "nope.db"),
        ])


def test_cli_unknown_session_raises_actionable_error(conn, db_path):
    with pytest.raises(SystemExit, match="no ableton_sessions row"):
        push_cli.main([
            "phases", "definitely-not-a-real-id", "--db", str(db_path),
        ])


# ---------------------------------------------------------------------------
# End-to-end CLI drive
# ---------------------------------------------------------------------------


@pytest.fixture
def filled_song(conn, song, session):
    """Same shape as test_push_song.filled_song so the CLI drive
    asserts the same emission counts. Returns metadata for assertions."""
    M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=120.0)
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    drums = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    bass = M.create_track(conn, song_id=song, track_index=2, name="Bass", kind="midi")
    reverb = M.create_return(conn, song_id=song, name="Reverb", position=1)

    drums_clip = M.create_clip(
        conn, track_id=drums, slot=1, length_beats=8.0, name="drums_loop",
    )
    M.insert_notes(
        conn, clip_id=drums_clip,
        notes=[{"pitch": 36, "start_beats": 0.0, "duration_beats": 0.25,
                "velocity": 110, "tags": ["kick"]}],
    )
    bass_clip = M.create_clip(
        conn, track_id=bass, slot=1, length_beats=8.0, name="bass_loop",
    )
    M.insert_notes(
        conn, clip_id=bass_clip,
        notes=[{"pitch": 40, "start_beats": 0.0, "duration_beats": 0.5,
                "velocity": 100, "tags": ["root"]}],
    )

    M.add_arrangement_clip(
        conn, song_id=song, track_id=drums, clip_id=drums_clip,
        start_bar=1.0, end_bar=3.0,
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=bass, clip_id=bass_clip,
        start_bar=1.0, end_bar=3.0,
    )
    M.set_send_level(conn, from_track_id=drums, to_return_id=reverb, level=0.4)
    M.add_cue_point(conn, song_id=song, position_bar=1.0, name="intro")

    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=drums,
    )
    M.add_breakpoint(
        conn, envelope_id=eid, time_beats=0.0, value=0.4, curve_kind="linear",
    )
    M.add_breakpoint(
        conn, envelope_id=eid, time_beats=4.0, value=0.7, curve_kind="linear",
    )
    return {
        "drums_id": drums,
        "bass_id": bass,
        "reverb_id": reverb,
        "drums_clip_id": drums_clip,
        "bass_clip_id": bass_clip,
    }


def test_cli_end_to_end_drive_links_everything(
    conn, song, session, db_path, tmp_path, filled_song, capsys,
):
    """Simulate the skill: probe-and-link with an empty snapshot
    (fresh Live set), then for each phase invoke plan → synthesize
    results → apply. Pin per-phase emission counts and final link
    state to detect regressions in the CLI-to-orchestrator wiring.

    This is the strong pre-real-Live signal that the wire-up is
    correct — the only difference from the real-Live smoke test is
    the source of MCP results (synthesized here, agent-executed there).
    """
    # Step 1: probe-and-link with empty snapshot (no pre-existing Live
    # tracks/returns) — every DB entity goes into unmatched, no links
    # written yet. Subsequent phases will create them.
    snap_path = tmp_path / "snap.json"
    snap_path.write_text(json.dumps({"tracks": [], "returns": []}))
    push_cli.main([
        "probe-and-link", session, "--db", str(db_path),
        "--snapshot", str(snap_path),
    ])
    pl = json.loads(capsys.readouterr().out)
    assert pl["matched_tracks"] == []
    assert pl["matched_returns"] == []
    assert len(pl["unmatched_db_tracks"]) == 2  # drums, bass
    assert len(pl["unmatched_db_returns"]) == 1  # reverb

    # Step 2: enumerate phases.
    push_cli.main(["phases", session, "--db", str(db_path)])
    phase_list = json.loads(capsys.readouterr().out)["phases"]
    assert [p["name"] for p in phase_list] == [
        "tempo_map", "time_signature_map", "tracks", "returns",
        "scenes", "clips", "mix", "devices", "routing", "device_sidechain",
        "envelopes", "performed_automation", "arrangement", "cues",
    ]

    # Step 3: drive each phase. We share counters across the loop so
    # successive applies emit monotonic indexes per kind.
    counters: dict[str, int] = {}
    emit_counts: dict[str, int] = {}
    for phase in phase_list:
        push_cli.main([
            "plan", phase["name"], session, "--db", str(db_path),
        ])
        plan_doc = json.loads(capsys.readouterr().out)
        emit_counts[phase["name"]] = len(plan_doc["calls"])
        # Synthesize: instead of going through the runtime PushPlan,
        # we walk the serialized call list to mimic what the agent
        # produces. The result shape is identical.
        results = []
        for call in plan_doc["calls"]:
            kind = call["key"].partition(":")[0]
            body: dict = {}
            if kind in _LINK_FIELDS:
                counters[kind] = counters.get(kind, 0) + 1
                body[_LINK_FIELDS[kind]] = counters[kind]
            results.append({
                "key": call["key"], "ok": True, "tool": call["tool"],
                "result": body,
            })
        rpath = tmp_path / f"r-{phase['name']}.json"
        rpath.write_text(json.dumps(results))
        push_cli.main([
            "apply", session, "--db", str(db_path), "--results", str(rpath),
        ])
        capsys.readouterr()  # discard apply summary; tested separately

    # Pin emission shape per phase (matches the test_push_song e2e).
    assert emit_counts["tempo_map"] == 1
    assert emit_counts["tracks"] == 2
    assert emit_counts["returns"] == 1
    assert emit_counts["scenes"] == 1   # one ensure_count (clips at slot 1)
    assert emit_counts["clips"] == 2
    assert emit_counts["devices"] == 0
    assert emit_counts["envelopes"] == 1
    assert emit_counts["arrangement"] == 2
    assert emit_counts["cues"] == 1

    # Final link state.
    fresh = init_db(db_path)
    try:
        for db_id in (filled_song["drums_id"], filled_song["bass_id"]):
            assert Q.get_ableton_link(
                fresh, session_id=session, db_kind="track", db_id=db_id,
            ) is not None
        assert Q.get_ableton_link(
            fresh, session_id=session, db_kind="return",
            db_id=filled_song["reverb_id"],
        ) is not None
    finally:
        fresh.close()


# ---------------------------------------------------------------------------
# W9-B: create-session + --auto-session for probe-and-link
# ---------------------------------------------------------------------------


def test_cli_create_session_emits_new_id(conn, song, db_path, capsys):
    push_cli.main([
        "create-session", "--song", "t", "--db", str(db_path),
        "--name", "smoke",
    ])
    out = json.loads(capsys.readouterr().out)
    assert out["song_name"] == "t"
    assert out["name"] == "smoke"
    assert len(out["session_id"]) == 32
    # And the row actually landed.
    fresh = init_db(db_path)
    try:
        s = Q.get_ableton_session(fresh, out["session_id"])
        assert s is not None
        assert s["song_id"] == song
    finally:
        fresh.close()


def test_cli_create_session_default_name_uses_timestamp(conn, song, db_path, capsys):
    push_cli.main([
        "create-session", "--song", "t", "--db", str(db_path),
    ])
    out = json.loads(capsys.readouterr().out)
    # Default name is <slug>-<utc-timestamp> matching r"<slug>-\d{8}-\d{6}".
    assert out["name"].startswith("t-")
    parts = out["name"].split("-", 1)
    assert len(parts[1]) == len("20260519-150000")  # YYYYMMDD-HHMMSS


def test_cli_create_session_refuses_missing_song(conn, db_path):
    with pytest.raises(SystemExit, match="no song named"):
        push_cli.main([
            "create-session", "--song", "nosuchsong", "--db", str(db_path),
        ])


def test_cli_probe_and_link_auto_session_creates_and_uses(
    conn, song, db_path, tmp_path, capsys,
):
    """End-to-end auto-session path: probe-and-link bootstraps the session
    on its own when no session_id is provided."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "tracks": [{"track_index": 1, "name": "Drums", "kind": "midi"}],
        "returns": [],
    }))
    push_cli.main([
        "probe-and-link", "--song", "t", "--db", str(db_path),
        "--snapshot", str(snapshot), "--auto-session",
    ])
    out = json.loads(capsys.readouterr().out)
    assert out["auto_session_created"] is True
    assert out["song_id"] == song
    assert out["session_id"] and len(out["session_id"]) == 32
    # The session row exists and the link was written.
    fresh = init_db(db_path)
    try:
        s = Q.get_ableton_session(fresh, out["session_id"])
        assert s is not None
    finally:
        fresh.close()


def test_cli_probe_and_link_auto_session_requires_song(conn, song, db_path, tmp_path):
    """--auto-session needs --song <slug> (--db alone can't infer the song)."""
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"tracks": [], "returns": []}))
    with pytest.raises(SystemExit, match="--auto-session requires --song"):
        push_cli.main([
            "probe-and-link", "--db", str(db_path),
            "--snapshot", str(snapshot), "--auto-session",
        ])


def test_cli_probe_and_link_auto_session_rejects_explicit_session_id(
    conn, song, session, db_path, tmp_path,
):
    """--auto-session + positional session_id is invalid (ambiguous intent)."""
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"tracks": [], "returns": []}))
    with pytest.raises(SystemExit, match="mutually exclusive"):
        push_cli.main([
            "probe-and-link", session, "--song", "t", "--db", str(db_path),
            "--snapshot", str(snapshot), "--auto-session",
        ])


def test_cli_probe_and_link_requires_session_id_when_no_auto(
    conn, song, db_path, tmp_path,
):
    """Without --auto-session AND without positional session_id, refuse."""
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"tracks": [], "returns": []}))
    with pytest.raises(SystemExit, match="--auto-session"):
        push_cli.main([
            "probe-and-link", "--song", "t", "--db", str(db_path),
            "--snapshot", str(snapshot),
        ])


# ---------------------------------------------------------------------------
# W18-B: --probe flag (in-process MCP TCP probe; no tmp snapshot file)
# ---------------------------------------------------------------------------


class _FakeResp:
    """Minimal stand-in for hallucinote_mcp.wire.Response. The CLI reads
    .ok / .error / .result via getattr, so a SimpleNamespace would do, but
    a named class makes intent obvious in test failures."""
    def __init__(self, *, ok: bool, result=None, error: str | None = None):
        self.ok = ok
        self.result = result
        self.error = error


def _fake_send(tracks, returns):
    """Build a send_fn that returns the right shape for the two probe
    calls. Use for --probe tests; mirrors how push_execute tests inject
    a send_fn to avoid touching hallucinote_mcp or Live."""
    def send(req):
        if req.tool == "ableton_track" and req.action == "list":
            return _FakeResp(ok=True, result={"tracks": list(tracks)})
        if req.tool == "ableton_return" and req.action == "list":
            return _FakeResp(ok=True, result={"returns": list(returns)})
        return _FakeResp(ok=False, error=f"unexpected probe call: {req.tool}/{req.action}")
    return send


def test_cli_probe_and_link_via_probe_flag(
    conn, song, session, db_path, capsys, monkeypatch,
):
    """--probe replaces --snapshot: live probe happens in-process via the
    injected send_fn, no tmp file involved."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    monkeypatch.setattr(
        push_cli, "_probe_live_via_mcp",
        lambda send_fn=None: ([{"track_index": 7, "name": "Drums", "kind": "midi"}], []),
    )
    monkeypatch.setattr(
        push_cli, "_probe_live_devices_via_mcp",
        lambda *, live_tracks, live_returns, send_fn=None: {},
    )
    push_cli.main([
        "probe-and-link", session, "--db", str(db_path), "--probe",
    ])
    out = json.loads(capsys.readouterr().out)
    assert out["matched_tracks"] == [
        {"db_id": tid, "name": "Drums", "ableton_index": 7},
    ]


def test_cli_probe_and_link_probe_and_snapshot_are_mutex(
    conn, song, session, db_path, tmp_path,
):
    """--probe and --snapshot can't both be given (argparse mutex)."""
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"tracks": [], "returns": []}))
    with pytest.raises(SystemExit):
        push_cli.main([
            "probe-and-link", session, "--db", str(db_path),
            "--probe", "--snapshot", str(snapshot),
        ])


def test_cli_probe_and_link_requires_probe_or_snapshot(
    conn, song, session, db_path,
):
    """Neither --probe nor --snapshot → argparse refuses (the mutex group
    is required=True so a forgotten flag isn't silently a stale read)."""
    with pytest.raises(SystemExit):
        push_cli.main([
            "probe-and-link", session, "--db", str(db_path),
        ])


def test_cli_probe_and_link_probe_threads_auto_session_created(
    conn, song, db_path, capsys, monkeypatch,
):
    """W18-D wiring: --probe + --auto-session + canonical defaults →
    default_scaffold_unmatched_tracks surfaces in CLI output."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    monkeypatch.setattr(
        push_cli, "_probe_live_via_mcp",
        lambda send_fn=None: (
            [
                {"track_index": 1, "name": "1-MIDI", "kind": "midi"},
                {"track_index": 2, "name": "2-MIDI", "kind": "midi"},
            ],
            [],
        ),
    )
    monkeypatch.setattr(
        push_cli, "_probe_live_devices_via_mcp",
        lambda *, live_tracks, live_returns, send_fn=None: {},
    )
    push_cli.main([
        "probe-and-link", "--song", "t", "--db", str(db_path),
        "--probe", "--auto-session",
    ])
    out = json.loads(capsys.readouterr().out)
    assert out["auto_session_created"] is True
    assert len(out["default_scaffold_unmatched_tracks"]) == 2


def test_cli_check_coherence_via_probe_flag(
    conn, song, session, db_path, capsys, monkeypatch,
):
    """check-coherence accepts --probe symmetrically with probe-and-link."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=4,
    )
    conn.commit()
    monkeypatch.setattr(
        push_cli, "_probe_live_via_mcp",
        lambda send_fn=None: ([{"track_index": 4, "name": "Drums"}], []),
    )
    rc = push_cli.main([
        "check-coherence", session, "--db", str(db_path), "--probe",
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["ok"] is True


def test_probe_live_via_mcp_surfaces_track_list_failure():
    """If Live's ableton_track(list) reports ok=false, the CLI raises a
    teaching SystemExit instead of silently returning empty lists."""
    def send(req):
        return _FakeResp(ok=False, error="connection refused")
    with pytest.raises(SystemExit, match="ableton_track\\(list\\) failed"):
        push_cli._probe_live_via_mcp(send_fn=send)


def test_probe_live_via_mcp_returns_flat_lists():
    """Unwraps the {tracks: [...]} + {returns: [...]} payload shape."""
    send = _fake_send(
        tracks=[{"track_index": 1, "name": "Drums", "kind": "midi"}],
        returns=[{"return_index": 1, "name": "A-Reverb"}],
    )
    live_tracks, live_returns = push_cli._probe_live_via_mcp(send_fn=send)
    assert live_tracks == [{"track_index": 1, "name": "Drums", "kind": "midi"}]
    assert live_returns == [{"return_index": 1, "name": "A-Reverb"}]


def test_probe_live_devices_via_mcp_builds_parent_keyed_dict():
    """W20-A: one device-list probe per Live track + return; result is keyed
    by ``(parent_kind, ableton_index)``."""
    def send(req):
        if req.tool != "ableton_device" or req.action != "list":
            return _FakeResp(ok=False, error=f"unexpected: {req.tool}/{req.action}")
        if "track_index" in req.params:
            idx = req.params["track_index"]
            return _FakeResp(ok=True, result={
                "devices": [
                    {"device_index": 1, "name": "Operator", "class_name": "Operator"},
                ] if idx == 1 else [],
            })
        if "return_index" in req.params:
            return _FakeResp(ok=True, result={
                "devices": [
                    {"device_index": 1, "name": "Reverb", "class_name": "Reverb"},
                ],
            })
        return _FakeResp(ok=False, error="missing parent index")
    by_parent = push_cli._probe_live_devices_via_mcp(
        live_tracks=[
            {"track_index": 1, "name": "Drums"},
            {"track_index": 2, "name": "Bass"},
        ],
        live_returns=[{"return_index": 1, "name": "A-Reverb"}],
        send_fn=send,
    )
    assert by_parent[("track", 1)] == [
        {"device_index": 1, "name": "Operator", "class_name": "Operator"},
    ]
    assert by_parent[("track", 2)] == []
    assert by_parent[("return", 1)] == [
        {"device_index": 1, "name": "Reverb", "class_name": "Reverb"},
    ]


def test_probe_live_devices_via_mcp_tolerates_per_parent_failure():
    """If one parent's device probe fails (ok=False), that parent gets
    dropped from the dict; other parents still appear. The whole probe
    doesn't abort on a single transient."""
    def send(req):
        if req.params.get("track_index") == 2:
            return _FakeResp(ok=False, error="transient")
        return _FakeResp(ok=True, result={"devices": []})
    by_parent = push_cli._probe_live_devices_via_mcp(
        live_tracks=[
            {"track_index": 1, "name": "Drums"},
            {"track_index": 2, "name": "Bass"},
        ],
        live_returns=[],
        send_fn=send,
    )
    assert ("track", 1) in by_parent
    assert ("track", 2) not in by_parent


def test_probe_live_devices_via_mcp_probes_master_chain():
    """ANALYZER-INDEX: the master chain is probed via master=True and keyed
    ("master", 0), so probe-and-link can reconcile master device links against
    analyzer drift."""
    master_devices = [
        {"device_index": 1, "name": "Limiter", "class_name": "Limiter"},
        {"device_index": 2, "name": "HallucinoteAnalyzer",
         "class_name": "MxDeviceAudioEffect"},
    ]

    def send(req):
        assert req.tool == "ableton_device" and req.action == "list"
        if req.params.get("master"):
            return _FakeResp(ok=True, result={"devices": master_devices})
        return _FakeResp(ok=True, result={"devices": []})
    by_parent = push_cli._probe_live_devices_via_mcp(
        live_tracks=[], live_returns=[], send_fn=send,
    )
    assert by_parent[("master", 0)] == master_devices


def test_probe_live_devices_via_mcp_tolerates_master_probe_failure():
    """A transient master probe failure drops the ("master", 0) key without
    aborting the whole probe — same per-parent tolerance as track/return."""
    def send(req):
        if req.params.get("master"):
            return _FakeResp(ok=False, error="transient")
        return _FakeResp(ok=True, result={"devices": []})
    by_parent = push_cli._probe_live_devices_via_mcp(
        live_tracks=[{"track_index": 1, "name": "Drums"}],
        live_returns=[],
        send_fn=send,
    )
    assert ("master", 0) not in by_parent
    assert ("track", 1) in by_parent


# ---------------------------------------------------------------------------
# W10-E: minimal results format (positional {ok, result}, no per-entry key/tool)
# ---------------------------------------------------------------------------


def test_cli_apply_accepts_minimal_results_with_plan(
    conn, song, session, db_path, tmp_path, capsys,
):
    """W10-E: agent assembles half as much JSON per call by dropping
    `key` and `tool` from each result; CLI re-derives them from --plan."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")

    # Plan the tracks phase to capture a real key.
    push_cli.main(["plan", "tracks", session, "--db", str(db_path)])
    plan_json = json.loads(capsys.readouterr().out)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan_json))
    assert len(plan_json["calls"]) == 1
    # The plan's one call should be a track create — fake a successful
    # Live response without echoing key/tool.
    minimal_results = [{"ok": True, "result": {"track_index": 1}}]
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(minimal_results))

    push_cli.main([
        "apply", session, "--db", str(db_path),
        "--results", str(results_path),
        "--plan", str(plan_path),
    ])
    apply_summary = json.loads(capsys.readouterr().out)
    assert apply_summary["applied"] == 1
    assert apply_summary["failed"] == 0
    # Link landed.
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=tid,
    ) is not None


def test_cli_apply_minimal_requires_plan(
    conn, song, session, db_path, tmp_path,
):
    """W10-E: minimal results without --plan is a teaching error."""
    minimal_results = [{"ok": True, "result": {"track_index": 1}}]
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(minimal_results))
    with pytest.raises(SystemExit, match="minimal results format requires --plan"):
        push_cli.main([
            "apply", session, "--db", str(db_path),
            "--results", str(results_path),
        ])


def test_cli_apply_minimal_length_mismatch_teaches(
    conn, song, session, db_path, tmp_path, capsys,
):
    """W10-E: results count mismatching plan count refuses with the
    actual counts in the message (so the user can spot the missing call)."""
    M.create_track(conn, song_id=song, track_index=1, name="T1", kind="midi")
    M.create_track(conn, song_id=song, track_index=2, name="T2", kind="midi")
    push_cli.main(["plan", "tracks", session, "--db", str(db_path)])
    plan_json = json.loads(capsys.readouterr().out)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan_json))
    assert len(plan_json["calls"]) == 2
    # Only one result for two calls.
    minimal_results = [{"ok": True, "result": {"track_index": 1}}]
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(minimal_results))
    with pytest.raises(SystemExit, match=r"length 1 doesn't match plan calls length 2"):
        push_cli.main([
            "apply", session, "--db", str(db_path),
            "--results", str(results_path),
            "--plan", str(plan_path),
        ])


def test_cli_apply_legacy_format_still_works(
    conn, song, session, db_path, tmp_path, capsys,
):
    """W10-E: existing callers using {key, ok, tool, result} keep working
    unchanged. --plan is ignored in this path (sniff: if any entry has key,
    treat as legacy)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    push_cli.main(["plan", "tracks", session, "--db", str(db_path)])
    plan_json = json.loads(capsys.readouterr().out)
    legacy_results = [
        {
            "key": plan_json["calls"][0]["key"],
            "ok": True,
            "tool": plan_json["calls"][0]["tool"],
            "result": {"track_index": 1},
        }
    ]
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(legacy_results))
    push_cli.main([
        "apply", session, "--db", str(db_path),
        "--results", str(results_path),
    ])  # NO --plan
    apply_summary = json.loads(capsys.readouterr().out)
    assert apply_summary["applied"] == 1
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=tid,
    ) is not None


def test_cli_apply_empty_results_is_no_op(
    conn, song, session, db_path, tmp_path, capsys,
):
    """W10-E: empty list applies cleanly (zero net work). Both formats
    happen to look identical for empty input — sniff defaults to legacy."""
    results_path = tmp_path / "results.json"
    results_path.write_text("[]")
    push_cli.main([
        "apply", session, "--db", str(db_path),
        "--results", str(results_path),
    ])
    apply_summary = json.loads(capsys.readouterr().out)
    assert apply_summary["applied"] == 0
    assert apply_summary["failed"] == 0


def test_cli_apply_rejects_mixed_results_format(
    conn, song, session, db_path, tmp_path,
):
    """W10-E PR-review correctness: half the entries with `key` and half
    without is almost certainly a bug — fail loudly rather than picking
    one format silently."""
    M.create_track(conn, song_id=song, track_index=1, name="T1", kind="midi")
    M.create_track(conn, song_id=song, track_index=2, name="T2", kind="midi")
    mixed_results = [
        {"key": "track:abc", "ok": True, "tool": "ableton_track", "result": {"track_index": 1}},
        {"ok": True, "result": {"track_index": 2}},  # missing key
    ]
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(mixed_results))
    with pytest.raises(SystemExit, match="mixed result formats"):
        push_cli.main([
            "apply", session, "--db", str(db_path),
            "--results", str(results_path),
        ])


def test_cli_apply_legacy_format_with_plan_warns_but_proceeds(
    conn, song, session, db_path, tmp_path, capsys,
):
    """W10-E PR-review correctness: passing --plan with legacy-keyed
    results was previously a silent ignore — now warns to stderr so the
    user notices the unused arg, but still applies cleanly."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    push_cli.main(["plan", "tracks", session, "--db", str(db_path)])
    plan_json = json.loads(capsys.readouterr().out)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan_json))

    legacy_results = [{
        "key": plan_json["calls"][0]["key"],
        "ok": True,
        "tool": plan_json["calls"][0]["tool"],
        "result": {"track_index": 1},
    }]
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(legacy_results))

    push_cli.main([
        "apply", session, "--db", str(db_path),
        "--results", str(results_path),
        "--plan", str(plan_path),  # ignored, but should warn
    ])
    captured = capsys.readouterr()
    assert "--plan is ignored" in captured.err
    apply_summary = json.loads(captured.out)
    assert apply_summary["applied"] == 1
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=tid,
    ) is not None


def test_cli_apply_minimal_format_handles_ack_only_batch(
    conn, song, session, db_path, tmp_path, capsys,
):
    """W10-E PR-review coverage: the mix phase emitting ack-only mixer
    property sets (no per-call link rows) — the minimal format dispatches
    all calls correctly via plan order even when the result bodies are
    empty. This is the common shape for the mix phase once tracks are
    linked."""
    # Build something that yields a heterogeneous mix plan: track + non-default
    # mixer state.
    tid = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    M.set_track_mixer(conn, track_id=tid, volume=0.5, pan=-0.25)
    # Link the track explicitly so the mix phase has work to do.
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1,
    )

    push_cli.main(["plan", "mix", session, "--db", str(db_path)])
    plan_json = json.loads(capsys.readouterr().out)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan_json))
    assert len(plan_json["calls"]) >= 2  # at least volume + pan
    # Mixer sets are ack-only — empty result body is fine.
    minimal_results = [{"ok": True, "result": {}} for _ in plan_json["calls"]]
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(minimal_results))

    push_cli.main([
        "apply", session, "--db", str(db_path),
        "--results", str(results_path),
        "--plan", str(plan_path),
    ])
    apply_summary = json.loads(capsys.readouterr().out)
    assert apply_summary["applied"] == len(plan_json["calls"])
    assert apply_summary["failed"] == 0


# ---------------------------------------------------------------------------
# R-1.2: cleanup-default-scaffold
# ---------------------------------------------------------------------------


def test_plan_cleanup_default_scaffold_descending_track_indexes():
    """Deletable tracks come out in descending index order so naive
    forward iteration over them produces safe descending deletes (each
    delete shifts later indexes down)."""
    plan = push.plan_cleanup_default_scaffold(
        unmatched_live_tracks=[
            {"track_index": 1, "name": "1-MIDI"},
            {"track_index": 2, "name": "2-MIDI"},
            {"track_index": 3, "name": "3-Audio"},
            {"track_index": 4, "name": "4-Audio"},
        ],
        unmatched_live_returns=[],
        total_live_track_count=8,  # 4 defaults + 4 song tracks
        matched_track_count=4,
    )
    assert plan.can_proceed is True
    assert [t["track_index"] for t in plan.deletable_tracks] == [4, 3, 2, 1]


def test_plan_cleanup_default_scaffold_refuses_non_canonical():
    """Non-canonical unmatched tracks → refuse with names listed.
    Cleanup never deletes anything the user might want to keep."""
    plan = push.plan_cleanup_default_scaffold(
        unmatched_live_tracks=[
            {"track_index": 1, "name": "1-MIDI"},
            {"track_index": 5, "name": "SomeoneElsesTrack"},
        ],
        unmatched_live_returns=[],
        total_live_track_count=5,
        matched_track_count=0,
    )
    assert plan.can_proceed is False
    kinds = [r["kind"] for r in plan.refusals]
    assert "non_canonical_tracks" in kinds
    detail = next(r["detail"] for r in plan.refusals
                  if r["kind"] == "non_canonical_tracks")
    assert "SomeoneElsesTrack" in detail


def test_plan_cleanup_default_scaffold_refuses_would_empty_live():
    """Deleting all 4 defaults when there are no song tracks would
    leave Live with zero tracks — Live's last-track delete refuses,
    so the cleanup planner refuses upstream with a teaching error."""
    plan = push.plan_cleanup_default_scaffold(
        unmatched_live_tracks=[
            {"track_index": 1, "name": "1-MIDI"},
            {"track_index": 2, "name": "2-MIDI"},
            {"track_index": 3, "name": "3-Audio"},
            {"track_index": 4, "name": "4-Audio"},
        ],
        unmatched_live_returns=[],
        total_live_track_count=4,  # only the 4 defaults
        matched_track_count=0,
    )
    assert plan.can_proceed is False
    assert any(r["kind"] == "would_empty_live_tracks" for r in plan.refusals)


def test_plan_cleanup_default_scaffold_descending_return_indexes():
    """Returns also descend; canonical default returns are
    A-Reverb (1) and B-Delay (2). No min-count constraint on returns."""
    plan = push.plan_cleanup_default_scaffold(
        unmatched_live_tracks=[{"track_index": 1, "name": "1-MIDI"}],
        unmatched_live_returns=[
            {"return_index": 1, "name": "A-Reverb"},
            {"return_index": 2, "name": "B-Delay"},
        ],
        total_live_track_count=5,
        matched_track_count=4,
    )
    assert plan.can_proceed is True
    assert [r["return_index"] for r in plan.deletable_returns] == [2, 1]


def test_plan_cleanup_default_scaffold_refuses_non_canonical_returns():
    """Same conservatism for returns: a renamed default or someone else's
    return refuses cleanup."""
    plan = push.plan_cleanup_default_scaffold(
        unmatched_live_tracks=[],
        unmatched_live_returns=[
            {"return_index": 1, "name": "A-Reverb"},
            {"return_index": 2, "name": "CustomBus"},
        ],
        total_live_track_count=4,
        matched_track_count=4,
    )
    assert plan.can_proceed is False
    assert any(r["kind"] == "non_canonical_returns" for r in plan.refusals)


def test_plan_cleanup_default_scaffold_nothing_to_do():
    """When all unmatched parents are non-canonical → refuse non-canonical.
    When NOTHING is unmatched → 'nothing_to_do' refusal so a CLI caller
    doesn't silently exit 0 against a fully-matched Live set."""
    plan = push.plan_cleanup_default_scaffold(
        unmatched_live_tracks=[],
        unmatched_live_returns=[],
        total_live_track_count=4,
        matched_track_count=4,
    )
    assert plan.can_proceed is False
    assert any(r["kind"] == "nothing_to_do" for r in plan.refusals)


def test_cli_cleanup_default_scaffold_dispatches_descending_deletes(
    conn, song, session, db_path, capsys, monkeypatch,
):
    """End-to-end CLI: probe Live, identify 4 defaults alongside one
    song track, dispatch four ``ableton_track(delete)`` calls in
    descending order, re-probe, output a summary."""
    # Set up: one song track ("Drums") already in Live at index 5,
    # alongside 4 defaults at 1-4. Mirrors the partial-push-recovery
    # scenario the sun-zone-done canary hit.
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")

    pre_tracks = [
        {"track_index": 1, "name": "1-MIDI", "kind": "midi"},
        {"track_index": 2, "name": "2-MIDI", "kind": "midi"},
        {"track_index": 3, "name": "3-Audio", "kind": "audio"},
        {"track_index": 4, "name": "4-Audio", "kind": "audio"},
        {"track_index": 5, "name": "Drums", "kind": "midi"},
    ]
    post_tracks = [
        # After cleanup the song's Drums shifts down to index 1.
        {"track_index": 1, "name": "Drums", "kind": "midi"},
    ]
    probe_calls = {"track_list": 0, "return_list": 0}

    def fake_probe_live(send_fn=None):
        probe_calls["track_list"] += 1
        # First call → pre-cleanup state; second call → post-cleanup state.
        if probe_calls["track_list"] == 1:
            return list(pre_tracks), []
        return list(post_tracks), []

    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", fake_probe_live)
    monkeypatch.setattr(
        push_cli, "_probe_live_devices_via_mcp",
        lambda *, live_tracks, live_returns, send_fn=None: {},
    )

    deletes: list[tuple[str, int]] = []

    def _fake_send(req):
        if req.tool == "ableton_track" and req.action == "delete":
            deletes.append(("track", req.params["track_index"]))
            return _FakeResp(ok=True, result={"deleted": True})
        if req.tool == "ableton_return" and req.action == "delete":
            deletes.append(("return", req.params["return_index"]))
            return _FakeResp(ok=True, result={"deleted": True})
        return _FakeResp(ok=False, error=f"unexpected: {req.tool}/{req.action}")

    monkeypatch.setattr(push_cli, "_resolve_send_fn", lambda: _fake_send)

    rc = push_cli.main([
        "cleanup-default-scaffold", session, "--db", str(db_path),
    ])
    assert rc == 0, capsys.readouterr().err
    out = json.loads(capsys.readouterr().out)

    # Deletes in descending track-index order, no return deletes (no
    # canonical default returns in this scenario).
    assert deletes == [
        ("track", 4), ("track", 3), ("track", 2), ("track", 1),
    ]
    assert len(out["deleted_tracks"]) == 4
    assert out["deleted_returns"] == []
    # The post-probe link re-pointed Drums from track_index=5 to 1.
    ableton_index = Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=tid,
    )
    assert ableton_index == 1


def test_cli_cleanup_default_scaffold_refuses_on_non_canonical(
    conn, song, session, db_path, capsys, monkeypatch,
):
    """If Live carries a non-canonical unmatched track, cleanup refuses
    (exit 1) without dispatching any deletes — conservative."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    monkeypatch.setattr(
        push_cli, "_probe_live_via_mcp",
        lambda send_fn=None: (
            [
                {"track_index": 1, "name": "1-MIDI", "kind": "midi"},
                {"track_index": 2, "name": "MyOtherSong", "kind": "midi"},
            ],
            [],
        ),
    )
    monkeypatch.setattr(
        push_cli, "_probe_live_devices_via_mcp",
        lambda *, live_tracks, live_returns, send_fn=None: {},
    )

    deletes: list = []

    def _fake_send(req):
        deletes.append((req.tool, req.action))
        return _FakeResp(ok=False, error="should not have been called")

    monkeypatch.setattr(push_cli, "_resolve_send_fn", lambda: _fake_send)

    rc = push_cli.main([
        "cleanup-default-scaffold", session, "--db", str(db_path),
    ])
    assert rc == 1
    captured = capsys.readouterr()
    # Refusal JSON lands on stderr.
    err_lines = captured.err
    assert "refused" in err_lines
    assert "MyOtherSong" in err_lines
    # Nothing was dispatched.
    assert deletes == []


# ---------- A1-resid — _cmd_execute default coherence-check hardening ----------


def test_cli_execute_refuses_when_no_coherence_flag_passed(
    conn, song, session, db_path, capsys,
):
    """A1-resid: pre-hardening, omitting all three coherence flags silently
    skipped the check (the punk-fate state-drift safety net). Now argparse
    refuses at the parser, surfacing the three valid options so a missed
    flag can't slip past the gate."""
    with pytest.raises(SystemExit) as exc:
        push_cli.main([
            "execute", session, "--db", str(db_path),
        ])
    # argparse exits 2 on bad usage.
    assert exc.value.code == 2
    err = capsys.readouterr().err
    # All three valid flags should appear in argparse's enumeration.
    assert "--probe" in err
    assert "--snapshot" in err
    assert "--no-coherence-check" in err


def test_cli_execute_no_coherence_check_skips_validation(
    conn, song, session, db_path, monkeypatch, tmp_path,
):
    """A1-resid: the explicit opt-out flag proceeds to dispatch without
    invoking the coherence check. We verify by monkeypatching
    ``push.check_coherence`` to fail the test if called — that asserts
    the opt-out path is structural, not a comment in the code."""
    def _check_should_not_run(*args, **kwargs):
        raise AssertionError(
            "push.check_coherence called despite --no-coherence-check"
        )
    monkeypatch.setattr(push, "check_coherence", _check_should_not_run)
    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", lambda send_fn=None: ([], []))

    def _fake_execute(**kwargs):
        from hallucinote.sync.push_execute import ExecuteResult
        return ExecuteResult(
            outcome="ok", exit_code=0, phase_halted=None,
            phases=[], state_file=None, errors_file=None,
        )
    monkeypatch.setattr(push_cli.push_execute, "execute_push", _fake_execute)

    rc = push_cli.main([
        "execute", session, "--db", str(db_path),
        "--no-coherence-check",
        "--state-dir", str(tmp_path),
    ])
    assert rc == 0


def test_cli_execute_partial_summary_includes_verbatim_recovery_command(
    conn, song, session, db_path, monkeypatch, capsys, tmp_path,
):
    """A5: the FAIL summary appends the verbatim re-run command so the
    agent doesn't have to assemble it. Pre-A5 the user/agent had to
    reach into the CLI help to reconstruct flags."""
    monkeypatch.setattr(push, "check_coherence", lambda *a, **kw: push.CoherenceResult(ok=True))
    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", lambda send_fn=None: ([], []))

    def _fake_execute(**kwargs):
        from hallucinote.sync.push_execute import ExecuteResult
        return ExecuteResult(
            outcome="partial", exit_code=1,
            phase_halted="devices",
            phases=[], state_file=None, errors_file=None,
        )
    monkeypatch.setattr(push_cli.push_execute, "execute_push", _fake_execute)

    rc = push_cli.main([
        "execute", session, "--db", str(db_path),
        "--probe",
        "--state-dir", str(tmp_path),
    ])
    assert rc == 1
    out = capsys.readouterr().out
    # The next-command line names execute + the session id + --probe.
    assert "Recovery:" in out
    assert "push_cli execute" in out
    assert session in out
    assert "--probe" in out


def test_cli_execute_ok_summary_omits_recovery_hint(
    conn, song, session, db_path, monkeypatch, capsys, tmp_path,
):
    """Mirror pin: clean ok exits don't emit the recovery line.
    Adding ceremony to a successful push would dilute the recovery
    signal when it actually matters."""
    monkeypatch.setattr(push, "check_coherence", lambda *a, **kw: push.CoherenceResult(ok=True))
    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", lambda send_fn=None: ([], []))

    def _fake_execute(**kwargs):
        from hallucinote.sync.push_execute import ExecuteResult
        return ExecuteResult(
            outcome="ok", exit_code=0, phase_halted=None,
            phases=[], state_file=None, errors_file=None,
        )
    monkeypatch.setattr(push_cli.push_execute, "execute_push", _fake_execute)

    rc = push_cli.main([
        "execute", session, "--db", str(db_path),
        "--probe",
        "--state-dir", str(tmp_path),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Recovery:" not in out


def test_cli_execute_probe_runs_coherence_check(
    conn, song, session, db_path, monkeypatch, tmp_path,
):
    """Sibling pin: --probe still invokes the coherence check. Asymmetric
    coverage with the opt-out test catches a regression that would
    silently disable the gate."""
    coherence_called = {"count": 0}
    original_check = push.check_coherence

    def _spy_check(*args, **kwargs):
        coherence_called["count"] += 1
        return original_check(*args, **kwargs)
    monkeypatch.setattr(push, "check_coherence", _spy_check)
    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", lambda send_fn=None: ([], []))

    def _fake_execute(**kwargs):
        from hallucinote.sync.push_execute import ExecuteResult
        return ExecuteResult(
            outcome="ok", exit_code=0, phase_halted=None,
            phases=[], state_file=None, errors_file=None,
        )
    monkeypatch.setattr(push_cli.push_execute, "execute_push", _fake_execute)

    rc = push_cli.main([
        "execute", session, "--db", str(db_path),
        "--probe",
        "--state-dir", str(tmp_path),
    ])
    assert rc == 0
    assert coherence_called["count"] == 1


# ---------------------------------------------------------------------------
# SYN-5C3J — version-mismatch recovery teaching
#
# When a fresh CLI process and the running Remote Script are built from
# different commits, every call refuses on the version handshake. The generic
# "fix build.py and re-run" recovery is wrong (re-running can't clear drift);
# the CLI must teach the pin recovery that resolves it instead. The refusal is
# generated by the (possibly OLD) Remote Script, so the teaching has to come
# from the CLI side — pinned here.
# ---------------------------------------------------------------------------


def _result_with_error_substring(substr: str):
    from hallucinote.sync.push_execute import ExecuteResult
    return ExecuteResult(
        outcome="partial", exit_code=1, phase_halted="tracks",
        phases=[], state_file=None, errors_file=None,
        top_error_patterns=[{
            "error_substring": substr, "count": 1, "affected_keys": ["track:1"],
            "tool": "ableton_track", "action": "create", "hint": None,
        }],
    )


def test_version_mismatch_recovery_teaches_pin_recipe():
    """A version-mismatch refusal yields the pin recovery: the worktree +
    PYTHONPATH recipe and the preflight verify step, plus the reinstall
    alternative."""
    result = _result_with_error_substring(
        "Hallucinote MCP version mismatch: MCP server side reports 0.9.4"
    )
    text = push_cli._version_mismatch_recovery(result)
    assert text is not None
    assert "git worktree add" in text
    assert "PYTHONPATH" in text
    assert "preflight" in text
    assert "ableton-mcp-install" in text  # the reinstall path is offered too


def test_version_mismatch_recovery_detects_handshake_missing_branch():
    """The other handshake refusal (server didn't send a version at all) is the
    same recovery shape — detect it via its marker too."""
    result = _result_with_error_substring(
        "Hallucinote MCP version handshake missing: the installed package"
    )
    assert push_cli._version_mismatch_recovery(result) is not None


def test_version_mismatch_recovery_none_for_ordinary_failure():
    """A normal push failure must NOT trigger the pin teaching — it would
    mislead toward a version fix when the real cause is content."""
    result = _result_with_error_substring(
        "RuntimeError: Couldn't create clip — slot 3 occupied"
    )
    assert push_cli._version_mismatch_recovery(result) is None


def test_version_mismatch_recovery_none_when_no_error_patterns():
    from hallucinote.sync.push_execute import ExecuteResult
    clean = ExecuteResult(
        outcome="ok", exit_code=0, phase_halted=None,
        phases=[], state_file=None, errors_file=None,
    )
    assert push_cli._version_mismatch_recovery(clean) is None


def test_cli_execute_version_mismatch_prints_pin_recovery_not_generic(
    conn, song, session, db_path, monkeypatch, capsys, tmp_path,
):
    """End-to-end through the CLI: a version-mismatch push prints the pin
    recovery and suppresses the misleading generic 'fix build.py and re-run'
    recovery (re-running won't clear drift)."""
    monkeypatch.setattr(push, "check_coherence", lambda *a, **kw: push.CoherenceResult(ok=True))
    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", lambda send_fn=None: ([], []))

    def _fake_execute(**kwargs):
        return _result_with_error_substring(
            "Hallucinote MCP version mismatch: MCP server side reports 0.9.4"
        )
    monkeypatch.setattr(push_cli.push_execute, "execute_push", _fake_execute)

    rc = push_cli.main([
        "execute", session, "--db", str(db_path),
        "--probe", "--state-dir", str(tmp_path),
    ])
    assert rc == 1
    out = capsys.readouterr().out
    assert "git worktree add" in out
    assert "PYTHONPATH" in out
    # The generic build.py recovery must NOT also fire — that's the bug.
    assert "fix the underlying issue (build.py or snapshot)" not in out


# ---------------------------------------------------------------------------
# push-notes (B1) — CLI wiring + exit-code mapping
# ---------------------------------------------------------------------------


def test_cli_push_notes_wires_args_and_returns_ok(
    conn, song, session, db_path, tmp_path, capsys, monkeypatch,
):
    from hallucinote.sync import push_notes as pn

    captured: dict = {}

    def fake_push_notes(conn_arg, *, song_id, session_id, state_dir,
                        clip_ids, changed_only, actor, reason):
        captured.update(
            song_id=song_id, session_id=session_id, state_dir=str(state_dir),
            clip_ids=clip_ids, changed_only=changed_only, actor=actor,
        )
        return pn.ScopedPushResult(pushed=[{"clip_id": "c1", "name": "A", "note_count": 3}])

    monkeypatch.setattr(push_cli.push_notes, "push_notes", fake_push_notes)
    rc = push_cli.main([
        "push-notes", session, "--db", str(db_path),
        "--clip", "c1", "--clip", "c2", "--changed",
        "--state-dir", str(tmp_path),
    ])
    assert rc == 0
    assert captured["clip_ids"] == ["c1", "c2"]
    assert captured["changed_only"] is True
    assert captured["session_id"] == session
    assert captured["song_id"] == song
    assert captured["state_dir"] == str(tmp_path)
    assert "scoped notes push" in capsys.readouterr().out


def test_cli_push_notes_maps_error_and_connection_exit_codes(
    conn, song, session, db_path, capsys, monkeypatch,
):
    from hallucinote.sync import push_notes as pn

    monkeypatch.setattr(
        push_cli.push_notes, "push_notes",
        lambda *a, **k: pn.ScopedPushResult(errors=[{"clip_id": "x", "error": "boom"}]),
    )
    assert push_cli.main(["push-notes", session, "--db", str(db_path)]) == \
        push_cli.push_execute.EXIT_PARTIAL
    capsys.readouterr()

    monkeypatch.setattr(
        push_cli.push_notes, "push_notes",
        lambda *a, **k: pn.ScopedPushResult(connection_lost=True),
    )
    assert push_cli.main(["push-notes", session, "--db", str(db_path)]) == \
        push_cli.push_execute.EXIT_CONNECTION_LOST


# ---------------------------------------------------------------------------
# prune (B1b) — orphan Live session clips
# ---------------------------------------------------------------------------


def _make_prune_send_fn(*, live_clips):
    """Fake send for prune: track list (1 track 'Drums'), empty return list,
    clip list per track from ``live_clips`` (dict track_index -> [clip dicts]),
    and records delete calls. Returns the send fn with a .deletes list.
    """
    from tests.unit.sync.test_push_notes import FakeResponse

    deletes: list[dict] = []

    def send(req):
        if req.tool == "ableton_track" and req.action == "list":
            return FakeResponse(ok=True, result={"tracks": [
                {"track_index": 1, "name": "Drums", "kind": "midi"}]})
        if req.tool == "ableton_return" and req.action == "list":
            return FakeResponse(ok=True, result={"returns": []})
        if req.tool == "ableton_clip" and req.action == "list":
            ti = req.params["track_index"]
            return FakeResponse(ok=True, result={"clips": live_clips.get(ti, [])})
        if req.tool == "ableton_clip" and req.action == "delete":
            deletes.append(dict(req.params))
            return FakeResponse(ok=True, result={"deleted": True})
        return FakeResponse(ok=False, error=f"unexpected {req.tool}:{req.action}")

    send.deletes = deletes  # type: ignore[attr-defined]
    return send


def _linked_track_with_one_db_clip(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(conn, session_id=session, db_kind="track", db_id=tid,
                         ableton_index=1, actor="sync")
    M.create_clip(conn, track_id=tid, slot=1, length_beats=4.0, name="A")
    return tid


def test_cli_prune_dry_run_lists_orphan_without_deleting(
    conn, song, session, db_path, capsys, monkeypatch,
):
    _linked_track_with_one_db_clip(conn, song, session)
    # Live: slot 1 (DB-backed) + slot 2 (orphan) populated, slot 3 empty.
    send = _make_prune_send_fn(live_clips={1: [
        {"clip_index": 1, "empty": False, "name": "A"},
        {"clip_index": 2, "empty": False, "name": "orphan"},
        {"clip_index": 3, "empty": True},
    ]})
    monkeypatch.setattr(push_cli, "_resolve_send_fn", lambda: send)

    rc = push_cli.main(["prune", session, "--db", str(db_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["prunable"] == [{"track_index": 1, "track_name": "Drums",
                                "clip_index": 2, "name": "orphan"}]
    assert send.deletes == []  # dry-run deletes nothing


def test_cli_prune_apply_deletes_only_the_orphan(
    conn, song, session, db_path, capsys, monkeypatch,
):
    _linked_track_with_one_db_clip(conn, song, session)
    send = _make_prune_send_fn(live_clips={1: [
        {"clip_index": 1, "empty": False, "name": "A"},
        {"clip_index": 2, "empty": False, "name": "orphan"},
    ]})
    monkeypatch.setattr(push_cli, "_resolve_send_fn", lambda: send)

    rc = push_cli.main(["prune", session, "--db", str(db_path), "--apply"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is False
    assert out["deleted"] == [{"track_index": 1, "clip_index": 2, "name": "orphan"}]
    # exactly the orphan slot deleted — never the DB-backed slot 1
    assert send.deletes == [{"track_index": 1, "location": "session", "clip_index": 2}]


# ---------------------------------------------------------------------------
# DOC-5W8B: auto-regen REQUIREMENTS.md after a device-changing push
# ---------------------------------------------------------------------------


def _fake_execute_result(*, devices_calls_ok: int):
    from hallucinote.sync.push_execute import ExecuteResult, PhaseOutcome
    return ExecuteResult(
        outcome="ok", exit_code=0, phase_halted=None,
        phases=[
            PhaseOutcome(name="tracks", status="ok", calls_ok=1),
            PhaseOutcome(
                name="devices",
                status="ok" if devices_calls_ok else "skipped",
                calls_ok=devices_calls_ok,
            ),
        ],
    )


def test_cli_execute_regenerates_requirements_after_device_push(
    conn, song, session, db_path, capsys, monkeypatch, tmp_path,
):
    """DOC-5W8B: a push whose devices phase applied calls leaves
    REQUIREMENTS.md regenerated in the same flow (--song path)."""
    import hallucinote.sync.compat as compat

    monkeypatch.setattr(
        push_cli.push_execute, "execute_push",
        lambda **kw: _fake_execute_result(devices_calls_ok=2),
    )
    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", lambda send_fn=None: ([], []))
    monkeypatch.setattr(push_cli, "_resolve_db_path", lambda args: db_path)
    regen_calls: list[str] = []

    def fake_regen(slug):
        regen_calls.append(slug)
        return tmp_path / "REQUIREMENTS.md"

    monkeypatch.setattr(compat, "regen_requirements", fake_regen)

    rc = push_cli.main([
        "execute", session, "--song", "t", "--no-coherence-check",
    ])
    assert rc == 0
    assert regen_calls == ["t"]
    assert "REQUIREMENTS.md regenerated" in capsys.readouterr().err


def test_cli_execute_no_regen_when_devices_phase_idle(
    conn, song, session, db_path, capsys, monkeypatch,
):
    """No device calls applied -> REQUIREMENTS.md untouched, no notice."""
    import hallucinote.sync.compat as compat

    monkeypatch.setattr(
        push_cli.push_execute, "execute_push",
        lambda **kw: _fake_execute_result(devices_calls_ok=0),
    )
    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", lambda send_fn=None: ([], []))
    monkeypatch.setattr(push_cli, "_resolve_db_path", lambda args: db_path)
    monkeypatch.setattr(
        compat, "regen_requirements",
        lambda slug: pytest.fail("regen must not run for an idle devices phase"),
    )
    rc = push_cli.main([
        "execute", session, "--song", "t", "--no-coherence-check",
    ])
    assert rc == 0
    assert "REQUIREMENTS.md" not in capsys.readouterr().err


def test_cli_execute_db_only_prints_stale_notice_instead_of_regen(
    conn, song, session, db_path, capsys, monkeypatch,
):
    """--db escape hatch has no slug to resolve the song dir; the flow says
    so instead of guessing (DOC-5W8B's explicit-prompt fallback)."""
    import hallucinote.sync.compat as compat

    monkeypatch.setattr(
        push_cli.push_execute, "execute_push",
        lambda **kw: _fake_execute_result(devices_calls_ok=1),
    )
    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", lambda send_fn=None: ([], []))
    monkeypatch.setattr(
        compat, "regen_requirements",
        lambda slug: pytest.fail("regen must not run without --song"),
    )
    rc = push_cli.main([
        "execute", session, "--db", str(db_path), "--no-coherence-check",
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "REQUIREMENTS.md may be stale" in err
    assert "write-requirements" in err


def test_cli_execute_regen_failure_never_masks_push_outcome(
    conn, song, session, db_path, capsys, monkeypatch,
):
    """A regen SystemExit (e.g. song dir missing) degrades to a notice; the
    push's own exit code survives."""
    import hallucinote.sync.compat as compat

    monkeypatch.setattr(
        push_cli.push_execute, "execute_push",
        lambda **kw: _fake_execute_result(devices_calls_ok=1),
    )
    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", lambda send_fn=None: ([], []))
    monkeypatch.setattr(push_cli, "_resolve_db_path", lambda args: db_path)

    def failing_regen(slug):
        raise SystemExit("compat: songs/t/ does not exist — wrong slug?")

    monkeypatch.setattr(compat, "regen_requirements", failing_regen)
    rc = push_cli.main([
        "execute", session, "--song", "t", "--no-coherence-check",
    ])
    assert rc == 0
    assert "regen skipped" in capsys.readouterr().err


def test_cli_execute_halted_push_with_device_changes_still_regenerates(
    conn, song, session, db_path, capsys, monkeypatch, tmp_path,
):
    """A push that applied device changes then halted at a later phase still
    regenerates (the doc tracks current set state, not push success) — and
    the push's own non-zero exit code survives the regen."""
    import hallucinote.sync.compat as compat
    from hallucinote.sync.push_execute import ExecuteResult, PhaseOutcome

    halted = ExecuteResult(
        outcome="partial", exit_code=1, phase_halted="envelopes",
        phases=[
            PhaseOutcome(name="devices", status="ok", calls_ok=1),
            PhaseOutcome(name="envelopes", status="halted", calls_failed=1),
        ],
    )
    monkeypatch.setattr(
        push_cli.push_execute, "execute_push", lambda **kw: halted,
    )
    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", lambda send_fn=None: ([], []))
    monkeypatch.setattr(push_cli, "_resolve_db_path", lambda args: db_path)
    regen_calls: list[str] = []
    monkeypatch.setattr(
        compat, "regen_requirements",
        lambda slug: regen_calls.append(slug) or (tmp_path / "REQUIREMENTS.md"),
    )
    rc = push_cli.main([
        "execute", session, "--song", "t", "--no-coherence-check",
    ])
    assert rc == 1
    assert regen_calls == ["t"]
    assert "REQUIREMENTS.md regenerated" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# PSH-2R7K — execute phase-targeting (CLI wiring + --resume resolution)
# ---------------------------------------------------------------------------


def test_resume_phase_from_state_reads_halted_phase(tmp_path):
    (tmp_path / ".last-push-state.json").write_text(
        json.dumps({"phase_halted": "routing"})
    )
    assert push_cli._resume_phase_from_state(tmp_path) == "routing"


def test_resume_phase_from_state_none_when_no_file(tmp_path):
    assert push_cli._resume_phase_from_state(tmp_path) is None


def test_resume_phase_from_state_none_when_no_halt(tmp_path):
    (tmp_path / ".last-push-state.json").write_text(
        json.dumps({"phase_halted": None, "outcome": "ok"})
    )
    assert push_cli._resume_phase_from_state(tmp_path) is None


def test_cli_execute_unknown_phase_exits_2(
    conn, song, session, db_path, capsys, monkeypatch,
):
    """A bad --only phase fails fast (exit 2) with the valid-phase list. The
    rejection is a PhaseTargetError (raised before any phase dispatches); the
    live probe is stubbed so the test needs no running Live."""
    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", lambda send_fn=None: ([], []))
    rc = push_cli.main([
        "execute", session, "--db", str(db_path),
        "--no-coherence-check", "--only", "bogus",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown --only phase 'bogus'" in err
    assert "tempo_map" in err  # the valid list, in order


def test_cli_execute_unknown_phase_rejected_before_live_probe(
    conn, song, session, db_path, capsys, monkeypatch,
):
    """PSH-PHASEORDER: a typo'd phase is rejected BEFORE any Live round-trip.

    Runs with coherence checking ON (--probe, the realistic default) and makes
    both the coherence probe and the arrangement probe raise if reached. With
    the up-front validation the typo exits 2 with the teaching message and
    NEITHER probe runs — so a typo can't pay a Live round-trip (or be masked by
    a stale-link coherence refusal) before being caught."""
    def _boom_coherence(*a, **k):
        raise AssertionError("coherence probe ran before phase-name validation")

    def _boom_probe(*a, **k):
        raise AssertionError("arrangement probe ran before phase-name validation")

    monkeypatch.setattr(
        push_cli, "_cmd_check_coherence_probe_or_snapshot", _boom_coherence,
    )
    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", _boom_probe)
    rc = push_cli.main([
        "execute", session, "--db", str(db_path),
        "--probe", "--start-at", "bogus",
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown --start-at phase 'bogus'" in err
    assert "tempo_map" in err


def test_cli_execute_resume_no_prior_run_exits_2(conn, song, session, db_path, capsys):
    rc = push_cli.main([
        "execute", session, "--db", str(db_path),
        "--no-coherence-check", "--resume",
    ])
    assert rc == 2
    assert "no halted prior run" in capsys.readouterr().err


def test_cli_execute_resume_with_only_exits_2(conn, song, session, db_path, capsys):
    rc = push_cli.main([
        "execute", session, "--db", str(db_path),
        "--no-coherence-check", "--resume", "--only", "tracks",
    ])
    assert rc == 2
    assert "cannot combine" in capsys.readouterr().err


def test_resume_phase_from_state_none_on_corrupt_file(tmp_path):
    """A corrupt/half-written state file resolves to None (not a crash) — the
    operator gets the teaching 'no halted prior run' message."""
    (tmp_path / ".last-push-state.json").write_text("{not json")
    assert push_cli._resume_phase_from_state(tmp_path) is None


def test_cli_execute_resume_resolves_and_passes_targeting(
    conn, song, session, db_path, monkeypatch, capsys,
):
    """End-to-end CLI wiring: --resume reads the halted phase into start_at and
    --stop-after rides through to execute_push (resume + stop-after is allowed).

    The window must be valid (stop_after at or after the resumed start) — the
    halt was at ``routing`` so ``--stop-after arrangement`` (a later phase) is a
    real window. PSH-PHASEORDER now validates this up front, before any Live
    probe."""
    (db_path.parent / ".last-push-state.json").write_text(
        json.dumps({"phase_halted": "routing"})
    )
    captured: dict = {}

    def fake_execute(**kw):
        captured.update(kw)
        return push_cli.push_execute.ExecuteResult(
            outcome="ok", exit_code=0, phase_halted=None,
        )

    monkeypatch.setattr(push_cli.push_execute, "execute_push", fake_execute)
    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", lambda send_fn=None: ([], []))
    rc = push_cli.main([
        "execute", session, "--db", str(db_path),
        "--no-coherence-check", "--resume", "--stop-after", "arrangement",
    ])
    assert rc == 0
    assert captured["start_at"] == "routing"       # --resume resolved it
    assert captured["stop_after"] == "arrangement"  # passed through
    assert captured["only"] is None


# ---------------------------------------------------------------------------
# PSH-ARRPROBE — `execute` must not probe arrangement lanes before `tracks`
# ---------------------------------------------------------------------------


def test_cli_execute_defers_the_arrangement_probe_until_the_phase_runs(
    conn, song, session, db_path, monkeypatch, tmp_path,
):
    """The CLI half of the first-push silent no-op.

    `execute` used to probe arrangement lanes up front, reusing the COHERENCE
    probe's track list — Live's state BEFORE the `tracks` phase created the
    song's tracks. On a first push into a set holding the 4 default scaffold
    tracks that map covered indices 1-4 while the song's tracks landed at 5-13,
    so the projection planner saw every lane as unprobed and built nothing.

    Contract: what reaches `execute_push` is a CALLABLE that has NOT run yet,
    and running it issues a FRESH `ableton_track(list)` rather than reusing the
    coherence snapshot.
    """
    coherence_tracks = [{"track_index": 1, "name": "1-MIDI", "kind": "midi"}]
    post_tracks_phase = coherence_tracks + [
        {"track_index": 5, "name": "Drums", "kind": "midi"},
    ]
    track_probes: list[str] = []
    lane_probe_inputs: list[list[int]] = []

    def _fake_probe_live(send_fn=None):
        # First call = the coherence probe (pre-phases); any later call is the
        # deferred lane probe, which must see the newly-created tracks.
        track_probes.append("probe")
        if len(track_probes) == 1:
            return (list(coherence_tracks), [])
        return (list(post_tracks_phase), [])

    def _fake_lane_probe(*, live_tracks, send_fn=None):
        lane_probe_inputs.append([t["track_index"] for t in live_tracks])
        return {t["track_index"]: [] for t in live_tracks}

    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", _fake_probe_live)
    monkeypatch.setattr(
        push_cli, "_probe_live_arrangement_clips_via_mcp", _fake_lane_probe,
    )
    monkeypatch.setattr(
        push, "check_coherence", lambda *a, **kw: push.CoherenceResult(ok=True),
    )

    captured: dict = {}

    def _fake_execute(**kwargs):
        from hallucinote.sync.push_execute import ExecuteResult
        captured["probe"] = kwargs["live_arrangement_clips_by_track"]
        # Not resolved yet at hand-off — that is the whole point.
        assert lane_probe_inputs == []
        return ExecuteResult(
            outcome="ok", exit_code=0, phase_halted=None,
            phases=[], state_file=None, errors_file=None,
        )

    monkeypatch.setattr(push_cli.push_execute, "execute_push", _fake_execute)

    rc = push_cli.main([
        "execute", session, "--db", str(db_path), "--probe",
        "--state-dir", str(tmp_path),
    ])
    assert rc == 0
    assert callable(captured["probe"])

    # Resolving it (what the arrangement phase does) re-probes Live and sees
    # the track the `tracks` phase created, at its OFFSET index.
    lanes = captured["probe"]()
    assert lane_probe_inputs == [[1, 5]]
    assert 5 in lanes


def test_cli_execute_lane_probe_failure_degrades_to_empty_not_none(
    conn, song, session, db_path, monkeypatch, tmp_path, capsys,
):
    """The lane probe now runs MID-RUN, so a Live-unreachable failure must not
    escape the phase loop (that would abandon the push with no terminal state
    file and an open request row).

    It degrades to an EMPTY map — "probed, and no lane's state is known" — which
    the projection planner reads as blocked-per-track: the phase reports
    INCOMPLETE and writes nothing. It must NOT degrade to ``None``, which means
    "no probe taken" and emits create+fill with NO clear (the stacking path)."""
    def _fake_probe_live(send_fn=None):
        if not getattr(_fake_probe_live, "called", False):
            _fake_probe_live.called = True  # the coherence probe succeeds
            return ([{"track_index": 1, "name": "1-MIDI", "kind": "midi"}], [])
        raise SystemExit("push_cli --probe: ableton_track(list) failed — no Live")

    monkeypatch.setattr(push_cli, "_probe_live_via_mcp", _fake_probe_live)
    monkeypatch.setattr(
        push, "check_coherence", lambda *a, **kw: push.CoherenceResult(ok=True),
    )

    captured: dict = {}

    def _fake_execute(**kwargs):
        from hallucinote.sync.push_execute import ExecuteResult
        captured["probe"] = kwargs["live_arrangement_clips_by_track"]
        return ExecuteResult(
            outcome="ok", exit_code=0, phase_halted=None,
            phases=[], state_file=None, errors_file=None,
        )

    monkeypatch.setattr(push_cli.push_execute, "execute_push", _fake_execute)
    push_cli.main([
        "execute", session, "--db", str(db_path), "--probe",
        "--state-dir", str(tmp_path),
    ])

    lanes = captured["probe"]()
    assert lanes == {}
    assert lanes is not None
    assert "INCOMPLETE" in capsys.readouterr().err
