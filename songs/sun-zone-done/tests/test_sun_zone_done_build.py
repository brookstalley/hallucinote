"""Shape tests for sun-zone-done — the through-composed harmonic-substrate arc.

End-to-end integration proof for `hallucinote.arrangement` + `hallucinote.theory`
(build-plan Chunk F): build.py authors the whole 184-bar THROUGH-COMPOSED song on
the arrangement + harmony modules, every section voicing a real MOVING
progression. These tests lock the structural + harmonic intent:

  - 6 instrument tracks + master + 3 returns
  - 9 sections / 184 bars (intro / verse1 / chorus1 / verse2 / chorus2 /
    development / break / integration / outro)
  - root E throughout; reggae sections are E Dorian, metal sections E Phrygian
    (the genre flip is a MODE flip); harmony MOVES — every section past the intro
    declares >1 chord (the intro is the deliberate single-chord dawn drone)
  - the intro has no lead (the vocal hasn't arrived) but carries the
    hand-authored polyrhythm build on the organ
  - organ is tacet only in the PURE metal choruses (chorus1 / chorus2); it plays
    every reggae section + the integration polyrhythm callback
  - steel pans play the reggae counter-melody (verse2 + outro), ENTER in the
    development collision arc, AND carry the back-half fusion textures: ethereal
    sparkle in the break + floating over the integration
  - the pure metal sections (chorus1 / chorus2) sustain energy: a crash per 4-bar
    phrase + fills; the integration's CLIMAX (its last 16 bars) sustains the same
  - the break (REINVENTED, decisions/08) is the EUREKA suspension: drums + bass drop
    OUT, a sustained polymodal FUSION pad + thinned shimmer carry the held breath, a
    half↔double-time call-response lets the worlds answer each other, a snare-roll
    riser launches the bass DROP at the integration downbeat, and (v2) a ghosted
    metal-guitar DRIFT haunts the field — swept hard L↔R through the Heavy amp
  - the integration (REINVENTED, decisions/08) is the PLAYGROUND — the two worlds
    genuinely COMBINED cell-by-cell (INTEG_CELLS), building to the EARNED climax that
    quotes the polyrhythm motif and RESOLVES it into the polymodal both-at-once
    FUSION_CHORD; the RESOLUTION proper lands later in the outro, which re-brightens
    to Dorian (confirmed creative decision: fuse-hard-in-integration, resolve-in-outro)
  - the outro double-times the no-time hook into the reggae groove (recap primitive)
  - recurring sections derive from their first instance via `vary()`:
    chorus2 lead = chorus1 lead + an octave-down doubling (transform-delta);
    verse2 = verse1 + steel ENTERING (add-delta) + a richer progression
  - Rhythm Gtr is MONOLITHIC: 1 session clip spanning the whole song
    (736 beats / 184 bars), hosting the Amp Type envelope (13 breakpoints — the amp
    now PLAYS the back half: Heavy break drift + the integration's cell-by-cell trade)
  - the energy curve carries deliberate discontinuities at every genre flip
  - 9 cue points (one per section start)
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


_SONG_DIR = Path(__file__).resolve().parent.parent
_BUILD_PATH = _SONG_DIR / "build.py"
_NOTES_BASELINE = Path(__file__).resolve().parent / "fixtures" / "notes_baseline.json"

# Organ plays the whole reggae world (intro polyrhythm build + every reggae
# section that carries the bubble) plus the integration polyrhythm callback; it
# is tacet only in the pure metal choruses (chorus1 / chorus2).
_SECTIONS_WITH_ORGAN = {
    "intro", "verse1", "verse2", "development", "break", "integration", "outro",
}
_PURE_METAL_NO_ORGAN = {"chorus1", "chorus2"}
_SECTIONS_WITH_LEAD = {  # every section except the intro (the vocal hasn't arrived)
    "verse1", "chorus1", "verse2", "chorus2",
    "development", "break", "integration", "outro",
}
# Steel plays the reggae counter-melody (verse2 + outro) AND the back-half fusion
# textures: it ENTERS in the development arc (the island lifting as the worlds collide),
# the ethereal sparkle in the break, and floats over the integration playground.
_SECTIONS_WITH_STEEL = {"verse2", "development", "outro", "break", "integration"}
_PURE_METAL_SECTIONS = {"chorus1", "chorus2"}  # the integration is now the playground, not uniform metal


def extract_notes(conn, song_id: str) -> dict:
    """Canonical, JSON-serializable snapshot of every clip's note array.

    The note arrays ARE the music; this locks them as a regression baseline
    (`test_notes_match_baseline`). It captures only what the listener hears —
    pitch, onset, duration, velocity, mute — keyed by (track name, slot). It
    EXCLUDES the DB-row `id` (fresh uuid each build) and `tags` (generator
    metadata). Floats rounded to 6 places to avoid representation noise.
    """
    from hallucinote.db import queries as Q

    snapshot: dict = {}
    for track in Q.get_tracks_for_song(conn, song_id):
        if track["name"] == "Master":
            continue
        clips_by_slot: dict = {}
        for clip in Q.get_clips_for_track(conn, track["id"]):
            notes = Q.get_notes_for_clip(conn, clip["id"])
            rows = sorted(
                [round(n["pitch"]), round(n["start_beats"], 6),
                 round(n["duration_beats"], 6), round(n["velocity"]),
                 int(n["mute"])]
                for n in notes
            )
            clips_by_slot[str(clip["slot"])] = {
                "name": clip["name"],
                "section_role": clip["section_role"],
                "length_beats": round(clip["length_beats"], 6),
                "notes": rows,
            }
        snapshot[track["name"]] = clips_by_slot
    return snapshot


@pytest.fixture(scope="module")
def build_module(tmp_path_factory):
    """Import build.py with DB_PATH redirected to a temp path so xdist
    parallel workers don't share state with each other (or with hand-runs
    of `python build.py`)."""
    spec = importlib.util.spec_from_file_location(
        "sun_zone_done_build", _BUILD_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DB_PATH = tmp_path_factory.mktemp("sun_zone_done") / "test.db"
    return mod


@pytest.fixture(scope="module")
def built(build_module):
    """Run a clean --reset build and return the song_id."""
    return build_module.build(reset=True)


def _clips_by_role(conn, song_id, track_name):
    """{section_role: clip_row} for a track."""
    from hallucinote.db import queries as Q
    track = next(t for t in Q.get_tracks_for_song(conn, song_id)
                 if t["name"] == track_name)
    return {c["section_role"]: c for c in Q.get_clips_for_track(conn, track["id"])}


def test_build_produces_canonical_shape(build_module, built):
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        song_id = built
        # Tracks: 6 instrument + 1 master = 7 (07 Tension added — the climax riser, #5)
        tracks = Q.get_tracks_for_song(conn, song_id)
        track_names = sorted(t["name"] for t in tracks)
        assert track_names == sorted([
            "01 Drums", "02 Bass", "03 Rhythm Gtr", "04 Organ", "05 Lead",
            "06 Steel", "07 Tension", "Master",
        ]), track_names

        # Returns: 3, named Plate / Room / DubDelay (stored stripped)
        returns = Q.get_returns_for_song(conn, song_id)
        return_names = sorted(r["name"] for r in returns)
        assert return_names == ["DubDelay", "Plate", "Room"], return_names

        # Sections: 9
        sections = Q.get_sections_for_song(conn, song_id)
        assert len(sections) == 9, [s["name"] for s in sections]
        assert [s["name"] for s in sections] == [
            "intro", "verse1", "chorus1", "verse2", "chorus2",
            "development", "break", "integration", "outro",
        ], [s["name"] for s in sections]

        # Per-track clip counts
        clip_counts: dict[str, int] = {}
        for t in tracks:
            if t["name"] == "Master":
                continue
            clip_counts[t["name"]] = len(Q.get_clips_for_track(conn, t["id"]))
        # Drums play every section (the break carries only the riser) → 9 clips
        assert clip_counts["01 Drums"] == 9
        # Bass plays every section EXCEPT the break (it drops OUT — the suspension) → 8
        assert clip_counts["02 Bass"] == 8
        # Lead plays every section except the intro → 8 clips
        assert clip_counts["05 Lead"] == 8
        # Organ: the reggae world (intro, verse1, verse2, development) + the break
        # FUSION pad + the integration (bubble in the cells + the polyrhythm climax) → 7
        assert clip_counts["04 Organ"] == 7
        # Steel: verse2 + outro (reggae counter-melody) + development arc + break
        # sparkle + integration → 5
        assert clip_counts["06 Steel"] == 5
        # Rhythm gtr is monolithic — exactly 1 clip
        assert clip_counts["03 Rhythm Gtr"] == 1
        # 07 Tension plays ONLY the climax riser → exactly 1 clip (integration)
        assert clip_counts["07 Tension"] == 1

        # Envelopes: 19 = 1 Amp Type (device_parameter)
        #   + 6 clip-local atmosphere pan/send: intro organ send+pan + intro DRUMS send
        #     (#4 the deepening dawn reverb RAMP) + break lead send + break steel send+pan
        #   + 4 clip-local OUTRO dub-throw sends into DubDelay (drums/organ/lead/steel — #5)
        #   + 3 clip-local OUTRO Room reverb lifts (organ/lead/steel — #D; Room because the
        #     Plate lanes are claimed by intro/break — create_envelope is find-or-create)
        #   + 2 whole-song reggae-gated gtr SKANK sends: gtr->Room + gtr->DubDelay (#3)
        #   + 3 whole-song bookended rhythm-gtr lanes: break drift pan SWEEP + VOLUME
        #     (amp-coupled Heavy trim + break ghost + integration blend) + deep-PLATE send
        # Pinned by test_atmosphere_envelopes_are_clip_local + the break-drift tests
        # (incl. test_break_drift_reverb_deep) + test_outro_dub_ending.
        envs = Q.get_envelopes_for_song(conn, song_id)
        assert len(envs) == 19, [(e["target_kind"], e["parameter_path"]) for e in envs]
        env = next(e for e in envs if e["target_kind"] == "device_parameter")
        assert env["parameter_path"] == "Amp Type"
        bps = Q.get_breakpoints(conn, env["id"])
        # One breakpoint at every AMP change (Clean=0.0, Heavy=5.0). The amp now PLAYS
        # the back half (decisions/08 v2): the break runs HEAVY for the ghosted metal
        # guitar DRIFT (480), and the integration follows INTEG_CELLS cell-by-cell —
        # Clean reggae skank (544), Heavy engine at cell B (560), then the TRADE cell
        # flips the amp BAR-BY-BAR (576 Clean, 580 Heavy, 584 Clean, 588 Heavy) before
        # holding Heavy through both + climax. The genre-flip device itself plays the
        # call-and-response rather than holding one timbre.
        bp_pairs = [(bp["time_beats"], bp["value"]) for bp in bps]
        assert bp_pairs == [
            (0.0,   0.0),   # intro:             Clean
            (107.0, 5.0),   # verse1 flash:      Heavy  ← #1 a 2-BEAT flash, one beat early
            (109.0, 0.0),   # verse1 resume:     Clean
            (160.0, 5.0),   # chorus1:           Heavy
            (224.0, 0.0),   # verse2:            Clean
            (267.0, 5.0),   # verse2 flash:      Heavy  ← #2 the same 2-beat flash in verse2
            (269.0, 0.0),   # verse2 resume:     Clean
            (320.0, 5.0),   # chorus2:           Heavy
            (384.0, 0.0),   # development:       Clean
            (480.0, 5.0),   # break:             Heavy  ← the metal-guitar DRIFT
            (544.0, 0.0),   # integration cellA: Clean  (reggae skank)
            (560.0, 5.0),   # integration cellB: Heavy  (the engine)
            (576.0, 0.0),   # trade reggae bar:  Clean  ┐ the amp trades
            (580.0, 5.0),   # trade metal bar:   Heavy  │ bar-by-bar with
            (584.0, 0.0),   # trade reggae bar:  Clean  │ the groove
            (588.0, 5.0),   # trade metal bar:   Heavy  ┘ (holds → both + climax)
            (672.0, 0.0),   # outro:             Clean
        ], bp_pairs

        # Arrangement: 39 placements (9 drums + 8 bass + 7 organ + 8 lead + 5 steel +
        # 1 gtr + 1 tension) — the climax riser (07 Tension) adds its single integration clip.
        arr = Q.get_arrangement_for_song(conn, song_id)
        assert len(arr) == 39, [(a["start_bar"], a["end_bar"]) for a in arr]

        # Cue points: 9, at each section start (the 184-bar arc's boundaries)
        cues = Q.get_cue_points(conn, song_id)
        assert len(cues) == 9
        cue_positions = sorted(c["position_bar"] for c in cues)
        assert cue_positions == [1.0, 17.0, 41.0, 57.0, 81.0, 97.0, 121.0, 137.0, 169.0]
    finally:
        conn.close()


def test_atmosphere_envelopes_are_clip_local(build_module, built):
    """Per-section 'space' (MIX-3S7P + #4 deepening reverb + #5 dub echo-out): the intro
    dawn cloud, the break suspension, and the outro echo-out each get clip-local send/pan
    envelopes that SNAP BACK to baseline at the section boundary AUTOMATICALLY, because
    each envelope's breakpoint range sits ENTIRELY inside the per-section clip that hosts
    it — intro [0,64); break [480,544); outro [672,736). The monolithic rhythm gtr's lanes
    (pan sweep, volume dip, deep-Plate send) are a DIFFERENT mechanism (song-spanning
    bookended automation) and are pinned by the break-drift tests — excluded here."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        tracks = {t["id"]: t["name"] for t in Q.get_tracks_for_song(conn, built)}
        rets = {r["id"]: r["name"] for r in Q.get_returns_for_song(conn, built)}
        plate = next(i for i, n in rets.items() if n == "Plate")
        dub = next(i for i, n in rets.items() if n == "DubDelay")
        room = next(i for i, n in rets.items() if n == "Room")
        # Collect (kind, track, return) → breakpoint range, for the non-Amp envelopes.
        atmos = {}
        for e in Q.get_envelopes_for_song(conn, built):
            if e["target_kind"] == "device_parameter":
                continue
            # The monolithic rhythm gtr is one clip spanning the whole song, so ANY
            # envelope on it is a song-spanning bookended lane (pan sweep / volume dip /
            # deep-Plate send), NOT clip-local atmosphere — pinned by test_break_drift_*.
            if tracks[e["target_track_id"]] == "03 Rhythm Gtr":
                continue
            bps = Q.get_breakpoints(conn, e["id"])
            rng = (min(b["time_beats"] for b in bps), max(b["time_beats"] for b in bps))
            vals = {round(b["value"], 3) for b in bps}
            atmos[(e["target_kind"], tracks[e["target_track_id"]],
                   e["target_send_return_id"])] = (rng, vals)
        # The intended clip-local set: intro organ send+pan + intro DRUMS send (#4 the
        # deepening dawn reverb), break lead send + steel send+pan (the suspension floats),
        # the OUTRO dub-throw sends into DubDelay (drums/organ/lead/steel — #5), and the
        # OUTRO Room reverb lifts (organ/lead/steel — #D, on Room because the Plate lanes
        # are already claimed by intro/break).
        windows = {
            ("send_level", "04 Organ", plate): (0.0, 64.0),
            ("mixer_pan", "04 Organ", None): (0.0, 64.0),
            ("send_level", "01 Drums", plate): (0.0, 64.0),
            ("send_level", "05 Lead", plate): (480.0, 544.0),
            ("send_level", "06 Steel", plate): (480.0, 544.0),
            ("mixer_pan", "06 Steel", None): (480.0, 544.0),
            ("send_level", "01 Drums", dub): (672.0, 736.0),
            ("send_level", "04 Organ", dub): (672.0, 736.0),
            ("send_level", "05 Lead", dub): (672.0, 736.0),
            ("send_level", "06 Steel", dub): (672.0, 736.0),
            ("send_level", "04 Organ", room): (672.0, 736.0),
            ("send_level", "05 Lead", room): (672.0, 736.0),
            ("send_level", "06 Steel", room): (672.0, 736.0),
        }
        assert set(atmos) == set(windows), set(atmos) ^ set(windows)
        for key, (rng, vals) in atmos.items():
            lo, hi = rng
            wlo, whi = windows[key]
            # Sits entirely inside its hosting section clip → snaps back at the boundary.
            assert wlo <= lo and hi < whi, (key, rng, (wlo, whi))
            # A reverb/echo send REACHES an elevated wet peak. A ramp (#4) or throw (#5)
            # STARTS at the dry baseline, so check the MAX, not every breakpoint.
            if key[0] == "send_level":
                assert max(vals) >= 0.30, (key, vals)  # baseline sends are ≤ 0.25
    finally:
        conn.close()


def test_break_drift_pans_extremely(build_module, built):
    """The break is no longer tacet guitar (decisions/08 v2): a ghosted metal-guitar
    DRIFT haunts the eureka suspension — sparse SUSTAINED E power chords at a ghost
    velocity, through the Heavy amp (pinned in the canonical-shape amp breakpoints),
    swept hard L↔R across the field. Locks the drift NOTES + the EXTREME pan sweep."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        tracks = {t["name"]: t["id"] for t in Q.get_tracks_for_song(conn, built)}
        # The drift notes: in the break window [480,544), ghost-quiet, SUSTAINED, low E
        # power chords (root + 5th → pitch classes E=4 / B=11).
        gtr_clip = Q.get_clips_for_track(conn, tracks["03 Rhythm Gtr"])[0]
        gnotes = Q.get_notes_for_clip(conn, gtr_clip["id"])
        drift = [n for n in gnotes if 480.0 <= n["start_beats"] < 544.0]
        assert drift, "the break carries a ghosted guitar drift (no longer tacet)"
        assert max(n["velocity"] for n in drift) <= 40, "ghost-quiet (much lower than usual)"
        assert max(n["duration_beats"] for n in drift) >= 4.0, "SUSTAINED swells, not chugs"
        assert {n["pitch"] % 12 for n in drift} <= {4, 11}, "E power chords (E / B)"
        # The EXTREME pan sweep on the rhythm gtr: reaches hard L and hard R…
        pan = next(e for e in Q.get_envelopes_for_song(conn, built)
                   if e["target_kind"] == "mixer_pan"
                   and e["target_track_id"] == tracks["03 Rhythm Gtr"])
        bps = sorted(Q.get_breakpoints(conn, pan["id"]), key=lambda b: b["time_beats"])
        vals = [b["value"] for b in bps]
        assert min(vals) <= -0.9 and max(vals) >= 0.9, ("extreme L↔R", vals)
        # …is dead-center before the break (bookended — only the drift wanders)…
        assert all(abs(b["value"]) < 1e-6 for b in bps if b["time_beats"] <= 480.0)
        # …and every hard-panned breakpoint lives inside the break window.
        swept = [b for b in bps if abs(b["value"]) >= 0.9]
        assert swept and all(480.0 <= b["time_beats"] <= 544.0 for b in swept), \
            [(b["time_beats"], b["value"]) for b in swept]
    finally:
        conn.close()


def test_gtr_volume_lanes(build_module, built):
    """The gtr VOLUME is COUPLED to the amp TIMBRE (user 2026-06-03): wherever the amp is
    HEAVY the gtr is trimmed (the Heavy amp adds ~3 dB), so the timbre flip is level-
    matched — chorus1/chorus2 + the verse1 flash. Two sections cut DEEPER: the break drift
    -> ghost, and the integration engine -> blend; the integration climax swells re-open.
    Derived from `_amp_segments` (one source of truth with the Amp Type envelope). Locks
    the shape + the relative ORDERING of the levels (ghost < blend < heavy < normal), not
    the exact dB (render-tuned)."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    VOL = build_module._GTR_VOL
    HEAVY = build_module._GTR_HEAVY
    GHOST = build_module._GTR_BREAK_GHOST
    BLEND = build_module._GTR_INTEG_BLEND
    assert GHOST < BLEND < HEAVY < VOL, (GHOST, BLEND, HEAVY, VOL)  # the intended ordering
    try:
        tracks = {t["name"]: t["id"] for t in Q.get_tracks_for_song(conn, built)}
        vol = next(e for e in Q.get_envelopes_for_song(conn, built)
                   if e["target_kind"] == "mixer_volume"
                   and e["target_track_id"] == tracks["03 Rhythm Gtr"])
        bps = sorted(Q.get_breakpoints(conn, vol["id"]), key=lambda b: b["time_beats"])

        def at(beat):  # hold semantics: the last breakpoint at or before `beat`
            prior = [b["value"] for b in bps if b["time_beats"] <= beat + 1e-6]
            return prior[-1] if prior else bps[0]["value"]

        # Clean reggae sits at normal (verse2 + verse1 OUTSIDE their flashes).
        assert abs(at(240.0) - VOL) < 1e-6, ("verse2 Clean", at(240.0))
        assert abs(at(70.0) - VOL) < 1e-6, ("verse1 pre-flash", at(70.0))
        # Heavy metal trims to the coupled level (chorus1/2 + the 2-beat verse flashes).
        assert abs(at(180.0) - HEAVY) < 1e-6, ("chorus1", at(180.0))
        assert abs(at(340.0) - HEAVY) < 1e-6, ("chorus2", at(340.0))
        assert abs(at(108.0) - HEAVY) < 1e-6, ("verse1 flash", at(108.0))   # local 43–45 -> 107–109
        assert abs(at(268.0) - HEAVY) < 1e-6, ("verse2 flash", at(268.0))   # verse2 flash 267–269
        # The break drift cuts DEEPER (a ghost); the integration ENGINE blends; the climax
        # SWELLS re-open to normal so the polyrhythm recap rings.
        assert abs(at(510.0) - GHOST) < 1e-6, ("break ghost", at(510.0))
        assert abs(at(600.0) - BLEND) < 1e-6, ("integ engine blend", at(600.0))
        assert abs(at(660.0) - VOL) < 1e-6, ("integ swells re-open", at(660.0))
    finally:
        conn.close()


def test_break_drift_reverb_deep(build_module, built):
    """#2 (user 2026-06-02): even ghosted, the break's metal-guitar drift read too loud /
    too foreground, so it's washed DEEP into the long dub Plate — the gtr's Plate send
    swells up only across the break, dry (its snapshot baseline) everywhere else. A
    song-spanning bookended lane on the monolithic gtr clip (like the pan/volume lanes).
    Locks the shape (not the exact depth — render-tuned)."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        tracks = {t["name"]: t["id"] for t in Q.get_tracks_for_song(conn, built)}
        plate = next(r["id"] for r in Q.get_returns_for_song(conn, built) if r["name"] == "Plate")
        send = next(e for e in Q.get_envelopes_for_song(conn, built)
                    if e["target_kind"] == "send_level"
                    and e["target_track_id"] == tracks["03 Rhythm Gtr"]
                    and e["target_send_return_id"] == plate)
        bps = sorted(Q.get_breakpoints(conn, send["id"]), key=lambda b: b["time_beats"])
        dry = bps[0]["value"]
        # Dry baseline before the break (only the drift gets the deep wash)…
        assert all(abs(b["value"] - dry) < 1e-6 for b in bps if b["time_beats"] <= 480.0)
        # …swells WELL above the dry send, every wet breakpoint inside the break window…
        wet = [b for b in bps if b["value"] > dry + 0.2]
        assert wet and all(480.0 <= b["time_beats"] <= 544.0 for b in wet), \
            [(b["time_beats"], b["value"]) for b in wet]
        # …and returns to dry by the end (the integration drop is not washed).
        assert abs(bps[-1]["value"] - dry) < 1e-6 and bps[-1]["time_beats"] >= 544.0
    finally:
        conn.close()


def test_outro_dub_ending(build_module, built):
    """#5 (user 2026-06-02): the outro was *great* but ended ABRUPTLY. The dub echo-out
    lands a sustained Em9 'button' over the last 2 bars while the busy bubble groove DROPS
    OUT, leaving the chord + a final accent to ring/echo away (the DubDelay throw is pinned
    by test_atmosphere_envelopes_are_clip_local). Locks: a sustained Em9 lands at the
    last-2-bars boundary, and the bubble groove has stopped before it."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    land = 56.0   # clip-local: the 16-bar (64-beat) outro's last 2 bars
    try:
        tracks = {t["name"]: t["id"] for t in Q.get_tracks_for_song(conn, built)}

        def _outro_notes(track):
            clips = [c for c in Q.get_clips_for_track(conn, tracks[track])
                     if "outro" in c["name"]]
            assert len(clips) == 1, [c["name"] for c in clips]
            return Q.get_notes_for_clip(conn, clips[0]["id"])

        organ = _outro_notes("04 Organ")
        # A sustained Em9 button lands at `land` (held into the wash; pitch classes ⊆ Em9).
        button = [n for n in organ
                  if abs(n["start_beats"] - land) < 1e-6 and n["duration_beats"] >= 6.0]
        assert len(button) >= 3, "a sustained organ chord lands the outro"
        assert {n["pitch"] % 12 for n in button} <= {4, 7, 11, 2, 6}, "Em9 (E G B D F#)"
        # The busy bubble groove has STOPPED before the landing (the groove drops out).
        assert not [n for n in organ
                    if n["start_beats"] >= land and n["duration_beats"] < 4.0], \
            "the organ bubble groove drops out for the wash"
        # A final drum accent lands the groove (then echoes out via the DubDelay throw).
        assert any(abs(n["start_beats"] - land) < 1e-6 for n in _outro_notes("01 Drums")), \
            "a final accent lands the outro"
    finally:
        conn.close()


def test_intro_has_polyrhythm_no_lead(build_module, built):
    """The intro is the sun coming up: drums + bass + the hand-authored
    polyrhythm build on the organ — but no lead yet (the vocal arrives at
    verse1)."""
    from hallucinote.db import init_db
    conn = init_db(build_module.DB_PATH)
    try:
        for track in ("01 Drums", "02 Bass", "04 Organ"):
            assert "intro" in _clips_by_role(conn, built, track), track
        assert "intro" not in _clips_by_role(conn, built, "05 Lead")
    finally:
        conn.close()


def test_intro_polyrhythm_is_em7_and_builds(build_module, built):
    """The intro organ is the 3:4:5:7 cross-rhythm: every pitch is an Em7 tone
    (the harmony stays pure under the rhythmic chaos), the four voices enter
    cumulatively (more distinct onsets as it thickens), and a velocity ramp
    drives the crescendo to the unbearable peak before the verse drop."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        organ = _clips_by_role(conn, built, "04 Organ")
        notes = Q.get_notes_for_clip(conn, organ["intro"]["id"])
        # Em7 chord tones only: E / G / B / D pitch classes.
        assert {n["pitch"] % 12 for n in notes} <= {4, 7, 11, 2}
        # Additive build: the first half has fewer distinct onsets than the
        # second half (voices keep entering).
        first_half = {n["start_beats"] for n in notes if n["start_beats"] < 16.0}
        second_half = {n["start_beats"] for n in notes if n["start_beats"] >= 16.0}
        assert len(second_half) > len(first_half)
        # Crescendo: late hits are louder than early hits.
        early = max(n["velocity"] for n in notes if n["start_beats"] < 4.0)
        late = max(n["velocity"] for n in notes if n["start_beats"] >= 28.0)
        assert late > early
    finally:
        conn.close()


def test_organ_tacet_only_in_pure_metal_choruses(build_module, built):
    """Organ plays the whole reggae world (intro, verse1, verse2, development,
    break) plus the integration polyrhythm callback; it is silent only in the
    pure metal choruses (chorus1 / chorus2) — that silence is what makes its
    return at the integration land."""
    from hallucinote.db import init_db
    conn = init_db(build_module.DB_PATH)
    try:
        organ_roles = set(_clips_by_role(conn, built, "04 Organ"))
        assert organ_roles == _SECTIONS_WITH_ORGAN, organ_roles
        assert organ_roles & _PURE_METAL_NO_ORGAN == set()
    finally:
        conn.close()


def test_break_is_the_eureka_suspension(build_module, built):
    """The REINVENTED break (decisions/08) is the EUREKA suspension, not the old
    reggae-through-a-heavy-amp convention-break: drums + bass DROP OUT (no groove),
    a sustained polymodal FUSION pad carries the held breath, a half↔double-time
    call-response plays on the lead, and a snare-roll RISER in the last two bars
    launches the bass DROP at the integration downbeat."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        # Bass DROPS OUT — there is no break bass clip at all.
        assert "break" not in _clips_by_role(conn, built, "02 Bass")
        # Drums carry ONLY the riser: every break drum hit is in the last two bars.
        drums = _clips_by_role(conn, built, "01 Drums")["break"]
        dnotes = Q.get_notes_for_clip(conn, drums["id"])
        assert dnotes, "the break has a riser"
        assert min(n["start_beats"] for n in dnotes) >= 56.0, "riser is the last two bars only"
        assert max(n["velocity"] for n in dnotes) > min(n["velocity"] for n in dnotes), \
            "the riser crescendos"
        # Organ is the sustained FUSION pad: long notes carrying BOTH modal colors
        # (F#/F and C#/C), plus a pp shimmer.
        organ = Q.get_notes_for_clip(conn, _clips_by_role(conn, built, "04 Organ")["break"]["id"])
        pad = [n for n in organ if n["duration_beats"] >= 16.0]
        assert pad, "the break carries a sustained pad (long notes)"
        pad_pcs = {n["pitch"] % 12 for n in pad}
        assert {6, 5} <= pad_pcs and {1, 0} <= pad_pcs, ("both-at-once fusion pad", pad_pcs)
        # Lead is the call-response dialogue: both the reggae chill (Dorian) and the
        # metal urgency (Phrygian F/C) sound in the same suspended field.
        lead = Q.get_notes_for_clip(conn, _clips_by_role(conn, built, "05 Lead")["break"]["id"])
        assert {n["pitch"] % 12 for n in lead} & {5, 0}, "the metal response colour (F/C) answers"
        # The bass DROP: the integration opens with a low sub slam on its downbeat.
        integ_bass = Q.get_notes_for_clip(conn, _clips_by_role(conn, built, "02 Bass")["integration"]["id"])
        downbeat = [n for n in integ_bass if n["start_beats"] < 0.5]
        assert downbeat and min(n["pitch"] for n in downbeat) <= 28, "the bass DROPS in low on beat 1"
    finally:
        conn.close()


def test_integration_amp_plays_clean_to_heavy(build_module):
    """The genre-flip device itself 'plays with combinations' (decisions/08 v2): the
    integration amp follows INTEG_CELLS cell-by-cell — Clean reggae skank in the
    reggae cell, the Heavy engine in metal/both/climax, and in the TRADE cell it flips
    BAR-BY-BAR — while the break runs Heavy for the metal-guitar drift and ordinary
    sections follow genre."""
    seg = build_module._amp_segments
    assert build_module._amp_for("metal") == "Heavy"
    assert build_module._amp_for("reggae") == "Clean"
    # Ordinary sections: a single genre-driven segment (development is Clean reggae).
    assert seg("development", "reggae") == [(0.0, "Clean")]
    assert seg("chorus1", "metal") == [(0.0, "Heavy")]
    # verse1 + verse2 (#1/#2, user 2026-06-03): a 2-BEAT HEAVY flash arriving ONE BEAT EARLY
    # (local 43–45 — the metal kicks the door in on the '4' into the downbeat, the steal
    # pattern in miniature), then back to Clean. Same in BOTH verses.
    assert seg("verse1", "reggae") == [(0.0, "Clean"), (43.0, "Heavy"), (45.0, "Clean")]
    assert seg("verse2", "reggae") == [(0.0, "Clean"), (43.0, "Heavy"), (45.0, "Clean")]
    # The break drift runs through the Heavy amp.
    assert seg("break", "reggae") == [(0.0, "Heavy")]
    # The integration amp is cell-aware: Clean reggae cell → Heavy engine → the trade
    # cell flips bar-by-bar (32 Clean / 36 Heavy / 40 Clean / 44 Heavy) → Heavy both +
    # climax. Derived from INTEG_CELLS (one source of truth with the guitar part).
    assert seg("integration", "metal") == [
        (0.0, "Clean"), (16.0, "Heavy"),
        (32.0, "Clean"), (36.0, "Heavy"), (40.0, "Clean"), (44.0, "Heavy"),
        (48.0, "Heavy"), (64.0, "Heavy"),
    ]


def test_integration_recaps_polyrhythm_and_resolves_to_fusion(build_module, built):
    """The integration is the CLIMAX (not the resolution — that lands in the
    outro). It FUSES both worlds: the intro's polyrhythm cloud, quoted on the
    organ that was tacet through the pure metal choruses, tiled across the full
    32 bars — Em7-pure (the harmony stays pure under the rhythm) — RESOLVING over
    the final 8 bars into the polymodal both-at-once FUSION_CHORD: an E pedal
    carrying BOTH the Dorian color (F#=6, C#=1) AND the Phrygian color (F=5,
    C=0) at once ("life is both crazy and mellow", made literally harmonic)."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        organ = _clips_by_role(conn, built, "04 Organ")
        assert "integration" in organ
        notes = Q.get_notes_for_clip(conn, organ["integration"]["id"])
        # The recap + fusion now live in the CLIMAX (the last 16 bars). Cells A–D
        # (beats 0–64) carry the reggae organ BUBBLE (the playground bed); the
        # polyrhythm cloud returns only when the climax does (decisions/08).
        climax_start = 16 * 4.0           # bar 16 of the 32-bar section
        peak_start = climax_start + (16 - 8) * 4.0  # fusion blooms over the climax's final 8 bars
        # The polyrhythm cloud is quoted Em7-pure across the climax, before the bloom.
        cloud = [n for n in notes if climax_start <= n["start_beats"] < peak_start]
        assert cloud
        assert {n["pitch"] % 12 for n in cloud} <= {4, 7, 11, 2}  # Em7 cloud
        assert max(n["start_beats"] for n in cloud) >= peak_start - 8.0  # tiled across the climax
        # The both-at-once fusion resolves at the peak: BOTH modal colors present.
        peak_pcs = {n["pitch"] % 12 for n in notes if n["start_beats"] >= peak_start}
        assert {6, 5} <= peak_pcs   # F# (Dorian) and F (Phrygian) together
        assert {1, 0} <= peak_pcs   # C# (Dorian) and C (Phrygian) together
        # And it is literally the authored FUSION_CHORD voicing.
        fusion = set(build_module.FUSION_CHORD.voicing(register=4))
        peak_pitches = {n["pitch"] for n in notes if n["start_beats"] >= peak_start}
        assert fusion <= peak_pitches, sorted(fusion - peak_pitches)
    finally:
        conn.close()


def test_outro_resolves_anxiety_into_peace_and_lift(build_module, built):
    """The outro RESOLVES (decisions/07), it doesn't retreat: the frantic 'NO TIME'
    hook returns AUGMENTED (slowed) and softened — the anxiety at peace — and a
    diatonic LIFT raises the chillin melody up a third IN KEY (joyful, rising into
    something new). Replaces the old frantic double-time bursts."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        lead = _clips_by_role(conn, built, "05 Lead")
        notes = Q.get_notes_for_clip(conn, lead["outro"]["id"])
        # The augmented 'NO TIME' statement (beats 32–48): carries the metal hook's
        # Phrygian color (F=pc5 / C=pc0), SLOWED (long durations) and SOFT (eased).
        mid = [n for n in notes if 32.0 <= n["start_beats"] < 48.0]
        assert mid, "expected the augmented no-time statement at beats 32–48"
        assert {n["pitch"] % 12 for n in mid} & {5, 0}, "expected the Phrygian color (F/C)"
        assert max(n["duration_beats"] for n in mid) >= 1.0, "augmented = slowed, not a stab"
        assert max(n["velocity"] for n in mid) <= 85, "at peace, not screaming"
        # The joyful diatonic lift (final 4 bars): the chillin melody raised in-key,
        # rising above its plain-register statement earlier in the outro.
        lift = [n for n in notes if n["start_beats"] >= 48.0]
        assert lift, "expected the diatonic lift in the final 4 bars"
        early_top = max(n["pitch"] for n in notes if n["start_beats"] < 16.0)
        assert max(n["pitch"] for n in lift) > early_top, "the lift should rise above the chill"
    finally:
        conn.close()


def test_development_collides_rhythmically(build_module, built):
    """The development is THROUGH-COMPOSED (decisions/08 v2), not a tiled loop: an
    accelerating 3-phase whiplash — a settled reggae groove with brief metal POKES →
    2-bar reggae↔metal trades → rapid bar-by-bar collision crescendoing into a snare
    FILL that launches the break's drop-out. The metal world breaks in (gallop crashes)
    yet reggae holds others (a trade, not a flat genre flip), and the section ENDS
    denser than it starts (the acceleration into the eureka)."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        drums = _clips_by_role(conn, built, "01 Drums")
        notes = Q.get_notes_for_clip(conn, drums["development"]["id"])
        crash_bars = {int(n["start_beats"] // 4) for n in notes if n["pitch"] == 49}
        assert crash_bars, "expected metal-gallop crashes where the metal world breaks in"
        # A trade, not a genre flip: metal intrudes on some bars, reggae holds others.
        assert 0 < len(crash_bars) < 24, (len(crash_bars), "should be a mix of worlds")
        # The acceleration: the FINAL bar is a dense 16th-note snare fill (≥8 hits)
        # launching the drop — far more snare onsets than any settled early reggae bar.
        last_bar_snares = [n for n in notes
                           if n["start_beats"] >= 23 * 4.0 and n["pitch"] == 38]
        assert len(last_bar_snares) >= 8, \
            ("the development ends in a crescendoing fill", len(last_bar_snares))
        # …and that fill crescendos (rising velocity into the drop).
        vels = [n["velocity"] for n in sorted(last_bar_snares, key=lambda n: n["start_beats"])]
        assert vels[-1] > vels[0], "the closing fill should crescendo into the eureka"
    finally:
        conn.close()


def test_steel_pans_play_counter_melody_and_fusion_textures(build_module, built):
    """Steel pans (Island Pans) play the reggae counter-melody — verse2 (entering as
    a vary() add-delta) + the enlightenment outro — AND the back-half fusion textures
    (decisions/08): ethereal sparkle in the break + floating over the integration
    playground. Never the intro, never the pure metal choruses. The bright island
    register stays E-Dorian throughout (the calypso 'happy' note C#)."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        steel = _clips_by_role(conn, built, "06 Steel")
        assert set(steel) == _SECTIONS_WITH_STEEL, set(steel)
        assert "intro" not in steel and steel.keys().isdisjoint(_PURE_METAL_SECTIONS)
        # E Dorian only (E F# G A B C# D = pitch classes 4 6 7 9 11 1 2), every section.
        for role in _SECTIONS_WITH_STEEL:
            notes = Q.get_notes_for_clip(conn, steel[role]["id"])
            assert {n["pitch"] % 12 for n in notes} <= {4, 6, 7, 9, 11, 1, 2}, (role,)
    finally:
        conn.close()


def test_verse2_add_delta_introduces_steel(build_module, built):
    """verse2's 'more layered, hasn't given up' is literally a new instrument
    arriving: the steel layer is present in verse2 but absent in verse1 — a
    vary() add-delta on top of the organ transform-delta."""
    from hallucinote.db import init_db
    conn = init_db(build_module.DB_PATH)
    try:
        steel = _clips_by_role(conn, built, "06 Steel")
        assert "verse2" in steel and "verse1" not in steel
    finally:
        conn.close()


def test_metal_sections_sustain_energy(build_module, built):
    """Metal energy: the PURE metal choruses get a crash on each 4-bar phrase start
    (4 in a 16-bar chorus) + a fill out of each phrase — the stretch breathes instead
    of looping flat. The integration is now the PLAYGROUND (decisions/08), not uniform
    metal, but its CLIMAX (the last 16 bars) sustains the same metal energy: a crash
    per 4-bar phrase, the first on the climax downbeat (beat 64)."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        drums = _clips_by_role(conn, built, "01 Drums")
        # The kit resolves the crash to the GM crash pad (49).
        for role in _PURE_METAL_SECTIONS:  # 16-bar choruses → 4 phrase crashes each
            crash_hits = sorted({n["start_beats"]
                                 for n in Q.get_notes_for_clip(conn, drums[role]["id"])
                                 if n["pitch"] == 49})
            assert len(crash_hits) == 4, (role, crash_hits)
            assert crash_hits[0] == 0.0  # entrance crash
        # The integration climax (beats 64–128) sustains metal energy: 4 phrase crashes,
        # first on the climax downbeat. (The playground cells before it also crash where
        # the metal world appears, so the section total is higher — the point is the
        # climax doesn't go flat.)
        integ = Q.get_notes_for_clip(conn, drums["integration"]["id"])
        climax_crashes = sorted({n["start_beats"] for n in integ
                                 if n["pitch"] == 49 and n["start_beats"] >= 64.0})
        assert climax_crashes == [64.0, 80.0, 96.0, 112.0], climax_crashes
    finally:
        conn.close()


def test_metal_steals_the_reggae_downbeat(build_module, built):
    """The RUDE INTERRUPTION (decisions/08 v4): the metal STEALS the reggae's last beat.

    In the verses that precede a chorus (verse1, verse2), the chorus's opening slam —
    crash + gallop kick + pedal-bass door-kick — is pulled a beat EARLY onto beat 4 of
    the verse's final bar ('on 4 rather than 1'), while the chill lead is robbed of its
    resolution (left hanging) and the chorus still CONFIRMS on its own downbeat (the
    felt arrival is on 4, the landing on 1 — an intentional double-hit). Length-
    preserving: the verse clip is still its full length — the grid never shifts. The
    LITERAL shorten-the-song steal (a bar of 3/4) is a meter-change feature → backlog.
    """
    from hallucinote.db import init_db, queries as Q
    arc_bars = {name: bars for name, _f, _g, bars, _e in build_module.ARC}
    conn = init_db(build_module.DB_PATH)
    try:
        for vname, cname in (("verse1", "chorus1"), ("verse2", "chorus2")):
            drums = _clips_by_role(conn, built, "01 Drums")[vname]
            bass = _clips_by_role(conn, built, "02 Bass")[vname]
            lead = _clips_by_role(conn, built, "05 Lead")[vname]
            length = drums["length_beats"]
            steal_at = length - 1.0  # beat 4 of the final bar (steal_beats=1.0)

            # Length-preserving: the steal did NOT shorten the verse (no grid shift).
            assert length == arc_bars[vname] * 4.0, (vname, length)

            # The stolen metal slam: a crash (49) lands on beat 4, a beat early.
            dn = Q.get_notes_for_clip(conn, drums["id"])
            assert any(n["pitch"] == 49 and abs(n["start_beats"] - steal_at) < 1e-6
                       for n in dn), f"{vname}: no stolen metal crash at beat {steal_at}"
            # The pedal-bass door-kick is stolen too (low-end weight under the slam).
            bn = Q.get_notes_for_clip(conn, bass["id"])
            assert any(abs(n["start_beats"] - steal_at) < 1e-6 for n in bn), \
                f"{vname}: no stolen pedal-bass downbeat at beat {steal_at}"
            # The chill lead is robbed of resolution — it hangs BEFORE the slam, never
            # resolving into it (the deep lead_gap cut).
            ln = Q.get_notes_for_clip(conn, lead["id"])
            assert max(n["start_beats"] for n in ln) < steal_at, \
                f"{vname}: the chill lead must hang before the slam, not resolve into it"

            # The chorus still CONFIRMS on its own downbeat (on-4 AND on-1, by design).
            cd = _clips_by_role(conn, built, "01 Drums")[cname]
            c0 = min(n["start_beats"] for n in Q.get_notes_for_clip(conn, cd["id"])
                     if n["pitch"] == 49)
            assert c0 == 0.0, f"{cname}: chorus must keep its own downbeat crash"
    finally:
        conn.close()


def test_reference_motifs_registered(build_module):
    """Both referenceable motifs are registered for the recapitulation/
    reference primitive: the polyrhythm cloud (quoted in the integration) and
    the no-time hook (fragmented + double-timed into the outro bursts)."""
    from hallucinote.generators.kit import Kit
    arr = build_module._build_arrangement(Kit.gm_default())
    assert {"polyrhythm-cloud", "no-time-stab"} <= set(arr.motifs)
    cloud = arr.get_motif("polyrhythm-cloud").notes
    assert cloud and {n["pitch"] % 12 for n in cloud} <= {4, 7, 11, 2}  # Em7
    no_time = arr.get_motif("no-time-stab").notes
    assert no_time and 65 in {n["pitch"] for n in no_time}  # Phrygian b2 (F)


def test_lead_present_except_intro(build_module, built):
    from hallucinote.db import init_db
    conn = init_db(build_module.DB_PATH)
    try:
        lead_roles = set(_clips_by_role(conn, built, "05 Lead"))
        assert lead_roles == _SECTIONS_WITH_LEAD, lead_roles
    finally:
        conn.close()


def test_recurrence_deltas_derive_from_first_instance(build_module, built):
    """Recurring sections evolve their first instance via `vary()` deltas (the
    cumulative-development primitive), not as independent copies:

      chorus2 lead = chorus1 lead + an octave-down doubling   (transform-delta)
      verse2       = verse1 + steel ENTERING (add-delta — see
                     test_verse2_add_delta_introduces_steel) + a richer
                     progression (Em9 / C#m7♭5 — the harmonic development)

    This locks the transform-delta directly and verifies verse2 is a genuine
    development of verse1 (its organ realizes a DIFFERENT, richer progression),
    not a literal copy. The add-delta is locked by
    test_verse2_add_delta_introduces_steel; the harmony axis by
    test_harmony_axis_moves_and_flips_modes.
    """
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        # chorus2 lead = chorus1 lead + an octave-down doubling.
        lead = _clips_by_role(conn, built, "05 Lead")
        c1_lead = Q.get_notes_for_clip(conn, lead["chorus1"]["id"])
        c2_lead = Q.get_notes_for_clip(conn, lead["chorus2"]["id"])
        assert len(c2_lead) == 2 * len(c1_lead), (len(c1_lead), len(c2_lead))
        c1_pitches = {n["pitch"] for n in c1_lead}
        c2_pitches = {n["pitch"] for n in c2_lead}
        assert c1_pitches <= c2_pitches            # originals retained
        assert {p - 12 for p in c1_pitches} <= c2_pitches  # octave-down added

        # verse2 is a development of verse1, not a copy: its organ realizes the
        # richer verse2 progression, so the harmonic content diverges.
        organ = _clips_by_role(conn, built, "04 Organ")
        v1_org = {n["pitch"] for n in Q.get_notes_for_clip(conn, organ["verse1"]["id"])}
        v2_org = {n["pitch"] for n in Q.get_notes_for_clip(conn, organ["verse2"]["id"])}
        assert v1_org != v2_org
    finally:
        conn.close()


def test_energy_curve_carries_the_narrative(build_module):
    """The authored energy curve (ARC is the authorship surface) carries the
    story: the two clean chorus interruptions are hard upward discontinuities,
    the releases back to the verses drop hard, and the integrating final chorus
    is the peak. (development and break deliberately hold HIGH-ish energy while
    the genre/timbre plays with convention — their discontinuity is timbre/
    time-feel, not an energy drop.)"""
    energy = {name: e for name, _fn, _g, _bars, e in build_module.ARC}
    assert energy == {
        "intro": 0.25, "verse1": 0.40, "chorus1": 0.80, "verse2": 0.45,
        "chorus2": 0.90, "development": 0.70, "break": 0.72,
        "integration": 1.00, "outro": 0.50,
    }
    # The clean reggae→metal interruptions jump hard (never smoothed).
    assert energy["chorus1"] - energy["verse1"] >= 0.35
    assert energy["chorus2"] - energy["verse2"] >= 0.35
    # The metal→reggae releases drop hard.
    assert energy["chorus1"] - energy["verse2"] >= 0.30
    # chorus2 escalates past chorus1; the integration is the single peak.
    assert energy["chorus2"] > energy["chorus1"]
    assert energy["integration"] == max(energy.values())
    # The outro RESOLVES into a lifted synthesis (decisions/07) — above the sleepy
    # verses but still below every chorus (a resolution, not a new climax).
    assert energy["outro"] < energy["chorus1"]
    assert energy["outro"] > energy["verse1"]  # lifted — not a retreat to sleepy reggae


def test_rhythm_gtr_clip_spans_full_song(build_module, built):
    """The structural fix for the Amp envelope: rhythm gtr is ONE clip
    736 beats long (184 bars × 4), hosting the section-boundary envelope.
    """
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        tracks = Q.get_tracks_for_song(conn, built)
        gtr = next(t for t in tracks if t["name"] == "03 Rhythm Gtr")
        clips = Q.get_clips_for_track(conn, gtr["id"])
        assert len(clips) == 1
        assert clips[0]["length_beats"] == 736.0
    finally:
        conn.close()


def test_harmony_axis_moves_and_flips_modes(build_module):
    """The harmony axis (Chunk F): root E throughout (the thesis — stay on E,
    evolve the mode), reggae sections are E Dorian and metal sections E Phrygian
    (the genre flip is a MODE flip), and the harmony MOVES — every section EXCEPT
    the two deliberate single-chord fields declares more than one chord. The two
    fields are the intro (the dawn drone) and the break (the EUREKA suspension over
    the E tonic, decisions/08) — the two places stasis is the intent."""
    from hallucinote.generators.kit import Kit
    arr = build_module._build_arrangement(Kit.gm_default())
    curve = {name: (key_pc, mode, n) for name, key_pc, mode, n in arr.harmonic_curve}
    # Root E (pc 4) throughout — the song never modulates away.
    assert all(key_pc == 4 for key_pc, _mode, _n in curve.values()), curve
    # Reggae = Dorian, metal = Phrygian. (The break declares the E-Dorian tonic the
    # suspension hovers on; its pad voices a richer polymodal colour as a texture.)
    for s in ("intro", "verse1", "verse2", "development", "break", "outro"):
        assert curve[s][1] == "Dorian", (s, curve[s])
    for s in ("chorus1", "chorus2", "integration"):
        assert curve[s][1] == "Phrygian", (s, curve[s])
    # Harmony moves everywhere except the two deliberate single-chord fields.
    fields = {"intro", "break"}
    assert curve["intro"][2] == 1 and curve["break"][2] == 1, curve
    assert all(n >= 2 for s, (_pc, _m, n) in curve.items() if s not in fields), curve


def test_harmony_realization_has_no_stasis(build_module):
    """LNT-1V9K: the harmony lens no longer GATES the build (a ruler, not a
    stamp), so the realization regression — the bass must actually SOUND the
    declared movement, never pedal one chord under a written change — lives HERE,
    in the song's own test where the intent is known. The intro + break are
    deliberate single-chord fields (declared==1, so never stasis); every section
    that declares movement must realize it, so stasis_sections must be empty."""
    from hallucinote.theory import lint_harmony
    from hallucinote.generators.kit import Kit
    arr = build_module._build_arrangement(Kit.gm_default())
    report = lint_harmony(arr.section_lints(harmony_layers=["02 Bass"]),
                          song_slug="sun-zone-done")
    assert report.stasis_sections == (), (
        f"the bass pedals a declared change in {report.stasis_sections} — fix the "
        f"composition (the lens only asks; this test is the gate)")
    # And — the LNT-1V9K contract — the lens never blocks regardless.
    assert report.ok is True
    assert report.blocking == ()


def test_outro_resolves_to_dorian_not_phrygian(build_module, built):
    """The CONFIRMED creative resolution (fuse-hard-in-integration, resolve-in-
    OUTRO): the outro re-brightens from the integration's polymodal fusion back
    to pure E Dorian — its organ (the harmonic bed) carries the Dorian
    characteristic F# (pc 6) and NOT the Phrygian ♭2 F-natural (pc 5) that
    defines the metal sections. The integration, by contrast, still carries that
    F (the fusion) — so the outro is where the dark mode is finally released."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        organ = _clips_by_role(conn, built, "04 Organ")
        outro_pcs = {n["pitch"] % 12
                     for n in Q.get_notes_for_clip(conn, organ["outro"]["id"])}
        assert 6 in outro_pcs        # F# — Dorian's bright characteristic tone
        assert 5 not in outro_pcs    # no F-natural — the Phrygian ♭2 is gone
        # The integration (the fusion) DID carry the Phrygian F — the outro
        # releases it. This is what makes the outro the resolution.
        integ_pcs = {n["pitch"] % 12
                     for n in Q.get_notes_for_clip(conn, organ["integration"]["id"])}
        assert 5 in integ_pcs
    finally:
        conn.close()


def test_build_is_idempotent_state_converger(build_module):
    """W12-A: re-running the build over an existing DB produces zero net
    state-change events. Validates the load-bearing state-converger promise
    on the real sun-zone-done build (not a synthetic one)."""
    from hallucinote.db import init_db

    # First build.
    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        state_events_first = [
            r["kind"] for r in conn.execute(
                "SELECT kind FROM events "
                "WHERE kind NOT IN ('request_created', 'request_closed') "
                "ORDER BY seq"
            ).fetchall()
        ]
        n_state_first = len(state_events_first)
    finally:
        conn.close()

    # Second build — no reset, expect zero new state-change events.
    song_id_2 = build_module.build(reset=False)
    assert song_id_2 == song_id  # same song row

    conn = init_db(build_module.DB_PATH)
    try:
        state_events_after = [
            r["kind"] for r in conn.execute(
                "SELECT kind FROM events "
                "WHERE kind NOT IN ('request_created', 'request_closed') "
                "ORDER BY seq"
            ).fetchall()
        ]
        assert len(state_events_after) == n_state_first, (
            f"Re-running build produced {len(state_events_after) - n_state_first} "
            f"extra state-change events — converger discipline broken."
        )
    finally:
        conn.close()


def test_metal_lead_uses_phrygian_b2(build_module, built):
    """The metal chorus melody includes F (E Phrygian's b2) — the
    harmonic trademark of the genre flip. Guards against accidentally
    sliding into Dorian on the metal side."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        lead = _clips_by_role(conn, built, "05 Lead")
        notes = Q.get_notes_for_clip(conn, lead["chorus1"]["id"])
        pitches = {n["pitch"] for n in notes}
        # F4 (65) is the Phrygian b2 in the metal lead melody
        assert 65 in pitches, sorted(pitches)
    finally:
        conn.close()


def test_notes_match_baseline(build_module, built):
    """REGRESSION BASELINE for the full narrative arc.

    Every clip's note array must match the locked baseline. An intentional
    musical change requires regenerating the fixture with a written rationale,
    never silently:

        python songs/sun-zone-done/tests/regen_notes_baseline.py
    """
    from hallucinote.db import init_db
    conn = init_db(build_module.DB_PATH)
    try:
        current = extract_notes(conn, built)
    finally:
        conn.close()

    assert _NOTES_BASELINE.exists(), (
        f"Baseline fixture missing: {_NOTES_BASELINE}. "
        f"Generate it with songs/sun-zone-done/tests/regen_notes_baseline.py"
    )
    baseline = json.loads(_NOTES_BASELINE.read_text())

    # Track-set parity first (clearer failure than a deep diff).
    assert set(current) == set(baseline), (
        f"Track set changed: {sorted(set(current) ^ set(baseline))}"
    )
    for track_name in sorted(baseline):
        cur_clips, base_clips = current[track_name], baseline[track_name]
        assert set(cur_clips) == set(base_clips), (
            f"{track_name}: slot set changed "
            f"{sorted(set(cur_clips) ^ set(base_clips))}"
        )
        for slot in sorted(base_clips, key=int):
            assert cur_clips[slot] == base_clips[slot], (
                f"{track_name} slot {slot} "
                f"({base_clips[slot]['name']}) diverged from baseline"
            )


# ---------------------------------------------------------------------------
# Symbolic performance lens (phase 2a) over the authored arrangement, AFTER the 1/f
# breathing pass (apply_profile). The both-sides loop, REALIZED: what decisions/07
# logged as the "Humanness" pending friction (flat organ, feels-quantized timing,
# constant-offset drums that read sloppy) is now resolved. These lock the new,
# stronger state: the reggae + blend pockets read HUMAN, metal stays machine-tight
# (mechanical), the break's slash-bass stays tight on purpose, and the only flat
# part left is the deliberate metal pedal bass (palm-mute single velocity).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lens_report(build_module, built):
    """The symbolic performance lens over the built arrangement (render-free)."""
    from hallucinote.db import init_db
    from hallucinote.performance import analyze_performance

    conn = init_db(build_module.DB_PATH)
    try:
        tracks = build_module._tracks_by_name(conn, built)
        kit = build_module._kit_for_drums(conn, tracks["01 Drums"])
        arr = build_module._build_arrangement(kit)
        return analyze_performance(
            arr.section_perf_inputs(), song_slug="sun-zone-done")
    finally:
        conn.close()


def test_performance_lens_breathing_de_flattens_the_reggae_organ(lens_report):
    # decisions/07's flat-organ friction is RESOLVED by the breathing pass: the reggae
    # organ BUBBLE carries velocity breathing and reads human — no flat-dynamics in any
    # reggae bubble section. The only flat-dynamics findings allowed are DELIBERATE
    # sustained drones: the metal pedal bass (one-velocity palm mutes) and the break's
    # sustained FUSION pad/shimmer (a pp drone — a sustained pad has no velocity
    # variation by design, decisions/08; LNT-1V9K: deliberate, never an error).
    flat = {(f.section, f.track) for f in lens_report.findings if f.kind == "flat-dynamics"}
    for sec, trk in flat:
        assert trk == "02 Bass" or sec == "break", \
            f"unexpected flat-dynamics (should breathe): {(sec, trk)}"
    # Specifically, no reggae organ BUBBLE reads flat (the breathing did its job).
    organ_flat_nonbreak = [(f.section, f.track) for f in lens_report.findings
                           if f.kind == "flat-dynamics" and f.track == "04 Organ"
                           and f.section != "break"]
    assert not organ_flat_nonbreak, organ_flat_nonbreak


def test_performance_lens_keeps_metal_machine_tight(lens_report):
    # The mechanical-timing reads are the CORRECT ones — metal stays tight, never
    # breathed. Every mechanical-timing finding is a metal/climax section (chorus1/2,
    # integration) or one of the break's DELIBERATELY-tight suspension parts: the
    # sustained pad (04 Organ), the riser (01 Drums), the sparkle (06 Steel). The
    # break's call-response LEAD is breathed (BREATH) and must NOT read mechanical;
    # no reggae bed part reads mechanical either (decisions/08).
    metal_sections = {"chorus1", "chorus2", "integration"}
    break_tight = {("break", "04 Organ"), ("break", "01 Drums"), ("break", "06 Steel")}
    mech = [f for f in lens_report.findings if f.kind == "mechanical-timing"]
    assert mech, "metal parts must still read mechanical — tight is correct"
    stray = [(f.section, f.track) for f in mech
             if f.section not in metal_sections and (f.section, f.track) not in break_tight]
    assert not stray, f"unexpected mechanical (should be breathing) parts: {stray}"
    # The breathed call-response lead is NOT mechanical.
    assert ("break", "05 Lead") not in {(f.section, f.track) for f in mech}


def test_performance_lens_reads_breathed_drums_as_human_not_sloppy(lens_report):
    # The breathing pass turns the reggae drums HUMAN (1/f-correlated), while the
    # metal drums stay mechanical — and NO drum part reads sloppy anymore. The old
    # constant-offset state that read sloppy is gone; this is the both-sides loop
    # (author breathing → lens reads human), the resolved state decisions/07 wanted.
    drum_parts = [p for s in lens_report.sections
                  for p in s.parts if p.track_name == "01 Drums"]
    assert drum_parts
    assert not any(p.classification == "sloppy" for p in drum_parts), \
        "no drum part should read sloppy after breathing"
    assert any(p.classification == "human" for p in drum_parts), \
        "reggae drums should read human (breathed)"
    assert any(p.classification == "mechanical" for p in drum_parts), \
        "metal drums should stay machine-tight"


def test_performance_lens_never_blocks_the_build(lens_report):
    # Authored feel is not error: the lens reports, it never gates.
    assert lens_report.ok is True
    assert lens_report.blocking == ()


def test_performance_lens_sections_match_the_arc(lens_report, build_module):
    assert [s.section for s in lens_report.sections] == [e[0] for e in build_module.ARC]


# ---------------------------------------------------------------------------
# Melody lens — the §9 both-sides demonstration via the melody_report() convention
# (DB-free: it builds the arrangement with a GM-default kit; harmony-fit reads the
# in-memory per-section progressions).
# ---------------------------------------------------------------------------


def test_melody_report_reads_both_hooks_active(build_module):
    """One lens, two profiles, neither graded against the other's ideal: the
    stepwise/third-based reggae lead and the angular ♭2 metal lead both read
    `active`, and harmony-fit runs for every section (melody-model.md §9)."""
    rep = build_module.melody_report()
    assert rep.song_slug == "sun-zone-done"
    lines = [(s.section, ln) for s in rep.sections for ln in s.lines]
    assert lines, "expected the 05 Lead hook in at least one section"
    assert all(ln.track_name == "05 Lead" for _s, ln in lines)
    assert all(ln.classification == "active" for _s, ln in lines)
    assert all(ln.harmony is not None for _s, ln in lines)  # in-memory progression read


def test_melody_report_reggae_anchors_harder_than_metal(build_module):
    """The intent-relative reading made concrete: the reggae verse sits closer to
    its chords than the angular metal chorus (whose Phrygian ♭2 raises its
    non-chord-tone share) — a fact the lens surfaces as a question, never a verdict."""
    rep = build_module.melody_report()
    by_section = {s.section: s.lines[0] for s in rep.sections if s.lines}
    assert by_section["verse1"].harmony.chord_tone_fraction \
        > by_section["chorus1"].harmony.chord_tone_fraction
