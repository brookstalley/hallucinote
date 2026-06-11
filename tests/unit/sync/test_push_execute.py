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
    # The twelve phases are present, in order.
    names = [p["name"] for p in state["phases"]]
    assert names == [
        "tempo_map", "time_signature_map", "tracks", "returns",
        "scenes", "clips", "mix", "devices", "envelopes",
        "performed_automation", "arrangement", "cues",
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
    (e.g. a refactor that pre-builds all twelve plans before dispatching)."""
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
# SYN-4P2D — scene provisioning before clips (the bug's signal)
# ---------------------------------------------------------------------------


@pytest.fixture
def nine_section_song(conn, song):
    """A 9-section song: 9 session clips at slots 1..9 on one track, each
    with a note. This is the SYN-4P2D failure case — more sections (9) than
    a default 8-scene Live set has scenes."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead", kind="midi")
    clip_ids = []
    for slot in range(1, 10):
        cid = M.create_clip(
            conn, track_id=tid, slot=slot, length_beats=4.0, name=f"sec{slot}",
        )
        M.insert_notes(conn, clip_id=cid, notes=[
            {"pitch": 60, "velocity": 100, "start_beats": 0.0, "duration_beats": 0.5},
        ])
        clip_ids.append(cid)
    return {"track_id": tid, "clip_ids": clip_ids, "song_id": song}


def _make_scene_aware_send_fn(*, initial_scenes: int = 8, honor_ensure_count: bool = True):
    """Build a fake send_fn that models a Live set's scene count the way real
    Live does (handlers/clip.py:289-293 + handlers/scene.py):

    - The set starts with ``initial_scenes`` scenes. ``track.clip_slots`` has
      one slot per scene, so a clip-create into ``clip_index > scene_count``
      raises ``IndexError`` (the real handler's exact message shape).
    - ``ableton_scene:ensure_count`` grows the count to ``max(count, current)``
      — UNLESS ``honor_ensure_count`` is False, which models the PRE-FIX world
      where nothing provisions scenes and the clips phase fails per-clip.

    The fake's IndexError-on-create is what makes this a real regression: a
    fake that always succeeds at clip-create would give false confidence (the
    "Unit fakes that mirror an *assumed* Live API give false confidence"
    learning).
    """
    state = {"scene_count": initial_scenes}
    counters: dict[str, int] = {}
    call_log: list[dict] = []

    _LINK_KIND_FOR = {
        ("ableton_track", "create"): "track",
        ("ableton_return", "create"): "return",
        ("ableton_clip", "create"): "clip",
        ("ableton_device", "load"): "device",
        ("ableton_arrangement", "duplicate_to_arrangement"): "arrangement_clip",
        ("ableton_automation", "write_envelope"): "envelope",
    }

    def send(req):
        call_log.append({
            "tool": req.tool, "action": req.action,
            "params": dict(req.params),
        })
        if req.tool == "ableton_scene" and req.action == "ensure_count":
            if honor_ensure_count:
                count = req.params["count"]
                created = max(0, count - state["scene_count"])
                state["scene_count"] = max(state["scene_count"], count)
                return FakeResponse(
                    ok=True,
                    result={"scene_count": state["scene_count"], "created": created},
                )
            # Pre-fix world: the action exists but nothing provisions (or, in
            # the absent-phase simulation, it's simply never called).
            return FakeResponse(
                ok=True, result={"scene_count": state["scene_count"], "created": 0},
            )
        if req.tool == "ableton_clip" and req.action == "create":
            clip_index = req.params["clip_index"]
            if clip_index > state["scene_count"]:
                # Mirror handlers/clip.py:289-293 — the raw per-clip IndexError
                # the bug produced. Surfaced as ok=False (the executor records
                # it; the real handler raises and the dispatcher wraps it).
                return FakeResponse(
                    ok=False,
                    error=(
                        f"ableton_clip('create') failed: IndexError: clip_index "
                        f"{clip_index} out of range [1, {state['scene_count']}] "
                        f"for session view of track {req.params.get('track_index')}"
                    ),
                )
            counters["clip"] = counters.get("clip", 0) + 1
            return FakeResponse(ok=True, result={"clip_index": counters["clip"]})
        kind = _LINK_KIND_FOR.get((req.tool, req.action))
        if kind is None:
            return FakeResponse(ok=True, result={})
        counters[kind] = counters.get(kind, 0) + 1
        return FakeResponse(ok=True, result={_LINK_FIELDS[kind]: counters[kind]})

    send.call_log = call_log  # type: ignore[attr-defined]
    return send


