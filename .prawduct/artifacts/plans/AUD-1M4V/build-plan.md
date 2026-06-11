# AUD-1M4V — Discovery Work Cycle Build Plan (probe tool + LOM probes + requirements artifact)

The AUD-1M4V umbrella ("Audio as first-class material") is at `stage: requirements` —
this cycle is the **discovery pass**, not implementation of the umbrella itself. It has
one code chunk (the probe tool that makes capability-probing a first-class, repeatable
operation), one evidence chunk (run the probes in real Live), and one artifact chunk
(the discovery/requirements document the umbrella's verifiable signal demands).

Branch: `feature/aud-1m4v-discovery` off `develop` (gitflow — pass the develop base to
`/prawduct:critic` and the PR reviewer, per `feedback_pr_gate_base_is_develop`).

## Requirements Confidence: **High** (for this cycle's own scope)

- **Problem (one sentence):** We cannot answer AUD-1M4V's design questions (audio clips,
  audio/group/master automation, in-Live vocal recording) without empirical LOM evidence,
  and today every probe requires hand-writing throwaway Remote Script code plus a Live
  restart per iteration.
- **Success (one sentence):** A permanent `ableton_probe` bridge tool exists (tested
  against fakes), the prioritized LOM probe list has been executed against real Live
  12.4.1 with results recorded, and a discovery artifact exists that the AUD-1M4V
  children can carry `refs:` to.
- **Out of scope (one sentence):** Implementing ANY of the umbrella's children (no
  audio-clip DB model, no envelope changes, no recording workflow) — this cycle produces
  evidence and requirements, and the staged plan for the children comes out of it.

**User-locked requirements (2026-06-10, this session):**

1. **Vocal ingest: in-Live recording first** — the bridge arms/routes/records against
   the click, then ingests; file-import is the secondary entry point.
2. **Master/group automation is a must-have early** — prioritized right after the
   audio-clip DB model; the realtime-automation-recording probe is critical path.
3. **Warp depth: minimal place-and-conform for wave 1** — file ref, gain, pitch,
   warp on/off + mode, start/end markers; warp-marker-level DB modeling later
   (write API confirmed present, so no door closes).
4. **Probe tool is permanent** — a constrained introspection action, not a throwaway
   (capability probing recurs per `feedback_third_party_devices_require_capability_probing`).
5. **Requirements must be producer-led, not LOM-led** (user direction): the deep-research
   pass on producer/mixing/mastering practice ("must-haves, best practices, never-dos")
   feeds the requirements artifact alongside the LOM evidence; capabilities are framed
   as what the music needs, with LOM facts constraining the *mechanism*, never the scope.

**Open assumptions / unknowns:**

- `[ASSUMPTION: wave-1 "ingest" = recorded clip modeled in DB (file ref + placement)
  and readable by the existing analysis pipeline; pitch-extraction-to-MIDI from audio
  is a separate later axis | HIGH impact | user can veto before the artifact locks]`
- `[ASSUMPTION: the probe tool may execute mutating LOM calls (that is its purpose —
  create_audio_clip IS the probe); safety comes from the bridge being localhost-only
  and single-user, and from probing in scratch Live sets | MED impact | user can
  override]`
- `[ASSUMPTION: probe results from Live 12.4.1 (build 2026-05-20) are the capability
  baseline; older Live versions are out of scope (12.2 is the floor for
  create_audio_clip) | LOW impact]`

## Status

- [x] Chunk 01: `ableton_probe` — permanent constrained LOM introspection action
      (+ small follow-ups: `then` chaining, `set` action, `any` ParamType)
- [x] Chunk 02: LOM probe suite executed against real Live 12.4.1 — all seven areas
      answered; results in `docs/research/audio-first-class/lom-probe-results.md`
- [x] Chunk 03: `discovery.md` authored; backlog updated (AUD-1M4V→design, children
      re-scoped, new children ENV-7G4K performed-automation + AUD-9R3V recording
      workflow)
