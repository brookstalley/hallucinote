"""Tests for ``push_cli execute`` (W10-E2) — the agent-bypassing dispatcher.

Strategy: build a tiny song, inject a fake ``send_fn`` that mimics
``hallucinote_mcp.client.send``'s contract (returns a Response-shaped
object). Tests exercise the dispatch loop end-to-end without touching MCP
or Live. The fake's behavior per call is parametric so we can simulate
success, per-call failure, and connection-class exceptions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push_execute


_LINK_FIELDS: dict[str, str] = {
    "track": "track_index",
    "return": "return_index",
    "clip": "clip_index",
    "device": "device_index",
    "arrangement_clip": "arrangement_clip_index",
    "envelope": "envelope_index",
}


@dataclass
class FakeResponse:
    """Shape-compatible with hallucinote_mcp.wire.Response for execute_push's
    duck-typed access (ok / result / error / hint)."""
    ok: bool
    result: dict | None = None
    error: str | None = None
    hint: str | None = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "exec.db"


@pytest.fixture
def conn(db_path):
    c = init_db(db_path)
    yield c
    c.close()


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    return d


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


@pytest.fixture
def tiny_song(conn, song):
    """1 track + 1 clip with 2 notes — exercises tracks + clips phases."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    cid = M.create_clip(
        conn, track_id=tid, slot=1, length_beats=4.0, name="loop",
    )
    M.insert_notes(conn, clip_id=cid, notes=[
        {"pitch": 60, "velocity": 100, "start_beats": 0.0, "duration_beats": 0.5},
        {"pitch": 62, "velocity": 110, "start_beats": 1.0, "duration_beats": 0.5},
    ])
    return {"track_id": tid, "clip_id": cid, "song_id": song}


def _make_send_fn(*, fail_keys: set[str] = frozenset(), raise_on_key: str | None = None):
    """Build a fake send_fn that returns synthetic ok results with monotonic
    link indexes per kind, unless the call's key is in ``fail_keys`` (returns
    ok=False) or matches ``raise_on_key`` (raises — simulates connection loss).

    The key is reconstructed from the Request shape — we look at the canonical
    plan's ``call.key`` which the CLI passes through but doesn't appear on
    the wire. So this fake substitutes: it observes the (tool, action, params)
    tuple and decides ok/fail based on a closure over the *expected* plan
    calls, which the test builds by re-running plan_push_song.

    To keep the fake simple, this version dispatches on (tool, action) plus a
    counter per link kind for unique indexes. Tests that want to fail a
    specific call inject the failure by tool+action match.
    """
    counters: dict[str, int] = {}
    call_log: list[dict] = []

    def _kind_for(tool: str, action: str) -> str | None:
        # Map (tool, action) to the link kind used by apply_push_results.
        # Source of truth: push.apply_push_results' _LINK_KINDS table.
        if tool == "ableton_track" and action == "create":
            return "track"
        if tool == "ableton_return" and action == "create":
            return "return"
        if tool == "ableton_clip" and action == "create":
            return "clip"
        if tool == "ableton_device" and action == "load":
            return "device"
        if tool == "ableton_arrangement" and action == "duplicate_to_arrangement":
            return "arrangement_clip"
        if tool == "ableton_automation" and action == "write_envelope":
            return "envelope"
        return None

    def send(req):
        call_log.append({
            "tool": req.tool, "action": req.action,
            "params_keys": sorted(req.params.keys()),
        })

        # The fake matches against the *request* shape. Tests that want to
        # fail or drop a call pass a predicate via closure modifications,
        # but the simplest entry point is (tool, action) match strings.
        composite = f"{req.tool}:{req.action}"
        if raise_on_key and composite == raise_on_key:
            raise ConnectionRefusedError("simulated Live unreachable")
        if composite in fail_keys:
            return FakeResponse(ok=False, error=f"simulated failure for {composite}")

        kind = _kind_for(req.tool, req.action)
        if kind is None:
            # ack-only path (cue points, set_tempo_map, replace_notes, etc.)
            return FakeResponse(ok=True, result={})
        counters[kind] = counters.get(kind, 0) + 1
        return FakeResponse(ok=True, result={_LINK_FIELDS[kind]: counters[kind]})

    send.call_log = call_log  # type: ignore[attr-defined]
    return send


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_execute_happy_path_writes_state_no_errors_file(
    conn, song, session, tiny_song, state_dir,
):
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(),
    )
    assert result.outcome == "ok"
    assert result.exit_code == push_execute.EXIT_OK
    assert result.phase_halted is None
    assert result.errors_file is None
    assert not (state_dir / ".last-push-errors.json").exists()

    state = json.loads((state_dir / ".last-push-state.json").read_text())
    assert state["outcome"] == "ok"
    assert state["phase_halted"] is None
    assert state["errors_file"] is None
    # The ten phases are present, in order.
    names = [p["name"] for p in state["phases"]]
    assert names == [
        "tempo_map", "time_signature_map", "tracks", "returns",
        "clips", "mix", "devices", "envelopes", "arrangement", "cues",
    ]
    # Per fixture: tracks + clips run. Others are skipped (idempotent — no DB
    # content) or ok-with-zero-calls if the planner still emits acks.
    by_name = {p["name"]: p for p in state["phases"]}
    assert by_name["tracks"]["status"] in {"ok"}
    assert by_name["clips"]["status"] in {"ok"}


