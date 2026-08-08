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


def _handle_arrangement_projection(req, arr_state):
    """Model the ARR-PROJ projection so the executor's post-arrangement integrity
    assert (Chunk 3) sees a faithful materialization: track create/delete on the
    arrangement lane and answer list / note-list from the accumulated state.
    Returns a FakeResponse, or None to fall through to the generic dispatch."""
    p = req.params
    if req.tool == "ableton_clip" and p.get("location") == "arrangement":
        lane = arr_state.setdefault(p["track_index"], [])
        if req.action == "create":
            lane.append({"start_beats": float(p["start_beats"]),
                         "name": p.get("name") or "",
                         "notes": list(p.get("notes") or [])})
            lane.sort(key=lambda c: c["start_beats"])
            idx = 1 + next(i for i, c in enumerate(lane)
                           if abs(c["start_beats"] - float(p["start_beats"])) < 1e-9)
            return FakeResponse(ok=True, result={"arrangement_clip_index": idx})
        if req.action == "delete":
            lane.sort(key=lambda c: c["start_beats"])
            ci = p["clip_index"]
            if 1 <= ci <= len(lane):
                lane.pop(ci - 1)
            return FakeResponse(ok=True, result={"deleted": True})
        if req.action == "list":
            lane.sort(key=lambda c: c["start_beats"])
            return FakeResponse(ok=True, result={"clips": [
                {"arrangement_clip_index": i, "start_beats": c["start_beats"],
                 "name": c["name"], "length": 4.0, "muted": False,
                 "note_count": len(c["notes"])}
                for i, c in enumerate(lane, 1)
            ]})
    if (req.tool == "ableton_note" and req.action == "list"
            and p.get("location") == "arrangement"):
        lane = sorted(arr_state.get(p["track_index"], []), key=lambda c: c["start_beats"])
        ci = p["clip_index"]
        notes = lane[ci - 1]["notes"] if 1 <= ci <= len(lane) else []
        return FakeResponse(ok=True, result={"notes": [
            {"note_id": j, "pitch": n["pitch"],
             "start_time": n.get("start_time", n.get("start_beats", 0.0)),
             "duration": n.get("duration", n.get("duration_beats", 0.0)),
             "velocity": n.get("velocity", 100), "mute": bool(n.get("mute", False))}
            for j, n in enumerate(notes)
        ]})
    return None


def _make_send_fn(
    *,
    fail_keys: set[str] = frozenset(),
    raise_on_key: str | None = None,
    fail_hint: str | None = None,
    perform_automation_state: int | None = 1,
):
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
    arr_state: dict[int, list[dict]] = {}  # ARR-PROJ: per-track arrangement lane

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

    def send(req, *, read_timeout=None):
        # Mirror client.send's signature: a planner-derived read ceiling
        # (perform_batch, ENV-8K2R #5) rides in as a keyword; record it so a
        # test can assert the ceiling was forwarded.
        call_log.append({
            "tool": req.tool, "action": req.action,
            "params_keys": sorted(req.params.keys()),
            "params": dict(req.params),
            "read_timeout": read_timeout,
        })

        # The fake matches against the *request* shape. Tests that want to
        # fail or drop a call pass a predicate via closure modifications,
        # but the simplest entry point is (tool, action) match strings.
        composite = f"{req.tool}:{req.action}"
        if raise_on_key and composite == raise_on_key:
            raise ConnectionRefusedError("simulated Live unreachable")
        if composite in fail_keys:
            return FakeResponse(
                ok=False,
                error=f"simulated failure for {composite}",
                hint=fail_hint,
            )

        # ARR-PROJ Chunk 3: model the arrangement projection (create/delete/list/
        # note-list) so the executor's post-arrangement integrity assert reads a
        # faithful materialization instead of an empty (looks-dropped) lane.
        arr_resp = _handle_arrangement_projection(req, arr_state)
        if arr_resp is not None:
            return arr_resp

        # perform_batch (ENV-9P4T) fans out to a per-arc result list; echo
        # each arc's arc_id with a configurable automation_state (default 1
        # = verified). The apply layer gates each arc independently on it.
        if req.tool == "ableton_automation" and req.action == "perform_batch":
            arcs_in = req.params.get("arcs", [])
            return FakeResponse(ok=True, result={
                "arcs": [
                    {
                        "arc_id": a.get("arc_id"),
                        "automation_state": perform_automation_state,
                    }
                    for a in arcs_in
                ],
                # The real handler reports how many arcs it prepared; the apply
                # layer cross-checks it against the returned count (ENV-8K2R #4).
                "arc_count": len(arcs_in),
            })

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
    # The fourteen phases are present, in order.
    names = [p["name"] for p in state["phases"]]
    assert names == [
        "tempo_map", "time_signature_map", "tracks", "returns",
        "scenes", "clips", "mix", "devices", "routing", "device_sidechain",
        "envelopes", "performed_automation", "arrangement", "cues",
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
    (e.g. a refactor that pre-builds all fourteen plans before dispatching)."""
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

    def plan_without_scenes(conn, *, song_id, session_id, **kwargs):
        return [
            p for p in real_plan_push_song(
                conn, song_id=song_id, session_id=session_id, **kwargs
            )
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
    for downstream in ("mix", "routing", "devices", "envelopes", "arrangement", "cues"):
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
    for downstream in ("mix", "routing", "devices", "envelopes", "arrangement", "cues"):
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


def test_format_summary_partial_includes_halt_cause_and_next_step(
    conn, song, session, tiny_song, state_dir,
):
    """PSH-4E2W: a failed push's output names the halt cause (tool.action +
    error) and a suggested next step — no JSON spelunking required."""
    send_fn = _make_send_fn(fail_keys={"ableton_clip:create"})
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    text = push_execute.format_summary(result)
    assert "PARTIAL" in text
    assert "halted" in text
    assert "Halt cause" in text
    assert "ableton_clip.create" in text
    assert "simulated failure" in text
    assert "next:" in text
    # No responder hint → generic fix-rebuild-rerun suggestion.
    assert "re-run" in text


def test_format_summary_next_step_prefers_responder_hint(
    conn, song, session, tiny_song, state_dir,
):
    """When the failing response carries a hint, the summary's next step IS
    that hint — the responder knows the cause better than any heuristic."""
    send_fn = _make_send_fn(
        fail_keys={"ableton_clip:create"},
        fail_hint="slot 1 is occupied; delete the clip in Live first",
    )
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    text = push_execute.format_summary(result)
    assert "next: slot 1 is occupied; delete the clip in Live first" in text


def test_format_summary_stays_payload_free_for_large_errors(
    conn, song, session, tiny_song, state_dir,
):
    """Governance checkpoint for PSH-4E2W: the richer summary must not
    reintroduce bulk payloads. A failing response whose error message embeds
    a large dump renders at most the 60-char grouping prefix."""
    payload = "notes=[" + ", ".join(f"{{'pitch': {60 + i}}}" for i in range(500)) + "]"
    send_fn = _make_send_fn(fail_keys={"ableton_clip:create"})

    # Wrap the fake so the failure carries the giant message.
    inner = send_fn

    def send(req):
        resp = inner(req)
        if not resp.ok:
            return FakeResponse(ok=False, error=f"clip rejected: {payload}")
        return resp

    send.call_log = inner.call_log  # type: ignore[attr-defined]

    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    text = push_execute.format_summary(result)
    assert "Halt cause" in text
    assert payload not in text
    # Only the 60-char grouping prefix of the error may appear.
    assert ("clip rejected: " + payload)[:60] in text
    assert all(len(line) < 200 for line in text.splitlines())


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
    # PSH-4E2W: connection-class halts point at the Live-side checklist.
    assert "Live is running" in text


def test_group_errors_carries_representative_tool_action_hint():
    """PSH-4E2W: grouped patterns carry enough context (tool, action, first
    non-null hint) for the summary to name the cause without the errors file."""
    records = [
        {"key": "clip:1", "tool": "ableton_clip", "action": "create",
         "error": "boom A", "hint": None},
        {"key": "clip:2", "tool": "ableton_clip", "action": "create",
         "error": "boom A", "hint": "try deleting the slot"},
        {"key": "dev:1", "tool": "ableton_device", "action": "load",
         "error": "no such preset", "hint": None},
    ]
    grouped = push_execute._group_errors(records)
    by_substr = {g["error_substring"]: g for g in grouped}
    boom = by_substr["boom A"]
    assert boom["count"] == 2
    assert boom["tool"] == "ableton_clip"
    assert boom["action"] == "create"
    assert boom["hint"] == "try deleting the slot"
    assert boom["affected_keys"] == ["clip:1", "clip:2"]


def test_suggest_next_step_device_load_points_at_requirements():
    """A hint-less device.load failure suggests the not-installed path —
    the canonical cross-machine failure — and names REQUIREMENTS.md."""
    pattern = {"tool": "ableton_device", "action": "load",
               "error_substring": "preset not found", "hint": None, "count": 1}
    step = push_execute._suggest_next_step(pattern, outcome="partial")
    assert "REQUIREMENTS.md" in step


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
    """An ok perform_batch wire call whose handler could not verify an
    arc's write (the fake echoes the arc with ``automation_state=0``) must
    not vanish: the exit code stays 0 (every wire call succeeded), but the
    errors file carries an ``apply_push_results`` record naming the arc,
    and no performed-state row is written so the next push retries."""
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
        state_dir=state_dir, send_fn=_make_send_fn(perform_automation_state=0),
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


def test_execute_forwards_perform_batch_read_ceiling(
    conn, song, session, tiny_song, state_dir,
):
    """ENV-8K2R #5: the planner-derived read ceiling on the perform_batch
    ToolCall must actually reach the wire send — otherwise the unbounded default
    policy would let a worker that dies mid-pass block push_cli forever."""
    master = M.create_track(
        conn, song_id=song, track_index=0, name="Master", kind="master",
    )
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=master,
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[
            {"time_beats": 0.0, "value": 0.85},
            {"time_beats": 16.0, "value": 0.4},
        ],
    )
    send_fn = _make_send_fn()
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send_fn,
    )
    perform_calls = [
        c for c in send_fn.call_log if c["action"] == "perform_batch"
    ]
    assert len(perform_calls) == 1, send_fn.call_log
    # A finite, span-derived ceiling reached the wire — not the unbounded None.
    assert perform_calls[0]["read_timeout"] is not None
    assert perform_calls[0]["read_timeout"] > 16.0
    # Non-perform calls keep the policy default (no explicit override forwarded).
    other = [c for c in send_fn.call_log if c["action"] != "perform_batch"]
    assert all(c["read_timeout"] is None for c in other), other


# ---------------------------------------------------------------------------
# SYN-9F2L — params_dialed lands in one execute (devices-phase convergence)
# ---------------------------------------------------------------------------


@pytest.fixture
def song_with_dialed_device(conn, song):
    """A track whose device carries a snapshot-authored dialed param —
    the swell Saturator case (display '14 dB', normalized 0.389)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Glitch", kind="midi")
    chain = M.create_device_chain(conn, parent_track_id=tid)
    did = M.create_device(
        conn, chain_id=chain, position=1, kind="Saturator",
        display_name="Saturator",
    )
    M.set_device_parameter(
        conn, device_id=did, name="Drive",
        value_display="14 dB", value_normalized=0.389,
    )
    return {"track_id": tid, "device_id": did}


