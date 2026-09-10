"""Capture must not ingest Live's brand-new-set scaffold as song content.

Live's default set ships four tracks (``1-MIDI`` / ``2-MIDI`` / ``3-Audio`` /
``4-Audio``). Captured, they become permanent song state: the push-side
``probe_and_link`` matches them by name, so they never reach
``unmatched_live_tracks``, the default-scaffold classifier goes silent, and the
"delete the default scaffold?" offer can never fire again — the link state
never converges across capture -> replay -> push rounds.

The predicate is deliberately narrower than the push side's. Push judges only
tracks that are already unmatched, so a canonical NAME is proof enough there;
capture judges every track in the set, so a scaffold slot the user has CLAIMED
(an instrument on ``2-MIDI``, a clip on ``3-Audio``) has to survive.

Synthetic fixtures only (the convention for tests/unit/capture/): the fake
``probe`` stands in for a running Live + bridge.
"""
from __future__ import annotations

import pytest

from hallucinote import capture

from hallucinote.capture import (
    assemble_snapshot_via_probes,
    is_untouched_default_scaffold_track,
    replay_capture,
)
from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "scaffold.db")
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Fake Live: a set described as a list of track specs
# ---------------------------------------------------------------------------


def _track(name, kind="midi", devices=(), session_clips=0, arrangement_clips=0,
           sends=None):
    return {
        "name": name, "kind": kind, "devices": list(devices),
        "session_clips": session_clips, "arrangement_clips": arrangement_clips,
        "sends": dict(sends or {}),
    }


def _instrument(name="Analog"):
    return {"device_index": 1, "name": name, "class_name": name,
            "class_display_name": name, "is_active": True}


class _FakeLive:
    """Probe transport over a static track list. Records every call so a test
    can assert which probes capture did (and did NOT) issue."""

    def __init__(self, tracks, returns=()):
        self.tracks = list(tracks)
        self.returns = list(returns)
        self.calls: list[tuple[str, str, dict]] = []

    def live_tracks(self):
        """The shape ``probe_and_link`` takes — Live's own 1-based indexes."""
        return [
            {"track_index": i, "name": t["name"], "kind": t["kind"]}
            for i, t in enumerate(self.tracks, start=1)
        ]

    def live_returns(self):
        return [
            {"return_index": r["return_index"], "name": r["name"]}
            for r in self.returns
        ]

    def _return(self, return_index):
        for r in self.returns:
            if r["return_index"] == return_index:
                return r
        raise AssertionError(f"no return at {return_index}")

    def __call__(self, tool, action, **params):
        self.calls.append((tool, action, params))
        if (tool, action) == ("ableton_session", "info"):
            return {
                "tempo": 120.0,
                "signature": {"numerator": 4, "denominator": 4},
                "master": {"volume": 0.85, "panning": 0.0},
                "track_count": len(self.tracks),
                "return_count": len(self.returns),
            }
        if (tool, action) == ("ableton_return", "list"):
            return {"returns": [
                {"return_index": r["return_index"], "name": r["name"]}
                for r in self.returns
            ]}
        if (tool, action) == ("ableton_return", "info"):
            r = self._return(params["return_index"])
            return {"name": r["name"], "volume": 0.85, "panning": 0.0,
                    "color": r.get("color")}
        if (tool, action) == ("ableton_track", "info"):
            t = self.tracks[params["track_index"] - 1]
            return {
                "track_index": params["track_index"], "name": t["name"],
                "kind": t["kind"], "volume": 0.85, "panning": 0.0,
                "mute": False, "solo": False, "arm": False,
            }
        if (tool, action) == ("ableton_track", "get_sends"):
            t = self.tracks[params["track_index"] - 1]
            return {"sends": [
                {"return_name": name, "value": value}
                for name, value in t.get("sends", {}).items()
            ]}
        if (tool, action) == ("ableton_clip", "list"):
            t = self.tracks[params["track_index"] - 1]
            if params["location"] == "session":
                # Live reports session slots dense: empty ones are flagged.
                return {"clips": [
                    {"clip_index": i, "empty": i > t["session_clips"]}
                    for i in range(1, 9)
                ]}
            return {"clips": [
                {"arrangement_clip_index": i, "name": f"clip {i}",
                 "start_beats": 0.0, "length": 4.0, "muted": False,
                 "note_count": 1, "is_audio": False}
                for i in range(1, t["arrangement_clips"] + 1)
            ]}
        if (tool, action) == ("ableton_device", "list"):
            if params.get("master"):
                return {"devices": []}
            if "return_index" in params:
                return {"devices": self._return(params["return_index"])["devices"]}
            return {"devices": self.tracks[params["track_index"] - 1]["devices"]}
        if (tool, action) == ("ableton_device", "get_parameters"):
            # Only a return that declares `params` reports a dialed one; the
            # snapshot's default filter drops anything sitting at its default,
            # so an undialed device comes back with an empty params_dialed map.
            ri = (params.get("node") or {}).get("parent", {}).get("index")
            kind = (params.get("node") or {}).get("parent", {}).get("kind")
            if kind == "return":
                dialed = self._return(ri).get("params") or {}
                return {"parameters": [
                    {"name": name, "value": value, "default_value": 0.0,
                     "value_display": str(value), "min": 0.0, "max": 1.0,
                     "is_enum": False}
                    for name, value in dialed.items()
                ]}
            return {"parameters": []}
        if (tool, action) == ("ableton_device", "get_input_routing"):
            return {"has_input_routing": False}
        raise AssertionError(f"unrouted probe {tool}.{action} {params}")