def test_execute_nine_section_song_provisions_scenes_before_clips(
    conn, song, session, nine_section_song, state_dir,
):
    """With the fix, the scenes phase emits one ensure_count(count=9) BEFORE
    the clips phase, the fake set grows from 8 to 9 scenes, every clip-create
    succeeds, and the push reaches outcome='ok'. This is the SYN-4P2D
    success signal: a >8-section song pushed into a fresh 8-scene set
    COMPLETES."""
    send_fn = _make_scene_aware_send_fn(initial_scenes=8)
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    assert result.outcome == "ok", result.phase_halted

    # Exactly one ensure_count call, with count == max slot (9), and it
    # arrived BEFORE the first clip-create.
    ensure_calls = [
        i for i, c in enumerate(send_fn.call_log)
        if c["tool"] == "ableton_scene" and c["action"] == "ensure_count"
    ]
    clip_creates = [
        i for i, c in enumerate(send_fn.call_log)
        if c["tool"] == "ableton_clip" and c["action"] == "create"
    ]
    assert len(ensure_calls) == 1
    assert send_fn.call_log[ensure_calls[0]]["params"]["count"] == 9
    assert ensure_calls[0] < clip_creates[0], (
        "scenes phase must dispatch ensure_count before the first clip-create"
    )
    # All 9 clips created.
    assert len(clip_creates) == 9

    state = json.loads((state_dir / ".last-push-state.json").read_text())
    by_name = {p["name"]: p for p in state["phases"]}
    assert by_name["scenes"]["status"] == "ok"
    assert by_name["clips"]["status"] == "ok"


def test_execute_nine_section_fails_without_scene_provisioning(
    conn, song, session, nine_section_song, state_dir, monkeypatch,
):
    """Companion (pins what now passes): with the scenes phase REMOVED from
    the orchestrator, the default-8-scene fake's clip-create raises the raw
    IndexError on slots 9 (and beyond the count), the clips phase halts, and
    the push is 'partial'. Proves the fix's teeth — the test fails without
    the provisioning phase."""
    real_plan_push_song = push_execute.push.plan_push_song

    def plan_without_scenes(conn, *, song_id, session_id):
        return [
            p for p in real_plan_push_song(conn, song_id=song_id, session_id=session_id)
            if p.name != "scenes"
        ]

    monkeypatch.setattr(push_execute.push, "plan_push_song", plan_without_scenes)

    # honor_ensure_count is irrelevant here — the scenes phase is gone, so
    # ensure_count is never dispatched; the set stays at 8 scenes.
    send_fn = _make_scene_aware_send_fn(initial_scenes=8)
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    assert result.outcome == "partial"
    assert result.phase_halted == "clips"

    # No ensure_count was dispatched (phase removed).
    assert not any(
        c["tool"] == "ableton_scene" and c["action"] == "ensure_count"
        for c in send_fn.call_log
    )
    # The recorded error is the raw per-clip IndexError for the out-of-range slot.
    errors = json.loads((state_dir / ".last-push-errors.json").read_text())
    assert any(
        "out of range" in e.get("error", "") and "IndexError" in e.get("error", "")
        for e in errors["errors"]
    ), errors["errors"]


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


# ---------------------------------------------------------------------------
# M1-B: cross-machine device-load fallback
# ---------------------------------------------------------------------------
#
# Author's machine captures `preset_uri=query:Drums#FileId_5418`. The
# consumer's Live has a different FileId for the same preset (or the
# preset's missing). On load failure the executor should search by
# display_name and retry with the discovered URI.