def test_devices_params_dialed_land_in_one_execute(
    conn, song, session, song_with_dialed_device, state_dir,
):
    """SYN-9F2L regression: the device loads AND its dialed param is written
    in the SAME execute. Before the fix, the set_parameter was deferred to a
    'rerun plan_push_devices' that no execute ever performed — the param
    silently never landed."""
    send = _make_send_fn()
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    assert result.outcome == "ok"
    set_param_calls = [
        c for c in send.call_log
        if c["tool"] == "ableton_device" and c["action"] == "set_parameter"
    ]
    assert len(set_param_calls) == 1
    params = set_param_calls[0]["params"]
    assert params["parameter_name"] == "Drive"
    # Display form preferred on the wire (center-zero-safe).
    assert params["value_display"] == "14 dB"
    assert "value" not in params
    # The pass-2 write is ordered AFTER the load it depends on.
    load_idx = next(
        i for i, c in enumerate(send.call_log)
        if c["tool"] == "ableton_device" and c["action"] == "load"
    )
    sp_idx = next(
        i for i, c in enumerate(send.call_log)
        if c["action"] == "set_parameter"
    )
    assert sp_idx > load_idx


def test_devices_second_pass_does_not_redispatch_first_pass_keys(
    conn, song, session, state_dir,
):
    """An already-linked device's params write in pass 1 and must NOT be
    re-sent by the convergence pass."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Keys", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1,
    )
    chain = M.create_device_chain(conn, parent_track_id=tid)
    did = M.create_device(
        conn, chain_id=chain, position=1, kind="EQ Eight", display_name="EQ",
    )
    M.set_device_parameter(
        conn, device_id=did, name="Freq",
        value_display="1.17 kHz", value_normalized=0.59,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=1,
    )
    send = _make_send_fn()
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    assert result.outcome == "ok"
    set_param_calls = [
        c for c in send.call_log if c["action"] == "set_parameter"
    ]
    assert len(set_param_calls) == 1  # exactly once, not once per pass


def test_devices_second_pass_failure_halts_partial(
    conn, song, session, song_with_dialed_device, state_dir,
):
    """A failing pass-2 set_parameter is a real failure: the devices phase
    halts partial, never a silent drop."""
    send = _make_send_fn(fail_keys={"ableton_device:set_parameter"})
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    assert result.outcome == "partial"
    assert result.phase_halted == "devices"


def test_devices_unwritable_param_surfaces_warning_already_linked(
    conn, song, session, state_dir,
):
    """SYN-9F2L's 'OR warns' half, on the execute path: a param with no
    writable form (no display, no normalized, no enum items) on an
    already-linked device must surface a warning in the push report — not be
    silently dropped. The planner warns into ``plan.notes``; before the fix
    ``execute`` never drained ``plan.notes`` into ``ExecuteResult.warnings``, so
    the warn was discarded and the silent drop SYN-9F2L was filed to kill
    survived on the primary push path."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Lead", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1,
    )
    chain = M.create_device_chain(conn, parent_track_id=tid)
    did = M.create_device(
        conn, chain_id=chain, position=1, kind="Saturator", display_name="Saturator",
    )
    # No display, no normalized, no items → unwritable.
    M.set_device_parameter(conn, device_id=did, name="Drive", value_display="")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=1,
    )
    send = _make_send_fn()
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    # Benign warning — the push is still OK (exit 0), not a PARTIAL halt.
    assert result.outcome == "ok"
    assert any(
        "no writable form" in w and "Saturator" in w for w in result.warnings
    ), f"unwritable-param warning not surfaced: {result.warnings!r}"


def test_devices_unwritable_param_surfaces_warning_same_pass_load(
    conn, song, session, state_dir,
):
    """The acute SYN-9F2L case: a device loaded THIS pass (track not pre-linked)
    is unlinked when the primary plan runs, so its unwritable param only becomes
    visible in the convergence re-plan. The re-plan's notes must drain too —
    and the warning must appear exactly ONCE (the re-plan regenerates the full
    plan, so a naive drain would double-report)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Glitch", kind="midi")
    # Deliberately NOT linked — forces a same-pass load + convergence re-plan.
    chain = M.create_device_chain(conn, parent_track_id=tid)
    did = M.create_device(
        conn, chain_id=chain, position=1, kind="Saturator", display_name="Saturator",
    )
    M.set_device_parameter(conn, device_id=did, name="Drive", value_display="")
    send = _make_send_fn()
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    assert result.outcome == "ok"
    matching = [w for w in result.warnings if "no writable form" in w and "Saturator" in w]
    assert len(matching) == 1, (
        f"expected exactly one unwritable-param warning (deduped), got: {result.warnings!r}"
    )


def test_set_parameter_enum_fallback_retries_display_as_enum(
    conn, song, session, state_dir,
):
    """A display write the handler refuses with 'is an enum' is retried once
    as value_type='enum' with the display string as the value — hand-authored
    snapshot enums land instead of halting the phase."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Op", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=1,
    )
    chain = M.create_device_chain(conn, parent_track_id=tid)
    did = M.create_device(
        conn, chain_id=chain, position=1, kind="Operator", display_name="Op",
    )
    M.set_device_parameter(conn, device_id=did, name="Filter Type",
                           value_display="Lowpass")  # no items, no normalized
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=did, ableton_index=1,
    )

    base = _make_send_fn()

    def send(req):
        if (
            req.action == "set_parameter"
            and req.params.get("value_display") is not None
        ):
            base.call_log.append({
                "tool": req.tool, "action": req.action,
                "params_keys": sorted(req.params.keys()),
                "params": dict(req.params),
            })
            return FakeResponse(
                ok=False,
                error=(
                    "parameter 'Filter Type' is an enum (is_quantized=True); "
                    "use value_type='enum' with `value`, not `value_display`"
                ),
            )
        return base(req)

    send.call_log = base.call_log  # type: ignore[attr-defined]
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    assert result.outcome == "ok"
    enum_writes = [
        c for c in send.call_log
        if c["action"] == "set_parameter"
        and c["params"].get("value_type") == "enum"
    ]
    assert len(enum_writes) == 1
    assert enum_writes[0]["params"]["value"] == "Lowpass"


