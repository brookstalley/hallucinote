# Build Plan — PSH-3K9D: push `devices` phase diff-reconcile + heartbeat

**Scope tag:** PSH-3K9D
**Type:** Bugfix (correctness + performance) · **Size:** Medium
**Branch:** `fix/push-devices-diff` (worktree, off `develop`)
**Critic mode:** cumulative (gates the PR); chunk review per chunk.

## Problem (observable)

The push `devices` phase re-issues a `set_parameter` for **every** dialed
parameter on **every** device, unconditionally — no comparison against the
current Live value. On a trivial 5-track song that is **1,243 planned calls**
(`set_parameter` ×1227 + `set_chain_property` ×16), all serial TCP round-trips.
When the chains were *just* captured from this same Live set (the canonical
`/song-pick-instruments` → capture → push flow), every parameter already matches
Live, so the reconcile should be ~empty — instead it stalls for minutes and is
externally indistinguishable from a hang (state flushes only at phase
boundaries; stdout buffers to a single end-of-run summary).

Source of the unconditional emit: `src/hallucinote/sync/push/devices.py`
`_emit_param_writes` (lines 439–461) — one `ToolCall` per stored param row, the
only filter being "is there a writable form?" (`_param_value_kv` → None).
The executor (`src/hallucinote/sync/push_execute.py` `_dispatch_calls`, 746–881)
sends every call. No probe-current-value / diff / skip exists anywhere.

Reported in `incoming-bugs/2026-06-19-push-devices-phase-reapplies-all-params-on-just-captured-set.md` (severity H — hits every first push of a real song).

## Requirements confidence

1. **Problem:** the `devices` phase applies redundant `set_parameter` calls that
   already match Live, stalling the most common first-push path.
2. **Success:** a push of an already-loaded + linked, already-correct chain set
   issues **~0** `set_parameter` device calls (only genuinely-changed params are
   written), and the phase completes in seconds. A genuinely-changed param IS
   still written. A long phase is observable (slow vs hung distinguishable).
3. **Out of scope:** the FK-violation bug (separate report, deferred — caller
   guard in `db/mutations/links.py`); a per-MCP-call timeout (report issue #3,
   unconfirmed — chase later via chunk 2's telemetry); the `device_param_override`
   and `set_chain_property` calls (kept always-dispatched — negligible count,
   trickier addressing; only `device_parameter` calls are diffed).

**Confidence: High.** Approach chosen with the user (probe-then-diff over
provenance-skip — robust for partial-change re-pushes too). Read + compare
surfaces verified against live code.

## Design

### Where the diff lives — the executor, `devices` phase only

Planners are pure (DB → `PushPlan`, no Live I/O); the executor owns `send_fn`.
So the diff is a **pre-dispatch filter** applied to the `devices` phase's
`plan.calls` inside `push_execute.py`, before `_dispatch_calls(plan.calls)`.

It filters only calls whose `key` starts with `device_parameter:` (the 1227-bulk
— a top-level or nested device param). `device_param_override:*`,
`device_chain_props:*`, and `device:*` (load) calls pass through untouched.

### The batched read — one call per device

The MCP `ableton_device(action='get_parameters', node=<NodeAddr>, detail='full')`
handler (`hallucinote_mcp/.../handlers/device.py:583`) returns **all** of a
device's parameters in one call, each with: `name`, `value` (raw float — for
enum, the index), `value_display` (the device's own `str_for_value` rendering at
the current value), `is_enum`, `value_items` (full), `min`, `max`, `default_value`.

