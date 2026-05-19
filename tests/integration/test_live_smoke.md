# Real-Live smoke tests

Manual smoke tests that exercise `hallucinote-mcp` against a real Ableton Live process. These cannot run unattended in CI — they require Live 12.4 running locally with the Hallucinote Remote Script installed and an MCP-capable agent (Claude Code) connected.

Each smoke is reproducible and self-contained: open Live, run the listed MCP calls in order, compare the observed output against the expected output, record pass/fail in `.prawduct/.session-reflected` or the chunk's evidence note.

Smokes here are gates for round-trip reliability — when a Live API behavior is assumed by code but not verified empirically, the unit suite gives false confidence (see `learnings.md` — `Unit fakes that mirror an *assumed* Live API give false confidence`).

---

## S-1 — W6-G/H envelope read idempotency

**Risk being verified.** The W6-G/H envelope read path (`hallucinote_mcp/src/hallucinote_mcp/handlers/automation.py:171-194`, `_find_existing_envelope`) calls `clip.create_automation_envelope(target)` on the assumption that **Live treats this as create-or-return** — returning the existing envelope when one is already bound. If real Live's implementation is destructive (creates a fresh envelope, wiping any bound one), the read path silently destroys the envelope it's reading.

**What the unit suite proves.** `hallucinote_mcp/tests/unit/handlers/test_envelope_read.py` (and adjacent) passes against a `FakeClip` where `create_automation_envelope` is implemented as idempotent. The fakes mirror the **assumed** API. This smoke is the only way to confirm the assumption holds in real Live 12.4.

**Pass criterion.** Reading the same envelope twice in a row returns the same breakpoints both times, identical to what was written.

**Fail criterion.** The second read returns empty / different breakpoints — indicating the first read destroyed (or modified) the envelope. **If this fires**, the read path must switch to **iterate `clip.automation_envelopes` and match by parameter identity** (already noted as the fallback in W6-G's design — see `.prawduct/backlog.md:11`).

### Prerequisites

- Ableton Live 12.4 installed and the active version Hallucinote MCP targets.
- Hallucinote MCP installed into Live (`/ableton-install-mcp` if not already; if reinstalling for a code change, `/mcp` to reconnect Claude Code's bridge and **fully quit + reopen Live** so the Control Surface module reloads — see project memory `project_mcp_reconnect_workflow`).
- A new empty Live set (`File → New Live Set`).

### Steps

1. **Create the fixture.** In Live, add one MIDI track (the new set should already have one) and one device — any device with a continuous parameter works; a Glue Compressor is a good default. Drag a short empty MIDI clip into clip slot 1 (Session view). You should now have: Track 1 (MIDI), Clip 1 in slot 1, Glue Compressor at device index 1.

2. **Confirm Claude Code sees the session.** Ask the agent:
   ```
   Call ableton_session(action='info').
   ```
   Confirm response includes track 1 and the clip in slot 1.

3. **Write a known envelope.** Author a `mixer_volume` envelope with 3 distinct breakpoints on the clip. Use Claude Code to run:
   ```
   ableton_automation(
       action='write_envelope',
       target_kind='mixer_volume',
       track_index=1,
       clip_index=1,
       location='session',
       breakpoints=[
           {'time_beats': 0.0,  'value': 0.85, 'curve': 'hold'},
           {'time_beats': 1.0,  'value': 0.50, 'curve': 'hold'},
           {'time_beats': 2.0,  'value': 0.20, 'curve': 'hold'},
       ],
   )
   ```
   Watch Live: the clip's volume envelope lane should now show the stepped curve.

4. **First read.** Ask the agent to call:
   ```
   ableton_automation(
       action='read_envelope',
       target_kind='mixer_volume',
       track_index=1,
       clip_index=1,
       location='session',
       resolution_beats=0.25,
   )
   ```
   Record the full response (`breakpoints`, `exists`, `time_range_beats`).

5. **Second read.** Immediately repeat the exact same call. Record the second response.

6. **Visual confirmation.** Look at Live's envelope lane on the clip. **The stepped curve should still be visible**, unchanged from step 3.

### Pass / fail

- **PASS** — Step 4 response includes 3 breakpoints (or close — sampling rate may merge breakpoints separated by less than `resolution_beats`) matching the values from step 3. Step 5 returns the same breakpoints. Step 6 confirms the envelope is intact in Live's UI. **The "create-or-return" assumption holds.** Record evidence and proceed to W7-A.

- **FAIL** — Step 4 succeeds (breakpoints come back) but step 5 returns empty / different breakpoints. OR Live's UI in step 6 shows an empty envelope lane. **The "create-or-return" assumption is broken.** `_find_existing_envelope` is destructive against real Live.

### Fail-path remediation

If S-1 fails, before W7-A starts:

1. Replace `_find_existing_envelope` (`handlers/automation.py:171-194`) with an implementation that **iterates `clip.automation_envelopes` and matches by parameter identity**. Use a stable identifier on each envelope's `parameter` attribute (e.g., `parameter.name`, plus disambiguation by parent device / track index when needed). **Do NOT use `is` for the parameter comparison** — Live re-wraps API objects (`learnings.md` — `Never use is for Live API object identity`).
2. Add a `FakeClip` variant in the test fakes that simulates the destructive behavior, and pin the new fallback against it.
3. Re-run S-1 to confirm the fix.
4. Record evidence and proceed to W7-A.

### Recording evidence

Append to the W7-0 chunk reflection in `.prawduct/.session-reflected`:

```
S-1 (W6-G/H idempotency): PASS|FAIL
- Live version: 12.X.Y
- Step 4 breakpoints (count + first/last): ...
- Step 5 breakpoints (count + first/last): ...
- Step 6 UI state: ...
- Fix applied: none | <brief description>
```

---

## Future smokes (placeholders — populated as wave-7 progresses)

- **S-2** — W7-A envelope-pull round-trip (added in W7-D).
- **S-3** — W7-B `get_device_chains` shape uniformity across rack subclasses (added in W7-D).
- **S-4** — W6-K real-Live confirmation pass (added in W7-D).
- **S-5** — Phaser/Flanger and Eq3/FilterEQ3 class_name preservation (added in W7-D).
- **S-6** — W5-D parameter-dialed instrument sound parity (added in W7-D).