# ---------- W23-C: request lifecycle wrap ----------


def test_execute_push_opens_and_closes_request_with_outcome_ok(
    conn, song, session, tiny_song, state_dir,
):
    """One push → one requests row, kind='push', outcome='ok'. Provenance
    layer can then list it via Q.list_requests_for_song(..., kind='push')."""
    from hallucinote.db import queries as Q
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(),
    )
    requests = Q.list_requests_for_song(conn, song, kind="push")
    assert len(requests) == 1
    assert requests[0]["outcome"] == "ok"
    assert requests[0]["kind"] == "push"


def test_execute_push_threads_request_id_into_link_events(
    conn, song, session, tiny_song, state_dir,
):
    """Every link-binding event apply_push_results emits gets the request_id
    threaded. Provenance can drill in via Q.get_events_for_request(rid)."""
    from hallucinote.db import queries as Q
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(),
    )
    rid = Q.get_latest_request_for_song(conn, song, kind="push")["id"]
    events = Q.get_events_for_request(conn, rid)
    # At minimum: request_created + request_closed + any links the apply
    # layer wrote. The fixture has at least one ableton_link_set per push.
    kinds = {e["kind"] for e in events}
    assert "request_created" in kinds
    assert "request_closed" in kinds
    assert "ableton_link_set" in kinds


def test_execute_push_request_outcome_partial_when_phase_halts(
    conn, song, session, tiny_song, state_dir,
):
    """A phase failure flips the push's outcome to 'partial'; the request
    closes with outcome='partial' (not 'ok'), so a provenance-side audit
    sees "the last push half-landed" rather than a false success."""
    from hallucinote.db import queries as Q
    bad_send = _make_send_fn(fail_keys={"ableton_clip:create"})
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=bad_send,
    )
    assert result.outcome == "partial"
    rid = Q.get_latest_request_for_song(conn, song, kind="push")["id"]
    req = Q.get_request(conn, rid)
    assert req["outcome"] == "partial"


def test_execute_writes_link_to_db_between_phases(
    conn, song, session, tiny_song, state_dir, db_path,
):
    """Tracks phase runs first; its link must land in ableton_links BEFORE
    plan_push_clips runs, or clips planning raises on unlinked deps. This
    test catches a regression where execute_push forgets to apply per phase."""
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(),
    )
    assert result.outcome == "ok"
    # Re-open with a fresh connection so the apply transactions are visible.
    fresh = init_db(db_path)
    try:
        link = Q.get_ableton_link(
            fresh, session_id=session, db_kind="track", db_id=tiny_song["track_id"],
        )
        assert link == 1
        clip_link = Q.get_ableton_link(
            fresh, session_id=session, db_kind="clip", db_id=tiny_song["clip_id"],
        )
        assert clip_link == 1
    finally:
        fresh.close()


