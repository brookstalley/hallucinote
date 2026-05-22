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

- **Drums:** the drum helper accepts a `feel` parameter. Reggae sections pass `feel='drag-skank'` (custom per-pad offsets per the table above); metal sections pass `feel='straight'`.
- **Bass / Gtr / Organ / Lead:** the build authors notes with explicit `start_beats` offsets — the offsets are encoded in the hand-authored note lists, not computed at runtime. This makes the feel inspectable at compose time + visible in the DB.
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
