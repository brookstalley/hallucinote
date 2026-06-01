# 03 — The reveal: reserved sub octave + sub-oscillator root

**Date:** 2026-06-01
**Decided by:** user (sub-osc as the thing that returns), agreed-after-confirm (reserved octave)
**Status:** locked

## Decision

The root's return is engineered as a **timbral and physical** event, not just a
harmonic one:

1. **The entire sub-bass octave (below ~100 Hz) is reserved.** Nothing — bass,
   pad, arp — is allowed weight in the bottom octave for the whole song.
2. **The reveal** (coda) is a **sub-oscillator tuned to E** swelling in over ~4 bars.
   It is the **first energy the listener has heard in the bottom octave all song.**
3. The root emerges *from inside the sound* (sub-osc opening up), not as a new note
   appearing on top — so it feels like the ground rising, not an instrument entering.
4. The **melody lands on E** for the first time at the same moment. Voice and floor
   arrive together = "found / located."

## Rationale

Because the sub register has been withheld for ~4 minutes, the arrival is felt in the
body before it's understood in the ear. The listener won't know *why* it hits so hard.
This is what makes Option A's single resolution worth the entire withholding. See
`annotations/00-theme.md` ("the root is the wound").

## Consequences

- **Bass must be high-passed** ~100 Hz and play non-root tones (`decisions/04`).
- **The kick must also be sub-rolled-off / mid-focused** until the coda — the bottom
  octave reservation applies to drums too, not just the bass (`decisions/08`). The
  reveal is where the kick regains its weight, lands on beat 3 for the first time, and
  the sub-osc E arrives — a triple low-end convergence with the harmonic resolution.
- The sub-osc patch must be authored so its level is fully closed until the coda
  (automation / envelope), then opens over ~4 bars.
- "Found" stays minor — the reveal is Em with a root, not a turn to major.
