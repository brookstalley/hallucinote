# Generator-Altitude Policy — helpers are rulers, never stamps

**Status:** decided (2026-06-03). **Backlog:** GEN-1S4K. **Related:** ARR-3R8F
(the rhythm/feel interplay axis — same gap from the rhythm side), GEN-2T8M
(LLM-direct vs deterministic transform — same "is the helper making the musical
decision?" test), ARR-8P5K (axis/altitude umbrella).
**Principles:** `feedback_great_art_not_software`, `feedback_tools_are_conveniences_not_limits`,
`feedback_prefer_llm_over_deterministic_module`. **Sibling:** `gate-verdict-policy.md`
(the read-side ruler-not-stamp; this is the authoring-side one).

## The principle

A generator/helper is a **ruler, not a stamp**. It exists to remove repetitive
BOOKKEEPING — never to make a musical decision. The decision is the composer's
(or the LLM-as-composer's); the helper just places the notes the decision implies.

Raised by the user (2026-06-01, sun-zone-done back-half), verbatim:

> *"I'm worried about this reliance on generators. We shouldn't be limited to what
> they can do; they are only meant to make repetitive tasks easier."*
> *"your comment about generators building a 'whole reggae section' or 'whole metal
> section' is proof — we are generating at too high of a level, or at least locking
> ourselves into song sections rather than musicality."*

## The worked example — the integration "smash" (the proof)

sun-zone-done's `integration` section was meant to be the protagonist *combining*
the two worlds (reggae + metal) — active-while-relaxing, discovery, play. It came
out a **smash, not a fusion**: a whole-metal-section (gallop drums + 16th pedal
bass + no-time lead) with the reggae organ merely *layered over* it.

Why? The available toolkit offered only **whole-section builders**
(`_reggae_layers`/`_metal_layers` → the `reg()`/`met()` helpers in
`songs/sun-zone-done/build.py`) or a **whole-bar trade** (`_dev_collision`). There
was **no vocabulary for interplay** — call-and-response, half/double-time dialogue,
simultaneous interlock of two worlds at the bar/cell grain. So the only move the
abstractions afforded was *superposition*. The smash is the direct artifact of the
altitude problem: when the available helper is "give me a reggae section," you
assemble *sections*, not music, and anything living BETWEEN or ACROSS archetypes
has no purchase. (The eventual fix, `_integration_play` + `INTEG_CELLS`, had to be
hand-authored song-local — the second song-local interplay site after
`_dev_collision`; see ARR-3R8F.)

## The altitude ladder

Three altitudes a helper can sit at — only the bottom two are legitimate, and only
the very bottom is package-shippable as a genre-neutral building block:

1. **Section / genre-ARCHETYPE builder** — builds a WHOLE section: which
   instruments play, what each plays, how they relate, the density, the feel.
   *This is a STAMP* — it makes the arrangement decision. Example:
   `_reggae_layers` / `_metal_layers` / `reg()` / `met()`.
2. **Single-part genre IDIOM** — realizes ONE part's pattern from composer-supplied
   musical parameters (a progression, register, feel). Convenient but coarse
   (bundles a genre's pattern + feel + velocity for that one part). Example:
   `harmony.reggae_skank`, `drums.metal_gallop`, `bass.reggae_offbeat_bass`,
   `harmony.organ_bubble`, `harmony.palm_mute_power_chords`.
3. **Sub-musical PRIMITIVE** — a genre-neutral building block the composer combines
   freely: a chord-tone set, a feel offset, an offbeat placement, a voicing
   strategy. Example: `primitives.chord_tones`, `primitives.apply_feel`.

## The decision (the rules)

- **R1 — The altitude line.** A package generator may realize ONE part's pattern
  from composer-supplied musical parameters. It may NOT decide WHICH parts play,
  HOW they relate, or a section's arrangement. The former is bookkeeping (a ruler);
  the latter is the composition itself (a stamp).
- **R2 — No section/genre-archetype builders in the package, ever.** Altitude-1
  builders may exist ONLY as song-local conveniences inside a song's `build.py`,
  explicitly understood as *disposable scaffolding* the composer breaks out of the
  moment the music wants something between or across archetypes. They are never
  promoted to `hallucinote.generators`.
- **R3 — Single-part genre idioms stay, as decomposable conveniences over exposed
  primitives — never the only door.** Altitude-2 idioms are legitimate (single
  part, chord-aware/parameterized) AS LONG AS the composer can always drop BELOW
  them to the primitive layer for a shape the idiom doesn't cover. The idiom is a
  shortcut, not a wall (`feedback_tools_are_conveniences_not_limits`). Friction-
  driven: expand the exposed primitive layer (currently thin —
  `primitives.chord_tones` + `apply_feel`) as real songs need to reach beneath an
  idiom.
- **R4 — The interplay vocabulary is the missing primitive layer.**
  Call-and-response, half↔double-time dialogue, and simultaneous interlock (the
  thing the smash couldn't express) are PRIMITIVES, not a "fusion section" builder.
  Building them is friction-driven (this is ARR-3R8F's rhythm-axis slice); they
  stay song-local until a SECOND non-sun-zone song needs them, then generalize as
  composable primitives (combine freely) — never as an altitude-1 archetype.

## Current-state audit (2026-06-03)

The boundary already mostly holds — this record ratifies it and names the rule for
the future:

| Altitude | Where it lives today | Verdict |
|---|---|---|
| 1 — section/genre archetype | song-local only (`sun-zone-done/build.py`: `reg()`/`met()`, `_dev_collision`, `_integration_play`) | ✅ correct (R2) — never in the package |
| 2 — single-part genre idiom | `hallucinote.generators` (`reggae_skank`, `metal_gallop`, `reggae_offbeat_bass`, `metal_pedal_16ths`, `organ_bubble`, `palm_mute_power_chords`, `reggae_one_drop`) | ✅ allowed (R3) — single-part, chord-aware/parameterized |
| 3 — sub-musical primitive | `hallucinote.generators.primitives` (`chord_tones`, `apply_feel`) | ✅ — thin today; grow friction-driven (R3) |

No package generator builds a section. The reg()/met() refactor the item floated
is **not pursued now**: those helpers are already song-local (R2-compliant), the
real gap is the missing interplay *primitives* (R4), and that generalization is
deliberately friction-driven (ARR-3R8F) — premature-building it would itself be the
mistake this policy warns against. The convention is documented in
`docs/song-authoring-conventions.md` ("Generator altitude — ruler vs stamp").