def test_set_parameter_display_fallback_retries_with_normalized(
    conn, song, session, song_with_dialed_device, state_dir,
):
    """A display write the handler refuses with 'exposes no str_for_value'
    is retried once with the DB's normalized value — the pre-SYN-9F2L wire
    form — so params on curve-less parameters still land."""
    base = _make_send_fn()

    def send(req):
        if (
            req.action == "set_parameter"
            and req.params.get("value_display") is not None
        ):
            base.call_log.append({
                "tool": req.tool, "action": req.action,
                "params_keys": sorted(req.params.keys()),
                "params": dict(req.params),
            })
            return FakeResponse(
                ok=False,
                error=(
                    "parameter 'Drive' exposes no str_for_value; set it via "
                    "the normalized `value`"
                ),
            )
        return base(req)

    send.call_log = base.call_log  # type: ignore[attr-defined]
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    assert result.outcome == "ok"
    normalized_writes = [
        c for c in send.call_log
        if c["action"] == "set_parameter" and "value" in c["params"]
    ]
    assert len(normalized_writes) == 1
    assert float(normalized_writes[0]["params"]["value"]) == pytest.approx(0.389)


def test_set_parameter_non_numeric_display_falls_back_to_normalized(
    conn, song, session, state_dir,
):
    """SYN-RACK-PRESET-RELINK §3: a pan param captured as a display string
    ("50L") that the handler refuses with the NON-NUMERIC-display teaching error
    ('...has a non-numeric display...; set it via the normalized `value`') is
    retried once with the DB's stored normalized value. Before this, that
    message matched no fallback hint, so it was 5 guaranteed, unrecoverable
    failures on every push of a track with a dialed Analog pan."""
    tid = M.create_track(
        conn, song_id=song, track_index=1, name="Alien Voice", kind="midi",
    )
    chain = M.create_device_chain(conn, parent_track_id=tid)
    did = M.create_device(
        conn, chain_id=chain, position=1, kind="Analog", display_name="Analog",
    )
    M.set_device_parameter(
        conn, device_id=did, name="AMP1 Pan",
        value_display="50L", value_normalized=0.25,
    )
    base = _make_send_fn()

    def send(req):
        if (
            req.action == "set_parameter"
            and req.params.get("value_display") is not None
        ):
            base.call_log.append({
                "tool": req.tool, "action": req.action,
                "params_keys": sorted(req.params.keys()),
                "params": dict(req.params),
            })
            return FakeResponse(
                ok=False,
                error=(
                    "parameter 'AMP1 Pan' has a non-numeric display "
                    "(' 50L'..' 50R'); set it via the normalized `value` "
                    "instead of `value_display`"
                ),
            )
        return base(req)

    send.call_log = base.call_log  # type: ignore[attr-defined]
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    assert result.outcome == "ok"
    normalized_writes = [
        c for c in send.call_log
        if c["action"] == "set_parameter" and "value" in c["params"]
    ]
    assert len(normalized_writes) == 1
    assert float(normalized_writes[0]["params"]["value"]) == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# SYN-6B4Q: cue deferral (skip-with-warning) + plan-error halt
# ---------------------------------------------------------------------------


def _cue_skip_send_fn(skipped_out_of_range, *, last_event_time=0.0):
    """Wrap the base fake send so ``cue_create_batch`` returns the handler's
    skip-mode shape (some/all cues deferred past Live's extent)."""
    base = _make_send_fn()

    def send(req):
        if req.tool == "ableton_arrangement" and req.action == "cue_create_batch":
            base.call_log.append({
                "tool": req.tool, "action": req.action,
                "params_keys": sorted(req.params.keys()),
                "params": dict(req.params),
            })
            n_in = len(req.params.get("cues", [])) - len(skipped_out_of_range)
            return FakeResponse(ok=True, result={
                "cue_count": max(n_in, 0),
                "cues": [],
                "skipped_out_of_range": skipped_out_of_range,
                "last_event_time": last_event_time,
            })
        return base(req)

    send.call_log = base.call_log  # type: ignore[attr-defined]
    return send


def test_execute_deferred_cues_surface_as_warning_not_partial(
    conn, song, session, tiny_song, state_dir,
):
    """SYN-6B4Q: a skeleton push (cues authored, no arrangement) defers every
    cue past Live's empty extent. The handler reports them in
    ``skipped_out_of_range``; the executor surfaces a benign warning and the
    push stays OK (exit 0) — NOT the old false PARTIAL."""
    M.add_cue_point(conn, song_id=song, position_bar=17.0, name="verse")
    M.add_cue_point(conn, song_id=song, position_bar=33.0, name="chorus")
    send = _cue_skip_send_fn([
        {"position_beats": 64.0, "name": "verse"},
        {"position_beats": 128.0, "name": "chorus"},
    ])
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    assert result.outcome == "ok"
    assert result.exit_code == push_execute.EXIT_OK
    assert result.phase_halted is None
    # Deferred cues surface as a warning, not an error file.
    assert result.errors_file is None
    assert not (state_dir / ".last-push-errors.json").exists()
    assert any("defer" in w.lower() for w in result.warnings)
    assert any("verse" in w or "chorus" in w for w in result.warnings)
    # State file carries the warnings channel.
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    assert state["outcome"] == "ok"
    assert any("defer" in w.lower() for w in state["warnings"])
    # The cues phase ran cleanly (the batch call itself succeeded).
    by_name = {p["name"]: p for p in state["phases"]}
    assert by_name["cues"]["status"] == "ok"


def test_execute_partial_cue_defer_does_not_pollute_warning(
    conn, song, session, tiny_song, state_dir,
):
    """When only some cues defer, the warning names the deferred ones and the
    push still succeeds."""
    M.add_cue_point(conn, song_id=song, position_bar=1.0, name="intro")
    M.add_cue_point(conn, song_id=song, position_bar=33.0, name="late")
    send = _cue_skip_send_fn(
        [{"position_beats": 128.0, "name": "late"}], last_event_time=32.0,
    )
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    assert result.outcome == "ok"
    assert len(result.warnings) == 1
    assert "late" in result.warnings[0]
    assert "intro" not in result.warnings[0]


def test_execute_cue_past_composed_length_halts_partial(
    conn, song, session, tiny_song, state_dir,
):
    """SYN-6B4Q: a cue past the composed song length is a hard authoring error.
    The planner emits ``plan.error`` (no calls); the executor halts the cues
    phase → PARTIAL, with the clear composed-length message in the errors file
    — NOT the opaque runtime ``past last_event_time`` error."""
    # Arrangement covers bars 1–2 (the tiny_song clip is 4 beats = 1 bar).
    M.add_arrangement_clip(
        conn, song_id=song, track_id=tiny_song["track_id"],
        clip_id=tiny_song["clip_id"], start_bar=1.0, end_bar=2.0,
    )
    M.add_cue_point(conn, song_id=song, position_bar=32.0, name="late")
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(),
    )
    assert result.outcome == "partial"
    assert result.exit_code == push_execute.EXIT_PARTIAL
    assert result.phase_halted == "cues"
    errors = json.loads((state_dir / ".last-push-errors.json").read_text())
    blob = json.dumps(errors)
    assert "composed song length" in blob
    assert "late@bar32.00" in blob
    # The cues phase is marked halted in the state file.
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    by_name = {p["name"]: p for p in state["phases"]}
    assert by_name["cues"]["status"] == "halted"


