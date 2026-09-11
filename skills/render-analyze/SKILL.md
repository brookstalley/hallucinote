---
name: render-analyze
description: Render a song to audio AND analyze the mix in one step, with the long-running render→analyze poll loops kept OUT of your main context. Delegates the orchestration (ableton_render start→poll, then ableton_analysis start→poll) to a subagent and surfaces back ONLY the MixReport summary (master true-peak, overshoot count, per-section count, out-of-tolerance reverbs) + the report_path — the full per-stem/per-band JSON stays on disk for /mix-review. Use when you want a fresh analysis and would otherwise hand-drive the render + analyze start/poll loops (before /mix-review, or to A/B a mix change with --compare). Both render and analyze are start+poll because they exceed the 60s tool-call timeout (see ableton://guides/conventions "Long-running actions = start + poll"). Needs Max for Live (the render uses the HallucinoteAnalyzer).
argument-hint: <song-slug> [start_beat] [stop_beat] [--compare <seq>]
user-invocable: true
disable-model-invocation: false
---

# /render-analyze — render + analyze, the poll loops kept out of your context

> **Running engine commands.** The engine ships in the plugin's uv env. Resolve `$PY` once from `ableton://server/info`'s `python`; the `hallucinote …` commands below run as `"$PY" -m hallucinote.cli …`. See [`docs/running-the-engine.md`](../../docs/running-the-engine.md).

A full render is realtime (minutes) and a many-surface analyze can exceed the
60 s tool-call timeout, so both are **start + poll** actions (see
`ableton://guides/conventions` "Long-running actions = start + poll"). Driving
both poll loops yourself fills your context with `running…` statuses. This skill
**delegates the whole render→poll→analyze→poll dance to a subagent** and brings
back only the MixReport summary — so your context stays on the music, not the
plumbing.

> **Requires Max for Live** — the render uses the HallucinoteAnalyzer (a M4L
> device). Without it you can't render; use `/compose-review` (symbolic; runs on
> Standard as well as Suite) for an intent read instead. See `ableton://guides/getting-started`.

## Arguments

- `<song-slug>` (required) — the song to render + analyze.
- `[start_beat] [stop_beat]` (optional) — render only this window (default: the
  whole arrangement). **Beats, not bars.**
