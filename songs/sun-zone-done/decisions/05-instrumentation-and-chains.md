# Instrumentation & Signal Chains

**Question:** What instruments? What signal chains? What sends?

**Answer:** **5 instrument tracks + 3 returns.** Same instruments throughout the song — what changes per section is *how they're played* and the Amp Type setting on the rhythm guitar (the most audible genre-flip device).

**Decided by:** Claude (in dialogue with user, 2026-05-22)

**Rationale:**

### The five instrument tracks

| Track | Instrument | Role | Genre behavior |
|---|---|---|---|
| **01 Drums** | Drum Rack (default kit; pads addressed by note) | Beat | Reggae: one-drop (snare on 3, sparse hats). Metal: gallop (kick 16ths, snare on 2&4, busy hats). |
| **02 Bass** | Operator (warm sine + sub) | Pulse + root | Reggae: rounded sub-bass, half-time, off-beat-of-2-and-4 walking pattern. Metal: same instrument, palm-mute root pedaling on 16ths. |
| **03 Rhythm Gtr** | Tension (synth guitar) → **Amp** → Cabinet → EQ Eight → Compressor | Harmonic skeleton + the **genre-flip mechanism** | Reggae: clean skanks on Em7/Am7 (Amp Type = Clean). Metal: palm-muted E5/F5 power chords (Amp Type = Heavy). **The Amp Type envelope per-section IS the song's most audible genre-flip device.** |
| **04 Organ** | Operator (Hammond-style bell + lowpass) | Reggae bubble + metal screech | Reggae: classic offbeat bubbles. Metal: drops out OR transforms into a high sustained scream. |
| **05 Lead** | Wavetable (warm pad → cutting lead patch) | Vocal placeholder | Reggae: warm sustained pad in E3-E4. Metal: cuts through with a sharper voicing. Placeholder for the eventual vocal hook. |

### Why 5 tracks (not 7)

The previous build went 7 tracks (added Counter-Melody + Vocal Bus). For v1 of the rebuild, **5 is enough.** Counter-melody can be added inside the Lead track via overlapping voicings; the Vocal Bus is unnecessary until there's a real vocal. Reducing track count keeps the mix less crowded and the composition tighter.

### The three returns

| Return | Effect | Purpose |
|---|---|---|
| **Plate** | Hybrid Reverb (Plate preset) | Long dub-style verb. High send on drums (especially snare) during reggae sections; lower send during metal (drier = more punch). |
| **Room** | Reverb (Room preset, tight tail) | Short room for metal punch. High send during metal sections (the guitar + drum kit live in a tight room); low during reggae. |
| **DubDelay** | Echo (1/4 note tap, ~30% feedback) | Classic reggae snare echo — turn up on reggae snare hits, off for metal. |

**Send strategy (initial values, no automation):**

- Drums → Plate: 0.15 (background space)
- Drums → DubDelay: 0.0 baseline (we'll automate or hand-trigger this; see `06-feel.md` for hit-specific routing)
- Bass → all returns: 0.0 (bass stays dry — keep the low end focused)
- Rhythm Gtr → Room: 0.10 (tight room enhances both genres)
- Organ → Plate: 0.20 (organ wants space)
- Lead → Plate: 0.25 (lead carries the vocal-ish role, wants the most space)

These are **initial** sends. If post-push iteration reveals the mix needs adjustments, they're authorship-level — bake them back into the snapshot, don't carry as a "post-push todo."

### The Amp Type envelope — E1's empirical driver

This is the song's structural test of Arc 7-tail's enum-parameter envelope authoring. **Per-section partition** (one envelope segment per section clip on the Rhythm Gtr track):

| Section | Amp Type | Why |
|---|---|---|
| `intro` | Clean | Setting the chill mood. |
| `verse1` | Clean | Reggae character. |
| `chorus1` | Heavy | Metal interruption. |
| `verse2` | Clean | Back to chill. |
| `chorus2` | Heavy | Second metal interruption. |
| `bridge` | Heavy | Sustained metal. |
| `outro` | Clean | Exhausted return to chill. |

**Authoring approach (lesson learned from the prior build):** the envelope **must be authored per session clip** (Live 12.4 LOM requires `device_parameter` envelopes to be hosted by a session clip covering the envelope's beat range). The prior build's mistake was authoring one big envelope spanning all 7 sections — Live couldn't route it because no single session clip covered all 256 beats. This rebuild authors 7 small envelopes, each scoped to a single section's session clip.

Each section's envelope is a single breakpoint at beat 0 of the clip with `curve='hold'` — instantly sets the Amp Type for that section. No transitions within sections; transitions happen at section boundaries via the next clip's envelope.

### Master + Vocal Bus

Master volume: 0.85 (Live's default).

No Vocal Bus track — placeholder vocal lives in the Lead track until real vocals are recorded.

### Out of scope

- **Send envelopes** (e.g. swelling Plate send into a transition). Could enrich the mashup but adds complexity; v1 keeps sends static.
- **Per-track sidechain compression** (kick → bass duck during metal sections). Worth doing post-v1 if the kick gets lost.
- **Saturator on the bass.** Optional warmth/grit; v1 leaves the bass clean to let Operator's tone speak.
- **Hybrid Reverb fancy params.** v1 uses the Plate preset defaults; no algorithm switching, no decay-time automation.