def test_execute_arrangement_integrity_assert_halts_on_drop(
    conn, song, session, tiny_song, state_dir,
):
    """ARR-PROJ Chunk 3: the post-arrangement PREVENTION assert HALTs the push
    when the materialized arrangement diverges from the DB — here a simulated
    bulk-drop (Live reports ZERO notes for a clip the DB filled) — instead of
    reporting OK. The structural backstop for the 2026-06-21/-22 drop/orphan
    bugs; without it the corrupt render passes every cheap check."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    M.insert_notes(conn, clip_id=tiny_song["clip_id"], notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 100},
    ])
    M.add_arrangement_clip(
        conn, song_id=song, track_id=tiny_song["track_id"],
        clip_id=tiny_song["clip_id"], start_bar=1.0, end_bar=2.0,
    )
    base = _make_send_fn()

    def corrupt(req, *, read_timeout=None):
        resp = base(req, read_timeout=read_timeout)
        if (req.tool == "ableton_note" and req.action == "list"
                and req.params.get("location") == "arrangement"):
            resp.result = {"notes": []}  # the clip is placed but its notes dropped
        return resp

    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=corrupt,
    )
    assert result.outcome == "partial"
    assert result.phase_halted == "arrangement"
    blob = json.dumps(json.loads((state_dir / ".last-push-errors.json").read_text()))
    assert "integrity" in blob.lower()
    assert "missing" in blob.lower()  # the drop reads as a missing note


def test_execute_arrangement_assert_connection_loss_writes_state(
    conn, song, session, tiny_song, state_dir,
):
    """ARR-PROJ Chunk 3: a Live disconnect DURING the post-arrangement integrity
    re-probe halts as connection_lost (not an uncaught traceback) and still writes
    the terminal state file — the executor's always-write-state contract."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    M.insert_notes(conn, clip_id=tiny_song["clip_id"], notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 100},
    ])
    M.add_arrangement_clip(
        conn, song_id=song, track_id=tiny_song["track_id"],
        clip_id=tiny_song["clip_id"], start_bar=1.0, end_bar=2.0,
    )
    base = _make_send_fn()

    def drop_conn(req, *, read_timeout=None):
        if (req.tool == "ableton_note" and req.action == "list"
                and req.params.get("location") == "arrangement"):
            raise ConnectionRefusedError("Live vanished mid-assert")
        return base(req, read_timeout=read_timeout)

    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=drop_conn,
    )
    assert result.outcome == "connection_lost"
    assert result.exit_code == push_execute.EXIT_CONNECTION_LOST
    assert (state_dir / ".last-push-state.json").exists()  # always-write-state held


def test_execute_arrangement_probe_failure_warns_not_silent_ok(
    conn, song, session, tiny_song, state_dir,
):
    """Cumulative-Critic W1: when the post-arrangement integrity re-probe FAILS
    (Live note-list errors — NOT a disconnect), the placement goes UNVERIFIED. The
    assert must NOT halt (a probe error isn't silent corruption), but the push must
    NOT silently report a clean OK either: it surfaces a benign warning so
    'couldn't verify N clip(s)' reads distinctly from 'verified all N'. Without it,
    a push where verification was IMPOSSIBLE is indistinguishable from one that
    PASSED — the exact gap the assert exists to close."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    M.insert_notes(conn, clip_id=tiny_song["clip_id"], notes=[
        {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 100},
    ])
    M.add_arrangement_clip(
        conn, song_id=song, track_id=tiny_song["track_id"],
        clip_id=tiny_song["clip_id"], start_bar=1.0, end_bar=2.0,
    )
    base = _make_send_fn()

    def probe_fails(req, *, read_timeout=None):
        # Let materialization (create/delete) and the clip-list succeed, but fail
        # the integrity re-probe's NOTE list so the placement can't be verified.
        if (req.tool == "ableton_note" and req.action == "list"
                and req.params.get("location") == "arrangement"):
            return FakeResponse(ok=False, error="simulated re-probe failure")
        return base(req, read_timeout=read_timeout)

    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=probe_fails,
    )
    # Probe failure is not silent corruption → no halt, exit stays clean.
    assert result.outcome == "ok"
    assert result.phase_halted is None
    # ...but the unverified placement is surfaced as a benign warning.
    assert any("could NOT be verified" in w for w in result.warnings), result.warnings
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    assert any("could NOT be verified" in w for w in state.get("warnings", []))


# ---------------------------------------------------------------------------
# PSH-2R7K — phase-targeting (--only / --start-at / --stop-after)
# ---------------------------------------------------------------------------


class _FakePhase:
    """Minimal phase stand-in for the pure _filter_phases unit tests."""
    def __init__(self, name):
        self.name = name


_DEMO_PHASES = [_FakePhase(n) for n in ("a", "b", "c", "d")]


def test_filter_phases_only_selects_one():
    sliced, scope = push_execute._filter_phases(_DEMO_PHASES, only="c")
    assert [p.name for p in sliced] == ["c"]
    assert scope == {"only": "c"}


def test_filter_phases_start_at_to_end():
    sliced, scope = push_execute._filter_phases(_DEMO_PHASES, start_at="c")
    assert [p.name for p in sliced] == ["c", "d"]
    assert scope == {"start_at": "c"}


def test_filter_phases_stop_after_prefix():
    sliced, scope = push_execute._filter_phases(_DEMO_PHASES, stop_after="b")
    assert [p.name for p in sliced] == ["a", "b"]
    assert scope == {"stop_after": "b"}


def test_filter_phases_window():
    sliced, scope = push_execute._filter_phases(
        _DEMO_PHASES, start_at="b", stop_after="c"
    )
    assert [p.name for p in sliced] == ["b", "c"]
    assert scope == {"start_at": "b", "stop_after": "c"}


def test_filter_phases_full_run_scope_none():
    sliced, scope = push_execute._filter_phases(_DEMO_PHASES)
    assert [p.name for p in sliced] == ["a", "b", "c", "d"]
    assert scope is None


def test_filter_phases_is_order_agnostic():
    """Filters by NAME, not index — so it composes with a future phase reorder
    (RTE-2P9X) without assuming positions. A reversed list still slices from the
    named start through that list's end."""
    reordered = [_FakePhase(n) for n in ("d", "c", "b", "a")]
    sliced, _ = push_execute._filter_phases(reordered, start_at="c")
    assert [p.name for p in sliced] == ["c", "b", "a"]


def test_filter_phases_unknown_name_teaches():
    with pytest.raises(push_execute.PhaseTargetError) as exc:
        push_execute._filter_phases(_DEMO_PHASES, only="nope")
    msg = str(exc.value)
    assert "unknown --only phase 'nope'" in msg
    assert "a, b, c, d" in msg  # the valid list, in order


def test_filter_phases_only_excludes_window():
    with pytest.raises(push_execute.PhaseTargetError):
        push_execute._filter_phases(_DEMO_PHASES, only="a", start_at="b")


def test_filter_phases_stop_before_start_errors():
    with pytest.raises(push_execute.PhaseTargetError):
        push_execute._filter_phases(_DEMO_PHASES, start_at="c", stop_after="a")


# PSH-PHASEORDER: validate_phase_targets is the pure name-validation the CLI
# runs up front (before any Live probe). It shares the rule with _filter_phases.
def test_validate_phase_targets_accepts_valid():
    # No raise = valid. Covers a bare run, --only, a window, and a prefix.
    names = ["a", "b", "c", "d"]
    push_execute.validate_phase_targets(names)
    push_execute.validate_phase_targets(names, only="c")
    push_execute.validate_phase_targets(names, start_at="b", stop_after="d")
    push_execute.validate_phase_targets(names, stop_after="b")


def test_validate_phase_targets_unknown_name_teaches():
    with pytest.raises(push_execute.PhaseTargetError) as exc:
        push_execute.validate_phase_targets(["a", "b"], start_at="nope")
    msg = str(exc.value)
    assert "unknown --start-at phase 'nope'" in msg
    assert "a, b" in msg  # the valid list, in order


def test_validate_phase_targets_only_excludes_window():
    with pytest.raises(push_execute.PhaseTargetError):
        push_execute.validate_phase_targets(["a", "b", "c"], only="a", stop_after="b")


def test_validate_phase_targets_stop_before_start_errors():
    with pytest.raises(push_execute.PhaseTargetError):
        push_execute.validate_phase_targets(["a", "b", "c"], start_at="c", stop_after="a")