def test_execute_track_link_visible_to_clip_phase_mid_run(
    conn, song, session, tiny_song, state_dir,
):
    """Mid-execute probe: when the clip-create call arrives at the wire, the
    track link must ALREADY be visible in the DB — otherwise plan_push_clips
    would have raised on the unlinked track. Catches a hypothetical regression
    where execute reads ableton_links once at start and never refreshes
    (e.g. a refactor that pre-builds all ten plans before dispatching)."""
    observed: list[bool] = []
    base_send = _make_send_fn()

    def send_with_mid_probe(req):
        if req.tool == "ableton_clip" and req.action == "create":
            # At this point in the dispatch loop, the tracks phase has
            # already applied. The link must be readable from the shared
            # conn the planner used.
            link = Q.get_ableton_link(
                conn, session_id=session, db_kind="track",
                db_id=tiny_song["track_id"],
            )
            observed.append(link is not None)
        return base_send(req)

    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_with_mid_probe,
    )
    assert result.outcome == "ok"
    assert observed == [True], (
        "track link must be visible to the conn at the moment the clip "
        "create call is dispatched"
    )


# ---------------------------------------------------------------------------
# Per-call error accumulation + halt-at-phase-boundary
# ---------------------------------------------------------------------------


def test_execute_halts_at_phase_boundary_after_clip_failure(
    conn, song, session, tiny_song, state_dir,
):
    """A failing ableton_clip(create) within the clips phase: the phase
    finishes (only one call here anyway), then halt — downstream phases
    are pending."""
    send_fn = _make_send_fn(fail_keys={"ableton_clip:create"})
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    assert result.outcome == "partial"
    assert result.exit_code == push_execute.EXIT_PARTIAL
    assert result.phase_halted == "clips"

    state = json.loads((state_dir / ".last-push-state.json").read_text())
    by_name = {p["name"]: p for p in state["phases"]}
    assert by_name["clips"]["status"] == "halted"
    assert by_name["clips"]["calls_failed"] == 1
    # Mix / devices / etc. all marked pending.
    for downstream in ("mix", "devices", "envelopes", "arrangement", "cues"):
        assert by_name[downstream]["status"] == "pending", downstream
    # tracks ran before the failure.
    assert by_name["tracks"]["status"] == "ok"

    # Errors file written.
    errors_file = state_dir / ".last-push-errors.json"
    assert errors_file.exists()
    errors_payload = json.loads(errors_file.read_text())
    assert errors_payload["phase"] == "clips"
    assert len(errors_payload["errors"]) == 1
    assert errors_payload["errors"][0]["tool"] == "ableton_clip"
    assert errors_payload["errors"][0]["action"] == "create"
    assert "grouped_by_error" in errors_payload


def test_execute_args_summary_strips_large_notes_array(
    conn, song, session, tiny_song, state_dir,
):
    """The point of execute_push is keeping notes payloads out of the agent's
    context. The errors file is agent-readable, so args_summary MUST strip
    large lists. Pin notes_count substitution."""
    send_fn = _make_send_fn(fail_keys={"ableton_clip:create"})
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    errors_payload = json.loads((state_dir / ".last-push-errors.json").read_text())
    err = errors_payload["errors"][0]
    assert "notes" not in err["args_summary"]
    assert err["args_summary"]["notes_count"] == 2


def test_execute_groups_errors_by_message_substring(
    conn, song, session, state_dir,
):
    """Two clips both failing with the same error message: grouped_by_error
    surfaces one pattern with count=2."""
    # Two clips on the same track.
    tid = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    for i in range(2):
        cid = M.create_clip(
            conn, track_id=tid, slot=i + 1, length_beats=4.0, name=f"c{i}",
        )
        M.insert_notes(conn, clip_id=cid, notes=[
            {"pitch": 60, "velocity": 100, "start_beats": 0.0, "duration_beats": 0.5},
        ])

    send_fn = _make_send_fn(fail_keys={"ableton_clip:create"})
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    errors_payload = json.loads((state_dir / ".last-push-errors.json").read_text())
    assert len(errors_payload["errors"]) == 2
    grouped = errors_payload["grouped_by_error"]
    assert len(grouped) == 1
    assert grouped[0]["count"] == 2


# ---------------------------------------------------------------------------
# Connection loss
# ---------------------------------------------------------------------------


