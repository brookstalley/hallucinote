"""Pull links the audio clips it ingests, and the next push conforms them.

A clip the user dragged into Live and pull staged into the DB used to reach
the push planner with no `ableton_links` row, so every push deleted it and
rebuilt it from the file — losing the Live-side state the DB does not model.
Pull holds the strongest evidence any writer will ever have about where that
clip lives (it read the slot out of Live), so it records the binding through
the same `link_db_to_ableton` mutator push records its own with.

The tests below pin both halves of that seam: the link pull writes, and what
the push planner does with it. An EXISTING row's link stays push's to
reconcile, and a dry-run must stage neither the row nor the link.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.db.connection import transaction
from hallucinote.sync import pull
from hallucinote.sync.push.clips import plan_push_clip


TRACK_AT = 5


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "pull.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


@pytest.fixture
def audio_track(conn, song, session):
    tid = M.create_track(
        conn, song_id=song, track_index=1, name="Stems", kind="audio",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid,
        ableton_index=TRACK_AT,
    )
    return tid


@pytest.fixture
def sample(tmp_path):
    """A file that exists on disk under the song directory.

    The push planner refuses to plan anything for a sample it cannot find, and
    nothing here decodes the file, so its bytes are irrelevant — only that
    `assets/line.wav` resolves to something `is_file()`.
    """
    path = tmp_path / "assets" / "line.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not really audio")
    return path


def _audio_entry(
    slot: int,
    sample: Path,
    *,
    name: str = "line",
    length: float = 8.0,
    gain: float = 0.5,
    pitch_coarse: int = 0,
    pitch_fine: float = 0.0,
    warping: bool = True,
    warp_mode: int = 0,
    start_marker: float = 0.0,
    end_marker: float = 8.0,
) -> dict[str, Any]:
    """One audio clip as `ableton_clip(action='list', location='session')`
    reports it — the discriminator plus the eight conform keys."""
    return {
        "clip_index": slot,
        "empty": False,
        "name": name,
        "length": length,
        "is_audio": True,
        "file_path": str(sample),
        "gain": gain,
        "pitch_coarse": pitch_coarse,
        "pitch_fine": pitch_fine,
        "warping": warping,
        "warp_mode": warp_mode,
        "start_marker": start_marker,
        "end_marker": end_marker,
    }


def _session_result(track_id: str, *entries: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": f"track_session_clips:{track_id}",
        "ok": True,
        "tool": "probe",
        "result": {
            "track_index": TRACK_AT,
            "location": "session",
            "clips": list(entries),
        },
    }


def _ingest(conn, *, song, session, track_id, entries, reason=None):
    return pull.apply_pull_results(
        conn,
        [_session_result(track_id, *entries)],
        song_id=song, session_id=session, reason=reason,
    )


def _only_clip(conn, track_id):
    rows = Q.get_clips_for_track(conn, track_id)
    assert len(rows) == 1
    return rows[0]


# ---------------------------------------------------------------------------
# Pull writes the link
# ---------------------------------------------------------------------------


def test_ingest_links_the_new_row_to_the_slot_live_reported(
    conn, song, session, audio_track, sample
):
    out = _ingest(
        conn, song=song, session=session, track_id=audio_track,
        entries=[_audio_entry(3, sample)],
    )

    assert out.mutations == 1
    row = _only_clip(conn, audio_track)
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="clip", db_id=row["id"],
    ) == 3


def test_ingest_reports_the_link_it_wrote(
    conn, song, session, audio_track, sample
):
    """The link is a change to the user's song, so the pull's own account of
    what it did has to name it — a write that surfaces nowhere is one the
    operator cannot review."""
    out = _ingest(
        conn, song=song, session=session, track_id=audio_track,
        entries=[_audio_entry(3, sample)],
    )

    ingest_lines = [d for d in out.details if "ingested from Live" in d]
    assert len(ingest_lines) == 1
    assert "linked to clip_index 3" in ingest_lines[0]


def test_ingest_counts_the_link_with_the_row_not_as_a_second_change(
    conn, song, session, audio_track, sample
):
    """Two ingested clips are two mutations. The link rides with the row it
    binds — it is not a diff the user could have applied on its own."""
    out = _ingest(
        conn, song=song, session=session, track_id=audio_track,
        entries=[
            _audio_entry(1, sample, name="one"),
            _audio_entry(2, sample, name="two"),
        ],
    )

    assert out.mutations == 2
    assert out.no_ops == 0


def test_ingest_link_goes_through_the_mutator_and_emits_its_event(
    conn, song, session, audio_track, sample
):
    """Mutator discipline: the binding is written through
    `link_db_to_ableton`, carrying the pull's attribution, rather than by a
    raw INSERT that leaves no event behind."""
    _ingest(
        conn, song=song, session=session, track_id=audio_track,
        entries=[_audio_entry(3, sample)], reason="test",
    )

    row = _only_clip(conn, audio_track)
    linked = [
        e for e in Q.get_events_for_song(conn, song)
        if e["kind"] == "ableton_link_set" and e["clip_id"] == row["id"]
    ]
    assert len(linked) == 1
    assert linked[0]["actor"] == "sync"
    assert linked[0]["reason"] == "test"


def test_a_refused_ingest_writes_no_link(
    conn, song, session, audio_track, sample
):
    """An audio entry with no `file_path` cannot be ingested. No row, so
    nothing to bind — a link pointing at a clip the DB does not have would be
    a binding to nothing."""
    entry = _audio_entry(3, sample)
    del entry["file_path"]

    out = _ingest(
        conn, song=song, session=session, track_id=audio_track,
        entries=[entry],
    )

    assert out.mutations == 0
    assert Q.get_clips_for_track(conn, audio_track) == []
    assert [
        link for link in Q.get_ableton_links_for_session(conn, session)
        if link["db_kind"] == "clip"
    ] == []


# ---------------------------------------------------------------------------
# An existing row's link stays push's to reconcile
# ---------------------------------------------------------------------------


def test_conforming_an_existing_row_leaves_its_link_alone(
    conn, song, session, audio_track, sample
):
    """Pull observed the clip's contents, not the history of the binding.
    A link that already points somewhere else is push's `probe_and_link` pass
    to reconcile, so a conform must not quietly re-point it."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file="assets/line.wav", name="line", gain=0.8,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=cid, ableton_index=7,
    )

    out = _ingest(
        conn, song=song, session=session, track_id=audio_track,
        entries=[_audio_entry(1, sample, gain=0.35)],
    )

    assert out.mutations == 1
    assert Q.get_clip(conn, cid)["audio_gain"] == 0.35
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="clip", db_id=cid,
    ) == 7


