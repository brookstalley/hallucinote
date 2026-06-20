> **RESOLVED 2026-06-20 (SYN-RACK-PRESET-RELINK, branch `fix/incoming-bugs-2026-06-20`).**
> Fix #1 (chosen): the load handler now honors a `browser_path` whose leaf is a
> preset FILE (`.adg`/`.adv`) as a STANDALONE selector — it resolves the preset
> content instead of the bare class node; push emits the standalone browser_path
> for such a device. §3 (pan): a non-numeric/non-monotonic display refusal now
> triggers the existing normalized-value retry. See `handlers/device.py`,
> `sync/push/devices.py`, `sync/push_execute.py` + tests.
> **Partly deferred:** §2 (batch `set_parameters`) = out of scope (optimization);
> #3 (fail-loud on empty-rack) filed to backlog — after #1 the primary cause is
> fixed, and a correct fail-loud needs runtime chain-count comparison in the
> execute loop (see `.prawduct/artifacts/build-plan-incoming-bugs-2026-06-20.md`).

# Fresh push loads `.adg` rack presets as EMPTY shells — snapshot carries `browser_path` only, no `preset_uri`/`preset_query`; 766 cascade failures + silent instruments

**Severity:** H. This breaks the core "DB + `captured_session.json` are the source of
truth; the set is regenerable" promise for any song whose instruments are
**rack presets** (Drum Rack / Instrument Rack `.adg`). After a fresh-set full push
the affected tracks are **silent / wrong** (empty racks, 0 chains), and every
nested-chain parameter write fails. The user hit this doing the textbook
"discard the messy set, open a fresh one, re-push from the DB" recovery — and the
re-push could not reconstitute the kit.

**Engine version:** `1.5.0`. Song: `alien`, branch `compose/swell`. Fresh session
`1905070a…`, `execute --probe`.

## What happens

`push execute` reached `devices` and halted: **469/1240 ok, 771 failed.** The
failures cluster on the rack-preset tracks:

| live track | instrument | snapshot device | errors |
|---|---|---|---|
| 5 Drums | **AG Techno Kit** | Drum Rack (`.adg`) | 485 |
| 9 Noise | **Inclement Drone Pad** | Instrument Rack (`.adg`) | 281 |
| 8 Alien Voice | Metalic Lead | Analog (`.adv`) | 5 (separate — see §3) |

Direct probe of the Drums rack after the push:

```
ableton_device(get_device_chains, track_index=5, device_index=1)
-> { "class_name": "DrumGroupDevice", "chain_count": 0, "chains": [] }
```

**0 chains.** The AG Techno Kit loaded as a bare empty Drum Rack. So all 485
per-pad parameter writes fail:

```
ableton_device('set_parameter') failed: IndexError: chain_index 1 out of range [1, 0]
ableton_device('set_chain_property') failed: IndexError: chain_index 1 out of range [1, 0]
```

(`[1, 0]` = an empty range; the rack has no chains to index.) Same story on Noise's
Instrument Rack (281 failures).

## Root cause: the snapshot has no loadable preset identity for these devices

The three affected instruments are specified in `captured_session.json` with
**`browser_path` ONLY** — `preset_uri` is null, `preset_query` is absent:

```json
"Drums"      device[0]: name="AG Techno Kit",        class="Drum Rack",
             browser_path=["drums","AG Techno Kit.adg"]            // no preset_uri/query
"Noise"      device[0]: name="Inclement Drone Pad",  class="Instrument Rack",
             browser_path=["instruments","Drift","Pad","Inclement Drone Pad.adg"]
"Alien Voice"device[0]: name="Metalic Lead",         class="Analog",
             browser_path=["instruments","Analog","Synth Lead","Metalic Lead.adv"]
```

The snapshot **does** record the full intended nested tree (Drums: 16 chains,
`Kick Dump`…`Ride RKTD1`, each with its Simpler + Erosion; Noise: 2 chains). But on
load the engine produced an empty rack of the right *class* and never populated it
from the `.adg`.