- `[--compare <seq>]` (optional) — diff the new report against the prior analysis
  whose `db_seq` matches this audit-log seq (per-surface loudness deltas +
  significance flags). To A/B a mix change: push the change first, then
  `/render-analyze <slug> --compare <db_seq-of-the-before-report>` (a
  mutate-without-push mislabels the report's own audio — see `/mix-review`).

## What to do — delegate the orchestration to a subagent

The point of this skill is that the poll loops run in a **subagent's** context,
not yours (the standard "heavy work in a clean context" delegation — see
`/prawduct:building` "Delegating Work to Subagents"). Spawn ONE subagent with the
Agent tool, give it the instructions below, then surface ONLY what it returns.

Subagent instructions (fill in the args from the invocation):

> Render the song `<slug>` and analyze the result, then return ONLY a compact
> summary. Do NOT echo intermediate `running` statuses or the full report.
>
> 1. **Render (start + poll).** Call `ableton_render(action='start',
>    song_slug='<slug>')` — add `start_at_beat=<start_beat>` /
>    `stop_at_beat=<stop_beat>` if given. It returns `{job_id, captures_dir,
>    poll}`. Then call `ableton_render(action='status', job_id=<job_id>)`
>    repeatedly — each call long-polls ~45 s — until `state` is `done` or
>    `failed`.
>    - `state='failed'` → STOP and return the `error` verbatim (it's a teaching
>      message — often a stale server or an open analyzer device-editor window;
>      see `ableton://guides/error-recovery`). Do NOT retry blindly.
>    - `{busy: true, job_id}` on start → a render is already running; poll that
>      `job_id` instead of starting a second.
>    - On `done`, keep `captures_dir` (and `render_status` — `ok`/`incomplete`),
>      **and `warning` whenever the status carries it** — the render raised an
>      advisory it did not refuse over (a soloed rack chain today), and dropping
>      it here is the one place the operator can no longer learn the capture is
>      not the mix as authored. Relay it verbatim in step 3.
> 2. **Analyze (start + poll).** Call `ableton_analysis(action='start',
>    song_slug='<slug>', captures_dir='<captures_dir from the render>')` — add
>    `compare_to=<seq>` if `--compare` was given. Then poll
>    `ableton_analysis(action='status', job_id=<job_id>)` until `done` or
>    `failed`. (`eta_seconds` is null for analyze — just poll.) On `failed`,
>    return the `error`.
> 3. **Return ONLY** (one short block, no full report): from the analyze `done`
>    status's `report` summary — master true-peak (dBTP), overshoot count,
>    per-section count, out-of-tolerance reverb count, and the
>    `analysis_code.stale` flag if true — plus `report_path`, plus (if
>    `--compare` was given) the one-line significant-delta count + overshoot
>    delta — **and `master_deltas_refused` whenever the summary carries it**,
>    **and the render's `warning` from step 1 whenever there was one.**
>    That key means the master was measured as not the sum of its stems, so
>    the master rows were WITHHELD and the delta counts beside it are smaller
>    for that reason, not because the render was quieter. Relaying the counts
>    without it inverts their meaning. Say which side was disqualified and on
>    what number. The full per-stem / per-band MixReport JSON stays on disk at
>    `report_path` for `/mix-review` to read; do not paste it.

When the subagent returns, present its summary in 2–3 lines and offer the next
step — usually **`/mix-review <slug>`** to interpret the report against the
song's intent (this skill produces the report; `/mix-review` reads it). If the
subagent returned a `failed` error, relay the teaching message + the fix, don't
silently re-run.

## Capture retention — old takes are swept automatically

Each render writes a take to `songs/<slug>/captures/<ts>/` holding a
32-bit-float WAV per track, return and master — roughly 23 MB per
surface-minute, so a full-length multi-track song costs gigabytes per take.
**Render start** applies a rolling window: it keeps the **2 newest takes that
already exist** and removes the rest, then the render adds its own — so a song
settles at **3 takes on disk** after each render. This is safe because the
MixReport in `songs/<slug>/analysis/` is the durable measurement — analysis reads
a take once and writes a self-contained JSON, and `--compare` resolves against
those JSONs, never the audio. Reports are never swept.

**Pin when the user expresses intent to keep this take** — they say to keep or
save it, or they ask to come back to it later. Don't wait to be asked in those
words; the window is silent and irreversible —
**an unpinned take survives the next two renders and is removed at the start
of the third**. But pin on *that* signal only, not on a passing compliment or a
nickname: a pin is permanent and does **not** consume a keep slot, so pinning
liberally re-creates the unbounded growth this window exists to stop. **Say so
when you pin**, and name the unpin (`captures unpin <dir>`) — an unmentioned pin
is a gigabyte the user never agreed to keep:

```
"$PY" -m hallucinote.cli captures pin songs/<slug>/captures/<ts>
```

`"$PY" -m hallucinote.cli captures list` shows what's on disk;
`… captures prune --song <slug> --dry-run` previews a sweep.

`HALLUCINOTE_CAPTURE_KEEP` changes the window and `HALLUCINOTE_CAPTURE_SWEEP=0`
disables the automatic sweep — but both are read by the **MCP server process**,
so they must be set in the `env` block of this server's entry in the user's
Claude settings, not exported in a terminal. The server logs
`retention sweep disabled` at INFO when the opt-out actually reached it.

## Exit criteria — this stage is done when

A MixReport exists **for the current build** — not a stale take from before the
last `/ableton-push` — and the render covered the **full arrangement length**. A
report over a truncated capture will read as a finished song that simply lacks
its ending, which is indistinguishable from a song whose ending was never built.
Check the report's span against the arrangement before handing it to
`/mix-review`.

Full model: [docs/song-workflow.md](../../docs/song-workflow.md#stage-exit-criteria).

## Why a subagent (not inline, not a CLI)

The render/analyze poll loops are pure plumbing — dozens of `running` statuses
that would bury the musical thread in your context. A subagent runs them in its
own context and hands back just the summary. It can also **react** to the
actions' teaching errors (busy / failed-with-diagnosis / unknown-job) instead of
following a rigid script — which a deterministic CLI couldn't. One render +
one analyze at a time per server (the actions enforce this with a `busy` handle).
