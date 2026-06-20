# `ableton_render` analyzer auto-load renames RETURN tracks (` | HallucinoteAnalyzer`) — breaks subsequent DB↔Live return linking

**Severity:** M (silent DB↔Live drift; every push after a render fails to link the
returns until a human renames them back). Not data-loss, but it derails the
push pipeline for any return-targeting phase (`returns`, `mix` sends,
`performed_automation` of `send_level` / `return_mixer_volume`, `device-sidechain`
sourced from a return) and is easy to misread as "the song's returns went missing."

**Engine version:** `1.5.0`.

## What happens

`ableton_render(action='start')` auto-loads `HallucinoteAnalyzer` on every audio
track + return + the master (idempotent device-load). On RETURN tracks the load
**also renames the return**, appending ` | HallucinoteAnalyzer` to its name:

- DB returns: `Reverb`, `Delay`
- After a render attempt, Live returns: `A-Reverb | HallucinoteAnalyzer`,
  `B-Delay | HallucinoteAnalyzer`

`push probe-and-link --probe` then can't match them — the suffix defeats the
name normalizer (which already strips the `A-`/`B-` return-letter prefix), so:

```
"unmatched_db_returns":   [{"name": "Reverb"}, {"name": "Delay"}]
"unmatched_live_returns": [{"name": "A-Reverb | HallucinoteAnalyzer"},
                           {"name": "B-Delay | HallucinoteAnalyzer"}]
```

Renaming the returns back to `Reverb` / `Delay` (`ableton_return(action='rename')`)
makes the next `probe-and-link` clean (`unmatched_*: []`).

## The tell: TRACKS with the analyzer are NOT renamed

The same render loads `HallucinoteAnalyzer` onto every audio TRACK too (e.g. on
`alien`'s Human Riff it sits at device_index 7), yet those tracks keep their names
("Human Riff" linked fine). Only RETURN names get the ` | HallucinoteAnalyzer`
suffix. So the rename is specific to the return-load path, not a universal
device-load side effect — which points at the return-specific insertion code.

## Repro (alien, branch `compose/swell`, engine 1.5.0)

1. A pushed song with two returns named `Reverb` / `Delay`, linked + performed.
2. `ableton_render(action='start', song_slug='alien', …)` — even a render that then
   FAILS (e.g. audio engine off; transport never advances) is enough: the analyzer
   auto-load runs before the transport gate, so the returns are already renamed.
3. `push probe-and-link --song alien --probe` → returns now `unmatched` (see above);
   tracks still match.

## Impact / why it matters

- The integrity story is "DB is the source of truth, Live is regenerable" — but a
  render silently mutates Live return names in a way the relink can't reconcile.
  A `send_level` arc whose destination return is now unlinked won't perform; a
  return `mix`/`device` phase silently no-ops or errors.
- It's invisible unless you run `probe-and-link` and read `unmatched_*`. An agent
  that renders, then later pushes, will hit confusing return failures with no
  obvious cause.

## Suggested fixes (pick one)

1. **Don't rename on analyzer load** — load the device without touching
   `Track.name` on returns (match the track-load path, which doesn't rename).
2. **Strip a trailing ` | HallucinoteAnalyzer` in the name normalizer** so
   probe-and-link matches regardless (defensive, but leaves Live names dirty).
3. **Restore return names after the render** (capture pre-load names, rename back
   in the render teardown), so a render leaves Live byte-for-byte as it found it.

(1) or (3) preferred — (2) hides the symptom but the dirty names persist in the set.

## Workaround (today)

After any render, before the next push: `ableton_return(action='rename')` each
return back to its DB name, then `probe-and-link` to confirm `unmatched_*: []`.
