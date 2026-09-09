"""BAK-7D2V — the pull-durability guard on `replay_capture`.

`/ableton-pull` writes live edits into the regenerable DB only; the next
`build.py`'s `replay_capture(captured_session.json)` would silently re-assert
the stale snapshot over them (both write as actor='sync', so actor precedence
cannot arbitrate). The guard refuses — `StaleSnapshotError` — when the DB
holds events from a `requests.kind='pull'` request, of a kind replay
re-asserts, NEWER than the snapshot's `captured_at` stamp.

Refuse/warn matrix under test (design:
.prawduct/artifacts/plans/BAK-7D2V/archive/design.md):

  * stamped snapshot + newer pulled mix edits  -> REFUSE, nothing reverted
  * allow_stale_snapshot=True                  -> proceed + warn, revert happens
  * no pull ever                               -> silent pass (converger intact)
  * fresh capture after the pull               -> silent pass
  * legacy snapshot (no captured_at)           -> warn, proceed
  * pulled non-mix domains (replay can't
    revert them)                               -> silent pass
"""
from __future__ import annotations

import json
import warnings

import pytest

from hallucinote.capture import (
    StaleSnapshotError,
    count_request_replay_asserted_events,
    utc_now_eventlike,
    compile_snapshot,
    replay_capture,
)
from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import pull, pull_cli

OLD_STAMP = "2020-01-01T00:00:00.000Z"   # long before any event this test emits
FUTURE_STAMP = "2999-01-01T00:00:00.000Z"


def _snapshot(captured_at: str | None = OLD_STAMP) -> dict:
    snap = {
        "snapshot_version": 1,
        "song": {"tempo": 120.0, "signature": "4/4"},
        "returns": [],
        "tracks": [
            {"index": 1, "name": "Drums", "type": "midi",
             "volume": 0.5, "panning": 0.0},
        ],
    }
    if captured_at is not None:
        snap["captured_at"] = captured_at
    return snap


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "song.db"


@pytest.fixture
def conn(db_path):
    c = init_db(db_path)
    yield c
    c.close()


def _replay(conn, snap, **kw):
    return replay_capture(conn, snap, song_name="t", **kw)


def _pull_mix_tweak(conn, *, song_id, session_id, track_id, volume=0.9):
    """Simulate exactly what `pull_cli apply` does around apply_pull_results:
    a `requests.kind='pull'` request whose id threads into the emitted events."""
    request_id = M.create_request(
        conn, actor="sync", intent="test pull", kind="pull", song_id=song_id,
    )
    out = pull.apply_pull_results(
        conn,
        [{"key": f"track_info:{track_id}", "ok": True, "tool": "probe",
          "result": {"volume": volume, "panning": 0.0}}],
        song_id=song_id, session_id=session_id,
        actor="sync", request_id=request_id,
    )
    M.close_request(conn, request_id=request_id, outcome="ok", actor="sync")
    assert out.mutations == 1
    return request_id


def _built_song(conn, snap):
    """First replay (song doesn't exist yet -> guard is a no-op) + a session."""
    song_id = _replay(conn, snap)
    session_id = M.create_ableton_session(conn, song_id=song_id, name="live")
    track_id = Q.tracks_by_name(conn, song_id)["Drums"]
    M.link_db_to_ableton(
        conn, session_id=session_id, db_kind="track", db_id=track_id,
        ableton_index=1,
    )
    return song_id, session_id, track_id


# ---------------------------------------------------------------------------
# The audit scenario: pull_cli apply -> replay refuses, nothing reverted
# ---------------------------------------------------------------------------


def test_replay_refuses_after_pull_cli_apply_and_does_not_revert(
    conn, db_path, tmp_path, capsys,
):
    """THE audit scenario, through the real CLI surface: `pull_cli apply`
    bakes a live edit into the DB, then a `build.py`-style re-replay of the
    (older) snapshot must refuse instead of silently reverting it."""
    snap = _snapshot(captured_at=OLD_STAMP)
    song_id, session_id, track_id = _built_song(conn, snap)

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "song_id": song_id, "session_id": session_id, "domain": "mix-state",
    }))
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps([
        {"key": f"track_info:{track_id}", "ok": True, "tool": "probe",
         "result": {"volume": 0.9, "panning": 0.0}},
    ]))
    rc = pull_cli.main([
        "apply", session_id, "--db", str(db_path),
        "--plan", str(plan_path), "--results", str(results_path),
    ])
    assert rc == 0
    capsys.readouterr()  # drop the ApplyResult JSON
    assert Q.get_track(conn, track_id)["volume"] == pytest.approx(0.9)

    with pytest.raises(StaleSnapshotError) as exc:
        _replay(conn, snap)

    # The refusal is actionable: names the newer rows + both escape hatches.
    msg = str(exc.value)
    assert "track_mixer_set" in msg
    assert "allow_stale_snapshot=True" in msg
    assert "--force-replay" in msg
    assert "/song-snapshot" in msg
    # And nothing was reverted — the pulled by-ear value survives.
    assert Q.get_track(conn, track_id)["volume"] == pytest.approx(0.9)


