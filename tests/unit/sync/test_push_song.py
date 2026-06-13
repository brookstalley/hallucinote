"""Tests for W4-D: ``plan_push_song`` master orchestrator + ``plan_push_clips``.

The orchestrator returns thirteen ordered :class:`PushPhase` objects, each
carrying a ``plan_fn`` thunk that produces a fresh ``PushPlan`` from
current DB state. Tests pin:

  - phase identity (count, names, order)
  - the W4-A ordering invariant: envelopes BEFORE arrangement
  - the cue invariant: cues AFTER arrangement
  - thunk semantics: ``plan_fn()`` re-reads ``ableton_links`` each call
  - end-to-end drive: a realistic fixture, fake-applying results between
    phases, produces the expected calls + final link state
  - idempotency: a second full pass produces empty plans
  - ``plan_push_clips`` aggregates per-clip plans with prefixed warnings
    and inherits the W3-C strict precondition.
"""
from __future__ import annotations

import dataclasses

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push


# Mirror of the apply-side dispatch table for fake-apply result synthesis.
# When a key kind needs a link, the fake result carries the corresponding
# index field; ack-only kinds get an empty result. Indexes are monotonic
# per kind so consecutive calls in the same plan don't collide.
_LINK_FIELDS: dict[str, str] = {
    "track": "track_index",
    "return": "return_index",
    "clip": "clip_index",
    "device": "device_index",
    "arrangement_clip": "arrangement_clip_index",
    "envelope": "envelope_index",
}


def _fake_apply(
    conn,
    plan: push.PushPlan,
    *,
    session_id: str,
    counters: dict[str, int],
) -> list[dict]:
    """Synthesize agent-success results for every call in ``plan`` and
    write them back via :func:`push.apply_push_results`. ``counters``
    is shared across phases so monotonic indexes don't collide across
    successive applies."""
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
    push.apply_push_results(conn, results, session_id=session_id)
    return results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "psong.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


# ---------------------------------------------------------------------------
# Phase identity
# ---------------------------------------------------------------------------


def test_plan_push_song_returns_fourteen_phases(conn, song, session):
    phases = push.plan_push_song(conn, song_id=song, session_id=session)
    assert len(phases) == 14


def test_plan_push_song_phase_names_and_order(conn, song, session):
    """The fourteen phase names are the contract between the planner and the
    push skill — renaming any breaks the skill prose. Order is
    load-bearing (see plan_push_song docstring). ``scenes`` runs
    immediately before ``clips`` (SYN-4P2D): session clip slots are scene
    rows, so the set must have enough scenes before clip-create. ``routing``
    runs after ``mix`` and before ``devices`` (RTE-1K9T / D5).
    ``device_sidechain`` runs immediately after ``devices`` (SDC-7K3M): a
    device's sidechain input routing can only be set once the device exists."""
    phases = push.plan_push_song(conn, song_id=song, session_id=session)
    assert [p.name for p in phases] == [
        "tempo_map",
        "time_signature_map",
        "tracks",
        "returns",
        "scenes",
        "clips",
        "mix",
        "devices",
        "routing",
        "device_sidechain",
        "envelopes",
        "performed_automation",
        "arrangement",
        "cues",
    ]


def test_plan_push_song_scenes_phase_precedes_clips(conn, song, session):
    """SYN-4P2D invariant: the ``scenes`` phase must run before ``clips``.
    Session clip slots ARE scene rows — a clip-create into slot N requires
    the set to have at least N scenes, so the provisioning pre-pass must
    precede the clip-create phase or the first push of a song with more
    sections than the set has scenes hits a raw per-clip IndexError."""
    phases = push.plan_push_song(conn, song_id=song, session_id=session)
    names = [p.name for p in phases]
    assert names.index("scenes") < names.index("clips")


def test_plan_push_song_routing_phase_after_devices(conn, song, session):
    """RTE-1K9T / fresh-push fix: the ``routing`` phase runs after ``mix`` AND
    after ``devices``. A MIDI track exposes *audio* output routing — the only
    kind that can target an audio submaster bus like PRE-MAIN — only once an
    instrument is loaded, so ``devices`` must precede ``routing`` or a fresh
    push fails ('PRE-MAIN not in available output routing types'). Routing also
    needs every track linked (created in the ``tracks`` phase, far earlier)."""
    phases = push.plan_push_song(conn, song_id=song, session_id=session)
    names = [p.name for p in phases]
    assert names.index("mix") < names.index("devices") < names.index("routing")


