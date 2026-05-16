"""Build falling-walking into a SQLite DB using the songwright layer.

Chunk 3 milestone: the mix layout (12 tracks, 2 returns, sends matrix, master)
is seeded from `captured_session.json` via `songwright.capture.replay_capture`
rather than being hand-authored in this file. Score data (tempo/meter/sections/
cue points) and clip authoring still live here; later chunks will absorb more.

Run:
    python songs/falling-walking/build.py
    python songs/falling-walking/build.py --reset    # drop + rebuild
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from songwright.capture import replay_capture
from songwright.db import init_db, mutations as M, queries as Q
from songwright.generators import bass, drums, harmony

DB_PATH = Path(__file__).parent / "falling-walking.db"
SNAPSHOT_PATH = Path(__file__).parent / "captured_session.json"

# MIDI roots for the verse / chorus chord progression.
D2, F2, C2, G2, BB1, A1 = 38, 41, 36, 43, 34, 33

# Pad voicings (matching gen_notes.py)
DM_PAD = [53, 57, 62]
GM_PAD = [55, 58, 62]
BB_PAD = [53, 58, 62]


def _tracks_by_name(conn, song_id: str) -> dict[str, str]:
    """Map track name -> id for the song. Master is included; returns are not."""
    return {row["name"]: row["id"] for row in Q.get_tracks_for_song(conn, song_id)}


def build(reset: bool = False) -> str:
    """Build the song. Returns the song_id (UUID hex)."""
    if reset and DB_PATH.exists():
        DB_PATH.unlink()

    conn = init_db(DB_PATH)
    try:
        existing = Q.get_song_by_name(conn, "falling-walking")
        if existing and not reset:
            print(f"song already exists (id={existing['id']}); use --reset to rebuild")
            return existing["id"]

        # Mix-half: replay the captured Ableton session into DB rows. Creates
        # 12 tracks (with kinds + mixer state), 2 returns, the master strip,
        # and the sends matrix.
        snapshot = json.loads(SNAPSHOT_PATH.read_text())
        song_id = replay_capture(
            conn,
            snapshot,
            song_name="falling-walking",
            song_key="Dm",
            actor="sync",
            reason="initial chunk-3 capture replay",
        )

        # Score-half: tempo / meter / sections / cue points (chunk 2).
        # `native` timing_mode is the default; setting it explicitly so the
        # event log records the choice rather than relying on the default.
        M.set_song_timing_mode(conn, song_id=song_id, timing_mode="native")
        # Bars are 1-based across the codebase — the song starts at bar 1.
        M.add_tempo_point(conn, song_id=song_id, start_bar=1.0, tempo_bpm=132.0)
        M.add_time_signature_point(
            conn, song_id=song_id, start_bar=1.0, numerator=4, denominator=4
        )
        # Sections — bar positions are 1-based to match the arrangement entries
        # below. The verse runs bars 1-16; the chorus runs bars 16-24.
        M.create_section(
            conn, song_id=song_id, name="verse",
            start_bar=1.0, end_bar=16.0,
            notes_md="trip-hop drums + Dm pad with bar 4/8 stabs",
        )
        M.create_section(
            conn, song_id=song_id, name="chorus",
            start_bar=16.0, end_bar=24.0,
            notes_md="tresillo bass walking through Dm-F-C-G",
        )
        # Cue points: arrangement-level markers at section starts so the Live UI
        # surfaces section boundaries even though Live has no native section
        # marker concept.
        M.add_cue_point(conn, song_id=song_id, position_bar=1.0, name="verse")
        M.add_cue_point(conn, song_id=song_id, position_bar=16.0, name="chorus")

        # Clip authoring lives on the *captured* tracks now — names match what
        # Ableton has, not the previous placeholder set.
        tracks = _tracks_by_name(conn, song_id)

        # ------------------------------------------------------------------
        # Verse drums (15 bars trip-hop with fills at bars 4/8/12)
        # ------------------------------------------------------------------
        verse_drums_clip = M.create_clip(
            conn,
            track_id=tracks["01 Drums"],
            slot=1,
            length_beats=60.0,
            name="Verse Drums",
            section_role="verse",
            generator_call={
                "fn": "drums.trip_hop_drum_pattern",
                "kwargs": {"bars": 14, "fill_bars": [3, 7, 11]},
            },
        )
        verse_drum_notes = drums.trip_hop_drum_pattern(bars=14, fill_bars=[3, 7, 11])
        M.replace_clip_notes(conn, clip_id=verse_drums_clip, notes=verse_drum_notes)

        # ------------------------------------------------------------------
        # Verse pad: long Dm sustain with bar 4/8 stabs
        # ------------------------------------------------------------------
        verse_pad_clip = M.create_clip(
            conn,
            track_id=tracks["04 Verse Pad"],
            slot=1,
            length_beats=60.0,
            name="Verse Pad",
            section_role="verse",
        )
        verse_pad_notes = (
            harmony.chord_pad(DM_PAD, start_beat=0.0, length_beats=32.0, velocity=80)
            + harmony.chord_pad(GM_PAD, start_beat=32.0, length_beats=16.0, velocity=84)
            + harmony.chord_pad(BB_PAD, start_beat=48.0, length_beats=8.0, velocity=88)
            + harmony.chord_stab([53, 57, 62], start_beat=14.0)
            + harmony.chord_stab([55, 58, 62], start_beat=46.0)
        )
        M.replace_clip_notes(conn, clip_id=verse_pad_clip, notes=verse_pad_notes)

        # ------------------------------------------------------------------
        # Chorus bass — tresillo on Dm + walking embellishment into next chord.
        # Authored on "03 Synth Bass" (the Fat Square Bass that carries the
        # progression); "02 Sub Bass" reinforces the root but is not authored
        # here.
        # ------------------------------------------------------------------
        chorus_bass_clip = M.create_clip(
            conn,
            track_id=tracks["03 Synth Bass"],
            slot=2,
            length_beats=32.0,
            name="Chorus Bass",
            section_role="chorus",
        )
        chorus_bass_notes = (
            # Bars 1-2: plain tresillo on Dm + embellishment walking to F
            bass.tresillo_bass(D2, bars=1, start_beat=0.0)
            + bass.chord_tone_embellishment(
                D2, third_offset=3, fifth_offset=7, octave_offset=12,
                start_beat=4.0, walk_to_next=40,  # E2 chromatic to F
            )
            # Bars 3-4: F + walk to C
            + bass.tresillo_bass(F2, bars=1, start_beat=8.0)
            + bass.chord_tone_embellishment(
                F2, third_offset=4, fifth_offset=7, octave_offset=12,
                start_beat=12.0, walk_to_next=38,  # D2 upper neighbor
            )
            # Bars 5-6: C + walk to G
            + bass.tresillo_bass(C2, bars=1, start_beat=16.0)
            + bass.chord_tone_embellishment(
                C2, third_offset=4, fifth_offset=7, octave_offset=12,
                start_beat=20.0, walk_to_next=41,  # F2 passing
            )
            # Bars 7-8: G + walk back to Dm (next loop)
            + bass.tresillo_bass(G2, bars=1, start_beat=24.0)
            + bass.chord_tone_embellishment(
                G2, third_offset=4, fifth_offset=7, octave_offset=12,
                start_beat=28.0, walk_to_next=45,  # A2 -> Dm 5th
            )
        )
        M.replace_clip_notes(conn, clip_id=chorus_bass_clip, notes=chorus_bass_notes)

        # ------------------------------------------------------------------
        # Arrangement: minimal demo — verse drums bar 1-15, chorus bass bar 16-23
        # (Real arrangement is much richer; this proves the schema.)
        # ------------------------------------------------------------------
        M.add_arrangement(
            conn, song_id=song_id,
            track_id=tracks["01 Drums"], clip_id=verse_drums_clip,
            start_bar=1.0, end_bar=16.0,
        )
        M.add_arrangement(
            conn, song_id=song_id,
            track_id=tracks["04 Verse Pad"], clip_id=verse_pad_clip,
            start_bar=1.0, end_bar=16.0,
        )
        M.add_arrangement(
            conn, song_id=song_id,
            track_id=tracks["03 Synth Bass"], clip_id=chorus_bass_clip,
            start_bar=16.0, end_bar=24.0,
        )

        return song_id
    finally:
        conn.close()


def report(song_id: str) -> None:
    """Print a quick summary of what got built."""
    conn = init_db(DB_PATH)
    try:
        song_row = Q.get_song(conn, song_id)
        tracks = Q.get_tracks_for_song(conn, song_id)
        print(f"song_id={song_id}, timing_mode={song_row['timing_mode']}, "
              f"tracks={len(tracks)}")
        for t in tracks:
            mixer = []
            if t["volume"] is not None:
                mixer.append(f"v={t['volume']:.3f}")
            if t["pan"] is not None and t["pan"] != 0:
                mixer.append(f"p={t['pan']:+.2f}")
            mixer_str = f" [{', '.join(mixer)}]" if mixer else ""
            clips = Q.get_clips_for_track(conn, t["id"])
            devs = Q.get_devices_for_track(conn, t["id"])
            devs_str = f"  devs: {', '.join(d['display_name'] for d in devs)}" if devs else ""
            print(f"  track {t['track_index']:>2}  {t['name']:<16} "
                  f"({t['kind']}, {len(clips)} clips){mixer_str}{devs_str}")
            for c in clips:
                notes = Q.get_notes_for_clip(conn, c["id"])
                print(f"      slot {c['slot']}  {c['name']:<20} "
                      f"{c['length_beats']:.1f}bt  {len(notes)} notes")
        returns = Q.get_returns_for_song(conn, song_id)
        print(f"returns: {len(returns)}")
        for r in returns:
            devs = Q.get_devices_for_return(conn, r["id"])
            devs_str = f"  devs: {', '.join(d['display_name'] for d in devs)}" if devs else ""
            print(f"  return {r['position']}  {r['name']:<12} v={r['volume']}{devs_str}")
        sends = Q.get_sends_for_song(conn, song_id)
        if sends:
            print(f"sends: {len(sends)}")
            for s in sends:
                print(f"  {s['from_track_name']:<16} -> {s['return_name']:<10} = {s['level']:.3f}")
        arr = Q.get_arrangement_for_song(conn, song_id)
        print(f"arrangement entries: {len(arr)}")
        sections = Q.get_sections_for_song(conn, song_id)
        print(f"sections: {[s['name'] for s in sections]}")
        tempo = Q.get_tempo_map(conn, song_id)
        print(f"tempo_map: {[(t['start_bar'], t['tempo_bpm'], t['ramp']) for t in tempo]}")
        ts = Q.get_time_signature_map(conn, song_id)
        print(f"time_signature_map: "
              f"{[(p['start_bar'], p['numerator'], p['denominator']) for p in ts]}")
        cues = Q.get_cue_points(conn, song_id)
        print(f"cue_points: {[(c['position_bar'], c['name']) for c in cues]}")
    finally:
        conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true", help="drop + rebuild")
    args = p.parse_args()
    sid = build(reset=args.reset)
    report(sid)