def test_force_replay_override_reverts_with_warning(conn):
    snap = _snapshot(captured_at=OLD_STAMP)
    song_id, session_id, track_id = _built_song(conn, snap)
    _pull_mix_tweak(conn, song_id=song_id, session_id=session_id,
                    track_id=track_id)

    with pytest.warns(UserWarning, match="REVERTING 1 pulled live edit"):
        _replay(conn, snap, allow_stale_snapshot=True)

    assert Q.get_track(conn, track_id)["volume"] == pytest.approx(0.5)


def test_forced_replay_does_not_disarm_the_guard(conn):
    """Forcing is per-run consent; the guard keeps firing until a re-capture
    refreshes `captured_at` (documented in the design + refusal message)."""
    snap = _snapshot(captured_at=OLD_STAMP)
    song_id, session_id, track_id = _built_song(conn, snap)
    _pull_mix_tweak(conn, song_id=song_id, session_id=session_id,
                    track_id=track_id)
    with pytest.warns(UserWarning, match="REVERTING"):
        _replay(conn, snap, allow_stale_snapshot=True)
    with pytest.raises(StaleSnapshotError):
        _replay(conn, snap)


# ---------------------------------------------------------------------------
# False-positive contract: ordinary dogfood cycles never trip the guard
# ---------------------------------------------------------------------------


def test_no_pull_replay_rerun_is_silent(conn):
    """The converger contract: build.py re-runs with no pull in history must
    not refuse and must not warn."""
    snap = _snapshot(captured_at=OLD_STAMP)
    first = _replay(conn, snap)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        second = _replay(conn, snap)
    assert first == second


def test_fresh_capture_after_pull_disarms_the_guard(conn):
    """pull -> re-capture (new snapshot with newer captured_at) -> build:
    the bake itself disarms the guard."""
    snap = _snapshot(captured_at=OLD_STAMP)
    song_id, session_id, track_id = _built_song(conn, snap)
    _pull_mix_tweak(conn, song_id=song_id, session_id=session_id,
                    track_id=track_id)

    fresh = _snapshot(captured_at=FUTURE_STAMP)
    fresh["tracks"][0]["volume"] = 0.9  # a real re-capture carries the edit
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _replay(conn, fresh)
    assert Q.get_track(conn, track_id)["volume"] == pytest.approx(0.9)


def test_pulled_nested_chain_deletion_trips_the_guard(conn):
    """Critic BLOCKING repro: removing a chain inside a Rack in Live and
    pulling devices calls M.delete_device_chain (sync/pull/devices.py), which
    emits ONLY device_chain_deleted — the cascade removes the chain's nested
    devices with NO per-device events — and _replay_rack_chains recreates
    every snapshot-declared chain. The chain-delete event is therefore the
    sole signal and MUST arm the guard."""
    snap = _snapshot(captured_at=OLD_STAMP)
    snap["tracks"][0]["devices"] = [{
        "index": 1, "name": "Kit", "class": "Drum Rack",
        "chains": [{"chain_index": 1, "name": "Kick", "devices": []}],
    }]
    song_id, session_id, track_id = _built_song(conn, snap)

    top_chain = Q.get_device_chains_for_track(conn, track_id)[0]
    rack = Q.get_devices_for_chain(conn, top_chain["id"])[0]
    nested = Q.get_device_chains_for_rack_device(conn, rack["id"])
    assert len(nested) == 1  # the snapshot-declared "Kick" chain

    # The pull path: user deleted the chain in Live; pull reconciles the DB.
    request_id = M.create_request(
        conn, actor="sync", intent="pull nested-rack-chains", kind="pull",
        song_id=song_id,
    )
    M.delete_device_chain(
        conn, chain_id=nested[0]["id"], actor="sync", request_id=request_id,
    )
    M.close_request(conn, request_id=request_id, outcome="ok", actor="sync")
    assert Q.get_device_chains_for_rack_device(conn, rack["id"]) == []

    with pytest.raises(StaleSnapshotError, match="device_chain_deleted"):
        _replay(conn, snap)
    # Not silently recreated: the pulled deletion survives the refusal.
    assert Q.get_device_chains_for_rack_device(conn, rack["id"]) == []


