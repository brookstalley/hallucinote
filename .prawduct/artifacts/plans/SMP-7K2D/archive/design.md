---
lifecycle: superseded
archived: 2026-09-08
superseded_by: "brookstalley/hallucinote#330 (author a Simpler or Sampler with an assigned sample)"
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# SMP-7K2D — Sample-instrument + the playback-parameter model

`status: design` · `cluster keystone` · driver: swell's buried-"we" centerpiece
(`hallucinote-songs/songs/swell/decisions/17-buried-we-centerpiece.md`)

This is the design for the **swell buried-"we" centerpiece cluster** — the four
backlog items filed 2026-06-13 (SMP-7K2D, ENV-4S2K, AUD-7R3M, AST-6D3K). It
supersedes the per-report framing those items were filed under: investigation
(2026-06-13, two read-only code maps + the user's requirements review) collapsed
the cluster onto a single principle and shrank it substantially.

## The problem

swell's centerpiece reveals a recorded "we all" sample through a per-phrase
window that widens with `breath`, folded as a time-palindrome (forward into the
phrase centre, then reversed out), under a centre-peaked volume aura. To author
that from `build.py`/DB the framework needs, decomposed to decision-free
primitives:

| # | Need | Status (post-investigation) |
|---|---|---|
| 1 | An instrument that plays an **assigned sample**, MIDI-triggered per phrase | ❌ **the keystone — genuinely missing** (SMP-7K2D) |
| 2 | Per-phrase `S Start`/`S Length` window automation, **sample-accurate** | ✅ **already shipped** (ENV-4S2K — see §"ENV-4S2K") |
| 3 | The fold — forward, then **reversed** | ↳ reverse is a playback parameter (§"The decision") |
| 4 | The centre-peaked volume aura | ✅ already shipped (`mixer_volume` clip envelope) |

Everything hangs on #1: nothing is audible until an instrument carries the
sample. #2 and #4 already work; #3 is a parameter, not a new subsystem.

## The decision (the load-bearing one)

**There is ONE immutable source asset — the recording. Every other property of
how it sounds — window start/length, gain, pitch, warp, AND reverse — is a
*declared playback parameter*, materialized onto the Live element at push. The
engine never duplicates the audio as an author-facing artifact.**

`reverse=True` is in the same family as `pitch_coarse=-12`: a property of the
*playback*, not a new file. This is not a new abstraction — it is the model
**CLP-AUD1 already shipped and didn't finish**. The `clips` audio columns
(`schema.sql:95-129`) are `audio_file`, `audio_gain`, `pitch_coarse/fine`,
`warping`, `warp_mode`, `start_marker`/`end_marker` — a list that is *entirely*
playback transforms on one immutable `audio_file`. **`reverse` is the
conspicuously missing sibling.** We complete that family; we do not bolt a
file-rendering pipeline beside it.

### Why this is the right model for all songs, going forward

- **Source-of-truth integrity.** The repo ethos is "`build.py` is the source of
  truth." A committed/derived `…-rev.wav` is a second source that silently goes
  stale when the recording or the fold changes. A declared `reverse` flag can't.
- **No intermediate state to retire.** A reverse *parameter* is the final shape;
  there is nothing provisional about it. (Explicit user constraint, 2026-06-13:
  "no intermediate state we're just going to retire later.")
- **Generalises.** Pitch/gain/warp/window already work this way; reverse joins
  them; trim is `start_marker`/`end_marker`; normalize is `audio_gain`. The
  playback-param family already covers the transforms the original AST-6D3K
  pipeline proposed to render — as *parameters*, not files.
- **Composability stays with the song.** swell's fold (forward-windowed voice +
  reverse-windowed voice of the same asset) is composed in song-local
  `breath.py` out of two parameterized sample-instruments — exactly the
  framework-owns-primitives / song-owns-the-gesture boundary the reports drew.

## The data model

Two carriers of the sample-playback spec, sharing one vocabulary:

**A. Audio clips (`clips`) — already most of the way there.** Add the one
missing playback param:

- `clips.reverse INTEGER` (0/1, nullable; NULL/0 = forward) — sibling to
  `warping`. This is AUD-7R3M's audio-clip path.

**B. Sample-instruments (`devices`) — the keystone primitive.** The *one*
genuinely missing thing is the **sample assignment**:

- `devices.audio_file TEXT` (nullable) — song-relative POSIX (canonically under
  `assets/`) or absolute, stored exactly as authored, resolved at push via the
  existing `paths.resolve_audio_path` (the SAME resolver `clips.audio_file`
  uses). NULL for every non-sampler device (mirrors how `clips.audio_file` is
  NULL for MIDI clips).