_SCAFFOLD = [
    _track("1-MIDI"), _track("2-MIDI"),
    _track("3-Audio", kind="audio"), _track("4-Audio", kind="audio"),
]


def _names(snapshot):
    return [t["name"] for t in snapshot["tracks"]]


# ---------------------------------------------------------------------------
# The predicate
# ---------------------------------------------------------------------------


def test_predicate_untouched_canonical_track_is_scaffold():
    assert is_untouched_default_scaffold_track({"name": "3-Audio"}, has_clips=False)


def test_predicate_non_canonical_name_is_never_scaffold():
    """A named track is the song's, however empty it is."""
    assert not is_untouched_default_scaffold_track({"name": "Drums"}, has_clips=False)


def test_predicate_is_case_sensitive_like_the_push_side():
    """Live's defaults are exact-cased; '1-midi' is a deliberate rename."""
    assert not is_untouched_default_scaffold_track({"name": "1-midi"}, has_clips=False)


def test_predicate_a_device_claims_a_scaffold_track():
    assert not is_untouched_default_scaffold_track(
        {"name": "2-MIDI", "devices": [_instrument()]}, has_clips=False,
    )


def test_predicate_a_clip_claims_a_scaffold_track():
    """The case a name-only predicate would get wrong: an empty-chain audio
    track the user has dropped a clip onto is song content."""
    assert not is_untouched_default_scaffold_track({"name": "3-Audio"}, has_clips=True)


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def test_untouched_scaffold_never_enters_the_snapshot():
    live = _FakeLive(_SCAFFOLD + [_track("Drums", devices=[_instrument()])])
    assert _names(assemble_snapshot_via_probes(live)) == ["Drums"]


def test_capturing_a_pristine_default_set_yields_no_tracks():
    assert assemble_snapshot_via_probes(_FakeLive(_SCAFFOLD))["tracks"] == []


def test_scaffold_track_carrying_a_device_survives_capture():
    """A claimed slot is song content — the user dropped an instrument on it."""
    live = _FakeLive([
        _track("1-MIDI"),
        _track("2-MIDI", devices=[_instrument("Wavetable")]),
        _track("3-Audio", kind="audio"), _track("4-Audio", kind="audio"),
    ])
    snap = assemble_snapshot_via_probes(live)
    assert _names(snap) == ["2-MIDI"]
    assert snap["tracks"][0]["devices"][0]["name"] == "Wavetable"


