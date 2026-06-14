# `pull device-parameters --dry-run` is unusable as a drift detector — reports every preset default as "added" + false "updated" on normalized params

**Severity:** M (correctness/usability of the bake preview) — the dry-run that
backs `/snapshot-bake-recent-changes` (and the natural Live↔source drift check)
cannot surface a real change. On an **in-sync** song it reports thousands of
"mutations"; and in the version-skew case it reports **zero** (every probe
failed). Broken in both directions, so it can neither confirm sync nor flag drift.

## What happens (swell, in sync, version-matched)

`python -m hallucinote.sync.pull_cli execute device-parameters --song swell --dry-run`
→ **mutations: 2530, no_ops: 91**, on a song whose dialed params all match Live.

Classifying the 2530 detail rows:
- **2452 "added"** — every preset-default knob on every device. The DB stores
  only *dialed* params (`params_dialed`); the pull reads the **full** parameter
  surface from Live and treats any param the DB doesn't hold as an `added`
  mutation. So a perfectly in-sync song shows 2452 "changes" that are just
  defaults the DB deliberately doesn't track.
- **78 "updated"** — the genuinely dialed params, flagged as changed even though
  the values match. Verified equal:
  - DB `Drum Buss` `Boom Amt` `value_normalized=0.35` vs Live raw `0.3499994` → equal,
    but reported `updated -> '35 %'`.
  - DB `Drum Buss` `Transients` `value_display="0.30"`, **`value_normalized=NULL`**
    vs Live raw `0.296875`/disp `"0.30"` → equal, reported `updated -> '0.30'`.
  Cause: the DB stores continuous params as a rounded `value_normalized` *or* a
  `value_display` string with `value_normalized=NULL`; the dry-run reads Live's
  raw value and the comparison doesn't round-trip the representation, so equal
  values read as `updated -> '<the same value>'`.

Net: a genuine knob move would be **1 line lost among 2530**. The skill's "show
the user what would change" step is meaningless and its `applied.mutations >= 1
→ continue` branch fires unconditionally.

## The dangerous twin (same command, version skew)

When Live's Remote Script is version-skewed from the working tree, every probe
raises a version-mismatch warning and the **same command reports `mutations: 0`**
— which reads as "in sync." So the detector silently degrades to a false "all
clear" exactly when it can't read anything. (Cost us a wrong "0 drift" read this
session until the per-probe warnings were noticed.)

## Why it matters

`/snapshot-bake-recent-changes` is the closed-loop way to make by-ear mix /
sound-design tweaks durable before a rebuild. Its whole value is the preview
("here's what would change, confirm to bake"). With the current behavior the
preview is unusable, so the human can't tell a real tweak from noise — and the
zero-on-error case can convince them nothing drifted when something did.

## Proposed fixes (any subset)

1. **Diff only DB-tracked params**, not the full Live surface — capturing every
   preset default is not the bake's job. (Or: only report a param as drift if it
   differs from the device's *default*.)
2. **Round-trip-aware comparison** — normalize both sides (raw float w/ epsilon,
   or both via display) before declaring `updated`; backfill `value_normalized`
   for display-stored params so equal values don't read as changes.
3. **Fail loudly on probe errors** — if probes error (version mismatch, etc.),
   return a nonzero/error status instead of `mutations: 0`; never let "couldn't
   read" look like "no drift." (Arguably the highest-priority half.)
4. Optionally split the report: `defaults_captured` vs `dialed_changed` vs
   `unreadable`, so the human sees the one number that matters.

## Repro

In-sync, version-matched swell:
`pull_cli execute device-parameters --song swell --dry-run` → 2530 mutations
(2452 `added` defaults + 78 false `updated` on dialed continuous params), 91
no_ops. Spot-check any `updated` row's DB `value_normalized` against the live raw
— equal.

Filed from the swell production pass, 2026-06-14.