Context: discovery cycle COMPLETE 2026-06-10. Headlines: CLP-AUD2 browser-load
design retired (create_audio_clip native since 12.2); ENV-8H1T reduces to deleting
a refusal once CLP-AUD1 lands; master/return performed-automation mechanism
playback-verified; recording end-to-end verified incl. comping shape. Probe Live
state (PROBE-AUDIO track, temp-project recordings, master/return automation lanes)
left in the scratch set — operator discards by not saving. Next: fresh cumulative
Critic (chunk-01 warning: old AUD-4W7K findings do NOT vouch for this branch),
then PR into develop per /prawduct:pr.

## Chunk 01 — `ableton_probe` (the only code chunk)

**What:** New bridge tool `ableton_probe` with actions `describe` / `get` / `call`:

- `describe(path)` — resolve a LOM path, return class name, properties (with values
  for JSON-primitives, type names for objects/vectors), methods.
- `get(path)` — read one property; serialized (primitives as-is, LOM objects as
  `{__lom__, repr}`, vectors as truncated lists).
- `call(path, method, args?, kwargs?)` — invoke a LOM method with JSON args; an arg of
  shape `{"$path": "song...."}` resolves to a live LOM object first (needed for e.g.
  `clip.create_automation_envelope(track.mixer_device.volume)`).

**Path grammar:** roots `song` | `application`/`app`; then `.attr` and `[int]` only —
tokenized by regex, resolved by getattr/index. No eval, no arbitrary expressions.

**Files:** `actions/probe.py` (schema), `handlers/probe.py` (resolver + serializer +
handlers), `actions/__init__.py` (import), `server.py` (`_register_tool` + docstring
counts 12→13), unit tests `tests/unit/test_actions_probe.py` (fakes per existing
convention).

**Foreign API:** Ableton Live LOM (via LiveContext) — but this chunk only *reflects*
over it (getattr/dir/call passthrough); the probe tool is itself the verify-api
mechanism for every later chunk.

**Done when:** schema registered (help included), handlers tested against fakes
(resolution errors, serialization shapes, $path args, per-attribute error capture),
full suite green, chunk Critic run.

## Chunk 02 — probe execution (evidence, not code)

Prioritized probe list (from the two LOM research passes; full rationale lands in
`discovery.md`):

1. `Track.create_audio_clip` / `ClipSlot.create_audio_clip` — signatures, path/format
   constraints, frozen/MIDI-track errors, returned clip state (warping default,
   file_path).
2. Arrangement clip `automation_envelope` / `create_automation_envelope` — expect
   None/error (decides automation architecture).
3. Audio session clip mixer-envelope write end-to-end (`create_automation_envelope`
   on `mixer_device.volume` → `insert_step` → `value_at_time`).
4. Realtime automation recording onto group/master mixer params (`record_mode` +
   `session_automation_record` + scripted `param.value` sweeps) — the only candidate
   master/group write path; **must-have early per user lock #2**.
5. Recording surface: `fire(record_length=)` kwargs, `trigger_session_record`,
   routing enumeration, resulting clip `file_path`, count-in accessibility.
6. `dir()` diffs vs Live 11.0 inventory on Clip/ClipSlot/Track/Song (undocumented 12.x
   RS additions); warp-marker write call shape (dict vs kwargs).

**Operator step:** Remote Script reinstall (copy-based install) + Live quit/reopen
once; all probes then run over the TCP bridge with no further restarts.

## Chunk 03 — discovery artifact + staged plan

`discovery.md` in this dir: LOM probe results (evidence), producer-practice research
synthesis (requirements source — raw research lives in
`docs/research/audio-first-class/` per user direction 2026-06-10: producer-practice
deep research, mastering gap-fill, two LOM passes; LINK, don't restate), the user's
four locks, the staged plan across children
(CLP-AUD1, CLP-AUD2, ENV-8H1T, ENV-3M7K, ENV-4M2T, AUD-6T2K; TPL-2D8K referenced, never
duplicated), and explicit requirement→mechanism traceability. Then
`/prawduct:backlog update` AUD-1M4V `stage=design refs=…` + children `refs:`.

**Critic mode:** chunk (per chunk); cumulative at PR time.
