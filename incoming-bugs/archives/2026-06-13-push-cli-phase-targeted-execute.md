# `push_cli execute` should support phase-targeted runs: `--only`, `--start-at`/`--from`, and `--resume`

**Type:** enhancement (sync/push CLI). **Source:** dogfooding the swell push, 2026-06-13.

**The pain.** `push_cli execute` is all-or-nothing: it always walks the full
14-phase sequence from the top. Two situations this session made the gap obvious:

1. **Recovery after a halt costs a full replay.** The push halted at `routing`.
   The only "retry" is re-running the *entire* `execute`, which re-walks every
   phase — including `performed_automation`, a **~8–11 min realtime perform** —
   even though only `routing` (and the phases after it) still need to run. Minutes
   of realtime playback to redo one failed phase.
2. **Running a single phase out-of-band requires replicating the engine.** To work
   around the routing-before-devices ordering bug, I needed to run *just* the
   `devices` phase first. There's no `execute --only devices`; the only option is
   the manual `plan <phase>` → hand-dispatch every MCP call → `apply` dance, which
   reimplements `execute`'s dispatch/apply/link-recording machinery (and is easy to
   get wrong — e.g. duplicate device loads if links aren't recorded).

**Request — add phase-targeting flags to `execute`:**
- `--only <phase>` — run exactly one phase in-process (full dispatch/apply/link
  machinery, just scoped). Turns "run the devices phase" into one command.
- `--start-at <phase>` / `--from <phase>` — run from the named phase through the
  end (the resume case). After a halt at `routing`, `--start-at routing` finishes
  the push without replaying tempo…mix or (when unchanged) re-performing.
- `--stop-after <phase>` — complement; bound a run to a prefix (handy for staging /
  debugging).
- `--resume` — read `.last-push-state.json`'s halted phase and continue from there
  automatically (sugar over `--start-at <halted_phase>`).

**Why it's cheap to build.** The order already lives as a tuple of `PushPhase`
objects (`plan_push_song` → each has `.name`); `execute_push` already iterates
them. `--only` / `--start-at` / `--stop-after` are just a slice/filter on that
list before the loop, with name validation (teaching error listing valid phases on
a typo). `--resume` reads the existing state file. Keep the coherence/`--probe`
gate and idempotency exactly as-is — a scoped run is still safe because every
phase's already-linked branch is a no-op.

**Payoff.** Recovery and iteration drop from minutes (full replay, incl. the
realtime perform) to seconds (the one phase that matters). It also removes the
need for the manual `plan`/`apply` dance for the common "just run this phase"
case, and it's the general tool that would have sidestepped today's
routing-order bug (`--only devices`, then `--start-at routing`).

**Related (same dogfood session, 2026-06-13):**
- Push `routing` runs before `devices` → audio-bus routing fails on fresh push
  (`devices`-before-`routing` reorder). `--start-at`/`--only` is the *operational*
  mitigation for that class of phase-ordering surprise.
- Push has no mid-run progress (buffered to exit) — smaller scoped runs also
  shrink the opaque window.
