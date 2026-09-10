"""Replay reconciles a track by NAME; ``track_index`` is an attribute it writes.

``track_index`` is a POSITION, and the system is allowed to renumber positions
— capture's dense rank around an excluded default scaffold does exactly that.
Replay used to upsert on ``(song_id, track_index)``, so "same index" silently
meant "same track": a snapshot whose real track moved from 5 to 1 renamed the
row that happened to hold index 1 and left the original stranded, and the song
ended up with two rows for one track. Nothing in the write path was matching on
identity at all.

So the reconciliation matches on the one thing that survives a renumber — the
name — and MOVES the row it finds, keeping its UUID so ``ableton_links`` and
every child row stay pointed at valid targets. Where a name cannot identify a
single row it refuses rather than guesses, because a wrong reconciliation is
worse than none: it renames a real row, which is the bug this exists to fix.

And a row the snapshot no longer defines is REPORTED, never pruned here. An
orphan can be carrying pulled human work — its mixer state, its sends, a device
chain with tuned parameters, its clips and notes — that a build without
``--reset`` does not re-author; ``_guard_stale_snapshot`` already refuses rather
than silently reverting pulled edits, and a replay that deleted rows on its own
authority would contradict a guard this module ships. The remedy is the
operator's: ``hallucinote prune-tracks``.

Synthetic fixtures only (the convention for tests/unit/capture/).
"""
from __future__ import annotations

import json

import pytest

from hallucinote.capture import (
    SNAPSHOT_SCHEMA_VERSION,
    plan_track_reconciliation,
    replay_capture,
    utc_now_eventlike,
)
from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.db.mutations.tracks import (
    describe_track_deletion,
    prune_track,
    reindex_tracks,
)
from hallucinote.tools import prune_tracks_cli


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "identity.db")
    yield c
    c.close()


def _song_with_tracks(conn, name, tracks):
    """Seed a song whose track rows sit at the given (index, name) pairs."""
    song_id = M.create_song(conn, name=name)
    for idx, tname in tracks:
        M.create_track(conn, song_id=song_id, track_index=idx, name=tname,
                       kind="midi")
    return song_id


def _snapshot(tracks):
    """A stamped snapshot, so the SNP-8R4K migration nudge stays out of the
    way of the "no warning at all" assertions."""
    return {
        "snapshot_version": SNAPSHOT_SCHEMA_VERSION,
        "captured_at": utc_now_eventlike(),
        "song": {"tempo": 120.0, "signature": "4/4", "master": None},
        "tracks": [
            {"index": i, "name": n, "type": "midi"} for i, n in tracks
        ],
        "returns": [],
    }


def _rows(conn, song_id):
    return [
        (r["track_index"], r["name"])
        for r in Q.get_tracks_for_song(conn, song_id)
        if r["kind"] != "master"
    ]


def _ids_by_name(conn, song_id):
    return {
        r["name"]: r["id"] for r in Q.get_tracks_for_song(conn, song_id)
    }


# ---------------------------------------------------------------------------
# The reported repro
# ---------------------------------------------------------------------------


def test_a_shifted_index_moves_the_row_instead_of_renaming_another(conn):
    """The headline. A pre-fix capture put the scaffold in the snapshot and
    pushed the real track to index 5. Post-fix the snapshot has `Drums` at 1.
    The song must end with ONE `Drums` row, at index 1, and no row named
    `1-MIDI` wearing `Drums`'s identity."""
    song_id = _song_with_tracks(
        conn, "shifted", [(1, "1-MIDI"), (2, "2-MIDI"), (5, "Drums")],
    )
    before = _ids_by_name(conn, song_id)["Drums"]

    replay_capture(conn, _snapshot([(1, "Drums")]), song_name="shifted")

    rows = _rows(conn, song_id)
    assert [name for _, name in rows].count("Drums") == 1
    assert (1, "Drums") in rows
    assert "1-MIDI" not in [name for _, name in rows if name == "Drums"]
    # Same row, moved — not a new row.
    assert _ids_by_name(conn, song_id)["Drums"] == before


