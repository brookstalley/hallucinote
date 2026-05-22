# Frequency & Spatial Discipline

**Question:** Reggae and metal both have busy mids. How does this song stay clean at transitions and through both genre modes — especially with a vocal hole reserved?

**Answer:** **Composition-time frequency carving** (not a mix-time EQ pass) + **center-dry channel reserved for vocals** + **send-based wet space** for everything that can't live dry.

**Decided by:** inferred and proposed, agreed by user (from "clean production around transitions so it's not muddy")

**Rationale:**

The "no muddy transitions" requirement and the "vocal hole pre-carved" requirement are the same problem at different scales. Solution is consistent across both: assign each track to a specific frequency band and stereo position *at write time*, and don't violate it.

## Frequency bands (composed-in, not EQ'd-in)

| Band | Hz range | Owner |
|------|----------|-------|
| Sub | 30–80 | Kick + bass fundamental |
| Bass | 80–250 | Bass body, metal palm-mute thump |
| Low-mid | 250–500 | Snare body, kick click, guitar low strings |
| **Vocal** | **500–3000** | **Lead voice → future vocals (RESERVED)** |
| Hi-mid | 3000–6000 | Skank/comp transients, organ presence, hi-hat |
| Air | 6000+ | Cymbals, organ harmonics, lead-voice consonants |

**Rule:** No instrument plays sustained content in the Vocal band except the lead voice / vocals. Skanks are short transients (energy is in attack, not sustain), so they pass through the band but don't *live* there. Organ voicings are written above 500 Hz on average — when an organ note dips low, it's a short stab, not a held chord.

## Stereo position

| Position | Owner |
|----------|-------|
| **Center, dry** | Kick (low), Bass (low), **Vocal (mid)** |
| Center, wet | Lead voice (counter-melody on a send) |
| Wide left | Clean rhythm guitar (skanks); dirty rhythm guitar L-double |
| Wide right | Organ; dirty rhythm guitar R-double |
| Sends | Plate reverb (reggae), Room reverb (metal), Dub delay |

**Rule:** Anything that's not kick, bass, or vocal either pans out or goes wet. Center-dry above 200 Hz is the vocal's seat.

## Rhythmic carving (when two tracks share a band)

When a track's content lands in the vocal band momentarily (e.g., organ bubble dipping low, lead voice playing the melody), the rule is **call-response with the vocal cadence**: instruments hit *between* the vocal phrases, not under them. This is composition-time, written into the patterns themselves.

Reggae does this automatically (skanks on 2&4, vocal on 1&3). Metal must do it deliberately: shouts on downbeats, chug fills in the gaps.

## Sidechain ducking (pre-wired in snapshot)

- Organ ducks under lead voice (4-5 dB, fast attack, ~80ms release).
- Rhythm guitar ducks under lead voice (3-4 dB, similar).
- When vocals are tracked, repoint sidechain source from lead voice → vocals.

This ships in `captured_session.json` as part of the device chain — it's authorship, not a follow-up mix pass.

## What this prevents

- **Mud in metal sections:** rhythm guitar low strings (palm-muted gallop in 80-250 Hz) don't fight bass because bass body lives in the same band but with completely different rhythmic content (long sustains vs. short stabs).
- **Mud in reggae sections:** organ in 4-6 kHz, bass below 250 Hz, skanks in transient 1-3 kHz — three roles, three bands.
- **Transition mud:** because organ drops out entirely in metal sections, and rhythm guitar channel-switches between clean and dirty, there's no double-occupancy at the seam.
- **Vocal arrival doesn't break anything:** the band and the center-dry channel are already empty.