def test_scaffold_track_carrying_a_session_clip_survives_capture():
    live = _FakeLive([
        _track("1-MIDI"), _track("2-MIDI"),
        _track("3-Audio", kind="audio", session_clips=1),
        _track("4-Audio", kind="audio"),
    ])
    assert _names(assemble_snapshot_via_probes(live)) == ["3-Audio"]


def test_scaffold_track_carrying_an_arrangement_clip_survives_capture():
    """Session slots can all be empty while the arrangement holds the take."""
    live = _FakeLive([
        _track("1-MIDI", arrangement_clips=1),
        _track("2-MIDI"), _track("3-Audio", kind="audio"),
        _track("4-Audio", kind="audio"),
    ])
    assert _names(assemble_snapshot_via_probes(live)) == ["1-MIDI"]


def test_surviving_tracks_are_densely_renumbered():
    """`create_track` upserts on (song, track_index), so a snapshot numbered
    around the scaffold would replay the same song track into a second row
    once the scaffold is deleted."""
    live = _FakeLive(_SCAFFOLD + [_track("Bass"), _track("Keys")])
    snap = assemble_snapshot_via_probes(live)
    assert [(t["index"], t["name"]) for t in snap["tracks"]] == [(1, "Bass"), (2, "Keys")]


def test_named_tracks_are_never_clip_probed():
    """The clip listing is the costly half of the predicate — it must not turn
    into two extra probes per track on an ordinary set."""
    live = _FakeLive([_track("Drums"), _track("Bass")])
    assemble_snapshot_via_probes(live)
    assert [c for c in live.calls if c[0] == "ableton_clip"] == []


# ---------------------------------------------------------------------------
# The loop: capture -> replay -> probe-and-link, round after round
# ---------------------------------------------------------------------------


def _round(conn, live, *, song_name, session_id):
    """One capture -> replay -> probe-and-link round against the same set."""
    snapshot = assemble_snapshot_via_probes(live)
    replay_capture(conn, snapshot, song_name=song_name)
    song_id = Q.get_song_by_name(conn, song_name)["id"]
    return push.probe_and_link(
        conn, song_id=song_id, session_id=session_id,
        live_tracks=live.live_tracks(), live_returns=[],
    )


def _links(conn, session_id):
    return sorted(
        (link["db_kind"], link["db_id"], link["ableton_index"])
        for link in Q.get_ableton_links_for_session(conn, session_id)
    )


def test_the_loop_converges_once_the_offered_cleanup_is_accepted(conn):
    """The headline: capture, take the cleanup the classifier offers, and the
    next round has nothing left to do.

    Ingesting the scaffold is what breaks this. Those four tracks become DB
    rows, so once Live's copies are gone every later round reports them as
    ``unmatched_db_tracks`` and push re-creates them — the set and the DB chase
    each other forever."""
    live = _FakeLive(_SCAFFOLD + [_track("Drums", devices=[_instrument()])])
    song_id = M.create_song(conn, name="loop")
    session_id = M.create_ableton_session(conn, song_id=song_id, name="draft")

    first = _round(conn, live, song_name="loop", session_id=session_id)
    assert first.default_scaffold_unmatched_tracks  # cleanup was offered

    # The operator accepts: Live deletes the scaffold, "Drums" slides to 1.
    live.tracks = [t for t in live.tracks if t["name"] == "Drums"]

    second = _round(conn, live, song_name="loop", session_id=session_id)
    assert second.unmatched_db_tracks == []   # nothing for push to re-create
    assert second.unmatched_live_tracks == []  # nothing left to clean up
    assert second.default_scaffold_unmatched_tracks == []

    # Converged: a further round against the settled set moves no link at all.
    after_second = _links(conn, session_id)
    third = _round(conn, live, song_name="loop", session_id=session_id)
    assert _links(conn, session_id) == after_second
    assert third.matched_tracks == second.matched_tracks
    assert third.unlinked_stale_tracks == []