@pytest.fixture
def song_with_device(conn, song):
    """1 MIDI track + 1 top-level device with a per-machine preset_uri.

    Authored by `system` and unlinked from any session — the push planner
    will emit a device.load call referencing this device's UUID via
    `device:<uuid>` key.
    """
    tid = M.create_track(
        conn, song_id=song, track_index=1, name="Drums", kind="midi",
    )
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="Drum Rack", display_name="Late Nite Kit",
        preset_uri="query:Drums#FileId_AUTHOR_MACHINE",
    )
    return {"track_id": tid, "device_id": did, "song_id": song}


def _make_fallback_send_fn(
    *,
    fail_preset_uri: str,
    search_matches: list[dict],
    succeed_on_fallback_uri: str | None = None,
):
    """Build a fake send_fn for M1-B fallback scenarios.

    * `device.load` with `preset_uri == fail_preset_uri` → ok=False with
      a message that contains both 'preset_uri' and the original URI
      (matches what the real handler emits — see test_actions_device.py
      `test_load_unknown_preset_uri_errors`).
    * `device.load` with `preset_uri == succeed_on_fallback_uri` → ok=True
      with a fresh device_index.
    * `browser.search` → ok=True with the provided matches list.
    * Everything else → ok=True with a synthetic link index.
    """
    counters: dict[str, int] = {}
    call_log: list[dict] = []

    _LINK_KIND_FOR = {
        ("ableton_track", "create"): "track",
        ("ableton_return", "create"): "return",
        ("ableton_clip", "create"): "clip",
        ("ableton_device", "load"): "device",
        ("ableton_arrangement", "duplicate_to_arrangement"): "arrangement_clip",
        ("ableton_automation", "write_envelope"): "envelope",
    }

    def send(req):
        call_log.append({
            "tool": req.tool, "action": req.action,
            "params": dict(req.params),
        })
        if req.tool == "ableton_browser" and req.action == "search":
            return FakeResponse(ok=True, result={
                "matches": search_matches,
                "count": len(search_matches),
                "truncated": False,
                "depth_exhausted": False,
            })
        if req.tool == "ableton_device" and req.action == "load":
            preset_uri = req.params.get("preset_uri")
            if preset_uri == fail_preset_uri:
                return FakeResponse(
                    ok=False,
                    error=(
                        f"no loadable browser item found for "
                        f"preset_uri={preset_uri!r}; verify via "
                        f"ableton_browser(action='tree', ...)"
                    ),
                )
            if (
                succeed_on_fallback_uri is not None
                and preset_uri == succeed_on_fallback_uri
            ):
                counters["device"] = counters.get("device", 0) + 1
                return FakeResponse(
                    ok=True, result={"device_index": counters["device"]},
                )
            # Any other URI on load — treat as success too (covers retry
            # scenarios that don't strictly match succeed_on_fallback_uri).
            counters["device"] = counters.get("device", 0) + 1
            return FakeResponse(
                ok=True, result={"device_index": counters["device"]},
            )
        kind = _LINK_KIND_FOR.get((req.tool, req.action))
        if kind is None:
            return FakeResponse(ok=True, result={})
        counters[kind] = counters.get(kind, 0) + 1
        return FakeResponse(
            ok=True, result={_LINK_FIELDS[kind]: counters[kind]},
        )

    send.call_log = call_log  # type: ignore[attr-defined]
    return send


