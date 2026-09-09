"""BAK-3M9T Chunk 01 — sidechain source round-trips through the durable snapshot.

A dialed sidechain SOURCE is the one mix element the snapshot couldn't carry
(trap #7). These tests prove it now round-trips through `captured_session.json`:
capture stores it by the source track's surface NAME (never a per-build UUID),
and `replay_capture` resolves the name → the song's track id and applies it via
the existing `set_device_sidechain`. The source is always a track — the DB column
`devices.sidechain_source_track_id` references `tracks(id)` (SDC-7K3M).

Synthetic snapshots only (no Live). The capture half drives
`assemble_snapshot_via_probes` with a fake `probe` that models the
`get_input_routing` surface faithfully (learning #7).

Tombstone protection for `device_sidechain_set` is already registered in
`_LATEST_ACTOR_EVENTS["device"]` and guarded by
`tests/unit/db/test_build_session.py::test_sync_sidechain_edit_protects_device_from_tombstone`
(verify-api finding) — not re-tested here. `test_sidechain_survives_rebuild` below
guards the distinct claim that the snapshot value persists across an idempotent
re-replay (the build.py rebuild loop).
"""
from __future__ import annotations

import pytest

from hallucinote.capture import assemble_snapshot_via_probes, replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q  # noqa: F401
from hallucinote.db import events as E

# The hand-built fixtures here are unstamped (no `snapshot_version`) and one uses
# Live's `<letter>-` prefixed return name — both emit working-as-intended
# UserWarnings on replay (the SNP-8R4K migration nudge + the W4-C strip). Same
# convention as test_capture.py: ignore them module-wide as noise.
pytestmark = [
    pytest.mark.filterwarnings(
        r"ignore:.*snapshot predates SNP-8R4K.*:UserWarning"
    ),
    pytest.mark.filterwarnings(
        r"ignore:.*stripped Live's <letter>- slot prefix.*:UserWarning"
    ),
]


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "cap.db")
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Replay: snapshot sidechain_source -> DB FK
# ---------------------------------------------------------------------------


def _snapshot_with_sidechain(*, source="Kick", channel="Post FX"):
    """A Compressor on 'Bass' (track index 1) sidechained off 'Kick' (track index
    2). The source track is created AFTER the device's track in the replay loop,
    so this also exercises the deferred resolution (a source may name a track that
    doesn't exist yet when the device is replayed)."""
    dev = {"index": 1, "name": "Bass Comp", "class": "Compressor",
           "sidechain_source": source}
    if channel is not None:
        dev["sidechain_source_channel"] = channel
    return {
        "song": {"master": {"volume": 0.85, "panning": 0.0}},
        "returns": [],
        "tracks": [
            {"index": 1, "name": "Bass", "type": "midi", "volume": 0.7,
             "panning": 0.0, "devices": [dev]},
            {"index": 2, "name": "Kick", "type": "midi", "volume": 0.7,
             "panning": 0.0},
        ],
    }


def _bass_comp(conn, sid):
    bass = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Bass")
    return Q.get_devices_for_track(conn, bass["id"])[0]


def test_round_trip_sets_sidechain_fk(conn):
    sid = replay_capture(conn, _snapshot_with_sidechain(), song_name="s")
    kick = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Kick")
    comp = _bass_comp(conn, sid)
    assert comp["sidechain_source_track_id"] == kick["id"]
    assert comp["sidechain_source_channel"] == "Post FX"


def test_round_trip_resolves_by_surface_name_not_uuid(conn):
    """Learning #22: the snapshot stores only the source's surface NAME; the FK
    resolves to the track's auto-generated UUID, which is neither the name nor the
    index. Proves resolution keys on the surface name, not a baked-in id."""
    snap = _snapshot_with_sidechain()
    assert snap["tracks"][0]["devices"][0]["sidechain_source"] == "Kick"
    sid = replay_capture(conn, snap, song_name="s")
    kick = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Kick")
    comp = _bass_comp(conn, sid)
    # The resolved FK is a UUID distinct from the surface name and the index.
    assert comp["sidechain_source_track_id"] == kick["id"]
    assert comp["sidechain_source_track_id"] not in ("Kick", "2", 2)