def test_the_cleanup_classifier_still_sees_the_scaffold_after_a_capture(conn):
    """The point of excluding the scaffold: it stays UNMATCHED, so the
    default-scaffold classifier keeps offering to delete it."""
    live = _FakeLive(_SCAFFOLD + [_track("Drums", devices=[_instrument()])])
    song_id = M.create_song(conn, name="offer")
    session_id = M.create_ableton_session(conn, song_id=song_id, name="draft")

    result = _round(conn, live, song_name="offer", session_id=session_id)

    assert [t["name"] for t in result.default_scaffold_unmatched_tracks] == [
        "1-MIDI", "2-MIDI", "3-Audio", "4-Audio",
    ]
    assert [m["name"] for m in result.matched_tracks] == ["Drums"]


def test_cleanup_plan_can_delete_the_scaffold_a_capture_has_seen(conn):
    """End of the loop: the unmatched scaffold reaches the cleanup planner and
    comes back deletable, which is exactly what the ingested-scaffold bug made
    impossible."""
    live = _FakeLive(_SCAFFOLD + [_track("Drums", devices=[_instrument()])])
    song_id = M.create_song(conn, name="clean")
    session_id = M.create_ableton_session(conn, song_id=song_id, name="draft")

    result = _round(conn, live, song_name="clean", session_id=session_id)
    plan = push.plan_cleanup_default_scaffold(
        unmatched_live_tracks=result.default_scaffold_unmatched_tracks,
        unmatched_live_returns=[],
        total_live_track_count=len(live.tracks),
        matched_track_count=len(result.matched_tracks),
    )

    assert plan.can_proceed
    assert [t["track_index"] for t in plan.deletable_tracks] == [4, 3, 2, 1]


def test_a_claimed_scaffold_track_still_matches_after_capture(conn):
    """The claimed slot must NOT be offered for deletion — it is the song's."""
    live = _FakeLive([
        _track("1-MIDI"),
        _track("2-MIDI", devices=[_instrument()]),
        _track("3-Audio", kind="audio"), _track("4-Audio", kind="audio"),
    ])
    song_id = M.create_song(conn, name="claimed")
    session_id = M.create_ableton_session(conn, song_id=song_id, name="draft")

    result = _round(conn, live, song_name="claimed", session_id=session_id)

    assert [m["name"] for m in result.matched_tracks] == ["2-MIDI"]
    assert [t["name"] for t in result.default_scaffold_unmatched_tracks] == [
        "1-MIDI", "3-Audio", "4-Audio",
    ]


# ---------------------------------------------------------------------------
# The upgrade boundary: a snapshot taken BEFORE the scaffold exclusion, refreshed
# AFTER it. Every real track's index moves, and the identity joins that carry
# browser paths and preset seeds forward key on that index.
# ---------------------------------------------------------------------------


def _old_scaffold_snapshot():
    """What a pre-fix capture of a scaffold-bearing set looks like: the four
    default tracks ingested as song content, the real track pushed to index 5."""
    return {
        "tracks": [
            {"index": 1, "name": "1-MIDI", "devices": []},
            {"index": 2, "name": "2-MIDI", "devices": []},
            {"index": 3, "name": "3-Audio", "devices": []},
            {"index": 4, "name": "4-Audio", "devices": []},
            {"index": 5, "name": "Drums", "devices": [
                {"index": 0, "class": "DrumGroupDevice", "name": "Kit",
                 "browser_path": ["Drums", "Kit", "909"],
                 "preset_query": "909 Core Kit"},
            ]},
        ],
        "returns": [],
    }


