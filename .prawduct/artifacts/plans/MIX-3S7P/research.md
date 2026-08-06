# MIX-3S7P — Research (RESEARCH stage)

**Item:** MIX-3S7P — "play with pan and reverb a bit more, especially in intro and
break. Nothing cheesy — just a little more space. Then snap back to the baseline at
verse/chorus." (area: mix; effort M / impact M)

**researchDone = false.** Per the stage directive: this is a **Live-LOM host-clip
strategy decision, not a music-theory or web-researchable question**, so there is no
web research to do. The substance below is (a) the foreign-API facts confirmed from
the LOM-routing code and DB mutators, and (b) a **discovery that reshapes the whole
item** — most of MIX-3S7P is already authored in the canonical songs repo.

---

## n/a — LOM mechanics, not web-researchable

No external sources consulted. "A little more space, nothing cheesy" is a by-ear
amount (render-gated — see PENDING-BY-EAR below), and "how is a mixer/send envelope
hosted in Live 12.4" is answered by reading our own sync layer + the LOM-gap notes
already in the code, not by a search engine. The directive explicitly set
`researchDone=false` for this reason.

---

## ⚠️ Headline finding — MIX-3S7P is substantially ALREADY IMPLEMENTED

The item brief and the "WHY DEFERRED" note describe MIX-3S7P as *unsolved* (pan/send
envelopes can't span the tacet gaps; host-clip strategy undecided). **That framing is
stale.** The work was authored in the canonical songs repo as part of the back-half
reinvention (decisions/08, dated 2026-06-01) and is committed clean.

### Repo topology (must read before any build)

Three trees exist on disk; only two matter and they are NOT interchangeable:

- **`<repo-root>`** (cwd) — the **framework + plugin**
  repo, branch `develop`. Owns `src/hallucinote/sync/...`, the DB mutators, the audio
  analyzers. This is where the engine lives. It has an **empty `songs/`** (the split,
  PR #133, moved songs out — confirmed in MEMORY `project_root_contract_shipped.md`).
- **`<songs-workspace>`** — the **private songs repo**,
  branch `main`, working tree clean (2 commits: `682cd87` initial, `48b3ad8` gitignore
  caches). This is where `songs/sun-zone-done/build.py` actually lives and builds
  *against the installed engine*. **This is the only canonical home of the song.**
- **`<stale-clone>`** — a **stale pre-split clone of the
  framework**, branch `develop`, last commit `c471b38` (PR #125). It still carries an
  old `songs/sun-zone-done/` that **predates** the MIX-3S7P work (its `build.py` has no
  `_author_atmosphere_envelopes`, no `_ATMOSPHERE`, no MIX-3S7P references). **Ignore
  this tree** — editing it would be working on a dead copy.

> Build-plan implication: the *engine-side* of any MIX-3S7P change (sync planner,
> mutators) is authored in `hallucinote` (cwd); the *song-side* authoring is in
> `hallucinote-songs`. Do not author song code into `hallucinote/songs/` (empty by
> design) or into `hallucinote-2`.

### What is already authored (canonical `hallucinote-songs/.../build.py`)

The "VERIFIABLE SIGNAL" the item asks for — *a decision-record naming the host-clip
strategy + sun-zone-done authoring per-section pan/send for intro+break that returns
to baseline* — **already exists**:

- **Decision record:** `songs/sun-zone-done/decisions/08-back-half-reinvention.md`
  §5 "Per-section pan/reverb space (MIX-3S7P, the clip-hosted route)" + the song md's
  `## Deferred` note (line 103) both name the chosen host-clip strategy explicitly.
- **Authoring:** `_author_atmosphere_envelopes()` + the `_ATMOSPHERE` table
  (build.py ~line 1526–1601) author the intro+break pan/send envelopes. Wired into the
  build pipeline (build.py line 1892: `atmos = _author_atmosphere_envelopes(...)`).
- The breakpoint ranges are in the DB after a build (the item's "verifiable by the
  breakpoints in the DB" — there are committed `.db` files in the song dir, e.g.
  `sun-zone-done-main.db`).

### The host-clip strategy that WAS chosen (the decision-record content)

The item's "WHY DEFERRED" worried that a song-spanning pan/send envelope has GAPS where
organ/lead/steel are tacet (no host clip across the metal choruses), and that the
Amp-Type precedent (one monolithic 736-beat Rhythm Gtr clip) was the only known fix.

**The chosen strategy sidesteps the gap entirely — it does NOT use a monolithic clip
for the atmosphere lanes.** From decisions/08 §5 + the build.py comment block at
line 1526:

> Each section's organ/lead/steel CLIP exists ONLY in that section, so a clip-local
> mixer/send envelope whose breakpoint range sits **entirely inside that per-section
> clip's beat range** is hosted by that clip and nowhere else. The mix **snaps back to
> baseline at verse/chorus automatically** — because the host clip ends at the section
> boundary, so the envelope simply stops existing there; the track reverts to its
> static snapshot send/pan. **No monolithic host clip is needed for these lanes.**

This is the inverse of the Amp-Type solution. Amp Type needed a monolith *because the
rhythm gtr's amp character must persist across the whole arc and the gtr is voiced in
every section* (so the source is never tacet). The atmosphere lanes are the opposite
case: they are *intentionally section-scoped*, and the per-section clip is a perfect,
already-existing host. The "tacet gap" is not a problem to solve — it is exactly where
the envelope is *supposed* to end.

Two distinct host-clip patterns therefore coexist in the song, and the decision record
is the contrast:

| Lane | Host strategy | Why |
|---|---|---|
| Amp Type (genre flip) | **monolithic** 736-beat gtr clip | character must persist song-wide; gtr never tacet |
| intro/break atmosphere pan+send | **clip-local** per-section clips | section-scoped *by intent*; auto-snaps to baseline at the boundary |
| break-drift gtr pan/vol/reverb | **monolithic gtr clip** (bookended to center/baseline) | the gtr IS the source, plays every section, so its lanes ride the existing monolith |

### Envelope identity is the collision-avoidance mechanism

`create_envelope` keys an envelope by `(song, target_kind, target_track_id,
target_send_return_id, parameter_path)` (find-or-create per identity — confirmed in the
mutator and the build comments). So each (track, kind, return) carries exactly ONE
clip-local timeline. The author allocated identities so they don't collide: organ +
drums serve the INTRO; lead + steel serve the BREAK; the OUTRO's extra reverb rides the
**Room** return (a free identity) rather than re-using the Plate lanes. This is the
load-bearing reason a single per-(track,return) timeline suffices — and the documented
limitation: a per-track *per-SECTION* Plate lane (same track wet in two different
sections via Plate) would need an envelope-model change (called out in the build.py
comment at line 1541).

---

## verify-api — foreign-API facts confirmed from LOM-routing code + DB mutators

The item's verify-api ask is "how mixer_pan + send_level envelopes are clip-hosted in
Live 12.4." Confirmed by **reading source** (the preferred verify-api mode), not docs:

1. **Live 12.4 LOM accepts mixer_volume / mixer_pan / send_level / device_parameter
   envelopes only on SESSION CLIPS, not on tracks/master/arrangement directly.** They
   are routed through a session clip on the target track, then
   `duplicate_to_arrangement` snapshot-copies the envelope into the arrangement.
   Source: `src/hallucinote/sync/push/envelopes.py` docstring lines 58–65 + the three
   emitters `_emit_mixer_envelope` (line 600), `_emit_send_envelope` (line 659),
   `_emit_device_parameter_envelope` (line 507). All route via
   `_resolve_and_translate_to_session_clip` (line 423).

2. **The host clip is resolved by BEAT-RANGE COVERAGE, not by name.**
   `_resolve_envelope_session_clip` (`sync/geometry.py` line 231) scans
   `arrangement_clips` on the target track and returns the placement whose
   `[start_beats, start_beats + source_clip.length_beats]` *covers* the envelope's
   `[env_min, env_max]`. **This is the mechanism that makes the clip-local strategy
   work:** an envelope whose breakpoints sit inside a per-section clip's range resolves
   onto that clip and gets translated to clip-local time (`_clip_local_breakpoints`,
   subtracting the placement offset, envelopes.py line 241).

3. **A miss is warn-and-skip, NON-FATAL.** When no arrangement clip on the track covers
   the envelope's beat range, the planner emits a teaching warn and skips that envelope
   (envelopes.py lines 459–472). It does **not** raise. So a too-wide atmosphere range
   that overruns its host clip degrades to "that lane silently doesn't push," surfaced
   as a warn — important for the verification plan (a build-time DB check is required;
   a push that warns is not a failure the harness would otherwise catch).

4. **Coverage uses the SOURCE clip's `length_beats`, not the placement's `end_bar`.**
   If a placement trims the clip shorter than its natural length, breakpoints past the
   trim point won't *sound* in that placement even though they "fit" the source length
   (geometry.py lines 244–251; `_warn_trimmed_placement`, envelopes.py line 364). The
   atmosphere author guards this by ending every clip-local breakpoint range at
   `end - 4.0` beats (the `_hold`/`_ramp` helpers, build.py lines 1566–1579) — i.e.
   keeping the range comfortably inside the host clip's extent.

5. **Multiple placements of the same session clip → the envelope fires at ALL of them**
   (`duplicate_to_arrangement` is a snapshot copy, not a live link;
   `_warn_extra_placements`, envelopes.py line 397). Relevant if any atmosphere host
   clip is placed more than once — for the section-scoped intro/break clips it isn't,
   but a build-plan verification step should assert single-placement for the hosts.

6. **Track-kind gate.** Only `kind='midi'` tracks host these session-clip-routed
   envelopes. (Updated 2026-06-11: ENV-7G4K replaced the old refusal with routing —
   `classify_envelope_route` in envelopes.py partitions midi→session_clip,
   master/group→perform, audio→refused. The session-clip mechanics this research
   relies on are unchanged.) The atmosphere tracks (Organ/Drums/Lead/Steel) are
   MIDI, so this is satisfied — but a build-plan check should confirm no atmosphere
   lane is accidentally targeted at a non-MIDI track.

7. **DB mutator signature (DB-side, no Live needed to author):** `create_envelope`
   (`src/hallucinote/db/mutations/devices.py` line 742) takes `target_kind` +
   `target_track_id` (mixer_pan / mixer_volume) or `target_track_id` +
   `target_send_return_id` (send_level); `parameter_path` is FORBIDDEN for these kinds.
   `replace_breakpoints` (line 1045) sets `{time_beats, value, curve_kind}` rows.
   `create_enum_envelope` (line 1126) is the Amp-Type path. All authoring is pure DB —
   no Live instance required to land the breakpoints (only the push → render verifies).

8. **Post-fader verification limit (shapes the verify plan).** The audio analyzer
   (`src/hallucinote/audio/automation.py`) can verify `send_level` envelopes
   objectively (return RMS moves in the declared direction, ±1.5 dB threshold) and
   `device_parameter` timbre shifts (spectral centroid), **but `mixer_pan` and
   `mixer_volume` are POST-FADER → invisible to the pre-fader stem tap.** It returns
   `measurable=False` with a teaching note rather than a false verdict (automation.py
   lines 61, 135–151). **Consequence:** the pan side of the atmosphere can be confirmed
   *present in the DB* but its *audible width* is NOT objectively measurable by the
   current analyzer — it is irreducibly by-ear. The send (reverb wetness) side IS
   objectively measurable on the Plate return surface.

---

## What is actually OPEN in MIX-3S7P (the design phase should target only this)

The item is mostly done. Three genuinely-open threads remain — the design/build phase
should NOT re-author the already-shipped atmosphere lanes:

1. **The song-spanning dynamic send (the original tacet-gap problem) is STILL deferred.**
   Song md line 104: *"A song-spanning dynamic send (dry-reggae / wet-metal DubDelay
   across the whole arc) still needs a host-clip strategy (it crosses the metal-chorus
   gaps where the source track is tacet) — tracked in MIX-3S7P. The Lead DubDelay stays
   a static send for v1."* This is the one case the clip-local trick does NOT solve,
   because the gesture must persist *across* sections where the source is tacet — the
   exact shape the item's "WHY DEFERRED" describes. If a build is wanted here, the
   monolithic-host approach (a song-spanning host clip on a track that's never tacet, or
   a dedicated silent host clip) is the candidate — but note it is explicitly punted to
   post-v1, so the design should confirm with the user whether to pursue it now or keep
   the static Lead DubDelay send.

2. **PENDING-BY-EAR: the exact amounts.** All atmosphere/space amounts are first-pass,
   render-gated. decisions/08 §"Open / render-gated" + v2/v3 notes list them: the
   atmosphere send/pan amounts, the break-drift ghost level + pan-sweep shape, the
   skank Room/DubDelay levels. Live is UP but UNATTENDED this run → the build-plan must
   flag the *pan width* and the *reverb wetness amount* as PENDING-BY-EAR: **render +
   measure objectively** (send wetness IS measurable on the Plate return per fact #8;
   pan width is NOT — surface it for the human ear), do **not** guess a final number.
   The DB already carries conservative values (e.g. `_ATMOSPHERE` intro organ Plate
   ramps 0.06→0.92, pan −0.30; the skank levels were already bumped once from a render
   that read them inaudible, build.py lines 1776–1777 — concrete evidence the by-ear
   loop is live and the amounts are not yet final).

3. **Model gap (out of scope to fix here, but record it):** the per-(track,return)
   single-timeline identity means a track can't be wet via the same return in two
   different sections with different amounts (build.py line 1541). Not blocking the
   current authoring; flag it as a known limitation if a future section needs it.

---

## PROPOSED deltas to canonical docs (record here; do NOT edit the canonical docs now)

Per the stage constraint (design-only, no canonical edits): the following are PROPOSED,
to be applied later under Critic governance.

- **`sun-zone-done.md` `## Deferred` (line 104):** if/when the song-spanning DubDelay
  send is built, move it out of Deferred and into the authored list (it currently says
  "still needs a host-clip strategy"). Until then, leave it — it is the honest open item.
- **No canonical *framework* model doc needs a change for the shipped atmosphere lanes**
  — the clip-local routing is an existing, documented capability of `sync/push/
  envelopes.py`, not a new mechanism. The only candidate framework delta is the
  per-(track,return)-per-section model gap (#3 above) IF a build chooses to address it;
  that would touch the envelope identity model and belongs in its own item, not MIX-3S7P.

---

## Verification approach for the build phase (Live UP, UNATTENDED)

- **DB-level (objective, no Live):** build the song, assert the intro+break atmosphere
  envelopes exist with breakpoints in the expected beat ranges, on MIDI tracks, single
  host-clip placement, range ≤ host clip extent. This is the item's stated verifiable
  signal and is fully checkable in a song-side shape test.
- **Plan-level (objective, no Live):** run `plan_push_envelopes` against the song DB and
  assert each atmosphere envelope produces a `write_envelope` ToolCall (not a
  warn-and-skip) — i.e. every lane resolves onto its host clip. A skip here is the
  silent-failure mode and must fail the test.
- **Render-level (objective, Live UP):** push → render → `ableton_analysis`. The Plate
  **send** wetness lift in intro+break IS objectively measurable (return RMS up in the
  declared direction); assert it. 
- **PENDING-BY-EAR (cannot resolve unattended):** the pan **width** (post-fader,
  unmeasurable) and the subjective "nothing cheesy / a little more space" amount.
  Render, surface the measured send numbers, and **flag the pan + the aesthetic amount
  as a by-ear call for the human** — do not guess the final value.
