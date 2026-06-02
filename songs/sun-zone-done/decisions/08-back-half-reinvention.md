---
date: 2026-06-01
kind: decision
scope: song
tags: [break, integration, verse1, structure, fusion, eureka, strum, mix, atmosphere, feel]
related: [decisions/07-rhythmic-collision-and-resolution.md, decisions/02-genre-mechanics.md, annotations/genre-alternation-intent.md, annotations/mix-intent-per-section.md]
---

# Back-half reinvention — the break became the eureka, the integration became the playground

**Question (user, 2026-06-01):** The `integration` and `break` sections "really
don't work, at all." The integration just *smashes* the metal drums into the reggae
instrumentation; the break is *tedious*. Reinvent both from first principles,
starting from the song's intent. Also: the first verse goes too long before hinting
at the metal side, and the mix clips.

**Decided by:** user + Claude (in dialogue, 2026-06-01), via three confirmed creative
locks-in (AskUserQuestion): break shape = *full suspension → bass drop*; integration
= *experiment-cells → earned fusion*; framework = *keep the interplay song-local*.

## The diagnosis (why the old versions failed)

- **Integration was a smash, not a fusion.** It was literally `met("integration")`
  — a whole metal section (gallop drums + 16th pedal bass + NO-TIME lead) — with the
  reggae polyrhythm organ *layered over* it. Superposition, not combination. The
  rhythmic foundation was incoherent (metal gallop) with a reggae texture bolted on.
- **The break was tedious** because nothing *happened*: it was a normal reggae groove
  (one-drop + skank + the Em/C#↔Em/C slash-bass vote) with one knob flipped (the Amp
  inverted to HEAVY — the old "convention-break"). A held note, not a turning point.

## The narrative re-reading (faithful, not a rewrite)

The back half now tells the story the intent always described — *adapting → accepting
both worlds at once*:

| Section | Story beat |
|---|---|
| development | the worlds **collide** — context-switching whiplash, accelerating (unchanged) |
| **break** | the **EUREKA**: "wait — I don't have to choose." Everything suspends; the bass drops *out*; the two worlds finally *listen* to each other |
| **integration** | the **PLAYGROUND**: applying the insight — actively, playfully *combining* the two (active-while-relaxing, chill-while-working) |
| outro | the settled **synthesis** — arrived (unchanged) |

The existing harmonic payoff (the both-at-once `FUSION_CHORD` + the polyrhythm recap)
**survives** — it becomes the *earned culmination of the play* instead of a cold
smash. The "fuse-hard-in-integration, resolve-in-outro" decision (decisions/07) holds.

## 1 — The break: the eureka suspension (full suspension → bass drop)

Drums **and** bass drop OUT. The section becomes a suspended, ethereal field:

- A sustained polymodal **FUSION pad** (pp) on the organ — the both-at-once sonority
  held quietly, so "hints of both reggae and metal" are present *harmonically and
  simultaneously* (the pad voices Dorian's F#/C# fused with Phrygian's F/C).
- The intro **polyrhythm thinned to a slow, distant shimmer** (two high voices on a
  slow cross-rhythm, pp) — the dawn cloud heard from far away.
- A **half↔double-time call-and-response** on the lead: a *half-time* (augmented,
  slowed) reggae "chillin" fragment as the CALL, answered by a *double-time*
  (diminished, fast) "NO TIME" fragment as the RESPONSE. The two worlds finally
  *answer* each other instead of *interrupting* (the verse/chorus whiplash).
- Sparse high **steel sparkle** — the ethereal top.
- A snare-roll **RISER** across the last two bars (8ths→16ths, crescendo) rebuilds the
  tension the suspension released, launching the **bass DROP** at the integration
  downbeat (a low sub slam + kick — the insight crystallising).

**Harmony declaration.** The break declares a **single sustained chord** (the E tonic
the insight hovers on), which the conformance lens honours as a deliberate field (NOT
stasis — `declared == 1` is never flagged). This is the musically-honest declaration
for a suspension; the pad's richer polymodal colour is a texture, not a lint target.
(The old multi-chord slash-vote `BREAK_H` is retired.) NB: the gate's pressure toward
this choice is logged separately as **LNT-1V9K** — the lens should never *coerce* a
declaration; this one happens to be right anyway.