def test_a_browser_path_survives_the_scaffold_renumber():
    """The renumber is what makes #514's fix work, and it is also what breaks
    this join: post-fix the real track is index 1, the old snapshot has it at 5,
    and the miss path drops the path SILENTLY. Losing every device's
    cross-machine identity on exactly the songs the exclusion exists for is not
    an acceptable price for it.
    """
    old = _old_scaffold_snapshot()
    new = {
        "tracks": [
            {"index": 1, "name": "Drums", "devices": [
                {"index": 0, "class": "DrumGroupDevice", "name": "Kit"},
            ]},
        ],
        "returns": [],
    }
    capture.preserve_browser_paths(old, new)
    assert new["tracks"][0]["devices"][0]["browser_path"] == ["Drums", "Kit", "909"]


def test_a_preset_seed_survives_the_scaffold_renumber():
    old = _old_scaffold_snapshot()
    new = {
        "tracks": [
            {"index": 1, "name": "Drums", "devices": [
                {"index": 0, "class": "DrumGroupDevice", "name": "Kit",
                 "chains": []},
            ]},
        ],
        "returns": [],
    }
    capture.preserve_preset_overrides(old, new)
    assert new["tracks"][0]["devices"][0].get("preset_query") == "909 Core Kit"


def test_a_duplicated_track_name_is_not_guessed_across_the_renumber():
    """The name fallback must never carry a path onto a device that never had
    one. Two tracks sharing a name make the name ambiguous, so it is dropped
    from the map — the join falls back to the index, which is the pre-fix
    behaviour, not a guess."""
    old = {
        "tracks": [
            {"index": 1, "name": "Dup", "devices": [
                {"index": 0, "class": "Operator", "browser_path": ["A"]},
            ]},
            {"index": 2, "name": "Dup", "devices": [
                {"index": 0, "class": "Operator", "browser_path": ["B"]},
            ]},
        ],
        "returns": [],
    }
    new = {
        "tracks": [
            {"index": 9, "name": "Dup", "devices": [
                {"index": 0, "class": "Operator"},
            ]},
        ],
        "returns": [],
    }
    capture.preserve_browser_paths(old, new)
    assert "browser_path" not in new["tracks"][0]["devices"][0]


def test_dropping_a_scaffold_track_is_never_silent():
    """A pristine set captures as zero tracks. Without a line saying why, the
    operator sees an empty capture and no cause — the failure looks like the
    probe, not like a deliberate exclusion."""
    with pytest.warns(UserWarning, match="untouched default scaffold track"):
        snap = assemble_snapshot_via_probes(_FakeLive(_SCAFFOLD))
    assert snap["tracks"] == []


def test_an_ordinary_set_gets_no_scaffold_warning(recwarn):
    """The line must fire only when something was actually dropped."""
    live = _FakeLive([
        {"name": "Drums", "kind": "midi", "devices": [{"index": 0, "class": "X"}]},
    ])
    assemble_snapshot_via_probes(live)
    assert not [
        w for w in recwarn.list
        if "untouched default scaffold" in str(w.message)
    ]


# ---------------------------------------------------------------------------
# The upgrade boundary's replay half lives in test_replay_track_identity.py —
# the shifted-index case is reconciled by name now, not merely warned about.
# What belongs HERE is the capture half's other remainder: the default
# scaffold's RETURNS.
# ---------------------------------------------------------------------------


def _stock(class_name):
    """Live's factory device on a default return: stock class, stock name,
    nothing dialed."""
    return {"device_index": 1, "name": class_name, "class_name": class_name,
            "class_display_name": class_name, "is_active": True}


def _scaffold_returns():
    return [
        {"return_index": 1, "name": "A-Reverb", "devices": [_stock("Reverb")]},
        {"return_index": 2, "name": "B-Delay", "devices": [_stock("Delay")]},
    ]


def _return_names(snapshot):
    return [r["name"] for r in snapshot["returns"]]


# --- the predicate ---------------------------------------------------------


def _return_entry(name, devices):
    return {"index": 1, "name": name, "devices": list(devices)}


