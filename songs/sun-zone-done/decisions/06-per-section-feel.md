# Per-Section Feel & Microtiming

**Question:** What's the groove feel for each section?

**Answer:** Reggae sections **drag** slightly (drums and skanks lay behind the grid by ~3-5%); metal sections sit **exactly on grid** (machine-tight). The microtiming is per-part, baked into the pattern at generation time — not a post-hoc humanize pass.

**Decided by:** Claude (in dialogue with user, 2026-05-22)

**Rationale:**

Per `feedback_microtiming_is_authorship`: feel is part of how a part is written, not something layered on after. The reggae feel and the metal feel are mutually exclusive — there's no global swing setting or song-level groove that works for both. Each pattern carries its own timing offsets.

### Reggae feel (intro / verse1 / verse2 / outro)

| Part | Offset | Why |
|---|---|---|
| **Drums (snare on 3)** | +0.04 beats (lay back) | Classic one-drop snare is *behind* the click. The drag is the feel. |
| **Drums (hi-hat)** | +0.02 beats | Slightly behind, less than snare. |
| **Drums (kick on 1)** | 0.0 (on grid) | The kick anchors. Don't drag the downbeat or the song loses its center. |
| **Bass** | +0.02 beats | Bass walks slightly behind, fattening the pocket. |
| **Rhythm Gtr (skank)** | +0.06 beats | Skanks lay the *most* behind — the iconic reggae lazy chuck. |
| **Organ bubble** | +0.04 beats | Bubbles match the skank's drag. |
| **Lead** | 0.0 (on grid) | Lead/vocal-placeholder sits on the click — it's the melodic anchor. |

The result: kick and lead are tight; everything else floats slightly behind. The pocket *swings* without being explicitly swung. (No 8th-note swing ratio is applied — straight 8ths with lay-back offsets.)

### Metal feel (chorus1 / chorus2 / bridge)

| Part | Offset | Why |
|---|---|---|
| **Drums (kick gallop)** | 0.0 (on grid) | Machine-tight 16ths. Any drag kills the urgency. |
| **Drums (snare on 2 & 4)** | 0.0 (on grid) | Backbeat is *exactly* on. |
| **Drums (hi-hat 16ths)** | 0.0 (on grid) | Robotic 16ths. |
| **Bass (palm-mute pedal)** | -0.01 beats (slightly pushed) | A hair ahead of the click — adds urgency. Some metal drummers do this naturally. |
| **Rhythm Gtr (palm-mute chunks)** | 0.0 (on grid) | Locked with the kick. The kick + guitar lock IS the metal feel. |
| **Lead (cutting)** | 0.0 (on grid) | Lead anchors. |

The result: machine-tight everything, with the bass *slightly* ahead to feel "rushing forward." The contrast against reggae's drag is structural — reggae's drag pulls the listener back, metal's push leans them forward.

### How this is implemented

The reggae/metal grooves live in the shared `hallucinote.generators` package (promoted from this song — it was the flagship that motivated two-genre coverage). `build.py` authors against that surface; the per-pad offsets in the tables above are the **baked-in default parameters** of each idiom, so they're reproduced on every build without the call site restating them:

- **Drums:** one genre function each — `drums.reggae_one_drop(bars, *, kit, lazy=0.04, feel=None)` bakes the per-pad drag (snare + open-hat get the full `lazy`, closed hats half, kick on grid); `drums.metal_gallop(bars, *, kit, feel=None)` emits the gallop cell + 16th-grid hats with no offset. Pads come from the loaded `kit` (`Kit.from_device`), never hardcoded MIDI notes.
- **Bass / Gtr / Organ:** `bass.reggae_offbeat_bass(root, ..., push=0.02)`, `bass.metal_pedal_16ths(root, ..., push=-0.01)`, `harmony.reggae_skank(voicing, ..., lazy=0.06)`, `harmony.organ_bubble(voicing, ..., lag=0.04)`, `harmony.palm_mute_power_chords(root, ...)` (on grid, locked to the kick gallop via the shared `METAL_GALLOP_OFFSETS` cell). The drag/push is the default; the value is visible in the DB note `start_beats`. (Exception: `metal_pedal_16ths` drops the negative push on any note whose absolute onset would land at/before 0.0 — Live's MIDI clip has no negative-beat region.)
- **Two grooves, not one parametrized groove.** There IS now a shared microtiming mechanism — every generator takes a `feel` dict (`Mapping[float, float]` → per-position shift, applied via `primitives.apply_feel`) for additional per-part intent. But reggae and metal stay **separate functions** rather than one `feel`-driven helper, because the grooves diverge on every pad (which pads drag, by how much, on grid vs. off) — collapsing them into one call would just move that per-pad table into the argument. This song passes no `feel` (the baked defaults carry the documented offsets); `feel` is the knob a *future* section or remix would reach for.
- **Lead melodies stay local.** The vocal hooks (`_reggae_lead_chillin`, `_metal_lead_no_time` in `build.py`) are song-specific content, not reusable idioms, so they aren't in the generators package.
- **Microtiming is final.** No `/clip-humanize` velocity-jitter pass on top — the velocities are already shaped (see below) and any timing humanization would muddy the deliberate feel choices.

### Velocity shaping (separate from microtiming, but part of feel)

| Section family | Velocity range | Shape |
|---|---|---|
| Reggae | 60-95 | Wider dynamic range, more variation between hits. Snare 75-85, hi-hat 50-72, bass 70-90, gtr 80-95. The looseness is part of the chill. |
| Metal | 95-115 | Loud, narrow range. Snare 110-115, kick 105-115, gtr 100-115. Everything *committed*. |

Lead velocities sit in the 70-95 range in both genres — the placeholder vocal melody is the same intent across, just the surrounding context flips.

### Why no song-wide groove instance

Live's groove pool would let us load a "reggae groove" template and apply it. But:

1. **No single groove fits both halves.** A reggae groove on metal would kill the urgency; a metal grid on reggae would erase the chill.
2. **Per-part feel needs per-part offsets.** The kick stays tight while the snare drags — a single groove can't model that. (Live grooves are per-clip, not per-pad.)
3. **The DB is the source of truth.** Per `architecture_db.md`: every offset baked into the note lists is reproducible, version-controlled, and survives a re-push. Live grooves are an Ableton concept that doesn't round-trip cleanly through the DB.

### Out of scope

- **Hi-hat opening variations** (closed → open → closed accents within a bar). Worth adding for v1.1 polish but v1 stays with closed hats.
- **Tempo automation for the outro fadeout** (slight ritardando into the final chord). Skipped because Live's per-bar tempo automation has gaps.
- **Late-section velocity decay** (the outro getting quieter as the protagonist runs out of energy). Tasteful but not v1; the genre flip + Amp envelope are doing enough work.
