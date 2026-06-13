# PSH cluster — push-execute operability (phase-targeting + mid-run progress)

Backlog: **PSH-2R7K** (phase-targeting), **PSH-5T9D** (mid-run progress).
Branch: `fix/push-execute-hardening`. Critic mode: **cumulative**.

**PSH-3H8M (perform-hang watchdog) is consciously DEFERRED this session** — see
"Scope" below. It is server-side (`handlers/automation.py`, in `_FINGERPRINT_PATHS`),
Live-gated to verify, and the discovery below shows its two easy sub-fixes already
exist; the real gap is a deeper, riskier core-primitive change.

## Confidence Check

1. **Problem.** `push_cli execute` is all-or-nothing and silent until exit: recovery
   after a halt replays every phase (incl. the ~8-11 min realtime perform), and for
   the whole run there is no progress signal (`.last-push-state.json` is written once
   at the end; stdout is buffered to exit) — a long push is indistinguishable from a
   hang.
2. **Success.** (a) `execute --only/--start-at/--from/--stop-after/--resume` runs a
   scoped slice of phases (order-agnostic, idempotent, coherence-gated as today), so
   recovery from a halt is one command, not a full replay. (b) `.last-push-state.json`
   is flushed after every phase (pollable for phase-level progress + current phase),
   and `execute` streams per-phase start/finish lines to stderr while stdout stays the
   final summary.
3. **Out of scope.** PSH-3H8M (perform watchdog) + PSH-5T9D layer-3 (intra-perform
   heartbeat) — both server-side / Live-gated; deferred with diagnosis. The routing
   phase REORDER (RTE-2P9X) is a parallel agent's WIP (`stash@{0}`) — NOT touched;
   phase-targeting is built name-filtered/order-agnostic so it composes with that
   reorder when it lands.

## PSH-3H8M discovery (why deferred, not dropped)

The bug proposed watchdog + hard-ceiling + pre-perform-reset. Reading
`perform_batch_handler`:
- **Hard wall-clock ceiling ALREADY EXISTS** (`automation.py` ~1953-1981): `deadline =
  wall_start + max(expected_s * _PERFORM_WALL_CLOCK_FACTOR, FLOOR) + settle`; the ramp
  loop raises `TimeoutError` past it.
- **Pre-perform reset PARTIALLY EXISTS** (`_arm_and_seek` ~1922-1933): stops if
  playing + seeks to `union_start` before arming.
- **The genuine residual:** the observed hang was flat **0% CPU for 4.5 min** — that's
  the worker **blocked inside `run_on_main(_ramp_step)`** (Live's main thread not
  servicing the callback), so NEITHER the deadline NOR a worker-side non-advancement
  watchdog (both run only *between* `run_on_main` calls) can fire. The real fix is a
  **timeout on `run_on_main` itself** — a core primitive used everywhere (high blast
  radius), and only reproducible/tunable against real Live. A worker-side
  non-advancement watchdog would also help the lesser "responsive-but-frozen
  transport" sub-case. Both need a Live session to validate thresholds.
This is filed back to PSH-3H8M (backlog) with the diagnosis so the next picker starts
from reality, not the partially-stale proposal.

## Chunks

- [x] **C1 — PSH-5T9D mid-run progress (layers 1-2).** In `push_execute.execute_push`:
  extract the state-payload build into a helper; flush `.last-push-state.json` after
  every phase (add `current_phase` + a `scope` field); add a `progress_fn:
  Callable[[str],None]|None` param called at each phase start/finish (a qualitative
  START line for the long `performed_automation` phase). `push_cli._cmd_execute` passes
  a stderr-writing `progress_fn`. Unit tests: per-phase flush is pollable (state file
  reflects partial progress mid-run via a send_fn that snapshots the file), progress_fn
  receives start+finish per phase, stdout summary unchanged.

- [x] **C2 — PSH-2R7K phase-targeting.** `execute_push` gains `only` / `start_at` /
  `stop_after` (validated against `push._PHASE_NAMES`; teaching `ValueError` on an
  unknown name listing valid phases; `only` mutually exclusive with start/stop). Filter
  the planned `phases` list by name (order-agnostic) before the loop; record the filter
  in the state file `scope`. `push_cli` adds `--only` / `--start-at` (`--from` alias) /
  `--stop-after` / `--resume` (reads `.last-push-state.json`'s `phase_halted` →
  `start_at`); validates combinations with teaching errors. Idempotency + coherence
  gate unchanged. Unit tests: each flag slices correctly, unknown-phase teaches, only/
  start mutex, resume reads the halted phase, a scoped run is still coherence-gated and
  its state file marks the scope.

## Acceptance

`execute --only devices` runs exactly the devices phase; `--start-at routing` runs
routing→end; `--stop-after mix` runs through mix; `--resume` continues from the last
halt; an unknown phase name teaches with the valid list. Mid-run, `.last-push-state.json`
shows completed phases + the current one; `execute` streams per-phase stderr lines.
Full suite green; Critic cumulative 0-blocking. MCP server fingerprint UNCHANGED
(engine-only) — no re-vendor forced by this feature.