def test_pulled_non_replay_asserted_domain_does_not_trip(conn):
    """A pull of state replay cannot revert (e.g. score globals staged for
    build.py) must not arm the guard — /ableton-pull's sanctioned staging use."""
    snap = _snapshot(captured_at=OLD_STAMP)
    song_id, _session_id, _track_id = _built_song(conn, snap)
    request_id = M.create_request(
        conn, actor="sync", intent="test pull", kind="pull", song_id=song_id,
    )
    M.add_tempo_point(
        conn, song_id=song_id, start_bar=1.0, tempo_bpm=133.0,
        actor="sync", request_id=request_id,
    )
    M.close_request(conn, request_id=request_id, outcome="ok", actor="sync")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _replay(conn, snap)


def test_pull_on_other_song_does_not_trip(conn):
    """The guard is song-scoped."""
    snap_other = _snapshot(captured_at=OLD_STAMP)
    other_id = replay_capture(conn, snap_other, song_name="other")
    other_session = M.create_ableton_session(conn, song_id=other_id, name="o")
    other_track = Q.tracks_by_name(conn, other_id)["Drums"]
    M.link_db_to_ableton(
        conn, session_id=other_session, db_kind="track", db_id=other_track,
        ableton_index=1,
    )
    _pull_mix_tweak(conn, song_id=other_id, session_id=other_session,
                    track_id=other_track)

    snap = _snapshot(captured_at=OLD_STAMP)
    _replay(conn, snap)  # create song "t"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _replay(conn, snap)


def test_non_pull_sync_writes_do_not_trip(conn):
    """actor='sync' alone is NOT the signal (replay itself writes as sync);
    only pull-request provenance arms the guard."""
    snap = _snapshot(captured_at=OLD_STAMP)
    song_id, _session_id, track_id = _built_song(conn, snap)
    # A sync write outside any pull request (e.g. replay's own upserts).
    M.set_track_mixer(conn, track_id=track_id, actor="sync", volume=0.7)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _replay(conn, snap)


# ---------------------------------------------------------------------------
# Legacy (unstamped) snapshots: warn, proceed
# ---------------------------------------------------------------------------


def test_legacy_snapshot_with_pulled_edits_warns_and_proceeds(conn):
    snap = _snapshot(captured_at=None)
    song_id, session_id, track_id = _built_song(conn, snap)
    _pull_mix_tweak(conn, song_id=song_id, session_id=session_id,
                    track_id=track_id)

    with pytest.warns(UserWarning, match="no `captured_at`"):
        _replay(conn, snap)
    # Legacy proceeds (and therefore reverts) — the warning is the defense.
    assert Q.get_track(conn, track_id)["volume"] == pytest.approx(0.5)


def test_legacy_snapshot_without_pulls_is_silent(conn):
    snap = _snapshot(captured_at=None)
    _replay(conn, snap)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _replay(conn, snap)


def test_unparseable_captured_at_is_treated_as_legacy(conn):
    snap = _snapshot(captured_at="yesterday-ish")
    song_id, session_id, track_id = _built_song(conn, snap)
    _pull_mix_tweak(conn, song_id=song_id, session_id=session_id,
                    track_id=track_id)
    with pytest.warns(UserWarning, match="no `captured_at`"):
        _replay(conn, snap)


def test_timezone_offset_captured_at_takes_the_legacy_path(conn):
    """Critic WARNING repro: an ISO stamp with a timezone OFFSET
    ("...T14:34:56+02:00") passes a prefix-shape check but compares
    lexicographically up to +14h ahead of UTC events.ts — which would
    silently defeat the guard (events look 'older' than the stamp). A
    non-exact shape must take the conservative legacy/warn path, never the
    stamped comparison."""
    # An offset stamp lexicographically AHEAD of any event this test emits:
    # if the guard (wrongly) compared it, no event would be "newer" and the
    # replay would pass silently — the exact silent defeat under test.
    snap = _snapshot(captured_at="2999-01-01T00:00:00+02:00")
    song_id, session_id, track_id = _built_song(conn, snap)
    _pull_mix_tweak(conn, song_id=song_id, session_id=session_id,
                    track_id=track_id)
    with pytest.warns(UserWarning, match="no `captured_at`"):
        _replay(conn, snap)


# ---------------------------------------------------------------------------
# The capture side: compile_snapshot stamps captured_at
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The pull-side durability notice fires exactly when the guard would — same
# kind set, same per-request provenance.
# ---------------------------------------------------------------------------