Crucially, the sample-instrument's **window / reverse / pitch / gain do NOT need
new columns** — they are *device parameters* of Simpler/Sampler (`S Start`,
`S Length`, `Reverse`, `Transpose`, `Volume`) and are already expressible two
ways that both ship today:

- **static initial value** → `device_parameters` row (`set_device_parameter`);
- **automated** → a `device_parameter` envelope (ENV-4S2K, sample-accurate on a
  clip-hosted MIDI track — see below).

So SMP-7K2D's DB surface reduces to **one nullable column** (`devices.audio_file`)
plus its snapshot encoding + push materialization. That is the whole keystone
data model.

### Questions the data must answer (lock-in discipline)

A persisted column is lock-in; before designing fields, enumerate the consumers'
future queries (`/prawduct:building` decision-research):

- "What sample does this instrument play?" → `devices.audio_file` (resolved like
  `clips.audio_file`).
- "Is this clip/sample played in reverse?" → `clips.reverse` (clip) /
  `device_parameters` row or envelope named `Reverse` (sample-instrument).
- "What window/pitch/gain?" → existing `device_parameters` + envelopes; no new
  fields.
- "Does it round-trip through the snapshot / `/song-snapshot`?" → yes — the
  device dict gains an `audio_file` key (capture probes it, replay materializes
  it), mirroring how the clip path already round-trips. (Same authorship-middle
  gap SNP-4K7M flagged for master devices — closed here for sample assignment.)

No field answers a question we can't name today → the additive shape is safe.

## Per-item disposition (cluster re-triage)

- **SMP-7K2D** (keystone) — `stage: requirements → design`. Scope = `devices.audio_file`
  + snapshot encoding + push sample-assignment. Push mechanism gated on the
  probe (§"The capability probe"). The DB/snapshot half is probe-independent and
  buildable now.
- **ENV-4S2K** — **largely already shipped; narrow to a confirmation + a doc.**
  A `device_parameter` envelope on a MIDI track covered by its session clip
  ALREADY routes to the sample-accurate `Clip.create_automation_envelope` path
  (`sync/push/envelopes.py` `classify_envelope_route` → `_emit_device_parameter_envelope`),
  NOT the lossy perform path; and targets are already a DB FK (`target_device_id`
  → `devices.id`), so they survive re-push within a build. Curve-kind loss on
  push (stepped holds) is a non-issue for a per-phrase window (set-once-per-phrase
  = a step). The semantic-addressing half (part 2 of the report) is **ergonomic
  sugar, not a correctness fix** — defer on rule-of-three. Remaining work: a
  confirmation test (route = session_clip for a sample-instrument track) + a
  one-line "breakpoint at/just-before the trigger note-on" authoring-discipline
  doc. Both no-Live.
- **AUD-7R3M** — **reframed**: "reverse is a playback parameter." Delivered as
  `clips.reverse` (audio-clip path) and, for a sample-instrument, as a `Reverse`
  device parameter / envelope (probe-gated whether the window-capable device
  exposes it). No standalone "reverse capability."
- **AST-6D3K** — **demoted; recommend close.** An author-declared derived-asset
  pipeline is the wrong abstraction (it makes the author manage a transform that
  should be an invisible parameter, and reintroduces a second source of truth).
  Its transforms are already playback params (reverse→`reverse`, trim→markers,
  normalize→`audio_gain`). The ONLY residual is a possible **hidden, push-time,
  deterministic materialization fallback** (§"Push design") — internal plumbing,
  never an author surface, never committed — and only if the probe shows a device
  gap. Track that residual under SMP-7K2D's push chunk, not as its own pipeline.

## The capability probe (the gate; needs Live)

The whole "does any reversed buffer ever get rendered" question reduces to one
device-capability fact, and the house rule is **probe, don't recall**
(`feedback_third_party_devices_require_capability_probing`,
`feedback_producer_led_requirements`). The reports' "Simpler has the window but
no Reverse; Sampler has Reverse but no window" is a *recalled* probe (2026-06-12)
and must be re-verified before the push mechanism is fixed.

Probe (scratch Live set, MCP bridge):

1. **Sample assignment.** How does a sample get onto a Simpler/Sampler via LOM?
   (a) `application.browser.load_item` on an audio-file BrowserItem onto a MIDI
   track (Live auto-wraps in Simpler), vs (b) load a Simpler device then set a
   sample property / hot-swap. Which works for an arbitrary `assets/` file?
   (Note the CLP-AUD2 caveat: `browser.load_item` needs the file addressable as a
   BrowserItem — Library/User/Places — not an arbitrary filesystem path.) Also
   confirm Live 12.2+ `create_audio_clip(abs_path)` is NOT the path here (that's
   clips, not instrument samples).