def test_plan_push_song_envelopes_phase_precedes_arrangement(conn, song, session):
    """W4-A invariant: ``duplicate_to_arrangement`` is a snapshot copy,
    so mixer/pan/send/device_parameter envelopes must be emitted on the
    session clip BEFORE the arrangement runs. Pin this ordering — a
    future reorder that puts arrangement before envelopes would
    silently lose all snapshot-copied envelopes."""
    phases = push.plan_push_song(conn, song_id=song, session_id=session)
    names = [p.name for p in phases]
    assert names.index("envelopes") < names.index("arrangement")


def test_plan_push_song_cues_phase_follows_arrangement(conn, song, session):
    """Live's ``set_or_delete_cue`` is clamped to
    ``[0, song.last_event_time]``. Cues emitted before the arrangement
    exists in Live get rejected. The plan_push_cue_points docstring
    documents this; the orchestrator enforces it via phase order."""
    phases = push.plan_push_song(conn, song_id=song, session_id=session)
    names = [p.name for p in phases]
    assert names.index("cues") > names.index("arrangement")


def test_plan_push_song_each_phase_has_description(conn, song, session):
    """Descriptions surface in the push skill's progress reporting.
    None being empty catches a copy-paste regression."""
    phases = push.plan_push_song(conn, song_id=song, session_id=session)
    for p in phases:
        assert p.description, f"phase {p.name!r} missing description"


def test_push_phase_is_frozen(conn, song, session):
    """PushPhase is a contract — mutating it post-construction would
    let a phase get re-pointed silently. Frozen dataclass raises
    ``FrozenInstanceError`` on field assignment."""
    phases = push.plan_push_song(conn, song_id=song, session_id=session)
    with pytest.raises(dataclasses.FrozenInstanceError):
        phases[0].name = "renamed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Thunk semantics
# ---------------------------------------------------------------------------