The break's guitar is **tacet** (the suspension); the Amp envelope simply holds the
preceding Clean (no breakpoint).

## 2 — The integration: the playground (experiment-cells → earned fusion)

Authored **cell-by-cell** from `INTEG_CELLS` (the shared world map — one source of
truth, consumed by both the layer builder and the rhythm-gtr/amp authoring so the
guitar + amp stay aligned with the groove). 32 bars:

| Cell | Bars | What combines |
|---|---|---|
| reggae | 0–4 | reggae one-drop groove + bass + organ, with metal NO-TIME lead stabs ANSWERING — *active while relaxing*. THE bass DROP lands on beat 0. |
| metal | 4–8 | metal gallop engine + pedal bass, with reggae organ + steel FLOATING over it — *chill while working* |
| trade | 8–12 | call & response bar-by-bar: reggae one-drop (half-time) ↔ metal gallop (double-time), the worlds in dialogue |
| both | 12–16 | both engines interlocking + the NO-TIME lead, rising into the climax |
| climax | 16–32 | both worlds full + the **polyrhythm recap** + the both-at-once **FUSION_CHORD** — the EARNED payoff |

**The genre-flip device plays too.** The guitar is a CLEAN reggae skank through cell A,
then the HEAVY power-chord engine from cell B on — so the Amp envelope makes ONE
internal Clean→Heavy flip *inside* the integration (bar 137+4), not at its boundary.
The hinge device itself "plays with combinations."

The bass voices `INTEG` (power chords — root+5th, in-mode) across every cell, so the
harmony-conformance lens passes (the harmonic through-line of the playground).

## 3 — verse1 metal punctuation

A subtle 1-bar Phrygian punctuation ~halfway through verse1 (bar 12): the one-drop
yields to a softened gallop+crash burst and the chillin lead cuts out for the "NO
TIME" head, then the groove resumes. The metal side *pokes through* the long chill
before chorus1's full interruption. Kept low-velocity — a shadow, not the flip.

## 4 — The reggae guitar: a STRUMMED electric (the strum rake)

The reggae skank "almost" sounded right but read as a keyboard *stab*, not a strummed
electric guitar — because the chord tones hit dead-synchronously. Fix: a **strum
rake** (`_strum`) staggers the notes that share an onset low→high (~4 ms/string at 180
BPM) and nudges the top strings a hair louder — a pick stroke. Applied to every reggae
skank (before the 1/f breathing). Song-local for now; a candidate for promotion once
**GEN-1S4K** (generator altitude) is resolved. The exact spread is render-gated.

## 5 — Mix: clipping headroom + per-section "space"

- **Clipping headroom (preliminary).** Master 0.85→0.80 and drums 0.75→0.70 in
  `captured_session.json` — conservative headroom, needed more now that the
  integration is denser. Final true-peak/LUFS tuning is **render-gated** (the mix pass).
