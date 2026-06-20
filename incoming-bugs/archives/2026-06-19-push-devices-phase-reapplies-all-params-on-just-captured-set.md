# `push execute` stalls for minutes at the `devices` phase — re-applies ALL device params (1243 calls) on a set whose params were just captured

**Severity:** H (the *first push* of any real song stalls/appears-hung on the
canonical pick→compose→push flow). On a deliberately tiny song (5 tracks, 555
notes, 9 clips, zero automation) the `devices` phase plans **1,243 MCP calls**
and does not complete in minutes. From outside it is indistinguishable from a
true hang: the only observable state is `current_phase: "devices"` (state flushes
per-phase, not per-call) and stdout is buffered, so the user correctly reads a
"tiny song" as stuck. The chains had *just* been built + captured from this exact
Live set, so every parameter already matches Live — yet the phase re-applies all
of them.

**Engine version:** `0.1.0+b66e0a9b729d` (server fingerprint `b66e0a9b729d`).

## What happened (alien, branch `compose/swell`)

Canonical creative-product flow, all green up to the push:
1. `/song-new alien` → scaffold (5 planned tracks).
2. `/song-pick-instruments` (strict) → built 5 chains **in Live** (Drum Rack/AG
   Techno Kit, Operator, Wavetable, Analog/Metalic Lead, Drift/Inclement Drone
   Pad as an Instrument Rack) + native FX, then **captured** them into
   `captured_session.json` via `capture_cli execute` (load-then-capture). So the
   snapshot params are a faithful read of the live set.
3. Composed intro + verse1 in `build.py` (tiny: 555 notes, 9 session clips).
4. `compat check` → 55 devices, all native, `has_issues: false`.
5. `push probe-and-link --auto-session --probe` → matched all 5 tracks + their
   devices, `unmatched_*: []`, minted session `58aa6aea…`.
6. `push execute <session> --song alien --probe` →
   `tempo_map`/`time_signature_map`/`scenes`/`clips`(9)/`mix`(48) all OK and
   fast, then **`devices` never completed**. State froze at
   `current_phase: "devices"`; process alive but no progress for minutes; killed.

## Diagnosis (what the phase intends to do)

```
push plan devices --song alien   →  1243 planned calls:
    ableton_device.set_parameter      1227
    ableton_device.set_chain_property   16
    (zero loads — the devices already exist & were matched in probe-and-link)
```

So the `devices` phase re-issues **every** parameter on all 55 devices
(Operator/Wavetable/Analog/Drift each expose ~100 params; the Instrument Rack
adds a nested chain walk), as 1,227 serial TCP round-trips. Because the params
were captured *from this same set* in step 2, they already equal Live — the
reconcile should be a near-empty no-op, not 1,243 calls.

Bounded reproduction (`push execute --only devices --probe`, 35s `timeout`):
stderr shows `[devices] running (1243 call(s))…` and then nothing — no completion,
no per-call line — before the timeout. Could not confirm *slow-but-progressing*
vs *hung-on-one-call* from outside, because there is no intra-phase telemetry
(see issue 2).

## Two (maybe three) distinct issues

1. **No skip-unchanged on the `devices` reconcile.** A freshly-captured set should
   yield an (almost) empty `devices` phase — every param already matches. Instead
   all 1,227 are planned + applied. Either the planner emits params unconditionally
   (no diff vs the probed live value), or the apply-time equality check fails to
   match (float precision / enum display-string vs index / quantized params), so it
   re-sets everything. Net: minutes of redundant round-trips on the most common
   first-push path.
2. **No intra-phase progress / heartbeat.** `.last-push-state.json` flushes only at
   phase boundaries (`current_phase` + appended results), and `execute`'s stdout is
   a single end-of-run summary (so any `… | tail` pipe buffers it to nothing until
   exit). A phase that issues 1,000+ calls is therefore a black box: a long, a slow,
   and a hung phase are externally identical. A per-N-calls counter to stderr +
   into the state file (e.g. `devices: 412/1243`) would make slow-vs-stuck
   diagnosable without killing the run.
3. **(Possible) a specific `set_parameter` may block.** Not confirmed — needs (2)
   or a per-MCP-call timeout to localize. Candidates to check first: the Instrument
   Rack nested-chain params (Noise track), and any read-only/quantized param that
   round-trips oddly.

## Impact

Every first push of a song with real instrument chains hits this. The user sees a
multi-minute stall on a trivially small song with no way to tell stuck from slow.
On this run it never completed across several minutes of waiting.

## Workaround (confirmed working)

Skip the `devices` phase — the devices are already physically loaded in Live and
their params are already correct (captured in step 2), so the reconcile is
redundant:

```
push execute <session> --song <slug> --start-at arrangement --probe
```

`arrangement` completed in **8s** (9/9 clips placed onto the timeline). (Here the
follow-on `cues` phase then halted for an unrelated, self-inflicted reason — cue
locators authored past the composed arrangement extent; that's a build.py
authoring fix, not this bug.)

## Suggested fixes

- Make `devices` a true diff-reconcile: compare each snapshot param against the
  probed live value and **skip equals** (with a tolerance for floats and a
  canonical compare for enums/quantized). A just-captured set should push ~0
  device calls.
- Emit intra-phase progress (every N calls) to stderr **and** to
  `.last-push-state.json` so a long phase is observable and a hang is localizable.
- Consider a per-MCP-call timeout inside `execute` so one blocking
  `set_parameter` fails that call (with the device/param named) instead of
  hanging the whole push.

## Repro

1. Scaffold a song, pick instrument chains via `/song-pick-instruments` (load
   into Live + capture), compose anything small, push with
   `push execute <session> --song <slug> --probe`.
2. Observe `devices` plan via `push plan devices --song <slug>` → ~1.2k
   `set_parameter` calls though nothing changed since capture.
3. Watch `devices` not complete; `current_phase` stuck at `devices`, no heartbeat.