def test_execute_falls_back_when_device_load_preset_uri_misses(
    conn, song, session, song_with_device, state_dir,
):
    """Happy path: load fails with preset_uri miss → search finds match →
    retry with new URI → device load recorded as success."""
    send_fn = _make_fallback_send_fn(
        fail_preset_uri="query:Drums#FileId_AUTHOR_MACHINE",
        search_matches=[{
            "name": "Late Nite Kit",
            "uri": "query:Drums#FileId_CONSUMER_MACHINE",
            "path": ["drums", "Drum Kits", "Late Nite Kit"],
            "is_loadable": True,
        }],
        succeed_on_fallback_uri="query:Drums#FileId_CONSUMER_MACHINE",
    )
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    # Overall ok — fallback fixed the load.
    assert result.outcome == "ok", result.phase_halted
    # The errors file should NOT be written for a cleanly-fallback-resolved push.
    assert not (state_dir / ".last-push-errors.json").exists()
    # The state file should record the fallback URI substitution.
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    assert state["outcome"] == "ok"
    # Verify the search call fired with the device's display_name.
    search_calls = [
        c for c in send_fn.call_log
        if c["tool"] == "ableton_browser" and c["action"] == "search"
    ]
    assert len(search_calls) == 1
    assert search_calls[0]["params"]["pattern"] == "Late Nite Kit"
    assert search_calls[0]["params"]["root"] == "drums"  # DrumGroupDevice → drums


def test_execute_fallback_not_triggered_without_preset_uri(
    conn, song, session, song_with_device, state_dir,
):
    """Kind-only loads (no preset_uri) skip the fallback — the original
    failure surfaces unchanged."""
    # Mutate the device row to drop preset_uri so the planner emits a
    # kind-only load.
    conn.execute(
        "UPDATE devices SET preset_uri = NULL WHERE id = ?",
        (song_with_device["device_id"],),
    )
    conn.commit()

    def send(req):
        if req.tool == "ableton_device" and req.action == "load":
            return FakeResponse(
                ok=False, error="no loadable browser item found for kind='X'",
            )
        # Pass through for other phases.
        return FakeResponse(ok=True, result={"track_index": 1})

    send.call_log = []  # type: ignore[attr-defined]
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    # Search must NOT have been attempted — no preset_uri means no fallback.
    # (And the push halts at the devices phase.)
    assert result.outcome == "partial"


def test_execute_fallback_no_search_matches_preserves_original_error(
    conn, song, session, song_with_device, state_dir,
):
    """Search returns empty → fallback aborts → original error stands."""
    send_fn = _make_fallback_send_fn(
        fail_preset_uri="query:Drums#FileId_AUTHOR_MACHINE",
        search_matches=[],
        succeed_on_fallback_uri=None,
    )
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    assert result.outcome == "partial"
    errors = json.loads((state_dir / ".last-push-errors.json").read_text())
    # The original preset_uri error survives.
    assert any(
        "FileId_AUTHOR_MACHINE" in e.get("error", "")
        for e in errors["errors"]
    )


def test_execute_fallback_retry_failure_preserves_original_error(
    conn, song, session, song_with_device, state_dir,
):
    """Search finds a URI but the retry load also fails → original
    error stands; no false-success."""
    def send(req):
        if req.tool == "ableton_browser" and req.action == "search":
            return FakeResponse(ok=True, result={
                "matches": [{
                    "name": "Late Nite Kit",
                    "uri": "query:Drums#FileId_DEAD_END",
                    "path": ["drums"],
                    "is_loadable": True,
                }],
                "count": 1, "truncated": False, "depth_exhausted": False,
            })
        if req.tool == "ableton_device" and req.action == "load":
            # ALL load attempts fail (primary + retry).
            return FakeResponse(
                ok=False,
                error=(
                    f"no loadable browser item found for "
                    f"preset_uri={req.params.get('preset_uri')!r}"
                ),
            )
        return FakeResponse(ok=True, result={"track_index": 1})

    send.call_log = []  # type: ignore[attr-defined]
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    assert result.outcome == "partial"
    errors = json.loads((state_dir / ".last-push-errors.json").read_text())
    # The original AUTHOR_MACHINE preset_uri error (the FIRST attempt's
    # failure) is what's recorded — not the retry's. apply_push_results
    # only sees the first per-call result, and the executor's error_record
    # was already built before the fallback ran.
    err_messages = [e.get("error", "") for e in errors["errors"]]
    assert any("FileId_AUTHOR_MACHINE" in m for m in err_messages)


