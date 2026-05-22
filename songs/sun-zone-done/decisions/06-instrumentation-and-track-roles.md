# Instrumentation & Track Roles

**Question:** What tracks does this song need, and what's each track's role across the genre alternation?

**Answer:** **6 instrument tracks + 1 empty vocal bus + 2-3 returns.**

| # | Track | Reggae role | Metal role | Register |
|---|-------|-------------|------------|----------|
| 1 | **Drums** | One-drop (snare/rim on beat 3 of 2-bar, kick on 1, hi-hat 16ths sparse) | Galloping double-kick, ride patterns, china hits on bII chord stabs | Full range |
| 2 | **Bass** | Melodic walking, syncopated, slides | Palm-muted root-pumping, locked to kick gallop | E1–E3 |
| 3 | **Rhythm guitar** | Clean channel: skanks on 2&4 (off-beats), short decay, high voicings | Dirty channel: palm-muted gallops, power-chord stabs on bII | Above E3 |
| 4 | **Organ** | Bubble (16th-note off-beats, drawbar voicing high) | **Silent** (drops out entirely) | E4–A5 |
| 5 | **Lead voice** *(placeholder)* | Clean tone: lyrical melodic line, behind the beat | Dirty tone: rhythmic shout-melody, locked to vocal cadence | E3–E4 (up to G4) |
| 6 | **Counter-melody lead** | Permanent hook material above the vocal — chorus/bridge primarily | Permanent hook material above the vocal — chorus/bridge primarily | B4–E5 |
| 7 | **Vocal bus** *(empty)* | Pre-wired for vocals; sidechain target source after tracking | (same) | E3–E4 |

**Decided by:** user (gave the track list explicitly: "drums, bass, rhythm guitar (clean↔dirty channel-switched), organ, lead voice (placeholder), counter-melody lead, empty vocal bus")

**Rationale:**

**Why only one rhythm guitar track (channel-switched), not two?**
Two separate tracks (clean-reggae, dirty-metal) would double the track count and tempt the composer to let them overlap. One track that channel-switches enforces the alternation discipline — only one guitar tone exists at a time, by construction. The "channel switch" is authored as an instrument-chain change at section boundaries (in practice: two instances on the track at different times, or amp-state automation, depending on what the chosen instrument supports).

**Why does organ drop out in metal sections?**
Organ in a metal context reads as cheesy (carnival, prog-rock, not the intent here). Its *absence* in metal sections is also a textural cue — the listener associates organ-present with "chill" and organ-absent with "urgency." That asymmetry strengthens the genre identity of each section.

**Why a separate counter-melody lead?**
The placeholder lead voice will get muted when vocals come in. The counter-melody lead carries permanent hook material above the vocal — chorus payoff lines, bridge motifs. Splitting these into two tracks lets the mute happen cleanly.

**Returns (proposed, finalized during instrument pick):**
- **Reverb (medium plate)** — for reggae spaces.
- **Reverb (short room)** — for metal tightness.
- **Delay (dub tape)** — for reggae transitions, possibly the WHACK aftermath.

Two reverbs (not one) because the genres want different spaces. The send levels per track are the mix-time authorship that ships in `captured_session.json`.
