# Sun Zone / Stuff Done

> **Composer intent + dated decisions** for this song live alongside this overview.
> The `decisions/*.md` records are **historical** — the original v2 design. The
> **current** structure (the arrangement-model rebuild) is the Structure section
> below; where they differ, this overview is authoritative.
>
> - `decisions/01-intent-and-theme.md` — user's original brief (the load-bearing source)
> - `decisions/02-genre-mechanics.md` — alternation, not overlap; transition mechanics
> - `decisions/03-key-tempo-meter.md` — E Dorian ↔ E Phrygian; 180 BPM; 4/4
> - `decisions/04-section-structure.md` — original 7-section/64-bar shape (superseded by the 9-section/184-bar through-composed arc below)
> - `decisions/05-instrumentation-and-chains.md` — instrumentation + the Amp Type envelope (now 6 tracks; see below)
> - `decisions/06-per-section-feel.md` — microtiming as authorship (reggae drag, metal straight)
> - `decisions/07-rhythmic-collision-and-resolution.md` — **(current)** rhythm is the third colliding world; the development collides rhythmically, the outro resolves into a new joyful synthesis
>
> Query via `/song-context [topic]` (FTS5-indexed). See `.prawduct/artifacts/song-conventions.md`.

---

## Concept

Reggae × speed-metal mashup. Alternating (not overlapping) sections express the tension between wanting to relax and having too much to do. The genres are antithetical on every axis (tempo feel, articulation, harmonic mood) and that contrast IS the song. Each transition is an interruption — exactly the rhetorical structure of the lyric:

> "chillin in the sun zone, rasta vibes flowin in the — NO TIME FOR THAT GOTTA GET STUFF DONE"

Fun, but not a novelty song: the harmony carries the joke. The arc is a story of *adapting* — the protagonist stops fighting and learns to hold both the crazy and the mellow at once.

> **Authored on the `hallucinote.arrangement` + `hallucinote.theory` modules** (`.prawduct/artifacts/arrangement-model.md`): the section map, energy curve, **per-section harmonic progressions** (the harmony axis), recurrence deltas, motifs, and references are all expressed through the model, and a build-time conformance lens fails the build if a section's parts don't realize its declared harmony (the structural fix for the old one-chord drone) — sun-zone-done is its first full demonstration. `build.py` is the integration proof.

## Core specs

- **Key:** Em — root E throughout, modes flip Dorian (reggae) ↔ Phrygian (metal)
- **Tempo:** 180 BPM (constant)
- **Time signature:** 4/4 (constant)
- **Length:** 184 bars (~4:05) — through-composed (no section is a literal repeat)

## Structure — the narrative arc (9 sections / 184 bars, through-composed)

Root **E throughout** — the song never modulates away; the *mode* evolves (Dorian reggae ↔ Phrygian metal) and fuses at the climax over an E pedal. Harmony is first-class: every section past the intro voices a real **moving progression**.