def test_channel_omitted_when_absent(conn):
    sid = replay_capture(conn, _snapshot_with_sidechain(channel=None), song_name="s")
    comp = _bass_comp(conn, sid)
    kick = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Kick")
    assert comp["sidechain_source_track_id"] == kick["id"]
    assert comp["sidechain_source_channel"] is None


def test_absence_writes_no_sidechain_and_emits_no_event(conn):
    """A device with no `sidechain_source` field leaves the FK NULL and emits no
    DEVICE_SIDECHAIN_SET event (the per-device clear is idempotent)."""
    snap = {
        "song": {"master": {"volume": 0.85, "panning": 0.0}},
        "returns": [],
        "tracks": [
            {"index": 1, "name": "Bass", "type": "midi", "volume": 0.7,
             "panning": 0.0,
             "devices": [{"index": 1, "name": "EQ", "class": "EQ Eight"}]},
        ],
    }
    sid = replay_capture(conn, snap, song_name="s")
    comp = _bass_comp(conn, sid)
    assert comp["sidechain_source_track_id"] is None
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE kind = ?",
        (E.DEVICE_SIDECHAIN_SET,),
    ).fetchone()["n"]
    assert n == 0


def test_return_hosted_device_sidechains_off_track(conn):
    """A device on a RETURN, sidechained off a regular track, resolves too —
    capture probes return devices and replay resolves the source against tracks."""
    snap = {
        "song": {"master": {"volume": 0.85, "panning": 0.0}},
        "returns": [
            {"index": 1, "name": "A-Glue", "volume": 0.8, "panning": 0.0,
             "devices": [{"index": 1, "name": "Bus Comp", "class": "Compressor",
                          "sidechain_source": "Kick"}]},
        ],
        "tracks": [
            {"index": 1, "name": "Kick", "type": "midi", "volume": 0.7,
             "panning": 0.0},
        ],
    }
    sid = replay_capture(conn, snap, song_name="s")
    kick = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Kick")
    glue = Q.get_returns_for_song(conn, sid)[0]
    bus_comp = Q.get_devices_for_return(conn, glue["id"])[0]
    assert bus_comp["sidechain_source_track_id"] == kick["id"]


def test_absence_is_no_opinion_not_clear_on_rebuild(conn):
    """CONTRACT CHANGE (replaces BAK-3M9T's `test_clear_on_absence_rebuild`):
    snapshot SILENCE is "no opinion", not "clear". Dropping the sidechain_source
    key from the snapshot and rebuilding now LEAVES the DB value intact — replay
    only touches a device's sidechain when the snapshot DECLARES it.

    Why the reversal: a snapshot that omits the key isn't necessarily saying
    "no sidechain" — it may simply not have captured one (capture writes the key
    only when it FINDS a source), while build.py authored it directly. The old
    "absent -> clear" rule clobbered that build.py-authored source on every
    build, breaking converger idempotency for any song with a mix-pass sidechain.
    The accepted cost: snapshot-silence no longer clears a removed sidechain on
    an INCREMENTAL rebuild — clear via an explicit null (next test), a fresh-DB
    rebuild, or set_device_sidechain(None) in build.py.
    See backlog SYN-7N4K
    """
    replay_capture(conn, _snapshot_with_sidechain(), song_name="s")
    snap_silent = _snapshot_with_sidechain()
    dev = snap_silent["tracks"][0]["devices"][0]
    del dev["sidechain_source"]
    del dev["sidechain_source_channel"]
    sid = replay_capture(conn, snap_silent, song_name="s")  # same song -> upsert
    kick = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Kick")
    comp = _bass_comp(conn, sid)
    # Preserved, NOT cleared — silence is no opinion.
    assert comp["sidechain_source_track_id"] == kick["id"]
    assert comp["sidechain_source_channel"] == "Post FX"