The diff groups the `device_parameter:` calls by `device_id` (parsed from the
key via `split(":", 2)` — the device id is a colon-free TEXT id, the param name
is the remainder and may contain colons), then issues **one** `get_parameters`
read per device (its `node` is taken from the first call's args). ~55 reads
replace ~1227 writes.

### The comparison — against the canonical DB row, conservative

The call args are lossy: `{"value": "0.5", "value_type": "continuous"}` is
ambiguous between a raw and a normalized value. So the diff compares against the
**DB param row** (unambiguous columns `value_raw` / `value_normalized` /
`value_display` / `value_items_json`), fetched via `Q.get_device_parameters`,
mirroring `_param_value_kv`'s priority:

| DB stored form (priority order)      | Compare against live read              | Equal when |
|--------------------------------------|----------------------------------------|------------|
| `value_items_json` (enum)            | live `value_display`                   | exact string match |
| `value_raw` (quantized/unclamped)    | live `value` (raw)                     | `\|Δ\| ≤ tol` |
| `value_display`                      | live `value_display`                   | exact string match |
| `value_normalized` (only)            | `min + n·(max−min)` vs live `value`    | `\|Δ\| ≤ tol` |

`tol = max(1e-6, 1e-6·max(|a|,|b|))` (Live params are 32-bit floats).
Enum/display use exact string equality — both the DB-captured and the live
`value_display` come from the **same** `str_for_value` curve, so identical value
⇒ identical string (sidesteps the display-rounding trap; no float compare on
displays). Float forms use tolerance (sidesteps the precision trap).

**Safety law — skip-on-confident-equal, keep-on-any-doubt.** A false *keep* is
harmless (a redundant write = today's behavior). A false *skip* is a correctness
bug (dialed intent silently not applied → wrong mix). So the diff skips a call
ONLY when it positively proves equality; on any uncertainty — param name absent
from the live read, missing `min`/`max` for a normalized compare, unparseable
key, comparison exception — it **keeps** the call. The optimization can only ever
degrade to the current re-write-everything behavior, never to a wrong result.

### Zero overhead on the fresh-set path

On a first push onto a *fresh* (un-pre-loaded) set, `_emit_device_calls` emits
**loads** for unlinked devices and returns before any `set_parameter` — so the
main `devices` plan has no `device_parameter:` calls and the diff fires **no
reads**. Params land via the SYN-9F2L convergence re-plan (`push_execute.py`
1027–1048), which the diff deliberately does **not** touch: a just-loaded device
is at factory defaults, so every captured param genuinely differs and must be
written. The diff thus targets exactly the "already loaded + linked + correct"
case (the reported bug) and is inert elsewhere.

## Chunks

### Chunk 1 — probe-then-diff skip-unchanged (the fix)  ·  thin vertical slice

- **New** `src/hallucinote/sync/push/device_param_diff.py` — pure, no I/O:
  - `_floats_equal(a, b)` tolerance helper.
  - `param_matches_live(db_row, live_entry) -> bool` — the table above; returns
    True only on confident equality.
  - `partition_device_param_calls(calls, *, conn, read_fn) -> (to_send, skipped)`
    — groups `device_parameter:` calls by device, calls `read_fn(node)` once per
    device, returns the calls to keep + a record of skipped ones (key + reason).
    `read_fn` is injected (the executor passes a `get_parameters` sender) so the
    module stays pure and unit-testable with a fake.
- **Wire into** `push_execute.py`: for `phase.name == "devices"`, run the
  partition over `plan.calls` before `_dispatch_calls`; dispatch only `to_send`;
  record skipped calls as `ok` no-op results so counts/state stay honest and the
  summary can report "N device params already current (skipped)".
- **Tests** (`tests/unit/sync/`):
  - comparison unit tests — each wire form, each equal/changed case, each trap
    (float epsilon equal; enum display match; display-string match; normalized↔
    raw via min/max); each keep-on-doubt fallback (missing param, missing min/max,
    bad key).
  - executor/integration test with a fake `send_fn` + an in-memory DB: a fully-
    matching device → 0 set_parameter dispatched; a one-param-changed device →
    exactly 1 dispatched; a freshly-loaded (convergence) device → all dispatched;
    a device absent from the read → all kept.
- **Done when:** new + full suite green; a matching-set devices phase dispatches
  ~0 `set_parameter`; a changed param still writes; chunk Critic clean.

### Chunk 2 — intra-phase progress heartbeat (observability)

- In `_dispatch_calls` (or a thin wrapper), every N calls (N≈25) emit a counter
  to stderr via `_emit_progress` (`[devices] 412/1243…`) **and** update
  `.last-push-state.json` (a `phase_progress: {done, total}` field) so a poller
  sees forward motion. Flush is throttled (every N) to avoid per-call disk churn.
- Makes a genuinely long phase (or the realtime perform) distinguishable from a
  hang, and localizes report-issue-#3 (a possible single blocking `set_parameter`)
  without a kill.
- **Tests:** assert the state file gains progress between calls (multi-hop), and
  the stderr counter fires at the cadence. Deferrable if scope tightens — chunk 1
  alone resolves the user-facing stall.
- **Done when:** suite green; state file shows mid-phase progress; chunk Critic clean.

## Acceptance criteria

- [ ] An already-loaded/linked/correct chain set → `devices` phase issues ~0
      `set_parameter` calls and completes in seconds (was 1227 / minutes).
- [ ] A genuinely-changed dialed param IS still written (no false-skip).
- [ ] Fresh-set first push unchanged: loads + convergence params still applied;
      diff fires no reads on that path.
- [ ] `device_param_override` / `set_chain_property` / load calls unaffected.
- [ ] (Chunk 2) a long phase reports mid-phase progress to stderr + state file.
- [ ] Full suite green; cumulative Critic clean before PR.

## Operator verification (live, post-merge — F10)

Real-bridge only (the unit suite uses a fake send_fn): on the `alien`/`swell`
just-captured set, run `push execute … --only devices` and confirm the plan
reports ~0 dispatched `set_parameter` with all params already current; then dial
one param in Live, re-capture, re-push, and confirm exactly that one writes.
Enqueue in `.prawduct/operator-verification.md`.