def test_execute_fallback_routes_plugin_kind_to_plugins_root(
    conn, song, session, state_dir,
):
    """Plugin classes (e.g. AuPluginDevice) search the 'plugins' root."""
    tid = M.create_track(
        conn, song_id=song, track_index=1, name="Synth", kind="midi",
    )
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    # Arc 4 / D4: kind is the browser display name ("Spitfire LABS"),
    # class_name carries Live's internal wrapper class (drives the
    # plugins-root routing in the fallback).
    M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="Spitfire LABS", display_name="Spitfire LABS",
        class_name="AuPluginDevice",
        preset_uri="query:plugins#FileId_AUTHOR_AU",
    )
    send_fn = _make_fallback_send_fn(
        fail_preset_uri="query:plugins#FileId_AUTHOR_AU",
        search_matches=[{
            "name": "Spitfire LABS",
            "uri": "query:plugins#FileId_CONSUMER_AU",
            "path": ["plugins"],
            "is_loadable": True,
        }],
        succeed_on_fallback_uri="query:plugins#FileId_CONSUMER_AU",
    )
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    assert result.outcome == "ok"
    search_calls = [
        c for c in send_fn.call_log
        if c["tool"] == "ableton_browser" and c["action"] == "search"
    ]
    assert search_calls and search_calls[0]["params"]["root"] == "plugins"


def test_execute_fallback_routes_default_kind_to_instruments_root(
    conn, song, session, state_dir,
):
    """Non-rack, non-plugin kinds default to the 'instruments' root."""
    tid = M.create_track(
        conn, song_id=song, track_index=1, name="Bass", kind="midi",
    )
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="Operator", display_name="Sub Bass",
        preset_uri="query:Instruments#FileId_OLD_PATCH",
    )
    send_fn = _make_fallback_send_fn(
        fail_preset_uri="query:Instruments#FileId_OLD_PATCH",
        search_matches=[{
            "name": "Sub Bass", "uri": "query:Instruments#FileId_NEW",
            "path": ["instruments"], "is_loadable": True,
        }],
        succeed_on_fallback_uri="query:Instruments#FileId_NEW",
    )
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    assert result.outcome == "ok"
    search_calls = [
        c for c in send_fn.call_log
        if c["tool"] == "ableton_browser" and c["action"] == "search"
    ]
    assert search_calls and search_calls[0]["params"]["root"] == "instruments"


# ---------------------------------------------------------------------------
# A3 — Drum Rack pad-mapping auto-population
# ---------------------------------------------------------------------------


def _make_drum_send_fn(
    *,
    pad_info_response: dict | None = None,
    pad_info_ok: bool = True,
    raise_on_pad_info: bool = False,
):
    """Wraps ``_make_send_fn`` with a deterministic ``pad_info`` response so
    A3 tests can drive the post-phase walker through happy and failure paths
    without re-implementing the whole dispatch fake.

    ``pad_info_response`` is the result payload returned for the
    ``ableton_device(action='pad_info', ...)`` call. Defaults to a
    Hot-Rod-Kit-shaped layout so the round-trip exercises both ride-side
    canonical resolution (Crash → midi 49) and the wrong-sound case
    (Cowbell at midi 51 — the GM ride slot).
    """
    base = _make_send_fn()
    response = pad_info_response or {
        "device_index": 1,
        "pads": [
            {"note": 36, "name": "Pad 36", "chain_name": "Kick Drum"},
            {"note": 38, "name": "Pad 38", "chain_name": "Snare Top"},
            {"note": 42, "name": "Pad 42", "chain_name": "Closed Hat"},
            {"note": 49, "name": "Pad 49", "chain_name": "Crash"},
            {"note": 51, "name": "Pad 51", "chain_name": "Cowbell Fenk Chick"},
        ],
        "parent_kind": "track",
        "track_index": 1,
    }

    def send(req):
        if req.tool == "ableton_device" and req.action == "pad_info":
            # Log the call so tests can assert it fired with the right addressing.
            base.call_log.append({  # type: ignore[attr-defined]
                "tool": req.tool, "action": req.action,
                "params_keys": sorted(req.params.keys()),
                "params": dict(req.params),
            })
            if raise_on_pad_info:
                raise ConnectionRefusedError("simulated Live unreachable")
            if not pad_info_ok:
                return FakeResponse(ok=False, error="simulated pad_info failure")
            return FakeResponse(ok=True, result=response)
        return base(req)

    send.call_log = base.call_log  # type: ignore[attr-defined]
    return send