def test_explicit_null_source_clears_on_rebuild(conn):
    """Forward-compatible: an EXPLICIT null `sidechain_source` (a future capture
    that records "no source here") DOES clear the prior value — distinct from an
    ABSENT key (no opinion, preserved above). Capture doesn't emit null today,
    but the replay path already honours it, so snapshot-driven clearing can be
    added later with no rework."""
    replay_capture(conn, _snapshot_with_sidechain(), song_name="s")
    snap_null = _snapshot_with_sidechain()
    dev = snap_null["tracks"][0]["devices"][0]
    dev["sidechain_source"] = None
    dev.pop("sidechain_source_channel", None)
    sid = replay_capture(conn, snap_null, song_name="s")
    comp = _bass_comp(conn, sid)
    assert comp["sidechain_source_track_id"] is None
    assert comp["sidechain_source_channel"] is None


def test_sidechain_survives_rebuild(conn):
    """The durable claim: a sidechain authored in the snapshot persists across an
    idempotent re-replay (the build.py rebuild loop) and re-asserts no spurious
    second event."""
    replay_capture(conn, _snapshot_with_sidechain(), song_name="s")
    sid = replay_capture(conn, _snapshot_with_sidechain(), song_name="s")
    kick = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Kick")
    comp = _bass_comp(conn, sid)
    assert comp["sidechain_source_track_id"] == kick["id"]
    # Idempotent: the unchanged re-replay emits no second sidechain event.
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE kind = ?",
        (E.DEVICE_SIDECHAIN_SET,),
    ).fetchone()["n"]
    assert n == 1


def test_build_authored_sidechain_survives_silent_snapshot_rebuild(conn):
    """The converger regression (swell): a sidechain authored in build.py (via
    M.set_device_sidechain, the `_author_sidechains` pattern) on a device the
    SNAPSHOT says nothing about must SURVIVE a rebuild, with no clobbering event.

    Before the fix, replay enqueued every device's `sidechain_source` (absent ->
    None) and cleared it, so each build ran real -> null (replay) -> real
    (author) per sidechain = 2 spurious state-change events per build, forever.
    The idempotency guard test was therefore un-satisfiable for every song that
    authors a mix-pass sidechain.
    See backlog SYN-7N4K
    """
    snap = {
        "song": {"master": {"volume": 0.85, "panning": 0.0}},
        "returns": [],
        "tracks": [
            {"index": 1, "name": "Bass", "type": "midi", "volume": 0.7,
             "panning": 0.0,
             "devices": [{"index": 1, "name": "Bass Comp", "class": "Compressor"}]},
            {"index": 2, "name": "Kick", "type": "midi", "volume": 0.7,
             "panning": 0.0},
        ],
    }
    sid = replay_capture(conn, snap, song_name="s")
    kick = next(t for t in Q.get_tracks_for_song(conn, sid) if t["name"] == "Kick")
    comp = _bass_comp(conn, sid)
    # build.py authors the sidechain source (snapshot never carried it).
    M.set_device_sidechain(
        conn, device_id=comp["id"], source_track_id=kick["id"], channel=None,
    )

    def _sc_events() -> int:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE kind = ?",
            (E.DEVICE_SIDECHAIN_SET,),
        ).fetchone()["n"]

    assert _sc_events() == 1  # the single build.py author

    # Rebuild over the existing DB with the SAME silent snapshot, then re-author
    # (the build.py loop). The authored source must survive and the converger
    # must reach a fixpoint — zero further sidechain events.
    replay_capture(conn, snap, song_name="s")
    comp = _bass_comp(conn, sid)
    assert comp["sidechain_source_track_id"] == kick["id"]  # survived replay
    M.set_device_sidechain(
        conn, device_id=comp["id"], source_track_id=kick["id"], channel=None,
    )
    assert _sc_events() == 1  # no real->null->real churn — idempotent


def test_unresolvable_source_raises(conn):
    """A hand-authored source naming no track raises — the same hard contract as a
    send to a return not in the snapshot. (A captured snapshot never trips this:
    capture filters unresolvable sources.)"""
    snap = _snapshot_with_sidechain(source="Ghost Track")
    with pytest.raises(ValueError, match="not a track defined in snapshot"):
        replay_capture(conn, snap, song_name="s")


# ---------------------------------------------------------------------------
# Capture: get_input_routing -> snapshot sidechain_source (by surface name)
# ---------------------------------------------------------------------------


