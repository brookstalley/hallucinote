> **RESOLVED 2026-06-16** (branch `fix/analyzer-infra-robustness-sunzone`). Fix
> (a) implemented — the structural one: `_probe_live_devices_via_mcp` now probes
> the master device chain into `live_devices_by_parent` as `("master", 0)`, and
> `_match_devices_for_linked_parents` reconciles the master device links with the
> same analyzer-aware position match it already runs for tracks/returns. The
> master device link now self-heals against analyzer drift, so a param re-push
> targets the authored device instead of the analyzer. Side-benefit: the
> push-preflight stale-set detector now covers the master surface (closes the
> "still-open piece" noted in `analyzer_staleness.py`). Regression test:
> `test_probe_and_link_reconciles_master_device_after_analyzer_shift`.

# Master device-parameter re-push isn't analyzer-aware — the stale master device link targets the HallucinoteAnalyzer and hard-halts the push

**Severity:** M (hard halt). Hits every iterative master-chain mix pass once a
render has run (i.e. the normal state). A scoped push works around it and the
parameter *value* is never corrupted, so it's recoverable — but the failure is a
hard halt of the whole `devices` phase, not a skip-and-warn.

Reported by a song consumer (2026-06-16) mixing the master Limiter on
`sun-zone-done`: after a render, re-pushing the master Limiter's **Ceiling**
targeted the `HallucinoteAnalyzer` instead and the push **halted there**.
Worked around with a scoped push; the Ceiling was already correct from the prior
push.

## TL;DR

Track/return device param re-pushes survive an analyzer-laden set because the
push **probe re-reconciles** their device links every push, filtering the
analyzer out before re-matching positions (the BUG1A fix,
`src/hallucinote/sync/push/probe.py:665-676`). **The master is excluded from that
reconciliation entirely**, so a master device's stored `device_index` link is
frozen at first-load time and never re-matched. Once the analyzer's presence /
terminal-reposition shifts the master chain relative to the stored index, the
param-set resolves the wrong device, the parameter name isn't found on it, and
the executor raises → the `devices` phase halts.

This is the same root family as the two archived analyzer reports, but a
**distinct, sharper finding**: it falsifies the earlier claim that *"param-only
changes on tracks that already have the device are fine"* — that's true for
tracks/returns precisely because they get reconciled, and **false for the master**
because it doesn't.

## Root cause / mechanism (verified against source)

1. **Master param-set trusts a stored index.** `plan_push_devices` resolves a
   master device's target purely from its stored link:
   `device_at = Q.get_ableton_link(..., db_kind="device", db_id=device["id"])`
   and passes `device_index=device_at` straight into the `set_parameter` node
   address — no live re-resolution at plan time.
   `src/hallucinote/sync/push/devices.py:172-174, 270-278` (master branch:
   `:62-77`, `:178-179`).

2. **The link that would self-heal it is never recomputed for the master.** The
   probe's device re-matcher — which walks the live chain, **drops the analyzer**
   (`authored_live = [d for d in live_devices if not is_analyzer_device(d)]`),
   and re-binds each authored DB device to its real `device_index` — iterates
   **only `track` and `return` parents**:
   ```python
   # src/hallucinote/sync/push/probe.py:654-657
   for matched, parent_kind, get_devices_fn in (
       (result.matched_tracks, "track",  Q.get_devices_for_track),
       (result.matched_returns, "return", Q.get_devices_for_return),
   ):
   ```
   Master is also dropped from the track set up front
   (`db_tracks = [t for t in ... if t["kind"] != "master"]`, `probe.py:403`), and
   the BUG1A analyzer filter lives *inside* that track/return loop
   (`probe.py:665-676`). So **no analyzer-aware reconciliation ever runs for the
   master device chain.** The master device link is written once (at first load,
   via `apply_push_results` recording the post-load index) and never corrected.

3. **The analyzer shifts the master chain after that link is frozen.** A render
   auto-loads the analyzer on the master and keeps it the strictly-last device
   via delete+re-add reposition
   (`hallucinote_mcp/.../analyzer/setup.py` `ensure_analyzers_loaded` /
   `_reposition_action`; master goes through the **same** path as tracks since
   DEV-6M2K, `setup.py:506-519`, `handlers/device.py:1111-1119`). Between the
   first-load index capture and a later re-push, the analyzer's
   presence/reposition changes where the authored device actually sits — but the
   stored master link doesn't move with it. (E.g. the Limiter was first linked
   while an analyzer already trailed the chain, then a later render's reposition
   shifted the authored devices down one; or any add/remove/reposition of the
   analyzer between pushes — the master link has no mechanism to track it.)