- **Per-section pan/reverb space (MIX-3S7P, the clip-hosted route).** The intro dawn
  cloud + break suspension get a wetter Plate tail + a wider image; the mix **snaps
  back to baseline at verse/chorus automatically**. The trick (the user's): each
  envelope's breakpoint range sits ENTIRELY inside the per-section clip that hosts it
  (the organ's intro clip; the lead/steel break clips), so the push hosts it there and
  nowhere else — no monolithic host clip needed. Envelope identity is `(track, kind,
  return, parameter)`, so each (track, param) carries only ONE clip-local timeline →
  the organ serves the intro, the lead+steel serve the break (no collision). Amounts
  are conservative; render-gated to tune.

## Framework note (the interplay gap — kept song-local)

The integration's interplay (call-response, half/double-time trade, simultaneous
interlock) is authored **by hand** in `build.py` (`_integration_play`, `INTEG_CELLS`),
NOT via a new generator primitive — the confirmed framework decision. The *reason* the
old integration was a smash is the toolkit's coarse altitude: it could build "a whole
reggae section" or "a whole metal section" or "trade whole bars", but had no vocabulary
for two worlds *interplaying*. That gap is recorded as **GEN-1S4K** (generator altitude
/ creativity ceiling) and **ARR-3R8F** (rhythm/feel collision as a structural axis) —
this section is the concrete second data point for both. The interplay stays song-local
until a second song needs it (don't add public API speculatively).

## Open / render-gated

- The break's exact feel (riser shape, shimmer density, call-response spacing),
  the integration cell balances, the strum spread, the atmosphere send/pan amounts,
  and the clipping headroom are reasoned first-pass values — **tune by ear at the next
  render** (the push → render → `/mix-review` loop).
- Per-cell breathing in the integration playground (the reggae-leaning cells could
  breathe while the climax stays tight) is a render-gated dial — v1 keeps the
  integration machine-tight.

## v2 — the render-gated tuning pass (user listen-back, 2026-06-01)

After the first push + render, the user listened and gave three directed notes (the
render-gated loop working as designed). All three are *refinements within* the v1
structure, not a re-reinvention:

**1 — Integration: "too loud, too relentless; switch back to the reggae amp sometimes,
and probably music as well — more combinations of sound design, music, rhythm."** The
mix-analysis confirmed it: the rhythm gtr was the section's primary masker (Steel 0.62,
**Organ 0.50 in the lows** — burying its OWN polyrhythm recap, the point of the climax),
and the section clipped (+1.52 dBTP). v1's amp was a single Clean→Heavy flip (Clean cell
A, Heavy for 28 bars straight) — relentless. v2 makes the guitar PLAY the playground
cell-by-cell from `INTEG_CELLS` (one source of truth with `_amp_segments`): a Clean skank
in the reggae cell, the Heavy engine in metal/both, a **bar-by-bar Clean↔Heavy amp trade**
in the trade cell (the genre-flip device itself plays the call-and-response), and a climax
that **OPENS** — the last 8 bars drop from a chugging wall to sustained power-chord swells
(`_integration_climax_gtr_swells`) so the recap + the both-at-once FUSION chord ring
through. Power-chord velocities pulled from 108 → 84–92; the climax organ recap boosted
(+20) so it cuts the wall. The arrange/thin fix (fix-order #1), not just a fader pull.

**2 — Break: "strong! but add some metal guitar drifting through, much lower volume than
usual, with extreme pan."** v1's break guitar was tacet. v2 adds `_break_drift`: sparse
SUSTAINED E power chords at a ghost velocity (30) through the **Heavy** amp (the break amp
is now Heavy for the drift), swept hard L↔R by a clip-spanning, bookended pan automation
(`_author_break_drift_pan`) — centered everywhere else, so only the drift wanders. The
metal anxiety still echoing in the moment of peace, distant. The suspension (pad / shimmer
/ call-response / riser) is untouched.

**3 — Development: "too repetitive… parts that are just glued together differently; needs
more through-composition."** Correct: v1 tiled one ~5-bar collision cell ~5×. v2 rewrites
`_dev_collision` as a THROUGH-COMPOSED 3-phase arc: bars 0–8 a settled reggae groove with
brief metal POKES; 8–16 2-bar reggae↔metal trades with the intro polyrhythm cloud CREEPING
back into the organ (`_dev_polyrhythm_creep`, foreshadowing the integration recap) and the
steel ENTERING; 16–24 rapid bar-by-bar whiplash accelerating, the chillin lead FRAGMENTING
under NO-TIME stabs, a gallop crescendo + a snare FILL (`_dev_fill`) launching the break's
drop-out. The contrast intensifies toward the eureka; continuous threads (the creep, the
steel, the rising velocity) carry through, so it reads as a build, not glued blocks. Stays
faithful to genre-alternation-intent — the development TRADES (true fusion is the
integration's job).

**Still render-gated (v2):** the drift's ghost level through the Heavy amp, the pan-sweep
shape, the integration cell velocities, the climax-swell level, the development fill, and
the master clipping headroom (the v2 thinning should help the +1.52 dBTP) — tuned on the
v2 render. Tests + the notes baseline regenerated for the v2 shape (intentional musical
change, per `regen_notes_baseline.py`).
