# `replay_capture` nulls authored sidechain sources every build → converger-discipline idempotency permanently broken for any song with sidechains

**Date:** 2026-06-17
**Severity:** medium — the load-bearing "re-run = zero net state-change events"
converger promise (and its guard test) is **un-satisfiable** for any song that
authors a sidechain source. Not cosmetic: it means the idempotency test can never
pass, so it stops catching the *real* non-convergence it exists to catch.

## Repro (swell, real)

`songs/swell/tests/test_swell_build.py::test_build_is_idempotent_state_converger`
fails on pristine `HEAD` (verified via `git stash`), independent of any working-tree
change:

```
AssertionError: Re-running build produced 10 extra state-change events
— converger discipline broken.   (730 == 720)
```

The 10 events are **exactly** the song's 5 sidechains, written twice per build:

```
device_sidechain_set | initial capture replay        | source_track_id=null   ×5
device_sidechain_set | sidechain source: kick -> ...  | source_track_id=<real> ×5
```

(`swell` authors 5 sidechains in `_author_sidechains` — decisions/19: kick→Bass
Punk, kick→Gtr Power, Timpani→Contrabass, Timpani→Celli, PRE-MAIN→Hall.)

## Root cause — a two-step bind

1. **`captured_session.json` can't carry a sidechain source** — sidechain-source
   *capture* (Live → snapshot) is the known SDC-7K3M / BAK-3M9T gap (author+push
   only). So the snapshot has no source field.
2. **`replay_capture` therefore emits `device_sidechain_set(source=null)`** for
   each Compressor on every build — actively *clearing* the source the previous
   build authored, rather than leaving the existing DB value untouched.
3. `_author_sidechains` then re-sets the real source (null → source = a change).

So every build does `<real> → null → <real>` per sidechain = 2 guaranteed
state-change events × N sidechains, forever. The converger can't reach a fixpoint
because replay clobbers the authored value to null *inside the same build* before
the authoring step re-asserts it.

## Why this matters

This is the canonical "song with a mix-pass sidechain" shape (every song that
follows the `/mix-sidechain` + decisions/19 pattern). The idempotency guard test —
the one that's supposed to protect the converger discipline — is dead-on-arrival
for all of them, training authors to ignore a red test.

## Suggested fix (one of)

- **Don't null on absence:** when the snapshot carries no sidechain source for a
  device, `replay_capture` should *leave the existing DB source as-is* (treat
  "absent in snapshot" as "no opinion", not "set to null"). This is the cleanest —
  it makes replay + author idempotent without needing capture.
- **Or** make `set_device_sidechain` a true converger no-op when the requested
  value already equals the stored value (so the `<real> → null` step is the only
  remaining churn, then close that via the bullet above).
- **Closing SDC-7K3M** (capture the source into the snapshot) would also fix it,
  but the "absent ≠ null" rule is the smaller, more general fix.

## Workaround

None at the song level — `_author_sidechains` already writes the correct source;
the churn is entirely in `replay_capture`'s null-write. The song's *materialized*
state is correct; only the converger-idempotency invariant (and its test) is broken.