def test_the_moved_row_keeps_its_uuid_so_links_and_children_stay_valid(conn):
    """The property `reset_song_content`'s docstring rests on: a reconciliation
    that recreated the row would strand every ableton_link and child row
    pointing at the old id."""
    song_id = _song_with_tracks(conn, "links", [(1, "1-MIDI"), (5, "Drums")])
    drums_id = _ids_by_name(conn, song_id)["Drums"]
    chain_id = M.create_device_chain(conn, parent_track_id=drums_id)
    session_id = M.create_ableton_session(conn, song_id=song_id, name="draft")
    M.link_db_to_ableton(
        conn, session_id=session_id, db_kind="track", db_id=drums_id,
        ableton_index=5,
    )

    replay_capture(conn, _snapshot([(1, "Drums")]), song_name="links")

    assert _ids_by_name(conn, song_id)["Drums"] == drums_id
    assert [c["id"] for c in Q.get_device_chains_for_track(conn, drums_id)] == [chain_id]
    assert [
        link["db_id"] for link in Q.get_ableton_links_for_session(conn, session_id)
        if link["db_kind"] == "track"
    ] == [drums_id]


def test_a_clean_shifted_index_replay_says_nothing(conn, recwarn):
    """R7 — the warning survives as the fallback channel, not as the fix. A
    warning that fires on the healthy path is one an operator learns to
    ignore."""
    _song_with_tracks(conn, "quiet", [(1, "Bass"), (2, "Drums")])
    replay_capture(conn, _snapshot([(1, "Drums"), (2, "Bass")]), song_name="quiet")
    assert [str(w.message) for w in recwarn.list] == []


# ---------------------------------------------------------------------------
# The cases the reconciliation must NOT confuse with each other
# ---------------------------------------------------------------------------


def test_a_deliberate_swap_reconciles_both_rows_and_warns_about_neither(conn):
    """R6. DB {1:'A', 2:'B'}, snapshot [(1,'B'), (2,'A')]. Each name also sits
    at another DB index, but the snapshot covers BOTH indices, so nothing is
    stranded — a guard that only asked "does the name sit elsewhere?" warned
    twice and was wrong twice."""
    song_id = _song_with_tracks(conn, "swap", [(1, "A"), (2, "B")])
    ids = _ids_by_name(conn, song_id)

    replay_capture(conn, _snapshot([(1, "B"), (2, "A")]), song_name="swap")

    assert sorted(_rows(conn, song_id)) == [(1, "B"), (2, "A")]
    after = _ids_by_name(conn, song_id)
    assert after["A"] == ids["A"] and after["B"] == ids["B"]


def test_a_swap_emits_no_orphan_warning(conn, recwarn):
    _song_with_tracks(conn, "swap2", [(1, "A"), (2, "B")])
    replay_capture(conn, _snapshot([(1, "B"), (2, "A")]), song_name="swap2")
    assert not [
        w for w in recwarn.list
        if "left behind as a duplicate" in str(w.message)
    ]


def test_a_genuine_rename_in_live_still_renames_the_row_it_should(conn, recwarn):
    """Indices unchanged, one track renamed. There is nothing to reconcile —
    the new name matches no row — so the index-keyed upsert stands in and is
    right. It must not warn."""
    song_id = _song_with_tracks(conn, "renamed", [(1, "Drums"), (2, "Bass")])
    drums_id = _ids_by_name(conn, song_id)["Drums"]

    replay_capture(conn, _snapshot([(1, "Kit"), (2, "Bass")]), song_name="renamed")

    assert sorted(_rows(conn, song_id)) == [(1, "Kit"), (2, "Bass")]
    assert _ids_by_name(conn, song_id)["Kit"] == drums_id
    assert not [w for w in recwarn.list if "RENAMED" in str(w.message)]


