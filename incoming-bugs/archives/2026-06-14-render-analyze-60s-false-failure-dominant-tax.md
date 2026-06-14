# Render/analyze 60s MCP-wrapper timeout is the dominant workflow tax — presents as a hard error, no completion signal, fragile dir-watch workaround

**Severity:** M — reinforces the already-filed
`archives/2026-06-13-analyze-action-exceeds-60s-mcp-timeout-multi-stem.md` and
`archives/2026-06-13-async-render-capability-and-skill-design.md` with fresh
impact data: a single mix-review iteration on swell (2026-06-14) made **4** of
these calls (2 renders ~8 min each, 2 analyses), and **every one returned a
red "timed out after 60s" error** while completing fine server-side. This is now
the single biggest friction in the compose→render→analyze→implement loop.

**Key clarification on the layer.** The framework side is already correct —
`client.py` sets `("ableton_render","render"): None` and
`("ableton_automation","perform_batch"): None` (unbounded socket read), and the
handler runs to completion regardless of the client. The 60 s cap is the **Claude
Code MCP tool-call wrapper**, a different layer the framework can't widen. So the
fix cannot be "raise the socket timeout" — it must be **an interaction shape that
returns within the wrapper budget**:
- `render`/`analyze` start the job and return immediately with a `job_id` +
  `captures_dir`/`report_path`; a cheap `render(action='poll', job_id=…)` (or a
  written `status.json` heartbeat) reports progress/done. This is the
  async-render design already filed — this report is a vote to prioritize it and
  to cover **`analyze` too**, not just render.

**Two UX/doc gaps that compound it (cheap to fix independently of async):**
1. **The timeout reads as a hard failure.** Nothing in the error says "this is
   expected; the job continues server-side and writes `manifest.json` /
   the MixReport when done." A first-time user concludes the render failed.
   Until async lands, the wrapper-timeout error for these actions should carry a
   teaching message: *"expected for long captures — poll `<captures_dir>` for
   `manifest.json`."*
2. **No completion signal, so the workaround is a fragile poll.** The only way to
   know a render finished is to watch the captures dir for `manifest.json`
   (analysis: watch `analysis/` for a newer JSON). I scripted `until [ -f
   manifest.json ]` background waiters each time. A written `status.json`
   (`{state: running|done|error, pct, ...}`) updated by the handler would make the
   wait robust and let an agent show real progress.

**Workaround (current):** fire the call, ignore the 60 s error, background-poll
the captures/analysis dir for the output artifact, proceed when it appears.

**Verifiable signal.** A long render/analyze returns a non-error response within
the wrapper budget and exposes a poll/heartbeat; agents stop scripting dir
watchers and stop surfacing false failures. Surfaced 2026-06-14 dogfooding the
swell mix pass (4 false-failure calls in one iteration).