def test_conforming_an_unlinked_existing_row_does_not_link_it(
    conn, song, session, audio_track, sample
):
    """The unlinked existing row is the case push legitimately declined to
    create (its sample was not on disk). Pull did not put that clip in Live,
    so it has no evidence the slot holds this row's clip."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file="assets/line.wav", name="line", gain=0.8,
    )

    _ingest(
        conn, song=song, session=session, track_id=audio_track,
        entries=[_audio_entry(1, sample, gain=0.35)],
    )

    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="clip", db_id=cid,
    ) is None


# ---------------------------------------------------------------------------
# What the next push does with the link
# ---------------------------------------------------------------------------


def _probe(sample: Path, slot: int, **overrides: Any) -> dict[int, list[dict]]:
    """The live session-clip inventory `plan_push_clip` reads, showing the
    ingested clip still sitting in its slot playing the same file."""
    entry = _audio_entry(slot, sample)
    entry.update(overrides)
    return {TRACK_AT: [entry]}


def test_the_next_push_conforms_the_ingested_clip_in_place(
    conn, song, session, audio_track, sample
):
    """The point of the link: push finds the clip at `clip_at` and writes the
    one drifted property, instead of deleting the slot and rebuilding it."""
    _ingest(
        conn, song=song, session=session, track_id=audio_track,
        entries=[_audio_entry(3, sample, gain=0.62)],
    )
    row = _only_clip(conn, audio_track)

    plan = plan_push_clip(
        conn, clip_id=row["id"], session_id=session,
        # Live's gain has drifted since the ingest; everything else matches.
        live_session_clips_by_track=_probe(sample, 3, gain=0.2),
    )

    actions = [c.args.get("action") for c in plan.calls]
    assert actions == ["set_property"]
    assert plan.calls[0].args["property"] == "gain"
    assert plan.calls[0].args["clip_index"] == 3
    assert "create" not in actions
    assert "delete" not in actions
    assert not any(c.args.get("replace") for c in plan.calls)
    assert plan.blocked_reasons == []


def test_an_unchanged_ingested_clip_plans_nothing_on_the_next_push(
    conn, song, session, audio_track, sample
):
    """Live still holds exactly what pull read out of it, so a re-push has
    nothing to say — the idempotence the link makes reachable."""
    _ingest(
        conn, song=song, session=session, track_id=audio_track,
        entries=[_audio_entry(3, sample, gain=0.62)],
    )
    row = _only_clip(conn, audio_track)

    plan = plan_push_clip(
        conn, clip_id=row["id"], session_id=session,
        live_session_clips_by_track=_probe(sample, 3, gain=0.62),
    )

    assert plan.calls == []
    assert plan.blocked_reasons == []


def test_without_the_link_the_next_push_would_rebuild_the_clip(
    conn, song, session, audio_track, sample
):
    """The behaviour the link exists to prevent, pinned so the seam stays
    visible: the same row, same probe, link removed, is recreated into an
    occupied slot."""
    _ingest(
        conn, song=song, session=session, track_id=audio_track,
        entries=[_audio_entry(3, sample, gain=0.62)],
    )
    row = _only_clip(conn, audio_track)
    M.unlink_db_from_ableton(
        conn, session_id=session, db_kind="clip", db_id=row["id"],
    )

    plan = plan_push_clip(
        conn, clip_id=row["id"], session_id=session,
        live_session_clips_by_track=_probe(sample, 3, gain=0.62),
    )

    creates = [c for c in plan.calls if c.args.get("action") == "create"]
    assert len(creates) == 1
    assert creates[0].args["replace"] is True


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


class _Rollback(Exception):
    """The dry-run sentinel `pull_cli execute --dry-run` raises to roll its
    outer transaction back."""


def test_dry_run_stages_neither_the_row_nor_its_link(
    conn, song, session, audio_track, sample
):
    """`pull_cli execute --dry-run` wraps the apply in a transaction it always
    rolls back. The link must join that transaction rather than commit on its
    own — a preview that leaves a binding behind has written to the song."""
    try:
        with transaction(conn):
            out = _ingest(
                conn, song=song, session=session, track_id=audio_track,
                entries=[_audio_entry(3, sample)],
            )
            # The diff is still computed and reported; only the write is undone.
            assert out.mutations == 1
            raise _Rollback
    except _Rollback:
        pass

    assert Q.get_clips_for_track(conn, audio_track) == []
    clip_links = [
        link for link in Q.get_ableton_links_for_session(conn, session)
        if link["db_kind"] == "clip"
    ]
    assert clip_links == []