def test_phase_plan_fn_reflects_current_db_state(conn, song, session):
    """The thunk pattern is the load-bearing reason ``plan_push_song``
    returns ``list[PushPhase]`` rather than ``list[PushPlan]``: later
    phases must re-read ``ableton_links`` after earlier-phase results
    apply. Verify that calling the same phase's ``plan_fn`` twice with
    a link write in between produces different output."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    phases = push.plan_push_song(conn, song_id=song, session_id=session)
    tracks_phase = next(p for p in phases if p.name == "tracks")

    # First call: track unlinked → one create call.
    plan_a = tracks_phase.plan_fn()
    assert len(plan_a.calls) == 1
    assert plan_a.calls[0].args["action"] == "create"

    # Link the track, re-call the SAME thunk: now skipped.
    track_db_id = plan_a.calls[0].key.partition(":")[2]
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track_db_id,
        ableton_index=1,
    )
    plan_b = tracks_phase.plan_fn()
    assert plan_b.calls == []


# ---------------------------------------------------------------------------
# Empty-song behavior
# ---------------------------------------------------------------------------


def test_empty_song_each_phase_plans_cleanly(conn, song, session):
    """Empty song: every phase's plan_fn runs without raising, each
    plan is either empty or carries an informational warn. Pin this so
    the skill can drive an empty song without special-casing."""
    phases = push.plan_push_song(conn, song_id=song, session_id=session)
    for phase in phases:
        plan = phase.plan_fn()
        assert isinstance(plan, push.PushPlan)
        # Either empty-with-warn or fully empty — never raises.


# ---------------------------------------------------------------------------
# End-to-end drive
# ---------------------------------------------------------------------------


@pytest.fixture
def filled_song(conn, song, session):
    """A modest song with content for every phase:
    - tempo + time signature (1 point each)
    - 2 tracks (drums + bass)
    - 1 return (Reverb)
    - 1 clip per track (with a note each)
    - 1 arrangement_clip per session clip covering [bar 1, bar 3] = beats [0, 8]
    - 1 send drums → Reverb
    - 1 cue point at bar 1
    - 1 mixer_volume envelope on drums covering beats [0, 4]
    """
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

    M.set_send_level(
        conn, from_track_id=drums, to_return_id=reverb, level=0.4,
    )

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
        "envelope_id": eid,
    }


def test_end_to_end_drive_links_every_entity(conn, song, session, filled_song):
    """Drive all thirteen phases with fake-applied results between each.
    Verifies the contract: each phase, given that prior phases' results
    applied, produces a clean plan that strict-link-precondition planners
    accept without raising. Pin the post-drive link state to detect
    apply-side regressions."""
    phases = push.plan_push_song(conn, song_id=song, session_id=session)
    counters: dict[str, int] = {}

    emitted_per_phase: dict[str, int] = {}
    for phase in phases:
        plan = phase.plan_fn()
        emitted_per_phase[phase.name] = len(plan.calls)
        _fake_apply(conn, plan, session_id=session, counters=counters)

    # Phase emission shape — every emit-bearing phase produced calls.
    assert emitted_per_phase["tempo_map"] == 1
    assert emitted_per_phase["time_signature_map"] == 1
    assert emitted_per_phase["tracks"] == 2          # drums, bass
    assert emitted_per_phase["returns"] == 1         # reverb
    # scenes: one ensure_count call (both clips sit at slot 1 → max_slot=1).
    assert emitted_per_phase["scenes"] == 1
    assert emitted_per_phase["clips"] == 2           # one per track
    # mix emits: 2 tracks × 6 mixer fields are default-None so they're
    # skipped — only set values emit. The fixture sets no track/return
    # mixer values explicitly, so only the send (one call) emits.
    assert emitted_per_phase["mix"] >= 1
    # devices: fixture has no device chains, so 0 calls (warn-only).
    assert emitted_per_phase["devices"] == 0
    assert emitted_per_phase["envelopes"] == 1       # the mixer_volume
    assert emitted_per_phase["arrangement"] == 2     # one per arr_clip
    assert emitted_per_phase["cues"] == 1            # batched single call

    # Final link state pins what apply_push_results recorded for each kind.
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=filled_song["drums_id"],
    ) is not None
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=filled_song["bass_id"],
    ) is not None
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="return", db_id=filled_song["reverb_id"],
    ) is not None
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="clip", db_id=filled_song["drums_clip_id"],
    ) is not None
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="clip", db_id=filled_song["bass_clip_id"],
    ) is not None


def test_end_to_end_drive_idempotent_on_second_pass(
    conn, song, session, filled_song,
):
    """After a full successful push, every link prereq is satisfied.
    A second full pass should produce per-phase plans that emit ZERO
    create/load calls (everything already linked) — only the
    ack-bearing emit phases (mix/envelopes/arrangement/cues/tempo/sig)
    re-emit. ``apply_push_results`` is safe to re-run because
    link writes use INSERT-OR-REPLACE semantics."""
    phases = push.plan_push_song(conn, song_id=song, session_id=session)
    counters: dict[str, int] = {}
    for phase in phases:
        _fake_apply(conn, phase.plan_fn(), session_id=session, counters=counters)

    # Second pass: re-fetch fresh phases (same conn / session).
    phases2 = push.plan_push_song(conn, song_id=song, session_id=session)
    second_pass: dict[str, list[push.ToolCall]] = {}
    for phase in phases2:
        second_pass[phase.name] = phase.plan_fn().calls

    # Create-phase planners (tracks, returns, clips) are idempotent —
    # all entities already linked, so zero calls emitted.
    assert second_pass["tracks"] == []
    assert second_pass["returns"] == []
    # clips: every clip already linked → replace_notes (not create).
    # Each existing clip emits exactly one replace_notes call.
    assert all(c.args["action"] == "replace_notes" for c in second_pass["clips"])
    assert len(second_pass["clips"]) == 2


# ---------------------------------------------------------------------------
# plan_push_clips (per-song clip aggregator)
# ---------------------------------------------------------------------------


def test_plan_push_clips_aggregates_one_call_per_clip(conn, song, session):
    """One per-clip plan combined into a single song-level plan, with
    every call/warn carried forward."""
    track = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=1,
    )
    c1 = M.create_clip(conn, track_id=track, slot=1, length_beats=4.0, name="a")
    c2 = M.create_clip(conn, track_id=track, slot=2, length_beats=4.0, name="b")
    plan = push.plan_push_clips(conn, song_id=song, session_id=session)
    keys = sorted(c.key for c in plan.calls)
    assert keys == sorted([f"clip:{c1}", f"clip:{c2}"])


def test_plan_push_clips_prefixes_per_clip_warnings(
    conn, song, session, monkeypatch,
):
    """Aggregator prefixes per-clip warnings with the clip name so the
    merged plan stays diagnosable. ``plan_push_clip`` emits no notes
    on the happy path today, so we monkeypatch it to inject a note
    and verify the prefix wrapper actually fires."""
    track = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=1,
    )
    c = M.create_clip(conn, track_id=track, slot=1, length_beats=4.0, name="loop_a")

    real = push.plan_push_clip

    def fake(conn, *, clip_id, session_id):
        sub = real(conn, clip_id=clip_id, session_id=session_id)
        sub.warn("synthetic note")
        return sub

    monkeypatch.setattr(push, "plan_push_clip", fake)

    plan = push.plan_push_clips(conn, song_id=song, session_id=session)
    assert plan.notes == ["[loop_a] synthetic note"]
    assert len(plan.calls) == 1


def test_plan_push_clips_raises_when_track_unlinked(conn, song, session):
    """Inherits the W3-C strict contract from ``plan_push_clip``. A
    silent skip here would leave Live missing clips with no signal."""
    track = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    M.create_clip(conn, track_id=track, slot=1, length_beats=4.0, name="loop")
    with pytest.raises(ValueError, match="plan_push_song_tracks.*first"):
        push.plan_push_clips(conn, song_id=song, session_id=session)


def test_plan_push_clips_empty_song_warns(conn, song, session):
    """No clips → no-op warn, not an empty plan with empty notes (so
    the caller can distinguish 'ran cleanly with nothing to do')."""
    plan = push.plan_push_clips(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("no clips" in n for n in plan.notes), plan.notes


def test_plan_push_clip_refuses_audio_clip_loudly(conn, song, session):
    """CLP-AUD1: a kind='audio' clip must never emit the MIDI create —
    warn (naming CLP-AUD2 + authored-but-not-synced) and emit no calls."""
    track = M.create_track(
        conn, song_id=song, track_index=1, name="Stems", kind="audio",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=1,
    )
    cid = M.create_audio_clip(
        conn, track_id=track, slot=1, length_beats=16.0,
        audio_file="assets/gtr.wav", name="gtr",
    )
    plan = push.plan_push_clip(conn, clip_id=cid, session_id=session)
    assert plan.calls == []
    assert len(plan.notes) == 1
    note = plan.notes[0]
    assert "CLP-AUD2" in note
    assert "authored but not synced" in note


def test_plan_push_clips_audio_skip_leaves_midi_siblings_unchanged(
    conn, song, session
):
    """Regression: the audio refusal must not perturb the MIDI emission —
    the sibling MIDI clip still gets its kind='midi' create call, and the
    audio warn rides through the aggregator with the clip-name prefix."""
    midi_track = M.create_track(
        conn, song_id=song, track_index=1, name="T", kind="midi",
    )
    audio_track = M.create_track(
        conn, song_id=song, track_index=2, name="Stems", kind="audio",
    )
    for tid, idx in ((midi_track, 1), (audio_track, 2)):
        M.link_db_to_ableton(
            conn, session_id=session, db_kind="track", db_id=tid,
            ableton_index=idx,
        )
    mc = M.create_clip(
        conn, track_id=midi_track, slot=1, length_beats=4.0, name="loop_a",
    )
    M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=16.0,
        audio_file="assets/gtr.wav", name="gtr",
    )
    plan = push.plan_push_clips(conn, song_id=song, session_id=session)
    assert [c.key for c in plan.calls] == [f"clip:{mc}"]
    assert plan.calls[0].args["action"] == "create"
    assert plan.calls[0].args["kind"] == "midi"
    assert any(n.startswith("[gtr] ") and "CLP-AUD2" in n for n in plan.notes)


def test_plan_push_arrangement_names_audio_kind_in_unlinked_skip(
    conn, song, session
):
    """An arrangement placement of an audio clip can't reach Live until
    CLP-AUD2; the skip-warn must name the real blocker, not loop the
    caller back to the clip-create phase (which refuses audio clips)."""
    track = M.create_track(
        conn, song_id=song, track_index=1, name="Stems", kind="audio",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=1,
    )
    cid = M.create_audio_clip(
        conn, track_id=track, slot=1, length_beats=16.0,
        audio_file="assets/gtr.wav", name="gtr",
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=cid,
        start_bar=1.0, end_bar=5.0,
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("kind='audio'" in n and "CLP-AUD2" in n for n in plan.notes)


# ---------------------------------------------------------------------------
# plan_push_scenes (SYN-4P2D — scene-provisioning pre-pass)
# ---------------------------------------------------------------------------


def test_plan_push_scenes_emits_ensure_count_at_max_slot(conn, song, session):
    """The scenes phase emits ONE ensure_count call whose count is the
    highest 1-based clip slot over the song's session clips — the exact
    upper bound the clips phase will address. Deriving from clip rows (not
    re-deriving from sections) keeps scenes and clips reading one source."""
    track = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    # Clips at slots 1, 5, 9 → max_slot = 9 (a >8-section song into a default
    # 8-scene set: the exact SYN-4P2D failure case).
    for slot in (1, 5, 9):
        M.create_clip(conn, track_id=track, slot=slot, length_beats=4.0, name=f"s{slot}")
    plan = push.plan_push_scenes(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_scene"
    assert call.args == {"action": "ensure_count", "count": 9}
    assert call.key == "scene:ensure"


def test_plan_push_scenes_empty_song_warns_not_bare_empty(conn, song, session):
    """No session clips → no ToolCall, but a warn (NOT a bare-empty plan) —
    matching the documented per-phase warn-not-bare-empty convention so the
    skill can distinguish 'ran cleanly with nothing to do' from 'phase
    skipped', exactly like the sibling plan_push_clips empty path. Pins
    review W2 as a contract, not just prose."""
    plan = push.plan_push_scenes(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("no session clips" in n for n in plan.notes), plan.notes