| Section | Bars | Genre | Harmony (the moving progression) | Energy | Story beat |
|---|---|---|---|---|---|
| intro | 1–16 | Reggae | E Dorian — Em7 dawn drone | 0.25 | Sun coming up — a 3:4:5:7 Em7 **polyrhythm** shimmer builds to unbearable, then drops |
| verse1 | 17–40 | Reggae | i–IV–♭VI–ii … B7 (V7/i push) | 0.40 | "Chillin in the sun zone" — the hook arrives |
| chorus1 | 41–56 | Metal | E Phrygian — i–♭II Neapolitan + ♭VI–♭VII | 0.80 | "NO TIME FOR THAT" — first interruption (discontinuity ↑) |
| verse2 | 57–80 | Reggae | richer: Em9–A7–C#m7♭5–Bm7 | 0.45 | Hasn't given up — harmonic development + **steel pans** enter |
| chorus2 | 81–96 | Metal | E Phrygian — darker, more motion | 0.90 | Second interruption, escalating — lead octave-down doubled |
| development | 97–120 | Reggae↔metal **collide** | Dorian cells answered by Phrygian; harmonic rhythm accelerates | 0.70 | The worlds **trade bars — harmonically AND rhythmically** (reggae drag ↔ metal stab), accelerating |
| break | 121–136 | Break | suspended polymodal field over an E pedal (single declared chord) | 0.72 | **EUREKA (decisions/08):** drums+bass drop OUT — an ethereal FUSION pad + thinned shimmer + a half↔double-time call-response; a riser launches the bass DROP. "I don't have to choose." |
| integration | 137–168 | Metal | polymodal — a both-at-once split chord (F#/F, C#/C) over an E pedal | 1.00 | **PLAYGROUND → CLIMAX (decisions/08):** the worlds COMBINED cell-by-cell (groove+lead answering, gallop+float, trade, interlock) → the earned fusion (polyrhythm recap + both-at-once chord) |
| outro | 169–184 | Reggae→**synthesis** | re-brighten to E Dorian, land a warm Em9 | 0.50 | **RESOLUTION → something NEW:** joyful synthesis, neither sleepy-reggae nor exhausting-metal; the "NO TIME" hook **augmented** (slowed) into peace + a diatonic lift; steel-pan joy |

Every genre flip is a deliberate **energy discontinuity** — never smoothed. The worlds collide on **three axes — harmony, timbre, AND rhythm/feel** (the development trades feel cell-by-cell, not just chords; see `decisions/07`). The back half (**`decisions/08`**) tells the *adapting* story: the **break** is the EUREKA suspension (drums+bass out, an ethereal fusion field, a half↔double-time call-response where the worlds finally *answer* each other), then the **integration** is the PLAYGROUND — the two worlds genuinely *combined* cell-by-cell, building to the **earned** fusion climax; the **resolution lands in the outro** — not a retreat to sleepy reggae but a *new, joyful synthesis* (a confirmed creative decision). Recurring sections are one identity + a delta (`vary()`) — chorus2 lead = chorus1 lead octave-down; verse2 = verse1 + steel + a richer progression — never independent copies. The polyrhythm cloud and the "NO TIME" hook are registered **motifs** that the break, integration, and outro **reference** (the recapitulation primitive).

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

The song's most audible genre-flip device. Rhythm Gtr is a **monolithic session clip** (one clip, 736 beats = whole song / 184 bars); the Amp Type envelope sits on the Amp device with breakpoints at the section boundaries where the genre flips. Live 12.4 LOM requires `device_parameter` envelopes to be hosted by a clip covering the envelope's full beat range — the single-long-clip structure is the cleanest way to satisfy that constraint. The guitar is **tacet in the break** (the eureka suspension), so the Amp simply holds the preceding Clean there. In the **integration** the device itself "plays with combinations" (decisions/08): a CLEAN reggae skank through cell A, then HEAVY from cell B on — one internal Clean→Heavy flip *inside* the section rather than at its boundary.

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

The full arrangement is **DB-verified** (build + 20 shape/intent tests + the build-time harmony-conformance lens, `ok=True`) but **not yet Live-verified** — the push → render → analysis → `/mix-review` loop needs Ableton open (a render-pipeline reset — full Live reopen — is the current gate; the multi-stem capture went stale). One push-time item to confirm: the **Island Pans** browser load (the steel track) resolves by pattern under `instruments`; if not, it's a one-word `preset_query` fix in `captured_session.json`. The final **measured mix pass** (drum trim, ~−1 dBTP true-peak headroom, LUFS/dynamics against the denser new arrangement) is render-gated and deliberately deferred — static levels/sends are set conservatively in the snapshot.

## Deferred (not yet authored)

- Per-section **atmosphere** (intro + break) IS now authored — clip-local pan + Plate-send envelopes hosted by the per-section clips, snapping back to baseline at verse/chorus (decisions/08, MIX-3S7P). The amounts are render-gated to tune.
- A **song-spanning** dynamic send (dry-reggae / wet-metal DubDelay across the whole arc) still needs a host-clip strategy (it crosses the metal-chorus gaps where the source track is tacet) — tracked in MIX-3S7P. The Lead DubDelay stays a static send for v1.
- Vocal Bus track (unnecessary until real vocals; the steel pans now carry the counter-melody role).
- Sidechain compression on bass (kick-driven duck during metal sections).
- Hi-hat opening variations within a bar (closed → open → closed).
- Outro tempo ritardando (Live's per-bar tempo automation has gaps).
