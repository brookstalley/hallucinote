"""Shape tests for sun-zone-done — the full narrative-arc rebuild.

This is the end-to-end integration proof for `hallucinote.arrangement`
(build-plan Chunk 2): build.py authors the whole song on the arrangement
module, and these tests lock the structural intent:

  - 6 instrument tracks + master + 3 returns (steel pans added in Chunk 4)
  - 9 sections / 80 bars (intro / verse1 / chorus1 / verse2 / chorus2 /
    break1 / break2 / integration / outro)
  - the intro has no lead (the vocal hasn't arrived) but carries the
    hand-authored polyrhythm build on the organ (Chunk 3)
  - organ is tacet only in the PURE metal choruses (chorus1 / chorus2); it
    returns for the break2 interleave and the integration fusion (Chunk 5)
  - steel pans enter only in the later reggae sections (verse2 + outro)
  - metal sections sustain energy: a crash per 4-bar phrase + fills (Chunk 4)
  - the convention-break decouples Amp timbre from groove time-feel (Chunk 5):
    break1 stays Heavy over the reggae groove; break2 goes Clean over metal
  - the integration quotes the polyrhythm motif; the outro double-times the
    no-time hook into the reggae groove (the reference/recap primitive)
  - recurring sections are derived from their first instance via `vary()`:
    verse2 = verse1 + organ octave-doubled; chorus2 = chorus1 + lead
    octave-doubled-down (the cumulative-development primitive)
  - Rhythm Gtr is MONOLITHIC: 1 session clip spanning the whole song
    (320 beats), hosting the Amp Type envelope (7 breakpoints at genre flips)
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

# Organ plays the whole reggae world: the intro (polyrhythm build) + the four
# reggae sections that carry the bubble. It is tacet in every metal section.
# Organ plays the whole reggae world + the two fusion sections (break2 interleave,
# integration polyrhythm callback); it is tacet only in the pure metal choruses.
_SECTIONS_WITH_ORGAN = {
    "intro", "verse1", "verse2", "break1", "break2", "integration", "outro",
}
_PURE_METAL_NO_ORGAN = {"chorus1", "chorus2"}
_SECTIONS_WITH_LEAD = {  # every section except the intro (the vocal hasn't arrived)
    "verse1", "chorus1", "verse2", "chorus2",
    "break1", "break2", "integration", "outro",
}
_SECTIONS_WITH_STEEL = {"verse2", "outro"}  # later reggae sections only
_METAL_SECTIONS = {"chorus1", "chorus2", "break2", "integration"}


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
        # Tracks: 5 instrument + 1 master = 6
        tracks = Q.get_tracks_for_song(conn, song_id)
        track_names = sorted(t["name"] for t in tracks)
        assert track_names == sorted([
            "01 Drums", "02 Bass", "03 Rhythm Gtr", "04 Organ", "05 Lead",
            "06 Steel", "Master",
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
            "break1", "break2", "integration", "outro",
        ], [s["name"] for s in sections]

        # Per-track clip counts
        clip_counts: dict[str, int] = {}
        for t in tracks:
            if t["name"] == "Master":
                continue
            clip_counts[t["name"]] = len(Q.get_clips_for_track(conn, t["id"]))
        # Drums + Bass play every section → 9 clips
        assert clip_counts["01 Drums"] == 9
        assert clip_counts["02 Bass"] == 9
        # Lead plays every section except the intro → 8 clips
        assert clip_counts["05 Lead"] == 8
        # Organ: reggae world (5) + break2 interleave + integration callback → 7
        assert clip_counts["04 Organ"] == 7
        # Steel pans enter only in the later reggae sections → 2 clips
        assert clip_counts["06 Steel"] == 2
        # Rhythm gtr is monolithic — exactly 1 clip
        assert clip_counts["03 Rhythm Gtr"] == 1

        # Envelopes: exactly 1, device_parameter on Amp Type, 7 breakpoints
        envs = Q.get_envelopes_for_song(conn, song_id)
        assert len(envs) == 1
        env = envs[0]
        assert env["target_kind"] == "device_parameter"
        assert env["parameter_path"] == "Amp Type"
        bps = Q.get_breakpoints(conn, env["id"])
        # One breakpoint at every AMP change (Clean=0.0, Heavy=5.0). The amp is
        # genre-driven EXCEPT in the convention-break, which inverts it: break1
        # (bar 41/beat 160) is a reggae groove but stays HEAVY (carries from
        # chorus2 → no breakpoint), and break2 (bar 49/beat 192) is a metal
        # groove turned CLEAN. The result is a clean Clean/Heavy alternation.
        bp_pairs = [(bp["time_beats"], bp["value"]) for bp in bps]
        assert bp_pairs == [
            (0.0,   0.0),   # intro:       Clean
            (64.0,  5.0),   # chorus1:     Heavy
            (96.0,  0.0),   # verse2:      Clean
            (128.0, 5.0),   # chorus2:     Heavy (carries through break1)
            (192.0, 0.0),   # break2:      Clean  ← convention inversion
            (224.0, 5.0),   # integration: Heavy
            (288.0, 0.0),   # outro:       Clean
        ], bp_pairs

        # Arrangement: 36 placements (9 drums + 9 bass + 7 organ + 8 lead +
        # 2 steel + 1 gtr)
        arr = Q.get_arrangement_for_song(conn, song_id)
        assert len(arr) == 36, [(a["start_bar"], a["end_bar"]) for a in arr]

        # Cue points: 9, at each section start
        cues = Q.get_cue_points(conn, song_id)
        assert len(cues) == 9
        cue_positions = sorted(c["position_bar"] for c in cues)
        assert cue_positions == [1.0, 9.0, 17.0, 25.0, 33.0, 41.0, 49.0, 57.0, 73.0]
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
    """Organ plays the whole reggae world plus the two fusion sections (break2
    interleave + integration polyrhythm callback); it is silent only in the
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