4. **The mis-target is a hard halt, not a skip.** `set_parameter` on the
   resolved (wrong) device can't find the parameter and raises:
   ```python
   # hallucinote_mcp/.../handlers/device.py:1559-1564
   if target_param is None:
       available = [p.name for p in getattr(dev, "parameters", ())]
       raise ValueError(
           f"parameter {parameter_name!r} not found on device "
           f"{device_index}; available: {available}"
       )
   ```
   Push uses phase-bounded error accumulation: any failed call halts the phase at
   its boundary (`src/hallucinote/sync/push/push_execute.py:16-21`). So the whole
   `devices` phase stops — matching the consumer's "the push halted there."

## Why the master is the hole (structural)

`DEV-6M2K` newly enabled master device **load + push** (master chains became
authorable+pushable; the prior refusal rested on a premise refuted on Live
12.4.2). But the probe's master-exclusion is a **pre-DEV-6M2K assumption** —
written when master had no pushable devices and was "reached via
`ableton_session`, not a track index" (`probe.py:360-363`). The BUG1A
analyzer-aware re-linking that made track/return param re-pushes robust was never
extended to master, because at the time master devices weren't in scope. DEV-6M2K
opened the door; the reconciliation didn't follow it through.

## Relationship to the two archived reports

- `archives/2026-06-14-device-authoring-not-analyzer-aware.md` — same root
  family (position-based matching + appended analyzer), but about **tracks/returns
  adding new devices**. It explicitly claimed *"Param-only changes on tracks that
  already have the device are fine (the analyzer is last, positions still
  match)."* This report shows that's only true **because tracks/returns get
  reconciled** — and is **false for the master**, which doesn't.
- `archives/2026-06-13-snapshot-capture-includes-hallucinote-analyzer-devices.md`
  — the capture/snapshot side of the same analyzer-as-infrastructure problem.

## Suggested fix (pick one; (a) is the structural one)

a. **Extend the probe's device reconciliation to the master.** Add a master
   branch to `_match_devices_for_linked_parents` (`probe.py:654`): walk the
   master's live device chain, filter via `is_analyzer_device` exactly as
   tracks/returns do, re-match authored DB master devices by position, and upsert
   the master `device` link. This makes master param re-pushes self-heal against
   analyzer drift the same way track/return ones already do — the smallest change
   that closes the actual gap. (Requires the probe to surface the master live
   chain; tracks/returns already flow through `live_devices_by_parent`.)

b. **Defensive re-resolve at set_parameter time.** Before setting, verify the
   resolved device's class matches the expected `kind`; on mismatch, re-resolve
   by class within the analyzer-filtered chain (and/or skip-with-warn instead of
   raising). Turns a hard halt into a self-heal, and helps any node-kind, but is
   a band-aid over the missing reconciliation rather than a fix for it.

c. **(Already half-present) skip, don't halt.** The DB-side analyzer row is
   already skipped at plan time (`devices.py:163-171`, SNP-8R4K). The gap is
   purely the *live-side* stale index — (a) is the real fix; this just notes the
   plan-time guard exists and isn't sufficient.

## Workaround (until fixed)

Scoped push (what the consumer did) — push only the corrected device/param, or
`ableton_render(action='strip')` the analyzers → push → re-render (analyzers
reload last). The Ceiling value itself survives; only the re-push targeting
breaks.

## Verifiable signal / repro

1. Author a device on the master (e.g. a Limiter), push, render (auto-loads +
   repositions the analyzer last on the master).
2. Change a master device param in `build.py` (e.g. Limiter Ceiling), rebuild,
   re-push.
3. **Bug:** the `set_parameter` resolves to the `HallucinoteAnalyzer`, raises
   `parameter 'Ceiling' not found on device <idx>`, and the `devices` phase
   halts. Re-pushing the same param on a *track* (not master) under an
   analyzer-laden chain succeeds (reconciled).
4. **Fixed signal:** a master device param re-push over an analyzer-laden master
   chain sets the right device with no manual strip and no halt.