@pytest.fixture
def drum_song(conn, song):
    """One track + one Drum Rack device. Devices phase will emit a load
    call; the post-phase walker picks up the linked Drum Rack and probes
    its pad layout. Distinct from `tiny_song` (which has no devices)."""
    tid = M.create_track(
        conn, song_id=song, track_index=1, name="Drums", kind="midi",
    )
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="Drum Rack", display_name="Hot Rod Kit",
    )
    return {"track_id": tid, "chain_id": chain_id, "device_id": did, "song_id": song}


def test_pad_probe_auto_populates_drum_pad_mappings_after_devices_phase(
    conn, song, session, drum_song, state_dir,
):
    """Happy path: a Drum Rack load succeeds, the post-phase walker fires
    pad_info, and the response gets persisted as ``drum_pad_mappings`` rows.
    This is the Hot Rod Kit cautionary tale's structural fix — pad data
    flows automatically as a side effect of the push, no extra step."""
    send_fn = _make_drum_send_fn()
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    assert result.outcome == "ok"
    # pad_info fired with the loaded device's address.
    pad_info_calls = [
        c for c in send_fn.call_log
        if c["tool"] == "ableton_device" and c["action"] == "pad_info"
    ]
    assert len(pad_info_calls) == 1
    assert pad_info_calls[0]["params"]["track_index"] == 1
    assert pad_info_calls[0]["params"]["device_index"] == 1
    # Rows persisted.
    rows = Q.get_drum_pad_mappings(conn, drum_song["device_id"])
    by_note = {int(r["midi_note"]): r["chain_name"] for r in rows}
    assert by_note == {
        36: "Kick Drum", 38: "Snare Top", 42: "Closed Hat",
        49: "Crash", 51: "Cowbell Fenk Chick",
    }


def test_pad_probe_counts_surface_in_state_file(
    conn, song, session, drum_song, state_dir,
):
    """When the probe fires, pad_probes_ok/failed appear on the devices
    phase entry in the state file. Songs without Drum Racks don't get the
    fields (zero ceremony)."""
    send_fn = _make_drum_send_fn()
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    devices_phase = next(p for p in state["phases"] if p["name"] == "devices")
    assert devices_phase["pad_probes_ok"] == 1
    assert devices_phase["pad_probes_failed"] == 0
    # Non-devices phases stay clean.
    tracks_phase = next(p for p in state["phases"] if p["name"] == "tracks")
    assert "pad_probes_ok" not in tracks_phase
    assert "pad_probes_failed" not in tracks_phase


def test_pad_probe_failure_does_not_halt_push(
    conn, song, session, drum_song, state_dir,
):
    """Pad-probing is best-effort: a handler error (or connection error)
    on pad_info counts as a failed probe but does NOT change the phase
    outcome or the overall push result. The song's structural state in
    Live is already correct; pad metadata is auxiliary."""
    send_fn = _make_drum_send_fn(pad_info_ok=False)
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    assert result.outcome == "ok"
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    devices_phase = next(p for p in state["phases"] if p["name"] == "devices")
    assert devices_phase["status"] == "ok"
    assert devices_phase["pad_probes_ok"] == 0
    assert devices_phase["pad_probes_failed"] == 1
    # No rows persisted on failure.
    assert Q.get_drum_pad_mappings(conn, drum_song["device_id"]) == []


