# Gate-Verdict Policy — BLOCKING means a likely error, never a choice

**Status:** decided + applied (2026-06-03, branch `feature/sun-zone-back-half`).
**Backlog:** LNT-1V9K. **Related:** ARR-1H9C (the harmony axis that introduced the
gate), GEN-1S4K (the generator-altitude sibling — same ruler-not-stamp principle),
`feedback_great_art_not_software`.

## The principle

A build-time lens is a **ruler, not a stamp**. It MEASURES and ASKS; it must never
VETO a deliberate musical choice. Therefore:

> **BLOCKING is reserved for things that are almost certainly technical or
> structural ERRORS — bugs, not aesthetics. A deliberate aesthetic choice must
> never block the build. Surface it loudly as INFO/WARNING; ship the build.**

Raised by the user (2026-06-01, sun-zone-done back-half), verbatim:

> *"blocking should only ever mean a likely unintentional error. Anything that's
> deliberate is fair game in art and music. We can ship 4'33 if we want."*

## What BLOCKING is reserved for (the enumerated list)

A finding may be `severity="blocking"` (fail the build) ONLY when it is almost
certainly a technical/structural defect the composer did not intend:

- a pitch outside the MIDI range (0–127)
- a note with non-positive duration, or a note starting past its clip's end
- a clip of zero or negative length
- a malformed or duplicate automation envelope; an envelope referencing a
  parameter that does not exist on its target
- a structural-identity violation already guarded by a DB CHECK/mutator
  (e.g. a bar position `< 1.0`) surfacing at a higher layer
- a reference to a track / return / section / device that does not exist

The test: *would any composer, on seeing it, call it a bug?* If yes → BLOCKING is
allowed. If it's even plausibly a choice → it is NOT a block.

## What must NEVER block (aesthetics — INFO/WARNING, then ship)

Silence (4'33"), a drone, harmonic stasis, a deliberately pedaled progression, an
absent/tacet layer, atonality, dissonance, a deliberately "wrong" note, an
unresolved non-chord tone, a static dynamic field, a mechanical or sloppy feel,
an aimless contour. These are the vocabulary of music. Surface them **loudly** as
coaching questions ("the harmony never moves — a deliberate field, or an
unrealized opportunity?") and **ship the build**. The composer, or the song's own
test, decides whether a given instance is intended.

## Audit (2026-06-03) — every build-time lens

Grepped all `severity="blocking"` emissions across `src/hallucinote/`:

| Lens | Blocking verdicts before | After |
|---|---|---|
| `theory/lint.py` (harmony) | `harmonic-stasis` (the only one in the codebase) | **none** — downgraded (see below) |
| `melody/lens.py` | none (declares the literal, emits only `info`) | none |
| `performance/lens.py` | none (declares the literal, emits only `info`) | none |

The melody + performance lenses were already info-only by design; the lone
build-failing verdict in the entire system was harmonic-stasis. After this change
**no build-time lens emits BLOCKING for an aesthetic choice.** The `ok`/`blocking`
machinery is kept on each report for interface symmetry (and so a future genuine
technical-error verdict has a home), but the harmony lens now always reports
`ok=True`.

The only build *raise* on a lens was sun-zone-done's `build.py`
(`if not report.ok: raise`). It is removed — the build prints the WARNING and
ships; the regression is the song's test.

## Worked example — the bass-less break (the trigger)

Reinventing sun-zone-done's break as an ethereal *suspension* (drums + bass drop
OUT) collided with the gate: a section with a declared multi-chord progression but
no harmony layer sounding has `sounded == 0` → the old gate classified that as
stasis → **build FAILED**. The "clean fix" was to contort the declaration (call
the break a single sustained chord) to dodge the gate. **The gate was the thing to
fix, not the art.** Absence is not stasis — nothing can realize movement with no
harmonic agent present.

## The resolution (harmonic-stasis, split three ways)

`theory/lint.py` now distinguishes (preserving the original bug-catch shape):

- **`sounded == 0`** (declared movement, no harmony layer sounding) →
  `harmonic-absence`, **INFO**. Never stasis, never a block. *This is the
  bass-less-break case.*
- **`sounded == 1` under `declared > 1`** (parts pedal a written change) →
  `harmonic-stasis`, **WARNING**. The realization bug-shape — but possibly a
  deliberate sustained field, so it ASKS, never blocks. Still named in
  `report.stasis_sections` (the regression signal).
- **`declared == 1`** (a single declared chord — a drone/minimalist field) → never
  stasis; an `ambition` **INFO** coaching question if long. (Unchanged.)

## How regressions are caught now (intent lives with the song)

The "is this stasis a bug or a choice?" verdict moved from a global gate to each
song's **own test**, where the intent is known. A song that intends movement
asserts `lint_harmony(...).stasis_sections == ()`. sun-zone-done does this in
`test_harmony_realization_has_no_stasis` (and asserts `report.ok is True` +
`report.blocking == ()` — the LNT-1V9K contract). The generic contract is locked
in `tests/unit/theory/test_lint.py::test_no_harmony_finding_ever_blocks_the_build`.

## The rule for future lenses

Any new build-time lens (rhythm/feel, energy-realization, recurrence, the vertical
consonance lens, …) inherits this policy: it emits INFO/WARNING coaching questions
against declared intent and ships the build. It may emit BLOCKING only for an item
on the enumerated technical-error list above. A new aesthetic dimension is
authored-and-measured, never authored-and-vetoed.
