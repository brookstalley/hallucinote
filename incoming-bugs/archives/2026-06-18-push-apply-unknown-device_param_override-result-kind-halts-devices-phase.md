# `apply_push_results` rejects the `device_param_override` result kind → the devices phase HALTS, so any song whose snapshot carries a `value_raw` param override can't be full-pushed

**Date:** 2026-06-18
**Severity:** high — a **full push from scratch is impossible** for any song whose
`captured_session.json` declares a `value_raw` device-param override. The `devices`
phase loads the chains fine, then dies while *applying the results*, so the song
never finishes materializing (no routing / envelopes / automation / arrangement /
cues). Discovered doing a clean rebuild of `swell` into a fresh blank Live set.

## Repro (swell, real)

`swell`'s snapshot baked one override on the Voice Lead's `Synth Vox Ai` rack —
`LFO 1 S. Rate` via `value_raw: 8.0` (the "bake Voice LFO S. Rate via value_raw"
commit). Full push to a blank set:

```
[clips]   ok (110 call(s))
[mix]     ok (159 call(s))
[devices] running (64 call(s))…
Traceback (most recent call last):
  ...
  File ".../sync/push/plan.py", line 496, in apply_push_results
    raise ValueError(
ValueError: unknown push result key kind 'device_param_override'
  (full key='device_param_override:<dev-id>:[{"chain_index": 1, "device_position": 1},
   {"chain_index": 1, "device_position": 1}]:LFO 1 S. Rate').
  Declare it in _LINK_KINDS / _ACK_ONLY_KINDS (or add a dedicated branch like
  'perform_batch') in sync/push/plan.py.
```

The device *loads* succeed; it's the **result-apply** step that doesn't recognise the
`device_param_override` kind the devices phase emits for a `value_raw` override.

## Root cause

`sync/push/plan.py::apply_push_results` switches on a result-key `kind` and has no case
for `device_param_override` (the kind produced when a planned override is applied and
its realized value comes back). The error message itself prescribes the fix.

## Suggested fix

Add `device_param_override` to `_ACK_ONLY_KINDS` in `sync/push/plan.py` (the realized
value needs no DB write — it's an ack), or a dedicated branch if the realized
`value_raw` should be reconciled back into the snapshot/DB. One-line for the ack path.

## Family

Related to the open param-override bugs (`2026-06-17-param-overrides-cannot-carry-
quantized-nonunit-range-param`, `2026-06-17-snapshot-cannot-carry-nested-param-
override-on-preset-instrument`) — same feature area (snapshot-carried nested param
overrides), but this is the **push-apply** side, not the carry side: even a
well-formed override that pushes correctly halts the run because the *result* can't be
applied.

## Status — prescribed fix applied locally (pending review)

2026-06-18: applied the prescribed one-liner — added `"device_param_override"` to
`_ACK_ONLY_KINDS` in `sync/push/plan.py` (with a comment pointing here). The full
push of `swell` then completed (devices 174/174 ok). **This needs proper framework
review/merge** (is ack-only correct, or should the realized `value_raw` reconcile
back into the snapshot?). The song-side `param_overrides` block was first removed to
unblock, then RESTORED once the handler was in — so `swell`'s baked Voice LFO
(`LFO 1 Sync`=Tempo, `LFO 1 S. Rate`=1/2) is intact.

A song-side-only workaround (no framework change) is to delete the `param_overrides`
block from `captured_session.json` — but note the build converger does NOT then
remove the override from an existing DB, so a clean **DB delete + fresh build** is
required for the removal to take effect.