def test_return_predicate_untouched_canonical_return_is_scaffold():
    assert capture.is_untouched_default_scaffold_return(
        _return_entry("A-Reverb", [{"class_name": "Reverb", "name": "Reverb"}]),
        has_sends=False,
    )


def test_return_predicate_name_alone_is_never_enough():
    """The whole reason the track predicate does not transfer: Live ships its
    default returns CARRYING devices, so a name-only rule would drop a claimed
    return's entire captured mix."""
    assert not capture.is_untouched_default_scaffold_return(
        _return_entry("A-Reverb", []), has_sends=False,
    )
    assert not capture.is_untouched_default_scaffold_return(
        _return_entry("A-Reverb", [{"class_name": "Chorus", "name": "Chorus"}]),
        has_sends=False,
    )


def test_return_predicate_a_dialed_parameter_claims_the_return():
    assert not capture.is_untouched_default_scaffold_return(
        _return_entry("A-Reverb", [
            {"class_name": "Reverb", "name": "Reverb",
             "params_dialed": {"Dry/Wet": {"value": "60 %"}}},
        ]),
        has_sends=False,
    )


def test_return_predicate_a_renamed_device_claims_the_return():
    assert not capture.is_untouched_default_scaffold_return(
        _return_entry("A-Reverb", [
            {"class_name": "Reverb", "name": "Big Room"},
        ]),
        has_sends=False,
    )


def test_return_predicate_a_second_device_claims_the_return():
    assert not capture.is_untouched_default_scaffold_return(
        _return_entry("A-Reverb", [
            {"class_name": "Reverb", "name": "Reverb"},
            {"class_name": "EQ Eight", "name": "EQ Eight"},
        ]),
        has_sends=False,
    )


def test_return_predicate_a_send_claims_the_return():
    """The conjunct that keeps replay satisfiable, not merely the mix tidy: a
    return something sends to can never be dropped, because the send would
    then name a return the snapshot no longer defines."""
    assert not capture.is_untouched_default_scaffold_return(
        _return_entry("A-Reverb", [{"class_name": "Reverb", "name": "Reverb"}]),
        has_sends=True,
    )


def test_return_predicate_wrong_slot_device_is_not_scaffold():
    """A-Reverb carrying a Delay is not the factory pairing."""
    assert not capture.is_untouched_default_scaffold_return(
        _return_entry("A-Reverb", [{"class_name": "Delay", "name": "Delay"}]),
        has_sends=False,
    )


# --- capture ---------------------------------------------------------------


def test_untouched_scaffold_returns_never_enter_the_snapshot():
    live = _FakeLive(
        [_track("Drums", devices=[_instrument()])], returns=_scaffold_returns(),
    )
    assert _return_names(assemble_snapshot_via_probes(live)) == []


def test_a_claimed_scaffold_return_survives_with_its_device():
    live = _FakeLive(
        [_track("Drums", devices=[_instrument()])],
        returns=[
            {"return_index": 1, "name": "A-Reverb",
             "devices": [_stock("Reverb")],
             "params": {"Dry/Wet": 0.6}},
            {"return_index": 2, "name": "B-Delay", "devices": [_stock("Delay")]},
        ],
    )
    snap = assemble_snapshot_via_probes(live)
    assert _return_names(snap) == ["A-Reverb"]
    assert snap["returns"][0]["devices"][0]["name"] == "Reverb"


def test_a_return_something_sends_to_survives():
    """A non-zero send is a claim on the return, whatever its chain looks like."""
    live = _FakeLive(
        [_track("Drums", devices=[_instrument()], sends={"A-Reverb": 0.4})],
        returns=_scaffold_returns(),
    )
    snap = assemble_snapshot_via_probes(live)
    assert _return_names(snap) == ["A-Reverb"]
    assert snap["tracks"][0]["sends"] == {"A-Reverb": 0.4}


