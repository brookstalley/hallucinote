# Push halts on a disabled chain-mixer param the capture itself wrote (capture→replay asymmetry)

**Type:** bug (push planner / capture fidelity).
**Severity:** M — halts every full-push `devices` phase for the affected song; workaround
is `--start-at <next-phase>`, but the halt recurs on every future full push because the
write can never succeed and so never becomes "already current."

**Engine / server:** current main-era. Surfaced on song `missing` (branch
`compose/missing`), re-push of the long form 2026-07-11.

## The asymmetry

`capture execute` (assemble_snapshot_via_probes, deep-rack walk) happily READS a nested
chain's mixer volume and bakes it into `captured_session.json`. On the next push, the
`devices` phase dispatches `ableton_device(action='set_chain_property', volume=0.75)`
for that same chain and Live refuses:

```
RuntimeError: Value cannot be set, the parameter is disabled
```

Concrete node (from `.last-push-errors.json`): track 1 (Drums, 909 Core Kit rack),
device_index 1, path `[{chain_index: 7, device_position: 1}]`, inner chain_index 1,
volume 0.75. The value was captured FROM this very Live set ~30 minutes earlier — the
write is a no-op value-wise, but the parameter is disabled (macro-controlled or
otherwise locked), so the phase HALTS with 16/17 ok.

## Why it matters

- The snapshot round-trip is supposed to be safe: capture → replay → push of an
  UNCHANGED set should be a clean no-op run. Instead it manufactures a permanent halt.
- The halt is sticky: the failing write can never apply, so idempotency never absorbs
  it — every future full push of the song halts at `devices` and needs a manual
  `--start-at routing`.

## Possible fixes (any one suffices)

1. **Capture-side:** mark disabled/locked chain-mixer params in the snapshot
   (`is_enabled: false`) and have the planner skip them.
2. **Planner-side:** pre-probe the param's enabled state and plan a skip-with-warning
   instead of a write.
3. **Executor-side:** treat `RuntimeError: ... parameter is disabled` on
   `set_chain_property` as a warning (param unreachable, value cannot diverge audibly)
   rather than a phase halt — the same spirit as the unverified-perform policy.

## Repro

On the `missing` set (909 Core Kit on track 1): `capture execute --song missing`,
merge to canonical, rebuild, `push execute <session> --song missing --probe` → halts
at `devices` on `set_chain_property` for the disabled chain volume.