def test_execute_only_runs_one_phase(conn, song, session, tiny_song, state_dir):
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(), only="tracks",
    )
    assert result.outcome == "ok"
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    assert [p["name"] for p in state["phases"]] == ["tracks"]
    assert state["scope"] == {"only": "tracks"}


def test_execute_start_at_resumes_after_earlier_phases(
    conn, song, session, tiny_song, state_dir,
):
    """The real --start-at use (resume): earlier phases already ran — here tracks
    are linked by a first scoped run — so resuming from clips plans + runs
    clips→cues without replaying tracks. (--start-at does NOT magic dependencies:
    starting at clips on a fresh set correctly fails, since clips need a linked
    track; that's the operator's resume contract, mirroring the dogfood case.)"""
    push_execute.execute_push(  # run 1: push through tracks → track linked
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(), stop_after="tracks",
    )
    push_execute.execute_push(  # run 2: resume from clips
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(), start_at="clips",
    )
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    names = [p["name"] for p in state["phases"]]
    assert names[0] == "clips"
    assert "tracks" not in names          # earlier phases not replayed
    assert names[-1] == "cues"
    assert state["scope"] == {"start_at": "clips"}
    by_name = {p["name"]: p for p in state["phases"]}
    assert by_name["clips"]["status"] == "ok"  # clips ran (track linked in run 1)


def test_execute_stop_after_bounds_run(conn, song, session, tiny_song, state_dir):
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(), stop_after="tracks",
    )
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    assert [p["name"] for p in state["phases"]] == [
        "tempo_map", "time_signature_map", "tracks",
    ]
    assert state["scope"] == {"stop_after": "tracks"}


def test_execute_unknown_phase_raises_before_request(
    conn, song, session, tiny_song, state_dir,
):
    """A bad phase name fails fast with a teaching error and leaves NO dangling
    open request row (validation happens before create_request)."""
    with pytest.raises(push_execute.PhaseTargetError):
        push_execute.execute_push(
            conn=conn, song_id=song, session_id=session,
            state_dir=state_dir, send_fn=_make_send_fn(), only="bogus",
        )
    assert Q.list_requests_for_song(conn, song, kind="push") == []


def test_execute_full_run_scope_is_none(conn, song, session, tiny_song, state_dir):
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(),
    )
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    assert state["scope"] is None


# ---------------------------------------------------------------------------
# PSH-5T9D — mid-run progress (per-phase flush + progress_fn)
# ---------------------------------------------------------------------------


def test_progress_fn_emits_per_phase_lines(conn, song, session, tiny_song, state_dir):
    lines: list[str] = []
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(),
        progress_fn=lines.append,
    )
    # Phases that dispatch announce a start + a finish; skips announce a skip.
    assert any(ln.startswith("[tracks] running") for ln in lines)
    assert any(ln.startswith("[tracks] ok") for ln in lines)
    assert any(ln.startswith("[clips] running") for ln in lines)
    assert any(ln.startswith("[clips] ok") for ln in lines)
    assert any("skipped" in ln for ln in lines)


def test_state_file_is_pollable_midrun(conn, song, session, tiny_song, state_dir):
    """The state file reflects progress BEFORE the run finishes (PSH-5T9D): a
    snapshot taken while the clips phase dispatches shows tracks already ok,
    current_phase=clips, and NO later phase (cues) recorded yet."""
    base = _make_send_fn()
    snapshots: list[dict] = []

    def spy(req, **kw):
        if req.tool == "ableton_clip" and req.action == "create":
            snapshots.append(
                json.loads((state_dir / ".last-push-state.json").read_text())
            )
        return base(req, **kw)

    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=spy,
    )
    assert snapshots, "clip create never dispatched — fixture changed?"
    mid = snapshots[0]
    assert mid["current_phase"] == "clips"
    by_name = {p["name"]: p for p in mid["phases"]}
    assert by_name.get("tracks", {}).get("status") == "ok"
    assert "cues" not in by_name  # a later phase — genuinely mid-run, not the end


def test_terminal_state_has_current_phase_none(conn, song, session, tiny_song, state_dir):
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(),
    )
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    assert state["current_phase"] is None


# ---------------------------------------------------------------------------
# MICROTUNE Chunk 3: the gated tuning notice rides the warnings channel
# ---------------------------------------------------------------------------
def _tuning_aware_send(*, tuning_system):
    """Wrap the standard fake so an ableton_probe get of song.tuning_system
    returns the given {type,value}; everything else delegates to _make_send_fn."""
    inner = _make_send_fn()

    def send(req, *, read_timeout=None):
        if req.tool == "ableton_probe" and req.action == "get":
            path = req.params.get("path")
            if path == "song.tuning_system":
                return FakeResponse(ok=True, result={"path": path, **tuning_system})
        return inner(req, read_timeout=read_timeout)

    send.call_log = inner.call_log  # type: ignore[attr-defined]
    return send


def _set_tuning_on(conn, song_id):
    from hallucinote.tuning.model import TuningData
    tuning = TuningData(
        name="19-EDO", step_count=19, period_cents=1200.0, reference_note=60,
        step_cents=tuple(round(1200.0 * i / 19, 6) for i in range(1, 20)),
    )
    M.set_song_tuning(
        conn, song_id=song_id,
        tuning_ref="tunings/19-edo.ascl", tuning_data=tuning.to_blob(),
    )


def test_execute_emits_tuning_notices_for_alt_tuned_song(
    conn, song, session, tiny_song, state_dir,
):
    _set_tuning_on(conn, song)
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session, state_dir=state_dir,
        send_fn=_tuning_aware_send(tuning_system={"type": "NoneType", "value": None}),
    )
    # Push still OK; the notices ride the benign warnings channel + the summary.
    assert result.outcome == "ok"
    joined = "\n".join(result.warnings)
    assert "tunings/19-edo.ascl" in joined  # the load instruction names the .ascl
    assert "NO tuning loaded" in joined
    assert "Warnings (push still OK)" in push_execute.format_summary(result)


def test_execute_no_tuning_notice_for_12tet_song(
    conn, song, session, tiny_song, state_dir,
):
    # No tuning set: the notice path returns [] without any probe of tuning_system.
    send_fn = _make_send_fn()
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session, state_dir=state_dir,
        send_fn=send_fn,
    )
    assert all("tuning" not in w.lower() for w in result.warnings)
    probed = [c for c in send_fn.call_log
              if c["tool"] == "ableton_probe"
              and c["params"].get("path") == "song.tuning_system"]
    assert probed == []  # 12-TET path costs no Live round-trip


# ---------------------------------------------------------------------------
# SYN-9F4K — fail loud on an empty-rack load (devices-phase convergence)
# ---------------------------------------------------------------------------