def test_convention_break_inverts_amp_against_groove(build_module):
    """The break's "playing with conventions" is the Amp timbre decoupled from
    the groove's time-feel: break1 is a reggae groove (Clean genre) but a HEAVY
    amp, break2 is a metal groove (Heavy genre) but a CLEAN amp."""
    amp = build_module._amp_for
    # Non-break sections: amp follows genre.
    assert amp("chorus1", "metal") == "Heavy"
    assert amp("verse1", "reggae") == "Clean"
    # The break inverts it.
    assert amp("break1", "reggae") == "Heavy"   # reggae groove, metal timbre
    assert amp("break2", "metal") == "Clean"    # metal groove, reggae timbre


def test_integration_quotes_polyrhythm_motif(build_module, built):
    """The integrating final chorus FUSES both worlds: the metal engine plus
    the intro's polyrhythm cloud, quoted on the organ that was tacet through the
    pure metal choruses. The callback is Em7-pure (the same cloud) and tiles the
    full 16 bars."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        organ = _clips_by_role(conn, built, "04 Organ")
        assert "integration" in organ
        notes = Q.get_notes_for_clip(conn, organ["integration"]["id"])
        assert {n["pitch"] % 12 for n in notes} <= {4, 7, 11, 2}  # Em7 cloud
        # Tiled across the full 16 bars (64 beats), not just the first cell.
        assert max(n["start_beats"] for n in notes) >= 56.0
    finally:
        conn.close()


def test_outro_has_double_time_metal_bursts(build_module, built):
    """The enlightenment outro flashes the no-time hook double-time over the
    reggae groove — a Phrygian descent (C natural, the metal mode) up in the
    metal lead register, derived by fragment+diminish from the registered
    motif."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        lead = _clips_by_role(conn, built, "05 Lead")
        notes = Q.get_notes_for_clip(conn, lead["outro"]["id"])
        # The bursts sit in the hook's gaps (beats 13+ and 29+), up high (>= C5).
        burst = [n for n in notes if n["start_beats"] >= 13.0
                 and n["start_beats"] < 15.5]
        assert burst, "expected a double-time burst around beat 13"
        assert all(n["pitch"] >= 72 for n in burst)        # metal-lead register
        assert 72 in {n["pitch"] for n in burst}           # C natural (Phrygian)
        # Double-time: the four stabs are an octave-of-beats apart (~0.5).
        onsets = sorted(n["start_beats"] for n in burst)
        gaps = [round(b - a, 3) for a, b in zip(onsets, onsets[1:])]
        assert all(g <= 0.5 for g in gaps), gaps
    finally:
        conn.close()


