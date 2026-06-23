# Bug: `device_parameters` orphaned by a device-class change survive every rebuild → cryptic device-phase HALT at push

**Type:** bug (data-integrity / silent-accumulation, with a misleading failure surface).
**Severity:** M–H. Hard-blocks `push execute` at the `devices` phase, and the error
gives no hint as to the real cause. Silent until push; the only *documented* cure
("delete the DB file") also discards the Ableton projection (sessions/links).
**Engine / server:** `1.5.0` (`d80fe21`, develop). Surfaced pushing `alien` (songs
repo) to a connected Live set — the routine `/hallucinote:ableton-push`.

## Symptom

`push execute --song alien --probe` ran clean through `tempo → … → mix`, then
**HALTED at `devices`** with `1235 ok, 107 failed`. 92 of the failures were:

```
ableton_device('set_parameter') failed: ValueError: parameter 'A Coarse' not found
on device 1; available: ['Device On', 'Voices', 'PB Range', 'Volume', …]
```

…repeated for `A/B/C/D Coarse`, `Ae/Be/Ce/De/Fe/Pe …`, `Algorithm`, `Osc-A/B/C/D …`,
`Filter Freq/Res`, `LFO Rate`, etc. — i.e. **Operator parameters being written to a
device that is an Analog.** All 92 were on the **Alien Voice** track's instrument.

The push `hint` was:

> *the action's preconditions and value ranges — check `ableton_device(action='help')`.*

That points the operator at value-range debugging, but the params **do not exist on
the device at all** — they are stale orphans. Nothing in the error suggests "stale
param from a device-class change; rebuild fresh / prune."

## Root cause (verified on the real DB + capture)

Alien Voice's instrument was historically an **Operator**; its ~92 Operator params
were written to `device_parameters`. The instrument was later swapped to **Analog
"Metalic Lead"** in `captured_session.json` (116 Analog params). Then:

1. **`replay_capture` is upsert-only (W12-A).** It inserts/updates the 116 params in
   the snapshot but **never deletes `device_parameters` rows absent from the
   snapshot.** (Docstring: *"every underlying mutator … is upsert-shaped … updates
   rows whose state changed and is a no-op for unchanged rows."*)
2. **`build.py --reset` is a *soft* reset (W18-C)** that *deliberately* preserves the
   mix layout — *"preserves the mix layout (tracks, returns, **devices**, sends) AND
   the Ableton projection … delete the DB file for a full clean slate."*

So neither a no-reset build **nor** `--reset` prunes the orphans. The DB carried
**208 params = 116 valid Analog + 92 stale Operator**, and the 92 fail forever
against the real Analog.

### Evidence

```
'A Coarse' substring count in whole captured_session.json : 0      # not in source
Alien Voice device params: DB=208, capture(params_dialed)=116, DB-only=92
capture-only (in capture, not DB)=0                                # capture is clean
after `build.py --reset`:  device params still 208, orphans intact # soft reset kept them
after deleting the 92 DB-only rows: 116  → push devices stops failing
```

The 92 DB-only names are exactly the Operator set (`A/B/C/D Coarse` — Analog has only
2 oscillators, never C/D, so these can *only* be Operator). `links`/`sessions` were
unchanged across `--reset` (129/1), confirming the soft reset is not regenerating
this table.

## The asymmetry

Device **chains** already get a drop-clears-stale reconciliation (see `capture.py`
comments around the per-chain "drop the prior one (idempotent) — the same
drop-clears-stale idiom" / survivor-rank logic). **`device_parameters` do not get the
same drop-stale treatment** when a device's param *set* shrinks or its class changes.
That gap is the bug: a device's identity can change (Operator → Analog) and its old
class's params linger indefinitely.

## Impact

Any device whose class/identity changes between captures silently accumulates orphan
params that (a) never get pruned by any rebuild short of deleting the DB file, and
(b) surface only as a confusing mid-`devices` HALT. The blessed cure — delete the DB
file — also wipes `ableton_sessions` + `ableton_links`, forcing a re-link
(`--auto-session`) and, on a fresh default-scaffold set, re-introducing the
index-mislink hazard the `--auto-session` discipline exists to avoid.

## Suggested fixes (in preference order)

1. **Reconcile the param SET per device in `replay_capture`** — drop
   `device_parameters` rows for a device that aren't in the snapshot's
   `params_dialed` (the drop-stale idiom chains already use). At minimum, when a
   device's `class_name`/identity differs from what's in the DB, clear its params
   before re-seeding.
2. **Surface orphans before the HALT** — `compat check` (or push's coherence gate)
   could probe the resolved live device and bucket "DB param not present on device"
   as `param_orphan`, warning pre-push instead of failing 92× mid-phase.
3. **Make the device-phase error teach** — when `set_parameter` 404s, include
   "looks like a stale orphan from a device-class change (snapshot has N params, DB
   has M); rebuild into a fresh DB or prune" rather than pointing at value-range help.

## Workaround used

Surgically deleted the 92 `device_parameters` rows for the Alien Voice device whose
names aren't in the capture's `params_dialed` (DB→116). **Durable** — `replay_capture`
never re-adds them (they're not in the snapshot), so the prune survives future builds.
Re-`probe-and-link` re-matched cleanly (5 tracks / 24 devices), and the re-run
`execute` no longer fails on those params. (A full `--reset` did *not* fix it; only a
DB-file delete or this surgical prune does.)
