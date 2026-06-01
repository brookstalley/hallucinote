---
date: 2026-05-22
kind: decision
scope: song
tags: [structure, sections, form]
---

# Section Structure

**Question:** What's the section layout?

**Answer:** 7 sections, 64 bars total at 180 BPM 4/4 = ~85 seconds. Alternating reggae/metal with the bridge sustaining metal long enough to feel exhausting.

**Decided by:** Claude (in dialogue with user, 2026-05-22)

**Rationale:**

| Section | Bars | Genre | Mode | Story beat |
|---|---|---|---|---|
| `intro` | 1–8 (8 bars) | Reggae | E Dorian | Sun's coming up. Sparse, bass + light skanks fading in. |
| `verse1` | 9–16 (8 bars) | Reggae | E Dorian | "Chillin in the sun zone, rasta vibes flowin in the —" |
| `chorus1` | 17–24 (8 bars) | Metal | E Phrygian | "NO TIME FOR THAT GOTTA GET STUFF DONE." First interruption. |
| `verse2` | 25–32 (8 bars) | Reggae | E Dorian | "Back to chillin..." Slightly more layered than v1 — the song hasn't given up. |
| `chorus2` | 33–40 (8 bars) | Metal | E Phrygian | "STILL NO TIME!" Second interruption, escalating. |
| `bridge` | 41–56 (16 bars) | Metal | E Phrygian | Sustained metal — the relaxation never comes back. Double the chorus length to make the listener feel the protagonist's exhaustion. |
| `outro` | 57–64 (8 bars) | Reggae | E Dorian | Exhausted return. Same instruments, slower-feeling, like collapsing onto a couch after a long day. |

**Why these proportions:**

- **Reggae sections (intro + v1 + v2 + outro = 32 bars).** Equal time given to the "chill" theme so the song reads as fundamentally a reggae song that gets *interrupted*, not a metal song with chill verses.
- **Metal sections (c1 + c2 + bridge = 32 bars).** Equal time, but distributed differently — the bridge concentrates the metal in one long stretch so the listener *feels* the protagonist running out of energy. Two 8-bar choruses + one 16-bar bridge ≠ four 8-bar metal sections; the asymmetry is the dramatic shape.
- **No final metal interruption.** Outro is reggae. The protagonist gives up trying to be productive. Stress doesn't win — but neither does relaxation; the song just ends with someone too tired to fight.

**Why 8-bar units (mostly):**

8 bars is the standard pop verse/chorus length and a multiple of any reasonable phrase length (1, 2, 4, 8 bars). The bridge is 16 because the dramatic intent is "more than expected, exhausting." If sections were 4 or 16 bars, the symmetry would be lost.

**Transitions:**

- **Reggae → Metal:** the last beat of the reggae bar is *silence* (the lyric's em-dash). Then the metal section comes in on the downbeat. Crash + power chord on beat 1.
- **Metal → Reggae:** the last metal bar ends on a sustained power chord (let it ring through beat 4). Then reggae one-drop on the next downbeat. The drop in dynamics IS the contrast.

**Cue points:**

One cue per section (7 cues). Names: `intro`, `verse1`, `chorus1`, `verse2`, `chorus2`, `bridge`, `outro`. Beat positions: 0, 32, 64, 96, 128, 160, 224 (1-based bars × 4 beats/bar, 0-indexed within the timeline).

**Out of scope:**

- Repeated cores (we don't repeat the bridge or do a chorus3). Keeps the song under 90 seconds — punchy.
- Live-style intro/outro that mirror each other note-for-note. Outro is the mood-equivalent of intro but the protagonist is wearier — different bassline emphasis, drums even more laid-back.
