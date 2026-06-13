# Bug report — `ableton_analysis(action='analyze')` exceeds the 60 s MCP call timeout on multi-stem songs (2026-06-13)

Context: mix/production review of `swell` (hallucinote-songs), a 23-surface
song (21 instrument tracks + Meter Hat + PRE-MAIN bus, 4 returns, master).
Plugin/MCP: `hallucinote-mcp` as launched by the plugin via uv; Live 12.x Suite,
set open. Capture `songs/swell/captures/20260613T004633Z` (machine→summit,
beats 515–705).

## TL;DR

```
mcp__plugin_hallucinote_hallucinote-mcp__ableton_analysis(action='analyze', song_slug='swell')
-> MCP server "plugin:hallucinote:hallucinote-mcp" tool "ableton_analysis" timed out after 60s
```

The analyze pipeline for a many-stem capture (loudness + attribution + masking +
timing + cross-rhythm, per the handler enabling all of these whenever the song
declares sections) takes **longer than the 60 s MCP tool-call timeout**, so the
call is abandoned and **no report is written** — even though the analysis would
have completed successfully given more time.

## Proof it's the transport timeout, not the analysis

Calling the *same* handler in-process from Python (off the MCP socket) with a
longer budget completes cleanly and writes the report:

```python
from hallucinote_mcp.handlers.analysis import analyze_handler
analyze_handler(None, song_slug="swell",
                captures_dir=".../captures/20260613T004633Z")
# -> writes songs/swell/analysis/20260613T131638Z.json, exit 0
```

Wrote `analysis/20260613T131638Z.json` (full per-section loudness + masking +
timing) in well under the 5-minute budget I gave it. So the DSP is fine; the
bottleneck is purely the 60 s ceiling on the MCP tool call.

## It is NOT just `analyze` — `render` and `session(info)` time out too (false failures)

Same session, after the mix pass, I rendered the machine→summit window
(`render`, start 515 / stop 705):

```
mcp__…__ableton_render(action='render', song_slug='swell', start_at_beat=515, stop_at_beat=705)
-> tool "ableton_render" timed out after 60s
```

…but the render **completed server-side**: a full `captures/<ts>/` dir appeared
with all 29 surface WAVs + a well-formed `manifest.json` (`status: ok`, 23
surfaces). A subsequent `ableton_session(action='info')` *also* timed out at 60s
**because the MCP server was still busy** driving the realtime pass. So:

1. The 60 s ceiling is **per-MCP-call, global** — it hits any long action
   (`analyze`, `render`) AND blocks unrelated calls (`session info`) while a long
   action runs.
2. `render` is **inherently** realtime and multi-minute (here ~98 s of playback
   for 190 beats + ring-out) — a 60 s cap can essentially never fit a real
   render, yet renders *do* finish and write correct output. The caller just gets
   a **false failure** (error returned, work actually succeeded) with **no
   completion signal** — you have to poll the filesystem for `manifest.json` to
   know it finished.

This makes the async-action fix below not just nice-to-have but necessary for
`render` to be usable at all without filesystem-polling workarounds.

## Why this is general, not swell-specific

Analysis cost scales with surface count (per-stem passes) and with the
cross-surface passes (masking/attribution are O(stems) to O(stems²)-ish). Most
*finished* songs are 15–25 tracks, so this is not a swell edge case — it will
hit essentially every song at mix-review time, which is precisely when the tool
is most needed. The richer the per-section analysis (masking/timing/cross-rhythm,
all auto-enabled when sections are declared), the more likely the timeout.

## Suggested fixes (in preference order)

1. **Make `analyze` a long-running/async action like `render`.** `render`
   already runs multi-minute realtime passes and returns a task handle the
   client polls — `analyze` has the same shape (kick off, poll, fetch report).
   This removes the unbounded-time-vs-fixed-timeout mismatch entirely and is the
   robust fix since analysis time is unbounded in track count.
2. **Raise the per-call timeout for this specific action** (action-scoped
   override) if the harness allows it — simpler but still a fixed ceiling, so it
   only defers the problem to larger songs.
3. **Speed up / parallelize the DSP** (per-stem passes are embarrassingly
   parallel; masking is the expensive cross term) — worthwhile regardless, but
   doesn't remove the fundamental unbounded-time issue.

(1) is the real fix; (2)/(3) are mitigations.

## Workaround for now

Run the handler in-process via Python with a longer timeout (as above), or split
captures into smaller beat windows so each `analyze` call stays under 60 s. Both
are friction the async-action fix would remove.

## Repro

1. Open a 20+-track song in Live with sections declared in the DB.
2. `ableton_render(render)` a multi-section span.
3. `ableton_analysis(action='analyze', song_slug=<slug>)` → times out at 60 s,
   no report written.