def _rack_song(conn, song, session):
    """A pre-linked track holding an UNLINKED rack whose nested chain carries a
    dialed param. On a fresh `only='devices'` push the rack loads, then the
    convergence pass emits the nested write — the exact shape that cascades when
    the rack comes up empty (the 2026-06-20 repro: AG Techno Kit, 0 chains)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5,
    )
    chain = M.create_device_chain(conn, parent_track_id=tid, position=0)
    rack = M.create_device(
        conn, chain_id=chain, position=1,
        kind="Drum Rack", display_name="AG Techno Kit",
    )
    nested_chain = M.create_device_chain(conn, parent_rack_device_id=rack, position=1)
    nested = M.create_device(
        conn, chain_id=nested_chain, position=1, kind="Simpler", display_name="Kick",
    )
    M.set_device_parameter(
        conn, device_id=nested, name="Volume",
        value_display="-6 dB", value_normalized=0.5,
    )
    return {"rack_id": rack, "nested_id": nested}


def _make_chain_count_send_fn(*, chain_count, model_cascade=False):
    """``_make_send_fn`` + a ``get_device_chains`` answer with a fixed
    ``chain_count`` (and otherwise acks, loads → device_index).

    ``model_cascade``: when True, a ``set_parameter`` whose node descends into a
    chain (``path`` present) — the doomed nested write — returns the real Live
    failure (``IndexError: chain_index … out of range [1, 0]``). With the guard
    working those writes are suppressed and this branch never fires; if the guard
    regressed it WOULD fire, so the test's "no chain_index cascade" assertion is
    meaningful (otherwise the fake would ack the doomed write and hide the bug).
    Also fails ``get_parameters`` on a nested node (the diff's read into a missing
    chain fails in real Live too → the diff keeps the write, then the guard catches
    it) so the re-push path is modeled honestly."""
    base = _make_send_fn()

    def send(req, *, read_timeout=None):
        if req.tool == "ableton_device" and req.action == "get_device_chains":
            base.call_log.append({
                "tool": req.tool, "action": req.action,
                "params_keys": sorted(req.params.keys()),
                "params": dict(req.params), "read_timeout": read_timeout,
            })
            return FakeResponse(ok=True, result={
                "chain_count": chain_count, "chains": [],
            })
        nested = bool((req.params.get("node") or {}).get("path"))
        if model_cascade and req.tool == "ableton_device" and nested and req.action in (
            "set_parameter", "get_parameters",
        ):
            base.call_log.append({
                "tool": req.tool, "action": req.action,
                "params_keys": sorted(req.params.keys()),
                "params": dict(req.params), "read_timeout": read_timeout,
            })
            return FakeResponse(
                ok=False, error="IndexError: chain_index 1 out of range [1, 0]",
            )
        return base(req, read_timeout=read_timeout)

    send.call_log = base.call_log  # type: ignore[attr-defined]
    return send


def test_execute_empty_rack_halts_with_one_error_no_cascade(
    conn, song, session, state_dir,
):
    """A rack that loads with 0 chains while the DB authored nested content halts
    the devices phase on ONE 'preset content did not load' error — the doomed
    nested write is never dispatched (no chain-index-out-of-range cascade)."""
    _rack_song(conn, song, session)
    # model_cascade=True: had the guard NOT suppressed, the nested write would
    # come back with the real chain-index error — so the "no cascade" assertion
    # below actually has teeth.
    send_fn = _make_chain_count_send_fn(chain_count=0, model_cascade=True)
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session, state_dir=state_dir,
        send_fn=send_fn, only="devices",
    )
    assert result.outcome == "partial"
    assert result.phase_halted == "devices"
    # The probe fired against the freshly-loaded rack's live address.
    probes = [c for c in send_fn.call_log if c["action"] == "get_device_chains"]
    assert len(probes) == 1
    assert probes[0]["params"]["track_index"] == 5
    assert probes[0]["params"]["device_index"] == 1
    # The doomed nested write was NEVER dispatched (suppressed, not cascaded).
    set_params = [c for c in send_fn.call_log if c["action"] == "set_parameter"]
    assert set_params == []
    # Exactly one error, naming the real cause — and NO chain-index cascade.
    errors = json.loads((state_dir / ".last-push-errors.json").read_text())["errors"]
    assert len(errors) == 1
    assert "preset content did not load" in errors[0]["error"]
    assert "AG Techno Kit" in errors[0]["error"]
    assert errors[0]["hint"]
    assert all("chain_index" not in e["error"] for e in errors)
    # The summary surfaces the single halt cause.
    assert "preset content did not load" in push_execute.format_summary(result)


def test_execute_repush_empty_rack_halts_in_main_dispatch_not_cascade(
    conn, song, session, state_dir,
):
    """W1 regression: a rack ALREADY linked (a re-push) that STILL loads empty
    re-emits its nested writes in the MAIN dispatch (not the convergence pass,
    which only sees a device loaded this pass). The guard must catch them there
    too, or the cascade returns on every push after the first. Here the rack is
    pre-linked at device_index 1; with no load this pass the rack's name isn't
    available, so the message falls back to its live address."""
    fx = _rack_song(conn, song, session)
    # Pre-link the rack: this is the second push, the device already has a Live
    # index from the first.
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=fx["rack_id"],
        ableton_index=1,
    )
    send_fn = _make_chain_count_send_fn(chain_count=0, model_cascade=True)
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session, state_dir=state_dir,
        send_fn=send_fn, only="devices",
    )
    assert result.outcome == "partial"
    assert result.phase_halted == "devices"
    # No load this pass (already linked); the guard fired in the MAIN dispatch.
    loads = [c for c in send_fn.call_log if c["action"] == "load"]
    assert loads == []
    probes = [c for c in send_fn.call_log if c["action"] == "get_device_chains"]
    assert len(probes) == 1
    # The nested write never dispatched — no cascade on the re-push either.
    set_params = [c for c in send_fn.call_log if c["action"] == "set_parameter"]
    assert set_params == []
    errors = json.loads((state_dir / ".last-push-errors.json").read_text())["errors"]
    assert len(errors) == 1
    assert "preset content did not load" in errors[0]["error"]
    assert all("chain_index" not in e["error"] for e in errors)
    # Address fallback (no load → no name): identifies the rack by its address.
    assert "track index 5" in errors[0]["error"]


def test_execute_populated_rack_dispatches_nested_writes(
    conn, song, session, state_dir,
):
    """The mirror case: when the same rack loads WITH chains, the guard keeps the
    nested writes — they dispatch and the phase completes OK."""
    _rack_song(conn, song, session)
    send_fn = _make_chain_count_send_fn(chain_count=16)
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session, state_dir=state_dir,
        send_fn=send_fn, only="devices",
    )
    assert result.outcome == "ok"
    # The nested write was dispatched (not suppressed).
    set_params = [c for c in send_fn.call_log if c["action"] == "set_parameter"]
    assert len(set_params) == 1
    assert set_params[0]["params"]["parameter_name"] == "Volume"
    # No errors file on a clean push.
    assert not (state_dir / ".last-push-errors.json").exists()


# ---------- SYN-2D9K: orphan-param teaching hint on a set_parameter 404 ----------


def test_orphan_param_hint_fires_on_param_not_found():
    """A set_parameter that 404s on a param the device lacks gets the orphan-cause
    hint (names the stale-orphan-from-class-change cause + the rebuild cure),
    replacing the MCP's misleading value-range hint."""
    h = push_execute._orphan_param_hint(
        tool="ableton_device", action="set_parameter",
        err_msg="parameter 'A Coarse' not found on device 1; available: ['Volume']",
        parameter_name="A Coarse",
    )
    assert h is not None
    assert "stale orphan" in h and "A Coarse" in h and "SYN-2D9K" in h


def test_orphan_param_hint_silent_on_non_orphan_failures():
    """It must NOT fire on a value-range refusal, a different tool/action, or a
    missing error — only on the param-not-found shape of a device set_parameter."""
    f = push_execute._orphan_param_hint
    # A value-range refusal is not the orphan shape.
    assert f(tool="ableton_device", action="set_parameter",
             err_msg="value 5.0 out of range [0, 1]", parameter_name="Volume") is None
    # Wrong tool / wrong action / no error message.
    assert f(tool="ableton_clip", action="set_parameter",
             err_msg="not found", parameter_name=None) is None
    assert f(tool="ableton_device", action="load",
             err_msg="not found", parameter_name=None) is None
    assert f(tool="ableton_device", action="set_parameter",
             err_msg=None, parameter_name="X") is None


# ---------------------------------------------------------------------------
# SYN-8Q3F (c): apply-layer contract drift is a CONTROLLED halt, not a traceback
# ---------------------------------------------------------------------------


def _one_phase_with_novel_key(monkeypatch):
    """Monkeypatch plan_push_song to a single phase whose planner emits a
    ToolCall with a key kind NO apply table declares — the runtime shape of the
    twice-shipped unknown-kind bug class (device_param_override 2026-06-18,
    device_chain_props 2026-06-20). The wire call succeeds; the REAL
    apply_push_results then raises its fail-loud ValueError."""
    from hallucinote.sync import push

    def fake_plan_push_song(conn, *, song_id, session_id, **kwargs):
        def plan_fn():
            plan = push.PushPlan()
            plan.add(push.ToolCall(
                tool="ableton_device",
                args={"action": "set_parameter"},
                key="warp_core:xyz",
                purpose="novel key kind the apply layer does not know",
            ))
            return plan
        return [push.PushPhase(
            name="devices", plan_fn=plan_fn, description="novel-kind fixture",
        )]

    monkeypatch.setattr(push, "plan_push_song", fake_plan_push_song)


