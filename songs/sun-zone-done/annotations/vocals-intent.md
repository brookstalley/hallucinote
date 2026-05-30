---
kind: annotation
scope: track
track: 05 Lead
tags: [vocals, lead, placeholder, todo]
related: [annotations/mix-intent-per-section.md, decisions/01-intent-and-theme.md]
---

# Lead / vocals — intent

`05 Lead` currently carries an **instrumental placeholder melody** standing in
for the eventual vocal. The two melodic phrases are the song's hooks and are
authored locally in `build.py` (`_reggae_lead_chillin`, `_metal_lead_no_time`)
— they're song content, not reusable genre idioms, so they live with the song.

Phrase intent:

- **Reggae lead — "chillin in the sun zone"** (E Dorian, mid-register, loops
  every 4 bars). Relaxed, conversational, sits *on* the click (the melodic
  anchor while everything else floats behind). Laid-back phrasing, lots of
  space between phrases.
- **Metal lead — "NO TIME FOR THAT GOTTA GET STUFF DONE"** (E Phrygian, upper
  register, loops every 2 bars). Stabbing, urgent, the Phrygian b2 (F) is the
  trademark — the harmonic shout that interrupts the chill.

## When real vocals land

- Replace the placeholder lead, keeping the same melodic contour and register
  intent (the placeholder *is* the topline).
- Reggae vocal: dry-ish, intimate, maybe a touch of the `DubDelay` throw on
  phrase ends (classic dub vocal echo).
- Metal vocal: more aggressive, forward, drier — matches the metal "wall" intent.
- The protagonist's arc (tries to be productive, gives up, collapses back into
  chill — exhausted, not victorious) should read in the *outro* vocal delivery:
  the return to reggae is defeated, not triumphant.

## Open

- [ ] Record / synthesize real vocals
- [ ] Final lyric beyond the two hook phrases