def test_a_zero_send_is_lives_default_wiring_not_a_claim():
    """Every track in a brand-new set carries a 0.0 send to every return. If
    that counted, the exclusion could never fire on a real set."""
    live = _FakeLive(
        [_track("Drums", devices=[_instrument()],
                sends={"A-Reverb": 0.0, "B-Delay": 0.0})],
        returns=_scaffold_returns(),
    )
    snap = assemble_snapshot_via_probes(live)
    assert _return_names(snap) == []


def test_dropping_a_return_strips_the_sends_that_named_it(conn):
    """The half that makes the snapshot REPLAYABLE rather than merely tidy:
    `replay_capture` raises on a send naming a return the snapshot does not
    define, so the zero-level send keys have to go with the return."""
    live = _FakeLive(
        [_track("Drums", devices=[_instrument()],
                sends={"A-Reverb": 0.0, "B-Delay": 0.0})],
        returns=_scaffold_returns(),
    )
    snap = assemble_snapshot_via_probes(live)
    assert "sends" not in snap["tracks"][0]
    # The proof the strip is load-bearing: this replays instead of raising.
    replay_capture(conn, snap, song_name="stripped")
    song_id = Q.get_song_by_name(conn, "stripped")["id"]
    assert [r["name"] for r in Q.get_returns_for_song(conn, song_id)] == []


def test_a_surviving_send_keeps_its_key():
    live = _FakeLive(
        [_track("Drums", devices=[_instrument()],
                sends={"A-Reverb": 0.4, "B-Delay": 0.0})],
        returns=_scaffold_returns(),
    )
    snap = assemble_snapshot_via_probes(live)
    assert snap["tracks"][0]["sends"] == {"A-Reverb": 0.4}


def test_surviving_returns_are_densely_renumbered():
    """`create_return` upserts on (song, position). A snapshot numbered AROUND
    a dropped scaffold return would replay the same return into a second row
    once Live's copy is actually deleted."""
    live = _FakeLive(
        [_track("Drums", devices=[_instrument()], sends={"B-Delay": 0.3})],
        returns=_scaffold_returns(),
    )
    snap = assemble_snapshot_via_probes(live)
    assert [(r["index"], r["name"]) for r in snap["returns"]] == [(1, "B-Delay")]


def test_dropping_a_scaffold_return_is_never_silent():
    live = _FakeLive(
        [_track("Drums", devices=[_instrument()])], returns=_scaffold_returns(),
    )
    with pytest.warns(UserWarning, match="untouched default scaffold return"):
        assemble_snapshot_via_probes(live)


def test_an_ordinary_return_set_gets_no_return_warning(recwarn):
    live = _FakeLive(
        [_track("Drums", devices=[_instrument()])],
        returns=[{"return_index": 1, "name": "Room",
                  "devices": [_stock("Reverb")]}],
    )
    assemble_snapshot_via_probes(live)
    assert not [
        w for w in recwarn.list
        if "untouched default scaffold return" in str(w.message)
    ]


def test_the_return_cleanup_offer_survives_a_capture(conn):
    """The point of the exclusion, end to end: the scaffold returns stay
    UNMATCHED after a capture -> replay round, so the push-side cleanup
    planner can still offer to delete them. Ingesting them is what made that
    offer impossible forever."""
    live = _FakeLive(
        [_track("Drums", devices=[_instrument()])], returns=_scaffold_returns(),
    )
    song_id = M.create_song(conn, name="returns")
    session_id = M.create_ableton_session(conn, song_id=song_id, name="draft")
    snapshot = assemble_snapshot_via_probes(live)
    replay_capture(conn, snapshot, song_name="returns")

    result = push.probe_and_link(
        conn, song_id=song_id, session_id=session_id,
        live_tracks=live.live_tracks(), live_returns=live.live_returns(),
    )
    assert [r["name"] for r in result.unmatched_live_returns] == [
        "A-Reverb", "B-Delay",
    ]
    plan = push.plan_cleanup_default_scaffold(
        unmatched_live_tracks=result.default_scaffold_unmatched_tracks,
        unmatched_live_returns=result.unmatched_live_returns,
        total_live_track_count=len(live.tracks),
        matched_track_count=len(result.matched_tracks),
    )
    assert plan.can_proceed
    assert [r["return_index"] for r in plan.deletable_returns] == [2, 1]