def test_a_rotation_never_collides_on_the_uniqueness_constraint(conn):
    """R4 — the intermediate state is never observable as a conflict. Every
    non-trivial renumber contains a step that transiently collides on
    UNIQUE(song_id, track_index); a three-way rotation is the smallest case
    where no ordering of naive updates avoids it."""
    song_id = _song_with_tracks(conn, "rot", [(1, "A"), (2, "B"), (3, "C")])
    ids = _ids_by_name(conn, song_id)

    replay_capture(
        conn, _snapshot([(1, "C"), (2, "A"), (3, "B")]), song_name="rot",
    )

    assert sorted(_rows(conn, song_id)) == [(1, "C"), (2, "A"), (3, "B")]
    assert _ids_by_name(conn, song_id) == ids


# ---------------------------------------------------------------------------
# R3 — ambiguity refuses rather than guesses
# ---------------------------------------------------------------------------


def test_a_duplicated_db_name_is_not_reconciled_and_alerts(conn):
    """Live permits duplicate track names. Two rows named 'Dup' make the name
    useless as an identity, so replay does not move either — and says so."""
    song_id = _song_with_tracks(conn, "dup", [(1, "Dup"), (2, "Dup")])
    with pytest.warns(UserWarning, match="could not reconcile"):
        replay_capture(conn, _snapshot([(3, "Dup")]), song_name="dup")
    # Nothing was moved on a guess; the fallback simply created index 3.
    assert sorted(_rows(conn, song_id)) == [(1, "Dup"), (2, "Dup"), (3, "Dup")]


def test_a_duplicated_incoming_name_is_not_reconciled_and_alerts(conn):
    """Which of two incoming 'Dup' tracks owns the one existing row is
    unknowable, so neither claims it."""
    song_id = _song_with_tracks(conn, "dup2", [(5, "Dup")])
    with pytest.warns(UserWarning, match="could not reconcile"):
        replay_capture(conn, _snapshot([(1, "Dup"), (2, "Dup")]), song_name="dup2")
    assert (5, "Dup") in _rows(conn, song_id)


def test_the_ambiguous_fallback_still_reports_an_orphaning_rename(conn):
    """The rename guard survives as the fallback channel (R7): where the name
    was ambiguous and the index-keyed upsert had to stand in, an orphaned row
    is still named."""
    _song_with_tracks(conn, "amb", [(1, "1-MIDI"), (2, "Dup"), (3, "Dup")])
    with pytest.warns(UserWarning, match="left behind as a duplicate"):
        replay_capture(
            conn, _snapshot([(1, "Dup"), (2, "Dup")]), song_name="amb",
        )


# ---------------------------------------------------------------------------
# R5 — an orphan is reported, never pruned by replay
# ---------------------------------------------------------------------------


def _orphan_song(conn, name="orphan"):
    """A song whose snapshot drops 'Old Bagpipes', with real work hanging off
    the row so the report has something to name."""
    song_id = _song_with_tracks(conn, name, [(1, "Drums"), (2, "Old Bagpipes")])
    bagpipes = _ids_by_name(conn, song_id)["Old Bagpipes"]
    clip_id = M.create_clip(
        conn, track_id=bagpipes, slot=1, length_beats=4.0, name="verse",
    )
    M.insert_notes(conn, clip_id=clip_id, notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 90},
    ])
    chain_id = M.create_device_chain(conn, parent_track_id=bagpipes)
    M.create_device(conn, chain_id=chain_id, position=1, kind="Operator",
                    display_name="Operator", class_name="Operator")
    return song_id, bagpipes


def test_replay_reports_an_orphan_and_deletes_nothing(conn):
    song_id, bagpipes = _orphan_song(conn)
    with pytest.warns(UserWarning, match="does not define") as caught:
        replay_capture(conn, _snapshot([(1, "Drums")]), song_name="orphan")

    message = "\n".join(str(w.message) for w in caught)
    assert "Old Bagpipes" in message
    # Names what is hanging off it, so the operator can judge the loss.
    assert "clips" in message and "notes" in message and "devices" in message
    # And names the remedy, because reporting without one relocates the
    # problem into the operator's head.
    assert "prune-tracks" in message
    assert Q.get_track(conn, bagpipes) is not None