def test_unknown_result_kind_halts_phase_controlled_not_traceback(
    conn, song, session, state_dir, monkeypatch,
):
    """A genuinely-unknown result key kind must take the DELIBERATE path:
    phase HALTED with the apply layer's teaching message in the errors file,
    terminal state file written, request closed 'partial', EXIT_PARTIAL —
    never an escaping ValueError (pre-SYN-8Q3F this was a raw traceback with
    no state file and the request row left open; contract artifact V4)."""
    from hallucinote.db import queries as Q

    _one_phase_with_novel_key(monkeypatch)

    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(),
    )  # must NOT raise

    assert result.outcome == "partial"
    assert result.exit_code == push_execute.EXIT_PARTIAL
    assert result.phase_halted == "devices"
    halted = [p for p in result.phases if p.status == "halted"]
    assert [p.name for p in halted] == ["devices"]

    # Terminal state file written (the always-write-state contract held).
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    assert state["outcome"] == "partial"
    assert state["phase_halted"] == "devices"

    # Errors file carries the apply-layer teaching message + the drift hint.
    errors = json.loads((state_dir / ".last-push-errors.json").read_text())
    apply_recs = [e for e in errors["errors"] if e["tool"] == "apply_push_results"]
    assert len(apply_recs) == 1
    assert "unknown push result key kind 'warp_core'" in apply_recs[0]["error"]
    assert "KNOWN_RESULT_KEY_KINDS" in apply_recs[0]["hint"]

    # The request row closed (outcome mirrors the halt) — not left open.
    req = Q.get_latest_request_for_song(conn, song, kind="push")
    assert req["outcome"] == "partial"


def test_unknown_result_kind_records_nothing_for_the_batch(
    conn, song, session, state_dir, monkeypatch,
):
    """The apply transaction rolls the WHOLE batch back on contract drift, so
    no link row from the halted batch may survive (a half-recorded batch would
    make the next push plan against phantom links)."""
    _one_phase_with_novel_key(monkeypatch)
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(),
    )
    links = Q.get_ableton_links_for_session(conn, session)
    assert list(links) == []


def test_known_result_key_kinds_is_the_union_of_the_apply_tables():
    """KNOWN_RESULT_KEY_KINDS is the ONE registry (SYN-8Q3F): exactly the two
    dispatch tables plus the dedicated perform_batch branch — so the static
    emitted-kind guard, the apply dispatch, and the executor hint can never
    disagree about what 'known' means."""
    from hallucinote.sync.push import plan

    assert plan.KNOWN_RESULT_KEY_KINDS == (
        frozenset(plan._LINK_KINDS) | plan._ACK_ONLY_KINDS | {"perform_batch"}
    )
    # Adding an enum-member-equivalent (a new kind) without declaring it can't
    # pass: the registry is DERIVED from the tables, and the static guard in
    # test_push.py checks every planner-emitted kind against those tables.


def test_errors_file_write_failure_still_closes_request(
    conn, song, session, tiny_song, state_dir, monkeypatch,
):
    """SYN-8Q3F review W1: the terminal errors-file write runs before
    close_request; if it raises (disk full / permissions), the request row must
    STILL close with the push's outcome and the terminal state file must
    already be on disk — an errors-file write failure must not reproduce the
    V4 open-request symptom. The write failure itself still propagates (a
    broken state_dir is operator-actionable)."""
    import os as _os

    real_replace = _os.replace

    def failing_replace(src, dst, *a, **kw):
        if str(dst).endswith(".last-push-errors.json"):
            raise OSError(28, "No space left on device (simulated)")
        return real_replace(src, dst, *a, **kw)

    monkeypatch.setattr(push_execute.os, "replace", failing_replace)

    # A per-call failure guarantees error_records is non-empty, so the
    # errors-file write path (the failing one) is exercised.
    bad_send = _make_send_fn(fail_keys={"ableton_clip:create"})
    with pytest.raises(OSError):
        push_execute.execute_push(
            conn=conn, song_id=song, session_id=session,
            state_dir=state_dir, send_fn=bad_send,
        )

    # The request row is CLOSED with the halt outcome, not left open.
    req = Q.get_latest_request_for_song(conn, song, kind="push")
    assert req["outcome"] == "partial"

    # The terminal state file was flushed before the failing write.
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    assert state["outcome"] == "partial"
    assert state["current_phase"] is None  # terminal flush, not a mid-run one


# ---------------------------------------------------------------------------
# Tolerated failures — a refused no-op must not halt a fourteen-phase push
# ---------------------------------------------------------------------------


_DISABLED_ERR = (
    "ableton_device('set_chain_property') failed: RuntimeError: "
    "Value cannot be set, the parameter is disabled"
)


def test_disabled_chain_property_is_tolerated():
    """Live's own 606 Core Kit hi-hat pads carry macro-locked chain mixers.

    Capture read the value, push wrote the identical value back, Live refused,
    and the whole push halted at the devices phase over a change that would
    have changed nothing.
    """
    assert push_execute._is_tolerated_failure(
        tool="ableton_device", action="set_chain_property",
        err_msg=_DISABLED_ERR,
    )


@pytest.mark.parametrize("tool, action, err_msg, why", [
    ("ableton_device", "set_chain_property",
     "value 2.5 out of range [0.0, 1.0]",
     "a value-range refusal is a real defect — the song asks for the impossible"),
    ("ableton_device", "set_chain_property",
     "parameter 'Volume' not found on device",
     "a missing parameter means the device changed under the song"),
    ("ableton_device", "set_parameter",
     _DISABLED_ERR,
     "only the CHAIN-MIXER write is a guaranteed no-op; a disabled device "
     "parameter is not in scope for this tolerance"),
    ("ableton_clip", "create", _DISABLED_ERR,
     "tolerance must be keyed on the tool as well as the message"),
    ("ableton_device", "set_chain_property", None,
     "no error message means no evidence it was the disabled case"),
])
def test_other_failures_are_not_tolerated(tool, action, err_msg, why):
    """The tolerance must stay narrow. A guard that swallows more than the one
    provably-harmless case turns a push from a verifier into a rubber stamp."""
    assert not push_execute._is_tolerated_failure(
        tool=tool, action=action, err_msg=err_msg,
    ), why


# ---------------------------------------------------------------------------
# PSH-ARRPROBE — the first-push silent arrangement no-op
#
# Observed 2026-08-07 against Live 12.4: a brand-new 9-track song pushed into a
# Live set that still held its 4 default scaffold tracks reported
# "OK — all 14 phases completed" with `arrangement: skipped (idempotent)` and an
# EMPTY timeline. Root cause: the arrangement lane probe ran BEFORE the phase
# loop, so it described Live indices 1-4 while the `tracks` phase then created
# the song's tracks at 5-13; every track read as "probe failed" and the planner
# (correctly) refused to clear+fill an unknown lane. Two independent defects:
# the probe ran too early, and the resulting do-nothing reported as clean.
# ---------------------------------------------------------------------------


@dataclass
class _Req:
    """Minimal stand-in for hallucinote_mcp.wire.Request — the fakes here read
    only .tool / .action / .params."""
    tool: str
    action: str
    params: dict


def _make_offset_live_send_fn(*, preexisting_tracks: int = 4):
    """A fake Live set that ALREADY holds ``preexisting_tracks`` tracks (the
    default 1-MIDI/2-MIDI/3-Audio/4-Audio scaffold), so tracks this push creates
    land at indices ``preexisting_tracks + 1 …`` — the geometry of the bug.

    Wraps :func:`_make_send_fn` so arrangement projection / link counters /
    perform batching all behave as in the other execute tests; only
    ``ableton_track`` create+list and ``ableton_return`` list are re-modeled so
    the Live-side track numbering is real rather than a monotonic counter.
    """
    inner = _make_send_fn()
    tracks = [
        {"track_index": i, "name": f"{i}-MIDI", "kind": "midi"}
        for i in range(1, preexisting_tracks + 1)
    ]

    def send(req, *, read_timeout=None):
        if req.tool == "ableton_track" and req.action == "create":
            idx = len(tracks) + 1
            tracks.append({
                "track_index": idx,
                "name": req.params.get("name") or "",
                "kind": req.params.get("kind") or "midi",
            })
            return FakeResponse(ok=True, result={"track_index": idx})
        if req.tool == "ableton_track" and req.action == "list":
            return FakeResponse(
                ok=True, result={"tracks": [dict(t) for t in tracks]},
            )
        if req.tool == "ableton_return" and req.action == "list":
            return FakeResponse(ok=True, result={"returns": []})
        return inner(req, read_timeout=read_timeout)

    send.call_log = inner.call_log  # type: ignore[attr-defined]
    send.live_tracks = tracks  # type: ignore[attr-defined]
    return send


