# Canary: `odd-meter-experimental`

## Shape

A 2-minute experimental instrumental in **7/8** with a polyrhythmic core (a 5-against-7 ostinato in the bass against the 7/8 drum cycle) and **two simultaneous notional tempos** — a slow harmonic layer at MM=72 (dotted quarter) and a fast percussive layer that implies MM=168 (eighth) on top of the 7/8 base. **Six tracks**: drums (MIDI), polyrhythm bass (MIDI), harmonic pad (MIDI), arpeggio (MIDI), bell-tone accents (MIDI), perc click (MIDI). **One return** (reverb). **Master**. **Notional base tempo: 168 BPM** (the eighth-note pulse).

Section shape:

| Section | Bars (7/8) | Length-in-eighths | Vibe |
|---------|------------|-------------------|------|
| `intro`    | 1–8     | 56  | Click + bell only, establishing the 7 cycle. |
| `lock`     | 9–24    | 112 | Add 5-against-7 bass; ear locks onto the polyrhythm. |
| `bloom`    | 25–40   | 112 | Harmonic pad enters (one chord per 14 eighths — implies MM=72 dotted quarter). |
| `fracture` | 41–48   | 56  | One bar changes to **5/8**, one to **6/8**, then back to 7/8 — meter ratchet. |
| `release`  | 49–56   | 56  | Drop to pad + bell, slow fade. |

## What this canary exercises

**The 1/64 grid encoding (the main target).** Per VISION.md: "multiple simultaneous tempos via 1/64 grid encoding." This canary writes a 5-against-7 polyrhythm where the bass plays 5 evenly-spaced notes per 7/8 bar. The fundamental subdivision needed is the LCM of 5 and 14 (the 7/8 bar in eighths) = 70 ticks per bar. The DB stores beats; positions need fractional-beat precision down to roughly 1/70 of a beat. Exercises whether `beat_start_in_bar` math and the push planner's beat-to-tick conversion survive non-power-of-2 subdivisions.

**Meter changes mid-song.** `fracture` section ratchets between 7/8, 5/8, 6/8. Exercises section-level `time_signatures` (per project-state.yaml, sections + scenes can carry per-section meter) and whether the push planner correctly emits per-section signature changes.

**7/8 (non-4/4) as the BASE meter.** Falling-walking is 4/4 throughout. Songs in 7/8 stress every place where bar-to-beat math quietly assumed 4 beats/bar. Per the J-6 health-check note, schema invariants enforce 1-based bar convention; this canary stresses whether THE BEAT side of that convention has equivalent 7/8 hygiene.

**Bars-of-different-length within the same section.** `fracture` mixes 7/8, 5/8, 6/8 bars. Exercises whether the section model assumes uniform bar length or whether each bar's signature is independently addressable.

**Note positions that don't fall on integer beats.** 5-against-7 puts notes at offsets like 0, 1.4, 2.8, 4.2, 5.6 beats within a 7-beat bar. Float vs. decimal vs. rational storage matters — surface what the DB does.

## Out of scope for the canary

- No tempo changes (the "two simultaneous tempos" is notional — both encoded against the 168 BPM base). The genuinely-multi-tempo case (tempo automation lane) is W3-later and out of v1.
- No third-party plugins (Live's stock Operator on every track).
- No vocals.

## Success criteria for the agent

Same as the other two canaries — scaffold + build.py + captured_session.json + tests, record every friction, do not push to Live.

Specifically log:

- **How does the agent express 5-against-7?** Does the library help? Do they hand-author float beat positions? What precision does the DB preserve?
- **How does the agent encode `fracture`'s mid-section meter changes?** Per-section signature works for the section transition; the *within-section* meter ratchet is the harder case. Does the data model support it? If not, that's a major v1 scope finding.
- **What does the test shape look like for 7/8?** Falling-walking's tests assume 4/4 implicitly (e.g., `bars * 4 == beats`). Surface where those implicit assumptions are.
- **Does any generator in `src/hallucinote/generators/` assume 4/4?** If `tresillo_bass` or any other generator computes positions via `bar * 4`, surface it.