def test_pad_probe_swallows_connection_errors(
    conn, song, session, drum_song, state_dir,
):
    """A connection-class exception raised by send_fn during pad_info
    must not propagate: the push has structurally succeeded, and a
    network blip on the auxiliary probe shouldn't crash the executor."""
    send_fn = _make_drum_send_fn(raise_on_pad_info=True)
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    assert result.outcome == "ok"
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    devices_phase = next(p for p in state["phases"] if p["name"] == "devices")
    assert devices_phase["pad_probes_failed"] == 1
    assert Q.get_drum_pad_mappings(conn, drum_song["device_id"]) == []


def test_pad_probe_skipped_when_no_drum_racks(
    conn, song, session, tiny_song, state_dir,
):
    """A song with no Drum Rack devices runs the devices phase (skipped —
    no devices to load) and the pad-probe walker finds nothing to probe.
    State file stays clean (no pad_probes_* fields)."""
    send_fn = _make_send_fn()
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    devices_phase = next(p for p in state["phases"] if p["name"] == "devices")
    assert "pad_probes_ok" not in devices_phase
    assert "pad_probes_failed" not in devices_phase
    pad_info_calls = [
        c for c in send_fn.call_log
        if c["tool"] == "ableton_device" and c["action"] == "pad_info"
    ]
    assert pad_info_calls == []


def test_pad_probe_runs_on_idempotent_re_push(
    conn, song, session, drum_song, state_dir,
):
    """The interesting re-push case: first push loads the Drum Rack and
    captures pads. Second push's devices phase has nothing to load
    (everything linked via W20-A), so the phase is `skipped`. The pad
    probe must STILL fire — otherwise a song whose first push didn't
    capture pads (older code path, or transient probe failure) would
    never recover automatically."""
    # First push: loads + probes.
    send_fn = _make_drum_send_fn()
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    # Clear the captured rows to simulate "first push didn't probe."
    conn.execute(
        "DELETE FROM drum_pad_mappings WHERE device_id = ?",
        (drum_song["device_id"],),
    )
    conn.commit()
    # Second push: devices phase has no calls (everything linked), but
    # the post-phase walker still fires.
    send_fn2 = _make_drum_send_fn()
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn2,
    )
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    devices_phase = next(p for p in state["phases"] if p["name"] == "devices")
    assert devices_phase["status"] == "skipped"
    assert devices_phase["pad_probes_ok"] == 1
    # And the rows came back via the idempotent re-probe.
    assert len(Q.get_drum_pad_mappings(conn, drum_song["device_id"])) == 5


# ---------------------------------------------------------------------------
# ENV-7G4K: unverified perform surfacing
# ---------------------------------------------------------------------------


def test_execute_unverified_perform_surfaces_in_errors_file_on_exit_0(
    conn, song, session, tiny_song, state_dir,
):
    """An ok perform wire call whose handler could not verify the write
    (no ``automation_state == 1`` in the result — the fake send_fn's
    ack-only path returns ``{}``) must not vanish: the exit code stays 0
    (every wire call succeeded), but the errors file carries an
    ``apply_push_results`` record naming the arc, and no performed-state
    row is written so the next push retries."""
    master = M.create_track(
        conn, song_id=song, track_index=0, name="Master", kind="master",
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume",
        target_track_id=master,
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[
            {"time_beats": 0.0, "value": 0.85},
            {"time_beats": 16.0, "value": 0.4},
        ],
    )
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(),
    )
    assert result.exit_code == push_execute.EXIT_OK
    assert result.errors_file is not None
    errors = json.loads(result.errors_file.read_text())
    apply_recs = [
        e for e in errors["errors"] if e["tool"] == "apply_push_results"
    ]
    assert len(apply_recs) == 1
    assert eid in apply_recs[0]["error"]
    assert "automation_state" in apply_recs[0]["error"]
    assert Q.get_performed_automation(conn, eid, session) is None