2. **Window + reverse co-expressibility.** Full Simpler AND Sampler playback
   surface: is there a `Reverse` param, is it an automatable `DeviceParameter`,
   and does it coexist with automatable `S Start`/`S Length`? Also probe whether
   Live's **audio-clip** reverse (the `clips.reverse` path) is LOM-settable.

Outcome determines SMP-7K2D's push mechanism (below). The DB/snapshot design is
robust either way — the probe changes HOW push materializes, not WHERE the
author declares.

## Push design (conditional on the probe)

`devices.audio_file` materialization, in the device-load push phase
(`sync/push/devices.py`):

- **If `browser.load_item(audio-file)` is the path** → the load ToolCall for a
  sample-bearing device resolves `audio_file` via `paths.resolve_audio_path`,
  ensures it's a loadable BrowserItem, and loads it (Live wraps in Simpler).
- **If a device-then-set-sample path exists** → load the device, then a
  sample-assign ToolCall points it at the resolved path.

Reverse materialization:

- **If window + reverse are co-expressible on one device** → reverse is a
  `device_parameter` (static or envelope); pure parameter-setting, **no file
  ever**.
- **If Live genuinely can't co-express them** → the engine MAY render a
  deterministic, content-addressed reversed buffer at push to honour a declared
  reverse on a window-only device. This is the demoted AST-6D3K residual:
  **hidden push plumbing** (like a compiler temp), deterministic, cached,
  **never authored, never committed, not an interim to retire**. Lives in the
  numpy-bound `hallucinote.audio` layer (NOT the stdlib-only pure layer, NOT the
  MCP server startup path — `project_mcp_server_stdlib_only`). Build only if the
  probe forces it.

## Boundary / contract notes

- **Database Schema surface** (`boundary-patterns.md` §"Database Schema"):
  adding `devices.audio_file` + `clips.reverse` touches the schema. Update
  mutators AND queries together; add the **additive migration in `init_db`**
  (`feedback_open_song_db_via_init_db` — bare connect reads a stale schema);
  re-run the full suite and rebuild a song with `--reset`. Both are nullable
  additive columns → no existing row invalidated.
- **Snapshot surface** (`capture.py`): the device dict gains an optional
  `audio_file` key; `replay_capture` materializes it; `capture_plan` probes it.
  Additive — old snapshots (no key) replay unchanged.
- **No MixReport/JSON schema bump** involved (different surface).

## Staged build plan (detail in `build-plan.md`)

0. **Probe** (Live) — gates chunks 3–4.
1. **`devices.audio_file` DB model** (no-Live) — schema + init_db migration +
   `create_device(audio_file=)` + event + snapshot replay encoding + tests.
   *The keystone foundation.*
2. **`clips.reverse` DB model** (no-Live) — schema + migration + clip-audio
   mutator support + validation + tests. *AUD-7R3M audio-clip path, DB side.*
3. **Sample-instrument push** (Live, probe-gated) — device-load materializes the
   assigned sample; capture probe round-trips it.
4. **Reverse push** (Live, probe-gated) — `clips.reverse` honoured at push and/or
   `Reverse` device-param path; hidden-materialization fallback only if forced.
5. **ENV-4S2K lock** (no-Live) — confirmation test (route=session_clip on a
   sample-instrument track) + the note-on ordering doc.

Chunks 1, 2, 5 are buildable now without Live. 3, 4 wait on the probe.

## Alternatives considered

- **Author-declared derived-asset pipeline (original AST-6D3K)** — rejected as
  the default: reintroduces a second source of truth, makes the author manage a
  transform that should be a parameter, and is heavier (build-time audio DSP) for
  no author benefit over a flag. Survives only as the hidden push fallback.
- **Preset-baked sample** (sample travels inside a Live preset via
  `preset_uri`/`preset_query`) — rejected: per-machine, not portable, and the
  sample isn't declared in `build.py` (fails source-of-truth).
- **Track-scoped sample assignment** — rejected: leaky; the sample is a device
  property in Live (Simpler holds it), so a track-level home mis-models it.
- **Sampler `Reverse` automation as the fold (route 2)** — dominated for the
  windowed reveal: Sampler has no automatable window, so live reverse costs the
  breath-windowing mechanism. Only viable if the probe shows Sampler can window.

## Open questions (resolve at/after the probe)

- The push sample-assignment mechanism (probe outcome #1).
- Whether any hidden reverse materialization is needed at all (probe outcome #2).
- Whether `clips.reverse` is LOM-settable on audio clips (probe outcome #2) — if
  not, the audio-clip reverse path is DB-authorable but push-blocked, noted as
  such (the sample-instrument path is swell's actual need regardless).