The `ableton_device(action='load')` contract (W13-A) treats `browser_path` as a
**fallback used _alongside_ `preset_uri`** ("tries the URI first; if the URI doesn't
resolve, falls back to a path-scoped browser search by `display_name`"). When
`preset_uri` is **absent**, `browser_path` alone does not appear to drive a
preset-content load — the device comes up bare (loaded by `kind`/class only). And
`/song-snapshot`'s capture "carries `browser_path` forward… (capture probes don't
surface `preset_uri`)" — so a snapshot-refreshed song **structurally cannot** carry
the `preset_uri`, leaving `browser_path` as the only identity, which the loader
won't honor on its own. The two halves combine into: **rack presets are
unreproducible from a snapshot-only fresh push.**

It's specifically RACK presets that die. Native devices that load by kind and take
params directly (Sub Bass: Operator/Saturator/EQ/Utility; Human Riff: Wavetable/
Overdrive/AutoFilter/Saturator/EQ/Redux) pushed cleanly — 0 errors. The `.adv`
Analog ("Metalic Lead") loaded as a settable Analog (its params set fine except
§3), but whether it got the *preset's* actual macro state vs. a default Analog is
unverified and suspect for the same reason.

## Suggested fixes (primary)

1. **Honor `browser_path` as a standalone load source.** If `preset_uri` is
   null/unresolved, resolve `browser_path` (the `.adg`/`.adv` file) against the
   browser and load THAT preset — not a bare device by class. This is the
   load-side half and fixes existing snapshots in place.
2. **Persist a portable preset identity at capture.** When `/song-pick-instruments`
   (or any load) places a rack preset, record `preset_query` (display-name +
   path-prefix, the cross-machine-portable form) into the snapshot so a refresh
   doesn't degrade to `browser_path`-only. Capture can't probe `preset_uri`, but it
   CAN preserve a `preset_query` that was known at author time.
3. **Fail loud on empty-rack load.** A rack that loads with `chain_count == 0` when
   the snapshot recorded N>0 chains should halt the `devices` phase immediately with
   "preset content did not load" — not emit hundreds of `chain_index out of range`
   errors that bury the real cause. (Diagnosing this took a `get_device_chains`
   probe; the 771 errors all point at the symptom, not the empty load.)

---

## §2 — Related: `devices` phase is chatty (1236 single-param round-trips)

Not the user's headline bug but surfaced alongside it (they asked "1219 calls —
were many just defaults?"). Answer: **not defaults.** The capture's non-default
filter works — EQ Eight stores **38–43** of its **84** params per instance, not all
84. The 1236 is a genuinely device-dense song:

```
116  Metalic Lead (Analog)      76  Operator        50  Drift
 83  Grainy Electric Shield      7× EQ Eight ≈ 280  + the two racks' nested trees
```

The real cost isn't redundancy, it's **one MCP round-trip per parameter**. 1236
sequential `set_parameter` calls is the bulk of the push wall-clock, and in this run
**771 of them were doomed** (empty racks) yet each was still dispatched and
round-tripped. Worth considering: (a) a **batch `set_parameters`** call (N params /
device in one round trip); (b) skip the per-param writes for a device whose load
came back structurally wrong (ties to fix #3).

Possible secondary inflation: the non-default filter may compare **normalized
floats** and catch float-epsilon drift as "non-default" — the same rounding noise
that made a clean snapshot re-capture show ~130 spurious param "changes" whose
*display values were identical* (`46.6 ms`→`46.6 ms`, `60.0 s`→`60.0 s`). If the
capture filter has the same epsilon blindness, some "non-default" params are really
defaults-plus-noise. Worth a look; would shrink the call count.

## §3 — Related: pan param pushed as display value → `DisplayValueError`

5 failures on Alien Voice's Analog:

```
ableton_device('set_parameter') failed: DisplayValueError: parameter 'AMP1 Pan'
has a non-numeric display (' 50L'..' 50R'); set it via the normalized `value`
```

The push sent a display-unit target for a pan param whose display is non-numeric
(`50L`/`50R`), which the setter rejects. Pan-style params should be written via the
normalized `value`, not `value_display`. Small, but it's 5 guaranteed failures on
every push of any track with a dialed Analog pan.

## Workaround (today)

For a fresh push of a song with rack presets: after `execute` halts in `devices`,
hand-load each empty rack from the browser (`ableton_browser` to find the `.adg`,
`ableton_device(action='load')` with the resolved `preset_uri`), then re-run
`execute --start-at devices` so the now-present chains accept their params.
