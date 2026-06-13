# Design request — asynchronous render (+ a render→analyze skill) (2026-06-13)

Context: mix pass on `swell`. `ableton_render(render)` and
`ableton_analysis(analyze)` both exceed the 60 s MCP call timeout (see
`2026-06-13-analyze-action-exceeds-60s-mcp-timeout-multi-stem.md`). render is
inherently realtime/minutes; it completes server-side but returns a **false
failure** and gives **no completion signal**, so the agent must poll the
filesystem for `manifest.json`. This proposes the proper fix, designed for agent
productivity + minimal context pollution.

## Principles

1. **Never hold the MCP socket for the realtime duration.** Kick-off returns
   immediately.
2. **Don't force polling, and never dump WAV lists / full manifests into agent
   context.** The agent should get a single tiny "kicked off" payload and, later,
   a single tiny "done" payload — nothing else.
3. **One completion signal, model-friendly.** Prefer a mechanism the host
   harness already understands (background-task completion notification) so the
   agent is *re-invoked on completion* rather than burning turns polling.
4. **A render is useless without its analysis** — the common path is
   render→analyze→read-summary. Make that one skill so the agent expresses intent
   once and gets back only the interpreted result.

## Framework layer — make `render` non-blocking

Split the action:

- `render(action='start', span...)` → returns immediately:
  `{render_id, captures_dir, expected_stop_beat, eta_seconds}`. Tiny. The
  realtime pass runs under the Remote Script's transport observer (it already
  drives transport + sfrecord~); the MCP call just arms it and returns.
- `render(action='status', render_id)` → tiny:
  `{state: 'running'|'done'|'failed', progress_beats, captures_dir, error?}`.
  No file lists.
- On completion the server writes the existing `manifest.json` (the sentinel)
  **and** emits a completion event the host can surface as a background-task
  notification (same channel Claude Code uses for backgrounded Bash) so the
  agent is *woken* on done instead of polling.
- Crucially, `start` must not block other MCP calls. If Live's single-threaded
  LOM makes true concurrency impossible during transport playback, at minimum the
  server should reject/queue concurrent calls with an instant
  `{busy: true, render_id}` rather than letting them hang to a 60 s timeout
  (what `session(info)` did mid-render).

## Skill layer — `/render-analyze` (the least-context-polluting path)

A dedicated skill so the agent never manages realtime mechanics:

```
/render-analyze [start_beat] [stop_beat] [--compare <seq>]
```

Orchestration (all OUT of the agent's main context):
1. `render(action='start', ...)`.
2. Wait on completion via a **background task** watching for `manifest.json`
   (the pattern that worked in this session) — its poll output goes to the task
   file, not the conversation.
3. `analyze(...)` (run in-process / server-side; also long — same async
   treatment).
4. Return to the agent **only**: the MixReport `summary` (true-peak, overshoot
   count, per-section count, out-of-tolerance reverbs) + `report_path` + an
   optional one-line delta vs `--compare`. The full per-stem / per-band JSON
   stays on disk for the agent to read *selectively* if a finding warrants it.

Net agent context cost for a full verify cycle: one skill call in, one ~6-line
summary out. Today it's: a timed-out render error, a filesystem poll, a manual
in-process analyze invocation, and hand-written extraction scripts.

## Interim (works today, no framework change)

The pattern used this session: call `render` (ignore the 60 s false-failure),
launch a **backgrounded** `bash` loop that waits for `manifest.json`, then run
`analyze` in-process via Python. The skill above is this, productized, with the
poll output kept out of context.

## Cross-refs

- Symptom + render/session false-failure detail:
  `2026-06-13-analyze-action-exceeds-60s-mcp-timeout-multi-stem.md`.
