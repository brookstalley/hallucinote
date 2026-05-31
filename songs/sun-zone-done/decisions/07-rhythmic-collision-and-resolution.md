---
date: 2026-05-30
kind: decision
scope: song
tags: [rhythm, feel, microtiming, collision, resolution, outro, variation-ops]
related: [decisions/02-genre-mechanics.md, decisions/06-per-section-feel.md, annotations/genre-alternation-intent.md]
---

# Rhythmic collision & resolution — rhythm is the third colliding world

**Question:** The song's thesis is two worlds colliding (reggae chill vs metal
urgency). Harmony carries it (Dorian↔Phrygian, fusing at the climax) and timbre
carries it (the Amp Type flip). But **rhythm / feel is just as central a dimension
of the collision as harmony or melody** — and until now it only collided at the
*section* grain (whole reggae sections drag, whole metal sections are tight). Two
gaps fell out of that:

1. The **development**, whose whole concept is "the worlds trade bars," morphed
   *harmonically* (Dorian cells answered by the F ♭II Phrygian intrusions, with the
   harmonic rhythm accelerating 4,4 → 2,2,2,2) but stayed *rhythmically* uniform —
   all reggae drag. The collision was only half-realized.
2. The **outro** resolved by *retreating* into sleepy reggae, rather than resolving
   the collision into something new — and an older note even framed it as
   "defeated, exhausted, not victorious."

## Decision (2026-05-30, with the user)

**1 — Rhythm collides too, at the cell grain in the development.** The accelerating
harmonic trade is mirrored in the FEEL: the Dorian/reggae cells lay back (reggae
drag); the F/♭II Phrygian intrusions snap to the metal grid and stab (metal
urgency). As the harmonic rhythm accelerates, the rhythmic whiplash accelerates
with it — the two worlds colliding faster and faster, "NO TIME" cutting into the
chill at shorter and shorter intervals. The collision is rhythmic, not just harmonic.

**2 — The outro RESOLVES the collision into a NEW third feel — not a retreat.**
Enlightenment / acceptance / **joy**: something *new and exciting*, **neither as
sleepy as reggae nor as exhausting as metal**. A lifted, bright synthesis pocket
(between reggae's lay-back and metal's push — a forward, joyful bounce), at a mid
energy (~0.50, up from the sleepy 0.35). The frantic "NO TIME FOR THAT" anxiety
hook is **augmented** (slowed ~2×) into a serene statement — the same melody that
screamed urgency, now at peace; the stress accepted, not banished. A small
**diatonic upward lift** gives the joy its "rising into something new" shape. The
steel pans stay (the bright island joy). The protagonist doesn't give up and
collapse back into chill — they integrate both worlds and arrive somewhere they've
never been.

**Rationale:** Per `feedback_microtiming_is_authorship` and the arrangement-model's
harmony decision, the dimensions that carry the song's meaning must be *authored
and recorded*, not incidental. "The worlds colliding" is a rhythmic statement as
much as a harmonic one — rhythm is co-equal with harmony and melody here.

## Variation ops — in service of meaning, not as a tech demo

Per the user: use a variation op only if it serves the song's meaning; we are not
obligated to demonstrate the whole suite.

- **augment** — **YES.** The "NO TIME" hook slowed into peace (anxiety → acceptance).
  The single most meaning-true variation in the song.
- **transpose_diatonic** — **YES (light).** The outro's joyful diatonic lift (rising
  into the new) — staying in E Dorian so the lift reads as brightening, not
  modulation.
- **invert / retrograde** — **NO.** No meaning-serving role in this arc; reserved
  for a future song. We don't use a variation just because it exists.

## How build.py realizes this (the rebuild recipe — providence)

The point is reproducibility: a clean rebuild must reproduce the collision and the
resolution from this recorded intent, with no one-off hacks.

- Per-world feel is carried by the genre generators themselves (reggae generators
  lay back via their `lazy` / `lag` / `push` defaults; metal generators sit on-grid
  / push) — see `decisions/06-per-section-feel.md` for the per-part offsets.
- The **development is authored by walking the `DEV` progression cell-by-cell**:
  reggae-world groove on the Dorian cells, metal-world stabs (gallop burst, on the
  grid) on the F ♭II cells — so the rhythmic collision is **derived from the same
  harmonic map that drives the pitches** (one source of truth, not a parallel
  hand-edit). Accelerating cells → accelerating trade, for free.
- The **outro** uses `variations.augment` on the registered `no-time-stab` motif
  for the slowed hook, `variations.transpose_diatonic` (mode=Dorian, key=E) for the
  joyful lift, a documented **synthesis feel** (a light forward bounce, distinct
  from both reggae drag and metal grid), and energy `0.50`.

## Open / pending

- **Audio tuning (render-gated):** the exact feel offsets, the augmentation factor,
  the synthesis-feel bounce, and the outro energy are reasoned first-pass values —
  to be confirmed and tuned **by ear** at the next render. The *intent and the
  mechanism* (this document) are the durable part; the numbers are the tunable surface.
- **Humanness (render-gated — from the 2026-05-30 microtiming spot-check):** the
  per-part feel currently applies a CONSTANT offset (a uniformly *shifted* grid:
  reggae drags +0.02–0.06 beat, metal sits tight, the development trades both,
  the outro halves the drag). The DIRECTION is genre-true and the collision +
  synthesis are real in the note data — but the offsets don't *breathe* (no
  per-hit micro-variation), and two parts are dynamically flat (the organ bubble:
  one velocity across 384 notes; the metal pedal bass: one velocity — defensible
  for palm-mutes). Metal staying tight is correct (the genre is machine-tight).
  For the reggae + blend to read as *performed* rather than *programmed*, those
  parts want subtle AUTHORED variation around the characteristic offset/velocity —
  looseness, never random jitter ("nothing sloppy"). Tune by ear; ties to backlog
  GEN-2T8M (humanize/groove module — revisit) and ARR-3R8F (the rhythm axis).
- **Framework question:** whether rhythmic-collision / feel deserves a first-class
  *structural* representation in the arrangement model — the rhythm analog of the
  harmony axis (`ARR-1H9C`). For now it is expressed via the per-call feel mechanism
  + this recorded intent. Tracked in the backlog (`ARR-3R8F`).