def test_count_helper_counts_only_replay_asserted_kinds(conn):
    """The notice's discriminator: a mix tweak (track_mixer_set) counts; a
    build.py-owned domain staged under a pull request (tempo point) does not —
    the same asymmetry the guard uses."""
    snap = _snapshot()
    song_id, session_id, track_id = _built_song(conn, snap)

    rid_mix = _pull_mix_tweak(conn, song_id=song_id, session_id=session_id,
                              track_id=track_id)
    assert count_request_replay_asserted_events(conn, request_id=rid_mix) == 1

    rid_tempo = M.create_request(
        conn, actor="sync", intent="pull tempo", kind="pull", song_id=song_id,
    )
    M.add_tempo_point(
        conn, song_id=song_id, start_bar=1.0, tempo_bpm=133.0,
        actor="sync", request_id=rid_tempo,
    )
    M.close_request(conn, request_id=rid_tempo, outcome="ok", actor="sync")
    assert count_request_replay_asserted_events(conn, request_id=rid_tempo) == 0


def _run_apply(db_path, tmp_path, *, song_id, session_id, track_id, volume):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({
        "song_id": song_id, "session_id": session_id, "domain": "mix-state",
    }))
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps([
        {"key": f"track_info:{track_id}", "ok": True, "tool": "probe",
         "result": {"volume": volume, "panning": 0.0}},
    ]))
    return pull_cli.main([
        "apply", session_id, "--db", str(db_path),
        "--plan", str(plan_path), "--results", str(results_path),
    ])


def test_pull_cli_apply_prints_durability_notice_on_mix_change(
    conn, db_path, tmp_path, capsys,
):
    snap = _snapshot()
    song_id, session_id, track_id = _built_song(conn, snap)
    rc = _run_apply(db_path, tmp_path, song_id=song_id, session_id=session_id,
                    track_id=track_id, volume=0.9)
    assert rc == 0
    err = capsys.readouterr().err
    assert "mix-layer change" in err
    assert "/song-snapshot" in err
    assert "REFUSE" in err


def test_pull_cli_apply_silent_when_nothing_changed(
    conn, db_path, tmp_path, capsys,
):
    """A no-op apply (probe value == DB value) stages no events, so the notice
    must not fire — otherwise it cries wolf on every in-sync pull."""
    snap = _snapshot()
    song_id, session_id, track_id = _built_song(conn, snap)
    rc = _run_apply(db_path, tmp_path, song_id=song_id, session_id=session_id,
                    track_id=track_id, volume=0.5)  # 0.5 == the built value
    assert rc == 0
    err = capsys.readouterr().err
    assert "mix-layer change" not in err


def test_pull_cli_execute_notice_fires_on_real_run_not_dry_run(
    conn, db_path, tmp_path, capsys, monkeypatch,
):
    """The `execute` path: a real run stages the mix change and prints the
    notice; `--dry-run` rolls the request + events back, so nothing is staged
    and the notice must stay silent (the `if not args.dry_run` guard)."""
    snap = _snapshot()
    song_id, session_id, track_id = _built_song(conn, snap)
    canned = [{"key": f"track_info:{track_id}", "ok": True, "tool": "probe",
               "result": {"volume": 0.9, "panning": 0.0}}]
    monkeypatch.setattr(pull_cli, "_execute_plan_via_mcp", lambda plan, **kw: canned)

    rc = pull_cli.main([
        "execute", "mix-state", session_id, "--db", str(db_path), "--dry-run",
    ])
    assert rc == 0
    assert "mix-layer change" not in capsys.readouterr().err
    assert Q.get_track(conn, track_id)["volume"] == pytest.approx(0.5)  # rolled back

    rc = pull_cli.main(["execute", "mix-state", session_id, "--db", str(db_path)])
    assert rc == 0
    assert "mix-layer change" in capsys.readouterr().err
    assert Q.get_track(conn, track_id)["volume"] == pytest.approx(0.9)


def test_compile_snapshot_stamps_captured_at_in_events_ts_shape(conn):
    snap = compile_snapshot(
        session_info={"tempo": 120.0, "signature": "4/4",
                      "master": {"volume": 0.85, "panning": 0.0}},
        returns=[],
        tracks=[{"index": 1, "name": "x", "type": "midi", "volume": 0.5}],
    )
    stamp = snap["captured_at"]
    # Exact events.ts shape: lexicographic compare == chronological compare.
    import re
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", stamp)
    # And it is comparable with what the guard generates.
    assert stamp <= utc_now_eventlike()
