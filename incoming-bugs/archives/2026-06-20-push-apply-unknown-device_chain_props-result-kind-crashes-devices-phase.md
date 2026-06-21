# Push apply crashes on unknown result kind `device_chain_props` → full push of a rack-preset song never completes

**Severity:** H (blocking) — a full `push execute` of any song whose rack chains
carry **non-default chain mixer state** (mute/solo/volume/pan) or
**choke_group/out_note** dies with an unhandled `ValueError` in the devices-phase
result-apply. The phases after `devices` (routing, device_sidechain, envelopes,
performed_automation, arrangement, cues) never run, so the song never finishes
materializing. Surfaced 2026-06-20 verifying the SYN-RACK-PRESET-RELINK / Bug 2
rack-preset fixes (`29f05c4` + `58f461f`) on a fresh full push of `alien`.

This is the **direct twin** of the already-fixed
`2026-06-18-push-apply-unknown-device_param_override-result-kind-halts-devices-phase.md`
— same bug class, one key kind over. That fix registered `device_param_override`
in `_ACK_ONLY_KINDS` but its sibling `device_chain_props` was missed.

## What happens

A fresh push of `alien` (Drum Rack `AG Techno Kit.adg` with per-pad chain
volumes, Instrument Rack `Inclement Drone Pad.adg`) dispatches the entire devices
phase to Live successfully — all 1219 device calls, racks load populated, params
land — then crashes in the client-side apply step:

```
Traceback (most recent call last):
  ...
  File ".../hallucinote/sync/push_execute.py", line 1150, in execute_push
    _apply_results(extra_results, phase.name)
  File ".../hallucinote/sync/push_execute.py", line 949, in _apply_results
    apply_warnings = push.apply_push_results(...)
  File ".../hallucinote/sync/push/plan.py", line 505, in apply_push_results
    raise ValueError(
ValueError: unknown push result key kind 'device_chain_props'
  (full key='device_chain_props:d88b076f960348b3a34e65cce32df00e').
  Declare it in _LINK_KINDS / _ACK_ONLY_KINDS (or add a dedicated branch
  like 'perform_batch') in sync/push/plan.py.
```

`execute` exits 1. `.last-push-state.json` shows `devices` never recorded a
terminal entry (the apply crashed before the phase status was written), so the
state file is left mid-write — misleading on its own (looks like it stalled at
`mix`); the real signal is the stderr traceback + exit 1.

## Root cause

- The devices planner emits per-chain mixer/choke calls keyed
  `device_chain_props:{chain['id']}` — `sync/push/devices.py:633`
  (`ableton_device(action='set_chain_property', ...)`, added by NODE-ADDR Chunk F
  `66e1f58` for mute/solo/volume/pan and Chunk C for choke_group/out_note).
- `apply_push_results` (`sync/push/plan.py`) is table-driven: every emitted key
  kind MUST appear in `_LINK_KINDS`, `_ACK_ONLY_KINDS`, or a dedicated branch, or
  it hits the catch-all `raise ValueError` at line ~505. `device_chain_props` is
  in **none** of them.
- `device_param_diff.py:34` already documents that "the planner also emits
  `device_param_override:` and `device_chain_props:`" — the `device_param_override`
  half got registered in `_ACK_ONLY_KINDS` (plan.py:357, the 2026-06-18 fix);
  `device_chain_props` was overlooked.

**Why it stayed latent until now.** Before the rack-preset-load fix, a captured
`.adg` rack loaded as an **empty shell** (0 chains), so the `set_chain_property`
calls failed at dispatch (`IndexError: chain_index N out of range [1, 0]`) and the
devices phase **halted on call failures** before any *successful*
`device_chain_props` result reached the apply step. Now that racks load populated
(the Bug 2 fix), those calls **succeed**, produce `device_chain_props:` result
entries, and apply trips the unregistered-kind guard. So the load fix is correct;
it just newly exposes this apply gap.

## The fix (one line, with precedent)

Add `device_chain_props` to `_ACK_ONLY_KINDS` in `sync/push/plan.py`, immediately
after `device_param_override`, with the same rationale: the chain's mixer/choke
state ORIGINATES in the snapshot/DB and the chain has no Live-side index to record
back (it's addressed by `chain_index`), so it's ack-only — no binding to write.

```python
    "device_param_override",
    # NODE-ADDR Chunk C/F: per-chain mixer state (mute/solo/volume/pan) +
    # choke_group/out_note via ableton_device(set_chain_property). Ack-only —
    # the chain state originates in the snapshot/DB and a chain has no Live-side
    # index to record back (addressed by chain_index). Without this case a full
    # push of any rack-preset song with non-default chain state CRASHES in the
    # devices-phase apply once the rack actually loads (Bug 2 fix exposed it).
    "device_chain_props",
```

## Regression test

Mirror the `device_param_override` apply test: feed `apply_push_results` a
synthetic `{"key": "device_chain_props:<id>", "ok": true, "tool":
"ableton_device", "result": {...}}` and assert it's accepted (no `ValueError`,
no DB link written). A grep-guard test that every `key=` prefix emitted across the
planners (`devices.py` etc.) is declared in `_LINK_KINDS ∪ _ACK_ONLY_KINDS ∪
{cue_batch-style branches}` would have caught both this and the 2026-06-18 twin at
once — worth adding so the next sibling key can't regress silently.

## Verifiable signal

A fresh full `push execute` of `alien` (or any song with a Drum/Instrument Rack
carrying non-default per-chain volume/mute/choke) completes through ALL phases
(exit 0), not just `devices` — i.e. routing → cues run and the arrangement
materializes in one pass.

## Repro (2026-06-20, develop @ 41665f1, server fingerprint 0fd1cec33ebc)

1. Fresh default Live set. `push probe-and-link --auto-session --song alien --probe`.
2. `push execute <session> --song alien --probe`.
3. Devices phase dispatches all calls (racks load populated), then exit 1 with the
   `device_chain_props` ValueError above. Scoping past devices
   (`--only arrangement`) completes fine — confirming only the devices-phase apply
   is affected.
