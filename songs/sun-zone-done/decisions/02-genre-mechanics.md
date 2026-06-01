---
date: 2026-05-22
kind: decision
scope: song
tags: [genre, structure, reggae, metal, alternation]
---

# Genre Mechanics — Alternation, Not Overlap

**Question:** Reggae and speed metal don't share an idiom. How do they coexist?

**Answer:** They don't coexist — they *alternate*. Each genre gets to be itself fully, on its own sections. The same root key + tempo + instruments persist across the alternation so the listener hears one song, not a mashup tape. The drama lives in the *transitions*, not in any single section.

**Decided by:** Claude (in dialogue with user, 2026-05-22)

**Rationale:**

The intent doc (`01`) commits to alternation explicitly. The structural shape mirrors the lyric:
> "chillin in the sun zone, rasta vibes flowing in the — NO TIME FOR THAT GOTTA GET STUFF DONE"

The mid-sentence cutoff IS the song's interruption mechanic. Every reggae→metal transition is the lyric's interruption point. Every metal→reggae transition is the moment of "ok back to chill."

**What ties the sections together (so it sounds like one song):**

1. **Constant tempo (180 BPM).** Metal sections inhabit 180 directly (16th-note gallop = urgency). Reggae sections feel half-time (skanks on the off-beat of beats 2 and 4 ⇒ effective pulse at 90).
2. **Constant root (E).** Both modes share E as tonic. Mode flips Dorian → Phrygian; see `03`.
3. **Shared instrumentation.** Drums, bass, rhythm guitar, organ, lead. Same five tracks throughout — what changes is the playing style + the Amp Type setting on the guitar.
4. **One mixed timbre.** The Amp Type enum-envelope (Clean ↔ Heavy) on the rhythm guitar is the single most audible genre-flip device. Same physical instrument, same string sound at the input — the amp model is what makes metal *be* metal. (Empirical-Live driver for E1's enum-parameter envelope authoring.)

**What changes per section:**

- **Drums:** reggae one-drop (snare on beat 3) ↔ metal gallop (kick gallops + 16th hats).
- **Bass:** reggae walking root-5-octave on the off-beat ↔ metal palm-mute root pedaling.
- **Rhythm gtr:** reggae off-beat skanks on Em7/Am7 voicings (Amp = Clean) ↔ metal palm-muted power chords on E5/F5 (Amp = Heavy).
- **Organ:** reggae bubbles on the off-beats (the iconic Hammond chuck) ↔ drops out or becomes a screaming sustained lead in metal sections.
- **Lead:** reggae sketches the vocal melody warm + slow ↔ metal pushes it into a cutting tone.

**The transition mechanic:**

Reggae → Metal: a single beat of silence on the last "and" of the final reggae bar, then a downbeat crash + power chord. The silence reads as the lyric's em-dash.

Metal → Reggae: a long sustained final metal chord, then drop straight into the reggae one-drop on the next downbeat. The contrast is the joke.

**What this is NOT:**

- Not a fusion/hybrid — no single section that's "reggae-metal" simultaneously.
- Not a tempo change — the BPM stays constant; only subdivision and articulation change.
- Not a key change — the root is E throughout; only the mode flips.
