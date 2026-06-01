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
  - steel pans enter only in the later reggae sections (verse2 + outro)
  - metal sections (chorus1 / chorus2 / integration) sustain energy: a crash per
    4-bar phrase + fills
  - the convention-break decouples Amp timbre from groove time-feel: the single
    `break` is a reggae groove through a HEAVY (metal) amp
  - the integration is the CLIMAX — it quotes the polyrhythm motif and RESOLVES it
    into the polymodal both-at-once FUSION_CHORD; the RESOLUTION proper lands
    later in the outro, which re-brightens to Dorian (confirmed creative decision:
    fuse-hard-in-integration, resolve-in-outro)
  - the outro double-times the no-time hook into the reggae groove (recap primitive)
  - recurring sections derive from their first instance via `vary()`:
    chorus2 lead = chorus1 lead + an octave-down doubling (transform-delta);
    verse2 = verse1 + steel ENTERING (add-delta) + a richer progression
  - Rhythm Gtr is MONOLITHIC: 1 session clip spanning the whole song
    (736 beats / 184 bars), hosting the Amp Type envelope (7 breakpoints)
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
_SECTIONS_WITH_STEEL = {"verse2", "outro"}  # later reggae sections only
_METAL_SECTIONS = {"chorus1", "chorus2", "integration"}  # break is now reggae-groove


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
            "development", "break", "integration", "outro",
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
        # Organ: the reggae world (intro, verse1, verse2, development, break) +
        # the integration polyrhythm callback → 7
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
        # genre-driven (metal→Heavy, reggae→Clean) EXCEPT the convention-break,
        # which inverts it: `break` (bar 121 / beat 480) is a reggae groove but
        # plays HEAVY — a metal timbre on reggae time. integration (beat 544) is
        # metal/Heavy and so carries `break`'s Heavy with no new breakpoint.
        bp_pairs = [(bp["time_beats"], bp["value"]) for bp in bps]
        assert bp_pairs == [
            (0.0,   0.0),   # intro:       Clean
            (160.0, 5.0),   # chorus1:     Heavy
            (224.0, 0.0),   # verse2:      Clean
            (320.0, 5.0),   # chorus2:     Heavy
            (384.0, 0.0),   # development: Clean
            (480.0, 5.0),   # break:       Heavy  ← convention inversion (reggae groove)
            (672.0, 0.0),   # outro:       Clean
        ], bp_pairs

        # Arrangement: 36 placements (9 drums + 9 bass + 7 organ + 8 lead +
        # 2 steel + 1 gtr)
        arr = Q.get_arrangement_for_song(conn, song_id)
        assert len(arr) == 36, [(a["start_bar"], a["end_bar"]) for a in arr]

        # Cue points: 9, at each section start (the 184-bar arc's boundaries)
        cues = Q.get_cue_points(conn, song_id)
        assert len(cues) == 9
        cue_positions = sorted(c["position_bar"] for c in cues)
        assert cue_positions == [1.0, 17.0, 41.0, 57.0, 81.0, 97.0, 121.0, 137.0, 169.0]
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