def test_execute_connection_loss_immediate_halt(
    conn, song, session, tiny_song, state_dir,
):
    """An exception from send_fn (any kind) halts immediately. Tracks phase
    ran first OK, then clips raises — halt before applying clips."""
    send_fn = _make_send_fn(raise_on_key="ableton_clip:create")
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    assert result.outcome == "connection_lost"
    assert result.exit_code == push_execute.EXIT_CONNECTION_LOST
    assert result.phase_halted == "clips"

    state = json.loads((state_dir / ".last-push-state.json").read_text())
    assert state["outcome"] == "connection_lost"
    # Downstream phases pending.
    by_name = {p["name"]: p for p in state["phases"]}
    for downstream in ("mix", "devices", "envelopes", "arrangement", "cues"):
        assert by_name[downstream]["status"] == "pending"

    # The errors file records the connection-class exception.
    errors_payload = json.loads((state_dir / ".last-push-errors.json").read_text())
    assert errors_payload["phase"] == "clips"
    assert "ConnectionRefusedError" in errors_payload["errors"][0]["error"]


# ---------------------------------------------------------------------------
# Idempotency — re-running execute on already-pushed state is a no-op
# ---------------------------------------------------------------------------


def test_execute_idempotent_re_run_skips_already_pushed(
    conn, song, session, tiny_song, state_dir,
):
    """First execute pushes everything. Second execute: planner sees the
    ableton_links and emits empty plans per phase. State shows everything
    skipped (idempotent)."""
    send_fn_1 = _make_send_fn()
    first = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn_1,
    )
    assert first.outcome == "ok"

    send_fn_2 = _make_send_fn()
    second = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn_2,
    )
    assert second.outcome == "ok"

    # The second run should NOT have dispatched any clip-create calls.
    composites = {f"{c['tool']}:{c['action']}" for c in send_fn_2.call_log}
    assert "ableton_clip:create" not in composites
    assert "ableton_track:create" not in composites

    state = json.loads((state_dir / ".last-push-state.json").read_text())
    by_name = {p["name"]: p for p in state["phases"]}
    # Tracks are fully idempotent — re-run emits empty plan, status=skipped.
    assert by_name["tracks"]["status"] == "skipped"
    # Clips are link-idempotent but still emit `replace_notes` on re-run so
    # note state matches the DB (notes aren't tracked by ableton_links). The
    # second run's clip call is replace_notes, NOT create — that's the
    # observable contract of W10-A clip idempotency.
    assert by_name["clips"]["status"] == "ok"
    replace_notes_calls = [
        c for c in send_fn_2.call_log
        if c["tool"] == "ableton_clip" and c["action"] == "replace_notes"
    ]
    assert len(replace_notes_calls) == 1


def test_execute_stale_errors_file_removed_on_clean_re_run(
    conn, song, session, tiny_song, state_dir,
):
    """Partial run writes .last-push-errors.json; clean re-run must remove
    it so the agent doesn't read stale forensics."""
    # First run fails.
    send_fn_fail = _make_send_fn(fail_keys={"ableton_clip:create"})
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn_fail,
    )
    errors_file = state_dir / ".last-push-errors.json"
    assert errors_file.exists()

    # Second run succeeds (no fail_keys); the stale errors file must go.
    send_fn_ok = _make_send_fn()
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn_ok,
    )
    assert result.outcome == "ok"
    assert not errors_file.exists()


# ---------------------------------------------------------------------------
# Summary formatting
# ---------------------------------------------------------------------------


def test_format_summary_ok_path(conn, song, session, tiny_song, state_dir):
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(),
    )
    text = push_execute.format_summary(result)
    assert "OK" in text
    assert "tracks" in text
    assert "clips" in text


def test_format_summary_partial_includes_top_patterns(
    conn, song, session, tiny_song, state_dir,
):
    send_fn = _make_send_fn(fail_keys={"ableton_clip:create"})
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    text = push_execute.format_summary(result)
    assert "PARTIAL" in text
    assert "halted" in text
    assert "Top error patterns" in text
    assert "simulated failure" in text


def test_format_summary_connection_lost(
    conn, song, session, tiny_song, state_dir,
):
    send_fn = _make_send_fn(raise_on_key="ableton_clip:create")
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    text = push_execute.format_summary(result)
    assert "CONNECTION LOST" in text