def test_a_return_browser_path_survives_the_scaffold_renumber():
    """The return half of the identity join. The exclusion renumbers surviving
    returns, and the join's miss path drops a browser path SILENTLY — losing
    every device's cross-machine identity on exactly the songs the exclusion
    exists for is not an acceptable price for it."""
    old = {
        "tracks": [],
        "returns": [
            {"index": 1, "name": "A-Reverb", "devices": [
                {"index": 1, "class": "Reverb", "name": "Reverb"},
            ]},
            {"index": 2, "name": "B-Delay", "devices": [
                {"index": 1, "class": "Delay", "name": "Delay",
                 "browser_path": ["Audio Effects", "Delay", "Slapback"]},
            ]},
        ],
    }
    new = {
        "tracks": [],
        "returns": [
            {"index": 1, "name": "B-Delay", "devices": [
                {"index": 1, "class": "Delay", "name": "Delay"},
            ]},
        ],
    }
    capture.preserve_browser_paths(old, new)
    assert new["returns"][0]["devices"][0]["browser_path"] == [
        "Audio Effects", "Delay", "Slapback",
    ]


def test_a_return_preset_seed_survives_the_scaffold_renumber():
    old = {
        "tracks": [],
        "returns": [
            {"index": 1, "name": "A-Reverb", "devices": [
                {"index": 1, "class": "Reverb", "name": "Reverb"},
            ]},
            {"index": 2, "name": "B-Delay", "devices": [
                {"index": 1, "class": "AudioEffectGroupDevice", "name": "Echo Rack",
                 "preset_query": "Tape Echo"},
            ]},
        ],
    }
    new = {
        "tracks": [],
        "returns": [
            {"index": 1, "name": "B-Delay", "devices": [
                {"index": 1, "class": "AudioEffectGroupDevice",
                 "name": "Echo Rack", "chains": []},
            ]},
        ],
    }
    capture.preserve_preset_overrides(old, new)
    assert new["returns"][0]["devices"][0].get("preset_query") == "Tape Echo"


def test_a_duplicated_return_name_is_not_guessed_across_the_renumber():
    """Same refusal as the track side: an ambiguous name is dropped from the
    map rather than carrying a path onto a device that never had one."""
    old = {
        "tracks": [],
        "returns": [
            {"index": 1, "name": "Dup", "devices": [
                {"index": 1, "class": "Reverb", "browser_path": ["A"]},
            ]},
            {"index": 2, "name": "Dup", "devices": [
                {"index": 1, "class": "Reverb", "browser_path": ["B"]},
            ]},
        ],
    }
    new = {
        "tracks": [],
        "returns": [
            {"index": 9, "name": "Dup", "devices": [{"index": 1, "class": "Reverb"}]},
        ],
    }
    capture.preserve_browser_paths(old, new)
    assert "browser_path" not in new["returns"][0]["devices"][0]


def test_the_return_name_join_ignores_lives_slot_prefix():
    """A snapshot may store the prefixed or the stripped form; the join must
    not be defeated by which."""
    old = {
        "tracks": [],
        "returns": [
            {"index": 3, "name": "A-Room", "devices": [
                {"index": 1, "class": "Reverb", "browser_path": ["Hall"]},
            ]},
        ],
    }
    new = {
        "tracks": [],
        "returns": [
            {"index": 1, "name": "Room", "devices": [{"index": 1, "class": "Reverb"}]},
        ],
    }
    capture.preserve_browser_paths(old, new)
    assert new["returns"][0]["devices"][0]["browser_path"] == ["Hall"]