def test_convention_break_inverts_amp_against_groove(build_module):
    """The break's "playing with conventions" is the Amp timbre decoupled from
    the groove's time-feel: the single `break` is a reggae groove (reggae genre)
    pushed through a HEAVY (metal) amp — metal timbre on reggae time."""
    amp = build_module._amp_for
    # Non-break sections: amp follows genre (metal→Heavy, reggae→Clean).
    assert amp("chorus1", "metal") == "Heavy"
    assert amp("integration", "metal") == "Heavy"
    assert amp("verse1", "reggae") == "Clean"
    assert amp("development", "reggae") == "Clean"
    # The break inverts it: a reggae groove through a HEAVY amp.
    assert amp("break", "reggae") == "Heavy"


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
        peak_start = (32 - 8) * 4.0  # the fusion blooms over the final 8 bars
        # The polyrhythm cloud is quoted, Em7-pure, tiled across the section
        # (before the fusion bloom) — not just the first cell.
        cloud = [n for n in notes if n["start_beats"] < peak_start]
        assert cloud
        assert {n["pitch"] % 12 for n in cloud} <= {4, 7, 11, 2}  # Em7 cloud
        assert max(n["start_beats"] for n in cloud) >= 88.0
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
    """The development collides on RHYTHM too, not just harmony (decisions/07): the
    feel trades bar-by-bar — bars where the Phrygian ♭II (F) intrudes go metal
    (gallop + an entrance crash), Dorian bars stay reggae (one-drop). So the drums
    carry metal crashes (the metal world breaks in) yet are NOT uniformly metal
    (reggae bars remain) — a trade, not a genre flip. Derived from the SAME DEV
    progression that drives the pitches."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        drums = _clips_by_role(conn, built, "01 Drums")
        notes = Q.get_notes_for_clip(conn, drums["development"]["id"])
        crash_bars = {int(n["start_beats"] // 4) for n in notes if n["pitch"] == 49}
        assert crash_bars, "expected metal-gallop crashes where the ♭II intrudes"
        # A trade, not a genre flip: metal intrudes on some bars, reggae holds others.
        assert 0 < len(crash_bars) < 24, (len(crash_bars), "should be a mix of worlds")
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
    """Metal energy: every metal section gets a crash on each 4-bar phrase start
    (so the 32-bar integration has 8, a 16-bar chorus has 4) plus a snare fill
    leading out of each phrase — the long stretch breathes instead of looping
    flat."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        drums = _clips_by_role(conn, built, "01 Drums")
        section_bars = {"chorus1": 16, "chorus2": 16, "integration": 32}
        for role in _METAL_SECTIONS:
            notes = Q.get_notes_for_clip(conn, drums[role]["id"])
            # The kit resolves the crash to the GM crash pad (49).
            crash_hits = sorted({n["start_beats"] for n in notes if n["pitch"] == 49})
            assert len(crash_hits) == section_bars[role] // 4, (role, crash_hits)
            assert crash_hits[0] == 0.0  # entrance crash
        # The integration (the 32-bar climax) carries the most crashes.
        integ = Q.get_notes_for_clip(conn, drums["integration"]["id"])
        assert len({n["start_beats"] for n in integ if n["pitch"] == 49}) == 8
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
    (the genre flip is a MODE flip), and the harmony MOVES — every section past
    the intro declares more than one chord. The intro is the deliberate
    single-chord dawn drone (the one place stasis is the intent)."""
    from hallucinote.generators.kit import Kit
    arr = build_module._build_arrangement(Kit.gm_default())
    curve = {name: (key_pc, mode, n) for name, key_pc, mode, n in arr.harmonic_curve}
    # Root E (pc 4) throughout — the song never modulates away.
    assert all(key_pc == 4 for key_pc, _mode, _n in curve.values()), curve
    # Reggae = Dorian, metal = Phrygian.
    for s in ("intro", "verse1", "verse2", "development", "break", "outro"):
        assert curve[s][1] == "Dorian", (s, curve[s])
    for s in ("chorus1", "chorus2", "integration"):
        assert curve[s][1] == "Phrygian", (s, curve[s])
    # Harmony moves everywhere except the deliberate intro drone.
    assert curve["intro"][2] == 1, curve["intro"]
    assert all(n >= 2 for s, (_pc, _m, n) in curve.items() if s != "intro"), curve


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


def test_performance_lens_breathing_de_flattens_the_organ(lens_report):
    # decisions/07's flat-organ friction is RESOLVED by the breathing pass: the
    # reggae organ now carries velocity breathing and reads human, so it no longer
    # surfaces a flat-dynamics finding. The only flat-dynamics findings left are the
    # metal pedal bass (deliberate one-velocity palm mutes — never breathed).
    organ_flat = [f for f in lens_report.findings
                  if f.kind == "flat-dynamics" and f.track == "04 Organ"]
    assert not organ_flat, "breathing should de-flatten the organ (no flat-dynamics)"
    flat_tracks = {f.track for f in lens_report.findings if f.kind == "flat-dynamics"}
    assert flat_tracks <= {"02 Bass"}, (
        f"only the intentional metal pedal bass should read flat; got {flat_tracks}")


def test_performance_lens_keeps_metal_machine_tight(lens_report):
    # The mechanical-timing reads are now the CORRECT ones — metal stays tight, never
    # breathed. Every mechanical-timing finding is a metal section (chorus1/2,
    # integration) or the break's slash-bass (kept tight so the Em/C#↔Em/C vote reads
    # clean at the fast harmonic-rhythm boundaries). No reggae bed part reads mechanical.
    metal_sections = {"chorus1", "chorus2", "integration"}
    mech = [f for f in lens_report.findings if f.kind == "mechanical-timing"]
    assert mech, "metal parts must still read mechanical — tight is correct"
    stray = [(f.section, f.track) for f in mech
             if f.section not in metal_sections
             and not (f.section == "break" and f.track == "02 Bass")]
    assert not stray, f"unexpected mechanical (should be breathing) parts: {stray}"


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