def test_an_orphan_is_moved_clear_rather_than_left_blocking_an_index(conn):
    """An orphan still holds an index a reconciled row may need. It steps
    aside — keeping its UUID and its children — so the renumber stays
    satisfiable; it is not deleted to make room."""
    song_id = _song_with_tracks(conn, "block", [(1, "Junk"), (2, "Drums")])
    junk = _ids_by_name(conn, song_id)["Junk"]
    with pytest.warns(UserWarning):
        replay_capture(conn, _snapshot([(1, "Drums")]), song_name="block")

    rows = dict((name, idx) for idx, name in _rows(conn, song_id))
    assert rows["Drums"] == 1
    assert rows["Junk"] > 1
    assert Q.get_track(conn, junk) is not None


def test_a_fresh_song_reports_no_orphans(conn, recwarn):
    """Every track of a first replay matches no existing row. That is the
    healthy path, and it must be silent."""
    M.create_song(conn, name="fresh")
    replay_capture(conn, _snapshot([(1, "Drums"), (2, "Bass")]), song_name="fresh")
    assert [str(w.message) for w in recwarn.list] == []


# ---------------------------------------------------------------------------
# R8 — the operator's prune
# ---------------------------------------------------------------------------


def test_describe_track_deletion_enumerates_the_whole_cascade(conn):
    _song_id, bagpipes = _orphan_song(conn, "enumerate")
    plan = describe_track_deletion(conn, track_id=bagpipes)
    assert plan is not None and plan.can_proceed
    assert plan.deletes["clips"] == 1
    assert plan.deletes["notes"] == 1
    assert plan.deletes["device_chains"] == 1
    assert plan.deletes["devices"] == 1
    assert "clips" in plan.summary()


def test_prune_removes_the_row_and_its_children(conn):
    song_id, bagpipes = _orphan_song(conn, "pruned")
    plan = prune_track(conn, track_id=bagpipes)
    assert plan.name == "Old Bagpipes"
    assert Q.get_track(conn, bagpipes) is None
    assert [name for _, name in _rows(conn, song_id)] == ["Drums"]


def test_prune_drops_the_projection_links_no_cascade_reaches(conn):
    """`ableton_links.db_id` carries no foreign key, so nothing cascades to it.
    A prune that left the link behind would point the next push at a row that
    stopped existing."""
    song_id, bagpipes = _orphan_song(conn, "linked")
    session_id = M.create_ableton_session(conn, song_id=song_id, name="draft")
    M.link_db_to_ableton(
        conn, session_id=session_id, db_kind="track", db_id=bagpipes,
        ableton_index=2,
    )
    plan = prune_track(conn, track_id=bagpipes)
    assert plan.links["track"] == 1
    assert Q.get_ableton_links_for_session(conn, session_id) == []


def test_a_second_replay_after_the_prune_is_clean_and_silent(conn, recwarn):
    """The end of the loop: prune the orphan the first replay reported, and the
    next replay of the same snapshot has nothing left to say."""
    song_id, bagpipes = _orphan_song(conn, "settled")
    with pytest.warns(UserWarning):
        replay_capture(conn, _snapshot([(1, "Drums")]), song_name="settled")
    prune_track(conn, track_id=bagpipes)

    recwarn.clear()
    replay_capture(conn, _snapshot([(1, "Drums")]), song_name="settled")
    assert [str(w.message) for w in recwarn.list] == []
    assert _rows(conn, song_id) == [(1, "Drums")]


# ---------------------------------------------------------------------------
# The prune CLI (R8's operator surface)
# ---------------------------------------------------------------------------


def _db_path(conn):
    return conn.execute("PRAGMA database_list").fetchone()["file"]