def test_steel_pans_enter_in_later_reggae_only(build_module, built):
    """Steel pans (Island Pans) play exactly the later reggae sections —
    verse2 (entering as a vary() add-delta) and the enlightenment outro — and
    nowhere else (not the intro, not any metal section)."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        steel = _clips_by_role(conn, built, "06 Steel")
        assert set(steel) == _SECTIONS_WITH_STEEL, set(steel)
        # E Dorian only (E F# G A B C# D = pitch classes 4 6 7 9 11 1 2).
        notes = Q.get_notes_for_clip(conn, steel["verse2"]["id"])
        assert {n["pitch"] % 12 for n in notes} <= {4, 6, 7, 9, 11, 1, 2}
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
    """Metal energy (Chunk 4): every metal section gets a crash on each 4-bar
    phrase start (so the 16-bar integration has 4, an 8-bar chorus has 2) plus
    a snare fill leading out of each phrase — the long stretch breathes instead
    of looping flat."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        drums = _clips_by_role(conn, built, "01 Drums")
        for role in _METAL_SECTIONS:
            notes = Q.get_notes_for_clip(conn, drums[role]["id"])
            # The kit resolves the crash to the GM crash pad (49).
            crash_hits = sorted({n["start_beats"] for n in notes if n["pitch"] == 49})
            bars = {"chorus1": 8, "chorus2": 8, "break2": 8, "integration": 16}[role]
            assert len(crash_hits) == bars // 4, (role, crash_hits)
            assert crash_hits[0] == 0.0  # entrance crash
        # The integration (the climax) carries the most crashes.
        integ = Q.get_notes_for_clip(conn, drums["integration"]["id"])
        assert len({n["start_beats"] for n in integ if n["pitch"] == 49}) == 4
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
    """verse2 / chorus2 are NOT independent copies — they are their first
    instance + one delta (the cumulative-development primitive via `vary`).

      verse2  organ = verse1 organ + an octave-up doubling
      chorus2 lead  = chorus1 lead + an octave-down doubling
    """
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        organ = _clips_by_role(conn, built, "04 Organ")
        v1_org = Q.get_notes_for_clip(conn, organ["verse1"]["id"])
        v2_org = Q.get_notes_for_clip(conn, organ["verse2"]["id"])
        # Doubled → twice the notes, and the +12 transposition is present.
        assert len(v2_org) == 2 * len(v1_org), (len(v1_org), len(v2_org))
        v1_pitches = {n["pitch"] for n in v1_org}
        v2_pitches = {n["pitch"] for n in v2_org}
        assert v1_pitches <= v2_pitches  # originals retained
        assert {p + 12 for p in v1_pitches} <= v2_pitches  # octave-up added

        lead = _clips_by_role(conn, built, "05 Lead")
        c1_lead = Q.get_notes_for_clip(conn, lead["chorus1"]["id"])
        c2_lead = Q.get_notes_for_clip(conn, lead["chorus2"]["id"])
        assert len(c2_lead) == 2 * len(c1_lead), (len(c1_lead), len(c2_lead))
        c1_pitches = {n["pitch"] for n in c1_lead}
        c2_pitches = {n["pitch"] for n in c2_lead}
        assert c1_pitches <= c2_pitches  # originals retained
        assert {p - 12 for p in c1_pitches} <= c2_pitches  # octave-down added
    finally:
        conn.close()


def test_energy_curve_carries_the_narrative(build_module):
    """The authored energy curve (ARC is the authorship surface) carries the
    story: the two clean chorus interruptions are hard upward discontinuities,
    the releases back to the verses drop hard, and the integrating final chorus
    is the peak. (The break sections deliberately hold HIGH energy while
    flipping genre — their discontinuity is timbre/time-feel, authored in
    Chunk 5, not an energy drop.)"""
    energy = {name: e for name, _fn, _g, _bars, e in build_module.ARC}
    assert energy == {
        "intro": 0.25, "verse1": 0.40, "chorus1": 0.80, "verse2": 0.45,
        "chorus2": 0.90, "break1": 0.70, "break2": 0.68,
        "integration": 1.00, "outro": 0.35,
    }
    # The clean reggae→metal interruptions jump hard (never smoothed).
    assert energy["chorus1"] - energy["verse1"] >= 0.35
    assert energy["chorus2"] - energy["verse2"] >= 0.35
    # The metal→reggae releases drop hard.
    assert energy["chorus1"] - energy["verse2"] >= 0.30
    # chorus2 escalates past chorus1; the integration is the single peak.
    assert energy["chorus2"] > energy["chorus1"]
    assert energy["integration"] == max(energy.values())
    # The enlightenment outro settles below every chorus (resolution, not climax).
    assert energy["outro"] < energy["chorus1"]


def test_rhythm_gtr_clip_spans_full_song(build_module, built):
    """The structural fix for the Amp envelope: rhythm gtr is ONE clip
    320 beats long (80 bars × 4), hosting the section-boundary envelope.
    """
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        tracks = Q.get_tracks_for_song(conn, built)
        gtr = next(t for t in tracks if t["name"] == "03 Rhythm Gtr")
        clips = Q.get_clips_for_track(conn, gtr["id"])
        assert len(clips) == 1
        assert clips[0]["length_beats"] == 320.0
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
