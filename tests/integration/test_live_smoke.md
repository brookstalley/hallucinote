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
- Hallucinote MCP installed into Live (`/ableton-mcp-install` if not already; if reinstalling for a code change, `/mcp` to reconnect Claude Code's bridge and **fully quit + reopen Live** so the Control Surface module reloads — see project memory `project_mcp_reconnect_workflow`).
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

### S-1 evidence (2026-05-19)

**Result: PASS — but only after two bug fixes triggered by the smoke.**

The smoke's pass/fail enumeration was incomplete. The spec anticipated
"PASS (idempotent return)" vs "FAIL (destructive overwrite)." Real Live
exhibited a *third* state not in the enumeration: `create_automation_envelope`
returns None (or raises) on already-bound targets — non-destructive but
also non-idempotent.

- Live version: 12.4
- MCP/Remote Script version (post-fix): `0.1.0+c671a9a12dc4`
- **First-pass first read (pre-fix):** `exists: false`, breakpoints `[]` — read could not find the envelope it just wrote.
- **Visual confirmation (pre-fix):** envelope WAS visible in Live, but with a
  spurious 0dB / 0-pan revert-to-default point at the last breakpoint's
  position (write-side bug: zero-duration anchor leaks default-revert).
- **Fixes applied (same session, 2026-05-19):**
  - `_find_existing_envelope` rewritten to iterate `clip.automation_envelopes`
    and match by parameter identity. Falls back to `create_automation_envelope`
    only for the fresh-target case.
  - `_write_breakpoints_as_steps` accepts a `tail_end` kwarg; clip-scoped
    callers (mixer / pan / send / device_parameter / clip_cc /
    clip_pitch_bend) pass `clip.length` so the last step extends to clip
    end instead of leaving a zero-duration anchor.
  - FakeClip / FakeEnvelope updated to mirror real Live (non-idempotent
    create, `automation_envelopes` iteration, `envelope.parameter`).
- **Post-fix Step 4 (first read):** `exists: true`, 3 breakpoints at
  values 0.85 / 0.50 / 0.20 (float32 precision artifacts visible).
- **Post-fix Step 5 (second read):** identical to Step 4 — non-destructive.
- **Post-fix Step 6:** Live's UI shows clean stepped curve, no revert artifact.

---

## Additional smokes — W7-0 session 2026-05-19

Run alongside S-1 once the same fixture was confirmed. Outcomes recorded
in line with each.

### S-3 — `get_device_chains` shape uniformity across rack subclasses

**Goal.** Verify the response shape is uniform across DrumGroupDevice,
InstrumentGroupDevice, and AudioEffectGroupDevice — same keys at each
level so consumers can write one walker.

**Result: PASS.** All three rack types return identical top-level shape:
`{device_index, class_name, chain_count, chains[], parent_kind,
track_index}`. Per-chain shape: `{chain_index, name, device_count,
devices[], is_muted, is_soloed}`. Per-nested-device:
`{position, name, class_name, parameter_count, is_active}`.

Populated case verified against "Late Nite Kit" (16 chains, mixed
device types including a nested `AudioEffectGroupDevice` that's
correctly NOT recursed — the one-level-deep design holds).

**Side findings → filed in backlog:**
- `load(kind='Drum Rack')` with no `preset_uri` can match an Instrument
  Rack saved preset by display name. Use `preset_uri` for unambiguous loads.
- `load(kind='Instrument Rack')` with no `preset_uri` fails outright —
  the bare name isn't a directly-loadable browser node.

### S-5 — class_name preservation

**Goal.** Verify `ableton_device(action='list')` returns canonical class
names that round-trip cleanly across Live 12.4's device-class renames.

**Result: PASS.** Empirical mapping observed:
- Phaser + Flanger → `class_name: PhaserNew` (Live 12 merged into one device
  named "Phaser-Flanger" with class `PhaserNew`; both legacy names route to it)
- EQ Three → `class_name: FilterEQ3`
- Auto Filter → `class_name: AutoFilter2`

Note the asymmetry: `kind` in the load response echoes the requested name
(e.g., `"Phaser"`), while `list` returns the empirical class (`"PhaserNew"`).
That's correct — `kind` is "what you asked for," `class_name` is "what
Live actually instantiated."

### S-6 — parameter-dialed Operator round-trip

**Goal.** Verify W5-D's claim: parameter values survive a set+get
round-trip via the MCP wire format (the core capability that captured
snapshots depend on).

**Result: PASS.** Three parameter shapes tested:
- `Filter Freq` (continuous, internal [0,1] mapped log to Hz): wrote
  0.5 → read 0.5 (display "745 Hz").
- `Tone` (continuous): wrote 0.3 → read 0.30000001192092896 (float32 boundary).
- `Algorithm` (is_enum=true, 11 values): wrote continuous `'5'` → read
  5.0, display "Alg. 6". Enum params accept the continuous write path
  without requiring `value_type='enum'`.

### S-2 — envelope-pull round-trip

**Status: COVERED BY PROXY — not run as a standalone smoke.**

S-1 verified the underlying `ableton_automation(action='read_envelope')`
path (the load-bearing primitive for envelope pull). The pull layer's
diff math is unit-tested in `tests/unit/test_pull.py`. Running a full
pull cycle would require building a song DB just to exercise diff logic
that's already pinned. The composition of `read_envelope` (real-Live
proven) + the pull layer (unit-test proven) is sufficient for V1.

### S-4 — W6-K real-Live confirmation

**Status: SUBSUMED — not run as a standalone smoke.**

W6-K's intent was "validate the bundle of W6 changes against real Live."
S-1 / S-3 / S-5 / S-6 collectively exercised the W6 surfaces that
mattered: envelope read (S-1), nested-rack probe (S-3), class-name
preservation (S-5), parameter writes via Operator (S-6 — covering W5-D
which W6-K bundled). The remaining W6-K items (sidechain, load_in_rack,
set_input_routing) have unit-test coverage and no smoke-caught surprises
during this session's fixture work. Strike — re-open if a specific
W6-K surface needs empirical attention.
