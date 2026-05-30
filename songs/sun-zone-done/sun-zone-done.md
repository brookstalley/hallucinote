# Sun Zone / Stuff Done

> **Composer intent + dated decisions** for this song live alongside this overview.
> The `decisions/*.md` records are **historical** — the original v2 design. The
> **current** structure (the arrangement-model rebuild) is the Structure section
> below; where they differ, this overview is authoritative.
>
> - `decisions/01-intent-and-theme.md` — user's original brief (the load-bearing source)
> - `decisions/02-genre-mechanics.md` — alternation, not overlap; transition mechanics
> - `decisions/03-key-tempo-meter.md` — E Dorian ↔ E Phrygian; 180 BPM; 4/4
> - `decisions/04-section-structure.md` — original 7-section/64-bar shape (superseded by the 9-section/80-bar arc below)
> - `decisions/05-instrumentation-and-chains.md` — instrumentation + the Amp Type envelope (now 6 tracks; see below)
> - `decisions/06-per-section-feel.md` — microtiming as authorship (reggae drag, metal straight)
>
> Query via `/song-context [topic]` (FTS5-indexed). See `.prawduct/artifacts/song-conventions.md`.

---

## Concept

Reggae × speed-metal mashup. Alternating (not overlapping) sections express the tension between wanting to relax and having too much to do. The genres are antithetical on every axis (tempo feel, articulation, harmonic mood) and that contrast IS the song. Each transition is an interruption — exactly the rhetorical structure of the lyric:

> "chillin in the sun zone, rasta vibes flowin in the — NO TIME FOR THAT GOTTA GET STUFF DONE"

Fun, but not a novelty song: the harmony carries the joke. The arc is a story of *adapting* — the protagonist stops fighting and learns to hold both the crazy and the mellow at once.

> **Authored on the `hallucinote.arrangement` module** (`.prawduct/artifacts/arrangement-model.md`): the section map, energy curve, recurrence deltas, motifs, and references are all expressed through the model — sun-zone-done is its first full demonstration. `build.py` is the integration proof.

## Core specs

- **Key:** Em — root E throughout, modes flip Dorian (reggae) ↔ Phrygian (metal)
- **Tempo:** 180 BPM (constant)
- **Time signature:** 4/4 (constant)
- **Length:** 80 bars (~107 seconds)

## Structure — the narrative arc (9 sections / 80 bars)

| Section | Bars | Genre | Energy | Story beat |
|---|---|---|---|---|
| intro | 1–8 | Reggae | 0.25 | Sun coming up — a 3:4:5:7 Em7 **polyrhythm** shimmer builds to unbearable, then drops |
| verse1 | 9–16 | Reggae | 0.40 | "Chillin in the sun zone" — the hook arrives |
| chorus1 | 17–24 | Metal | 0.80 | "NO TIME FOR THAT" — first interruption (discontinuity ↑) |
| verse2 | 25–32 | Reggae | 0.45 | Back to chill, hasn't given up — recurrence + delta (organ doubled, **steel pans** enter) |
| chorus2 | 33–40 | Metal | 0.90 | Second interruption, escalating — recurrence + delta (lead power-octave) |
| break1 | 41–48 | Break | 0.70 | **Convention-break:** reggae groove through a HEAVY amp (metal timbre, reggae time) |
| break2 | 49–56 | Break | 0.68 | **Convention-break:** metal groove turned CLEAN + organ bubble (reggae timbre, metal time) |
| integration | 57–72 | Metal | 1.00 | **Integrating final chorus:** the metal engine FUSED with the intro polyrhythm (organ callback) — accepting life is both crazy and mellow |
| outro | 73–80 | Reggae | 0.35 | **Enlightenment:** reggae beat + steel pans + brief metal double-time bursts (the stress, at peace) |

Every genre flip is a deliberate **energy discontinuity** — never smoothed. Recurring sections are one identity + a delta (`vary()`), never independent copies. The polyrhythm cloud and the "NO TIME" hook are registered **motifs** that the integration and outro **reference** (the recapitulation primitive).

## Instrumentation

| Track | Instrument chain | Role |
|---|---|---|
| 01 Drums | Drum Rack (Hot Rod Kit) → EQ Eight → Drum Buss → Compressor | Beat (reggae one-drop ↔ metal gallop + crashes/fills) |
| 02 Bass | Operator → EQ Eight → Compressor | Pulse + root (walking offbeats ↔ 16th palm-mute pedal) |
| 03 Rhythm Gtr | Tension → **Amp** → Cabinet → EQ Eight → Compressor | Harmonic skeleton + **genre-flip mechanism** (Amp Type Clean ↔ Heavy via envelope; **inverted** in the break) |
| 04 Organ | Operator (Hammond) → EQ Eight → Chorus-Ensemble | Reggae bubbles + the intro polyrhythm + the integration callback (tacet only in the pure metal choruses) |
| 05 Lead | Wavetable → EQ Eight → Compressor | Vocal melody placeholder (+ outro double-time bursts → DubDelay) |
| 06 Steel | Island Pans → EQ Eight | Bright E-Dorian calypso counter-melody — later reggae sections only (verse2 + outro) |

**3 returns**: Plate (Hybrid Reverb), Room (Reverb), DubDelay (Echo — 1/4-note tempo-synced, scale-safe; carries the metal di-di-di echo via a static Lead send).

## The Amp Type envelope

The song's most audible genre-flip device. Rhythm Gtr is a **monolithic session clip** (one clip, 320 beats = whole song / 80 bars); the Amp Type envelope sits on the Amp device with breakpoints at the section boundaries where the genre flips. Live 12.4 LOM requires `device_parameter` envelopes to be hosted by a clip covering the envelope's full beat range — the single-long-clip structure is the cleanest way to satisfy that constraint. In the **convention-break** the Amp is deliberately decoupled from the groove (break1 stays Heavy over the reggae groove; break2 goes Clean over the metal groove).

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

## Verification status

The full arrangement is **DB-verified** (build + 18 shape/intent tests, full suite green) but **not yet Live-verified** — the push → render → analysis → `/mix-review` loop needs Ableton open. One push-time item to confirm: the **Island Pans** browser load (the steel track) resolves by pattern under `instruments`; if not, it's a one-word `preset_query` fix in `captured_session.json`. The final **measured mix pass** (drum trim, ~−1 dBTP true-peak headroom, LUFS/dynamics against the denser new arrangement) is render-gated and deliberately deferred — static levels/sends are set conservatively in the snapshot.

## Deferred (not yet authored)

- Per-section send **automation** (dry-reggae / wet-metal DubDelay) — currently a static Lead send; precise automation needs a render to tune and a host-clip strategy (the Lead is per-section, like the gap the monolithic gtr clip solves for the Amp envelope).
- Vocal Bus track (unnecessary until real vocals; the steel pans now carry the counter-melody role).
- Sidechain compression on bass (kick-driven duck during metal sections).
- Hi-hat opening variations within a bar (closed → open → closed).
- Outro tempo ritardando (Live's per-bar tempo automation has gaps).