def _probe_arrangement_lanes(send_fn):
    """The engine-side twin of ``push_cli._probe_arrangement_lanes``: re-probe
    the track list, THEN each track's arrangement lane. Returns the thunk, plus
    a list recording each invocation's observed track indices so a test can
    assert WHEN the probe ran."""
    invocations: list[list[int]] = []

    def probe() -> dict[int, list[dict]]:
        resp = send_fn(_Req("ableton_track", "list", {}))
        live_tracks = list((resp.result or {}).get("tracks") or [])
        invocations.append([t["track_index"] for t in live_tracks])
        by_track: dict[int, list[dict]] = {}
        for t in live_tracks:
            r = send_fn(_Req("ableton_clip", "list", {
                "track_index": t["track_index"], "location": "arrangement",
            }))
            if getattr(r, "ok", False):
                by_track[t["track_index"]] = list((r.result or {}).get("clips") or [])
        return by_track

    probe.invocations = invocations  # type: ignore[attr-defined]
    return probe


@pytest.fixture
def offset_song(conn, song, tiny_song):
    """tiny_song + a time signature + one arrangement placement, so the
    arrangement phase has real work."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=tiny_song["track_id"],
        clip_id=tiny_song["clip_id"], start_bar=1.0, end_bar=2.0,
    )
    return tiny_song


def test_arrangement_materializes_when_tracks_land_at_a_live_offset(
    conn, song, session, offset_song, state_dir,
):
    """The bug, end to end: Live already holds 4 tracks, so this push's track
    lands at index 5. With the probe deferred to the arrangement phase, the
    placement materializes — on track 5, not on the pre-push numbering."""
    send = _make_offset_live_send_fn(preexisting_tracks=4)
    probe = _probe_arrangement_lanes(send)

    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
        live_arrangement_clips_by_track=probe,
    )

    assert result.outcome == "ok", result.warnings
    arrangement = next(p for p in result.phases if p.name == "arrangement")
    assert arrangement.status == "ok"
    assert arrangement.calls_ok == 1
    assert arrangement.blocked_reasons == []

    # The DB track is linked at the OFFSET Live index, and that is where the
    # arrangement clip was created.
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="track",
        db_id=offset_song["track_id"],
    ) == 5
    creates = [
        c for c in send.call_log
        if c["tool"] == "ableton_clip" and c["action"] == "create"
        and c["params"].get("location") == "arrangement"
    ]
    assert [c["params"]["track_index"] for c in creates] == [5]


def test_arrangement_probe_runs_after_the_tracks_phase(
    conn, song, session, offset_song, state_dir,
):
    """The structural half: the probe is a THUNK resolved inside the arrangement
    phase, so it sees the tracks the `tracks` phase created. A probe taken any
    earlier describes a different set of Live indices — which is precisely how
    the phase came to skip every track."""
    from hallucinote.sync import push

    send = _make_offset_live_send_fn(preexisting_tracks=4)
    probe = _probe_arrangement_lanes(send)

    # Not called merely by handing it to execute_push / plan_push_song.
    push.plan_push_song(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=probe,
    )
    assert probe.invocations == []

    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
        live_arrangement_clips_by_track=probe,
    )
    # Probed exactly once, and by then the song's track (index 5) existed.
    assert len(probe.invocations) == 1
    assert 5 in probe.invocations[0]


def test_stale_pre_tracks_probe_reports_incomplete_not_ok(
    conn, song, session, offset_song, state_dir,
):
    """The reporting half, driven by the exact stale map the bug produced: a
    dict covering only Live's pre-push tracks (1-4). The planner still refuses
    to clear+fill an unknown lane — that part was always right — but the run
    must now say so: INCOMPLETE, non-zero exit, and never
    'skipped (idempotent)'."""
    send = _make_offset_live_send_fn(preexisting_tracks=4)
    stale = {i: [] for i in range(1, 5)}  # probed before the tracks phase

    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
        live_arrangement_clips_by_track=stale,
    )

    assert result.outcome == "incomplete"
    assert result.exit_code == push_execute.EXIT_PARTIAL
    assert result.phase_halted is None  # a gap, not a halt
    arrangement = next(p for p in result.phases if p.name == "arrangement")
    assert arrangement.status == "incomplete"
    assert any(
        "the per-track probe failed" in r for r in arrangement.blocked_reasons
    ), arrangement.blocked_reasons
    # Later phases still ran — an undeterminable phase does not stop the push.
    assert all(p.status != "pending" for p in result.phases)

    text = push_execute.format_summary(result)
    assert "skipped (idempotent)" not in text
    assert "INCOMPLETE" in text
    assert "the per-track probe failed" in text
    # And it must not be filed under the benign channel.
    assert not any("per-track probe failed" in w for w in result.warnings)


def test_incomplete_phase_state_file_carries_status_and_reasons(
    conn, song, session, offset_song, state_dir,
):
    """`.last-push-state.json` is the machine-readable half of the same
    contract: a reader must be able to tell a failed-probe skip from an
    idempotent one without parsing prose."""
    send = _make_offset_live_send_fn(preexisting_tracks=4)
    push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
        live_arrangement_clips_by_track={i: [] for i in range(1, 5)},
    )
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    assert state["outcome"] == "incomplete"
    by_name = {p["name"]: p for p in state["phases"]}
    assert by_name["arrangement"]["status"] == "incomplete"
    assert by_name["arrangement"]["blocked_reasons"]
    # A genuinely empty phase stays a clean skip and carries no reasons.
    assert by_name["tempo_map"]["status"] == "skipped"
    assert "blocked_reasons" not in by_name["tempo_map"]


def test_genuine_empty_arrangement_still_reports_a_clean_skip(
    conn, song, session, tiny_song, state_dir,
):
    """The other side of the split: a song with no arrangement rows has nothing
    to do, and that is still a clean, zero-exit skip. The new status must not
    turn every quiet phase into a scary one."""
    send = _make_offset_live_send_fn(preexisting_tracks=4)
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
        live_arrangement_clips_by_track=_probe_arrangement_lanes(send),
    )
    assert result.outcome == "ok"
    assert result.exit_code == push_execute.EXIT_OK
    arrangement = next(p for p in result.phases if p.name == "arrangement")
    assert arrangement.status == "skipped"
    assert "skipped (nothing to push)" in push_execute.format_summary(result)


def test_partially_blocked_arrangement_never_reports_clean(
    conn, song, session, offset_song, state_dir,
):
    """A second track whose lane IS probed materializes; the unprobed one does
    not. Pre-fix this reported `[ok] arrangement 1/1 ok`, hiding a track that
    never got built. Here the post-phase integrity assert catches the
    un-materialized placement and halts — the halt is honest, and it must NOT
    swallow the planner's reason for skipping (the state file and the summary
    both still name the unprobed lane)."""
    tid2 = M.create_track(
        conn, song_id=song, track_index=2, name="Bass", kind="midi",
    )
    cid2 = M.create_clip(
        conn, track_id=tid2, slot=1, length_beats=4.0, name="bass-loop",
    )
    M.insert_notes(conn, clip_id=cid2, notes=[
        {"pitch": 36, "velocity": 100, "start_beats": 0.0, "duration_beats": 1.0},
    ])
    M.add_arrangement_clip(
        conn, song_id=song, track_id=tid2, clip_id=cid2,
        start_bar=1.0, end_bar=2.0,
    )
    send = _make_offset_live_send_fn(preexisting_tracks=4)

    # Probe only the FIRST song track (index 5); track 6's lane stays unknown.
    def half_probe() -> dict[int, list[dict]]:
        return {5: []}

    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
        live_arrangement_clips_by_track=half_probe,
    )
    arrangement = next(p for p in result.phases if p.name == "arrangement")
    assert arrangement.calls_ok == 1  # the probed track DID materialize
    assert result.exit_code != push_execute.EXIT_OK
    assert result.outcome == "partial"
    assert result.phase_halted == "arrangement"
    assert any(
        "Live index 6" in r for r in arrangement.blocked_reasons
    ), arrangement.blocked_reasons
    text = push_execute.format_summary(result)
    assert "Live index 6" in text
    state = json.loads((state_dir / ".last-push-state.json").read_text())
    by_name = {p["name"]: p for p in state["phases"]}
    assert by_name["arrangement"]["blocked_reasons"]