def _capture_probe(*, source="Kick", channel="Post FX", has_routing=True):
    """Fake probe: tracks 'Kick' (1) and 'Bass' (2); a Compressor on Bass whose
    input routing the test controls. Models the `get_input_routing` shape
    (`has_input_routing` / `current_type` / `current_channel`) faithfully."""
    def probe(tool, action, **params):
        if (tool, action) == ("ableton_session", "info"):
            return {"tempo": 120.0,
                    "signature": {"numerator": 4, "denominator": 4},
                    "master": None, "track_count": 2, "return_count": 0}
        if (tool, action) == ("ableton_return", "list"):
            return {"returns": []}
        if (tool, action) == ("ableton_track", "info"):
            ti = params["track_index"]
            return {"track_index": ti, "name": "Kick" if ti == 1 else "Bass",
                    "kind": "midi", "volume": 0.7, "panning": 0.0}
        if (tool, action) == ("ableton_track", "get_sends"):
            return {"sends": []}
        if (tool, action) == ("ableton_device", "list"):
            if params.get("track_index") == 2:
                return {"devices": [{"device_index": 1, "name": "Bass Comp",
                                     "class_name": "Compressor2",
                                     "class_display_name": "Compressor"}]}
            return {"devices": []}
        if (tool, action) == ("ableton_device", "get_parameters"):
            return {"parameters": []}
        if (tool, action) == ("ableton_device", "get_input_routing"):
            if params.get("track_index") == 2 and params.get("device_index") == 1:
                return {"has_input_routing": has_routing,
                        "current_type": source if has_routing else None,
                        "current_channel": channel}
            return {"has_input_routing": False}
        raise AssertionError(f"unrouted {tool}.{action} {params}")
    return probe


def _bass_device(snap):
    bass = next(t for t in snap["tracks"] if t["name"] == "Bass")
    return bass["devices"][0]


def test_capture_stores_sidechain_source_by_name_and_channel():
    snap = assemble_snapshot_via_probes(_capture_probe())
    dev = _bass_device(snap)
    assert dev["sidechain_source"] == "Kick"
    assert dev["sidechain_source_channel"] == "Post FX"


def test_capture_omits_channel_when_routing_has_none():
    snap = assemble_snapshot_via_probes(_capture_probe(channel=None))
    dev = _bass_device(snap)
    assert dev["sidechain_source"] == "Kick"
    assert "sidechain_source_channel" not in dev


def test_capture_filters_own_track_default_input():
    """When the device's input routing points at its OWN host track (Live's
    default, not a sidechain), no field is written."""
    snap = assemble_snapshot_via_probes(_capture_probe(source="Bass"))
    dev = _bass_device(snap)
    assert "sidechain_source" not in dev
    assert "sidechain_source_channel" not in dev


def test_capture_warns_and_drops_non_track_source():
    """A genuine sidechain whose source isn't a track in the snapshot can't be a
    surface-stable reference — Chunk 02: WARN with a re-apply list, never drop it
    silently. Capture still completes (warn, don't abort)."""
    with pytest.warns(UserWarning, match=r"RE-APPLY MANUALLY in Live.*Ext\. In"):
        snap = assemble_snapshot_via_probes(_capture_probe(source="Ext. In"))
    dev = _bass_device(snap)
    assert "sidechain_source" not in dev
    assert "sidechain_source_channel" not in dev
    # The rest of the snapshot is captured normally.
    assert dev["name"] == "Bass Comp"
    assert {t["name"] for t in snap["tracks"]} == {"Kick", "Bass"}


def test_capture_own_track_default_does_not_warn(recwarn):
    """The own-track default input is not a sidechain — dropped quietly, no
    re-apply warning (there is nothing to re-apply)."""
    assemble_snapshot_via_probes(_capture_probe(source="Bass"))
    assert not [
        w for w in recwarn.list
        if issubclass(w.category, UserWarning)
        and "RE-APPLY MANUALLY" in str(w.message)
    ]


def test_capture_no_field_when_routing_unavailable():
    snap = assemble_snapshot_via_probes(_capture_probe(has_routing=False))
    dev = _bass_device(snap)
    assert "sidechain_source" not in dev