def test_cli_prunes_a_named_track_after_showing_what_goes(conn, capsys):
    song_id, bagpipes = _orphan_song(conn, "cli")
    db = _db_path(conn)
    conn.commit()

    code = prune_tracks_cli.main([
        "--db", db, "--song", "cli", "--track", "Old Bagpipes", "--yes",
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "Old Bagpipes" in out and "clips" in out
    assert Q.get_track(conn, bagpipes) is None


def test_cli_dry_run_removes_nothing(conn, capsys):
    _song_id, bagpipes = _orphan_song(conn, "dry")
    db = _db_path(conn)
    conn.commit()

    code = prune_tracks_cli.main([
        "--db", db, "--track", "Old Bagpipes", "--dry-run",
    ])
    assert code == 0
    assert "dry run" in capsys.readouterr().out
    assert Q.get_track(conn, bagpipes) is not None


def test_cli_refuses_without_confirmation(conn, capsys):
    _song_id, bagpipes = _orphan_song(conn, "noconfirm")
    db = _db_path(conn)
    conn.commit()

    code = prune_tracks_cli.main(
        ["--db", db, "--track", "Old Bagpipes"], reader=lambda _: "n",
    )
    assert code == 1
    assert "aborted" in capsys.readouterr().out
    assert Q.get_track(conn, bagpipes) is not None


def test_cli_takes_a_typed_confirmation(conn):
    _song_id, bagpipes = _orphan_song(conn, "confirm")
    db = _db_path(conn)
    conn.commit()

    code = prune_tracks_cli.main(
        ["--db", db, "--track", "Old Bagpipes"], reader=lambda _: "yes",
    )
    assert code == 0
    assert Q.get_track(conn, bagpipes) is None


def test_cli_refuses_to_guess_a_duplicated_name(conn, capsys):
    _song_with_tracks(conn, "dupcli", [(1, "Dup"), (2, "Dup")])
    db = _db_path(conn)
    conn.commit()

    code = prune_tracks_cli.main(["--db", db, "--track", "Dup", "--yes"])
    assert code == 2
    assert "2 tracks are named" in capsys.readouterr().err


def test_cli_needs_a_target(conn, capsys):
    _song_with_tracks(conn, "bare", [(1, "Drums")])
    db = _db_path(conn)
    conn.commit()
    assert prune_tracks_cli.main(["--db", db]) == 2
    assert "not the default for a forgotten argument" in capsys.readouterr().err


def test_cli_removes_every_orphan_against_a_snapshot(conn, tmp_path, capsys):
    song_id, bagpipes = _orphan_song(conn, "allorphans")
    M.create_track(conn, song_id=song_id, track_index=3, name="Junk", kind="midi")
    snapshot_path = tmp_path / "captured_session.json"
    snapshot_path.write_text(json.dumps(_snapshot([(1, "Drums")])), encoding="utf-8")
    db = _db_path(conn)
    conn.commit()

    code = prune_tracks_cli.main([
        "--db", db, "--all-orphans", "--snapshot", str(snapshot_path), "--yes",
    ])
    assert code == 0
    assert Q.get_track(conn, bagpipes) is None
    assert [name for _, name in _rows(conn, song_id)] == ["Drums"]


def test_cli_all_orphans_needs_a_snapshot(conn, capsys):
    _song_with_tracks(conn, "nosnap", [(1, "Drums")])
    db = _db_path(conn)
    conn.commit()
    assert prune_tracks_cli.main(["--db", db, "--all-orphans"]) == 2
    assert "needs --snapshot" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The pieces, directly
# ---------------------------------------------------------------------------


def _row(id_, index, name, kind="midi"):
    return {"id": id_, "track_index": index, "name": name, "kind": kind}


def test_planner_ignores_the_master_sentinel():
    """The master is a track row at the reserved index 0 and is never part of
    a snapshot's `tracks`; treating it as an orphan would report it forever."""
    plan = plan_track_reconciliation(
        [_row("m", 0, "Master", kind="master"), _row("d", 5, "Drums")],
        [{"index": 1, "name": "Drums"}],
    )
    assert plan.orphans == []
    assert plan.moves == {"d": 1}


def test_planner_leaves_an_uncontested_orphan_where_it_is():
    """Relocating an orphan is only ever about clearing a claimed index. One
    sitting somewhere nobody wants keeps its position."""
    plan = plan_track_reconciliation(
        [_row("d", 1, "Drums"), _row("j", 9, "Junk")],
        [{"index": 1, "name": "Drums"}],
    )
    assert plan.moves == {}
    assert [r["id"] for r in plan.orphans] == ["j"]


def test_reindex_refuses_two_rows_bound_for_one_index(conn):
    song_id = _song_with_tracks(conn, "clash", [(1, "A"), (2, "B")])
    ids = _ids_by_name(conn, song_id)
    with pytest.raises(ValueError, match="both move to index"):
        reindex_tracks(
            conn, song_id=song_id, moves={ids["A"]: 3, ids["B"]: 3},
        )
    assert sorted(_rows(conn, song_id)) == [(1, "A"), (2, "B")]


def test_reindex_refuses_a_target_a_stationary_row_holds(conn):
    """A caller whose reconciliation is wrong must not get a silent pass — the
    parked-index trick would happily land the mover on a row that never
    moved."""
    song_id = _song_with_tracks(conn, "held", [(1, "A"), (2, "B")])
    ids = _ids_by_name(conn, song_id)
    with pytest.raises(ValueError, match="is not moving out of"):
        reindex_tracks(conn, song_id=song_id, moves={ids["A"]: 2})
    assert sorted(_rows(conn, song_id)) == [(1, "A"), (2, "B")]


def test_reindex_is_a_no_op_where_a_row_already_sits_right(conn):
    song_id = _song_with_tracks(conn, "noop", [(1, "A")])
    ids = _ids_by_name(conn, song_id)
    assert reindex_tracks(conn, song_id=song_id, moves={ids["A"]: 1}) == {}


def test_reindex_rejects_a_row_from_another_song(conn):
    song_id = _song_with_tracks(conn, "mine", [(1, "A")])
    other = _song_with_tracks(conn, "theirs", [(1, "B")])
    stranger = _ids_by_name(conn, other)["B"]
    with pytest.raises(ValueError, match="not track rows"):
        reindex_tracks(conn, song_id=song_id, moves={stranger: 2})


def test_every_link_kind_that_can_hang_off_a_track_is_mapped():
    """The 'cannot fully enumerate' promise, made structural. `ableton_links`
    carries no foreign key, so nothing cascades to it — a link kind whose table
    is unmapped would leave links pointing at rows the prune deleted. Adding a
    kind without mapping it must break this, not ship silently."""
    from hallucinote.db.mutations.links import ABLETON_LINK_KINDS
    from hallucinote.db.mutations.tracks import (
        _LINK_KIND_BY_TABLE,
        _LINK_KINDS_NOT_UNDER_A_TRACK,
    )

    assert ABLETON_LINK_KINDS - _LINK_KINDS_NOT_UNDER_A_TRACK == set(
        _LINK_KIND_BY_TABLE.values()
    )


def test_an_unmapped_link_kind_makes_the_prune_refuse(conn, monkeypatch):
    """Not merely a naming convention — the plan itself blocks."""
    from hallucinote.db.mutations import tracks as tracks_mod

    _song_id, bagpipes = _orphan_song(conn, "unmapped")
    monkeypatch.setattr(
        tracks_mod, "_LINK_KIND_BY_TABLE",
        {k: v for k, v in tracks_mod._LINK_KIND_BY_TABLE.items() if v != "note"},
    )
    plan = describe_track_deletion(conn, track_id=bagpipes)
    assert not plan.can_proceed
    with pytest.raises(ValueError, match="refusing to prune"):
        prune_track(conn, track_id=bagpipes)
    assert Q.get_track(conn, bagpipes) is not None
