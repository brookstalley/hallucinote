# Sun Zone / Stuff Done

> **Composer intent + dated decisions** for this song live alongside this overview:
>
> - `decisions/01-intent-and-theme.md` — user's original brief (the load-bearing source)
> - `decisions/02-genre-mechanics.md` — alternation, not overlap; transition mechanics
> - `decisions/03-key-tempo-meter.md` — E Dorian ↔ E Phrygian; 180 BPM; 4/4
> - `decisions/04-section-structure.md` — 7 sections, 64 bars, asymmetric dramatic shape
> - `decisions/05-instrumentation-and-chains.md` — 5 tracks + 3 returns; the Amp Type envelope
> - `decisions/06-per-section-feel.md` — microtiming as authorship (reggae drag, metal straight)
>
> Query via `/song-context [topic]` (FTS5-indexed). See `.prawduct/artifacts/song-conventions.md`.

---

## Concept

Reggae × speed-metal mashup. Alternating (not overlapping) sections express the tension between wanting to relax and having too much to do. The genres are antithetical on every axis (tempo feel, articulation, harmonic mood) and that contrast IS the song. Each transition is an interruption — exactly the rhetorical structure of the lyric:

> "chillin in the sun zone, rasta vibes flowin in the — NO TIME FOR THAT GOTTA GET STUFF DONE"

Fun, but not a novelty song: the harmony carries the joke. The protagonist eventually gives up trying to be productive and collapses back into chill — but exhausted, not victorious.

## Core specs

- **Key:** Em — root E throughout, modes flip Dorian (reggae) ↔ Phrygian (metal)
- **Tempo:** 180 BPM (constant)
- **Time signature:** 4/4 (constant)
- **Length:** 64 bars (~85 seconds)

## Structure

| Section | Bars | Genre | Mode | Story beat |
|---|---|---|---|---|
| intro | 1–8 | Reggae | E Dorian | Sun coming up |
| verse1 | 9–16 | Reggae | E Dorian | "Chillin in the sun zone" |
| chorus1 | 17–24 | Metal | E Phrygian | "NO TIME FOR THAT" — first interruption |
| verse2 | 25–32 | Reggae | E Dorian | Back to chill |
| chorus2 | 33–40 | Metal | E Phrygian | Second interruption, escalating |
| bridge | 41–56 | Metal | E Phrygian | Sustained metal, exhausting |
| outro | 57–64 | Reggae | E Dorian | Exhausted return |

## Instrumentation

| Track | Instrument chain | Role |
|---|---|---|
| 01 Drums | Drum Rack (Hot Rod Kit) → EQ Eight → Drum Buss → Compressor | Beat (reggae one-drop ↔ metal gallop) |
| 02 Bass | Operator → EQ Eight → Compressor | Pulse + root (walking offbeats ↔ 16th palm-mute pedal) |
| 03 Rhythm Gtr | Tension → **Amp** → Cabinet → EQ Eight → Compressor | Harmonic skeleton + **genre-flip mechanism** (Amp Type Clean ↔ Heavy via envelope) |
| 04 Organ | Operator (Hammond) → EQ Eight → Chorus-Ensemble | Reggae offbeat bubbles (drops out in metal sections) |
| 05 Lead | Wavetable → EQ Eight → Compressor | Placeholder vocal melody |

**3 returns**: Plate (Hybrid Reverb), Room (Reverb), DubDelay (Echo).

## The Amp Type envelope

The song's most audible genre-flip device. Rhythm Gtr is a **monolithic session clip** (one clip, 256 beats = whole song); the Amp Type envelope sits on the Amp device with breakpoints at the section boundaries where the genre flips. Live 12.4 LOM requires `device_parameter` envelopes to be hosted by a clip covering the envelope's full beat range — the single-long-clip structure is the cleanest way to satisfy that constraint.

Other tracks (drums / bass / organ / lead) use per-section clips for compose-time convenience.

## Build

```bash
python songs/sun-zone-done/build.py            # state-converger
python songs/sun-zone-done/build.py --reset    # drop + rebuild
pytest songs/sun-zone-done/tests/ -v           # shape tests
```

## Push to Live

```bash
python3 -m hallucinote.sync.compat check sun-zone-done --probe
python3 -m hallucinote.sync.push_cli probe-and-link --auto-session --song sun-zone-done --probe
python3 -m hallucinote.sync.push_cli execute <session_id> --song sun-zone-done --probe
```

The compose-time helpers (`/ableton-push` skill) wrap this flow end-to-end.

## After push — manual Ableton steps

1. **Drum Rack pads.** Hot Rod Kit ships with standard pad assignments; if the build's drum hits (notes 36 / 38 / 42 / 46 / 49) don't trigger sounds, drop drum samples onto the corresponding pads.
2. **Mixer envelopes hidden by default.** None authored here, but if you add `mixer_volume` / `mixer_pan` / `send_level` envelopes via build.py, right-click the affected slider in Live and choose "Show Modulation" to make them editable.

## Out of scope (for v2)

- Counter-melody track + Vocal Bus track (v1 of the rebuild had them; deferred until real vocals)
- Send envelopes (e.g. swelling Plate send into a transition)
- Sidechain compression on bass (kick-driven duck during metal sections)
- Hi-hat opening variations within a bar (closed → open → closed)
- Outro tempo ritardando (Live's per-bar tempo automation has gaps)
