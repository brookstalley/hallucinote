# 13 — Genre is section-dependent: synthpop choruses, cinematic verses

**Date:** 2026-06-01
**Decided by:** user ("synthpop chorus, cinematic verse") · agreed-after-confirm
(the per-section idiom map + the arc-mapping rationale)
**Status:** concept locked; the exact per-section idiom map is the working plan,
to be confirmed by ear in Live.

## Decision

"missing" does not sit in one genre — it **shifts idiom by section**, and the shift
itself carries the theme:

- **Cinematic electronic = the truth / the wound.** Atmospheric, textural, sustained,
  darker. Purity Ring / Trent Reznor / M83's quieter side. Used for the *interior,
  real* material.
- **Melancholic synthpop = the reach / the false promise.** Dazzling, energetic,
  hook-forward. CHVRCHES / Robyn / M83's anthemic side. Used where the song *reaches
  and lies* — the choruses that deny arrival, the false-summit break.

The pop brightness is the **surface**; the cinematic depth is what's **underneath** it.
Genre is doing thematic work, not just decoration.

## Per-section idiom map

| Section | Idiom | Why |
|---|---|---|
| intro | cinematic | the phantom-root tail; atmospheric, no key yet |
| verse 1–2 | cinematic | lost, drifting, interior |
| chorus 1–2 | **synthpop** | reach / dazzle / denied resolution |
| break | **synthpop** → cinematic | euphoric false summit, then *collapses toward cinematic* at the B7 pivot — the genre-pivot IS the illusion-pivot |
| verse 3 | cinematic | the disabuse — cold, stripped |
| final chorus | **synthpop** | the last reach |
| coda | cinematic | found — located not happy; the dazzle falls away, the real ground appears quiet and close |

The outer frame (intro / verses / coda) is cinematic = the real lost-and-found; the
choruses + break peak are synthpop = the bright, false hope. The song's most euphoric
*sound* sits on its least honest *moments*.

## Texture implications

- **Verse (cinematic):** pads-forward, sustained, open/ambiguous voicings (no dense
  extensions that would clarify the key); the notch-LFO is most audible here
  (`decisions/10`); heavier reverb/atmosphere. Arp recessed + filtered.
- **Chorus (synthpop):** dazzling arp foregrounded + backbeat stabs; brighter, tighter,
  close mid-register, hook-forward. (Chorus voicings: `i–V–iv–V` rootless, E-free except
  in the iv — see the chorus-voicings decision / `build.py`.)

## Coherence with prior decisions (no contradictions)

- **`decisions/07` (energetic):** still holds — the tresillo+backbeat groove runs
  *through* the cinematic verses (atmospheric pads over a driving beat, M83-style).
  "Cinematic" describes the harmonic/textural layer, not an energy drop.
- **`decisions/08` invariant 8 (constant arp pulse):** preserved. The arp's *pulse* is
  constant; its *prominence* is section-dependent — recessed/filtered under cinematic
  verses, dazzling/foregrounded in synthpop choruses. The motion never stops; the role
  changes.

## To confirm by ear (Live)

- The break's synthpop→cinematic collapse at the B7 pivot — how abrupt vs. how morphed.
- Whether the coda is fully cinematic or keeps a ghost of the chorus arp as it grounds.
- Exact verse arp recession level (filtered-and-buried vs. nearly absent).
