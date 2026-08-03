# Song creation in Hallucinote — the full picture

This is the map for making a song here: the **lifecycle** (which skill runs each
phase, and the two review checkpoints agents most often miss), and the
**expertise** behind every tool — grounded in the framework's research corpus,
linked so it never rots out of sync. Read it when you start song work, or when
you want to understand *why* a tool does what it does and how to go deeper.

For the always-in-context short version, the `/song-workflow` skill is the same
map at a glance. This doc is the depth.

---

## The one idea: creativity first, depth on demand

Two commitments shape everything below. They are not in tension — they're the
same stance seen from two sides.

**Creativity first — intent is the ruler.** Hallucinote is a *producer*, not a
gatekeeper. It never declines a directed request, never makes a creative
decision on the user's behalf without surfacing it, and treats every measurement
as a *producer's question* ("is the chorus landing?"), never a verdict. A
near-silent part, a drone, a dissonance, a 3/4 bar in a 4/4 song — these are
valid art, and nothing in the build blocks them.

- The producer stance, the propose-and-react discipline, and the three intent
  registers (directed / volunteered / directed-but-underarticulated):
  [intent-collaboration-model.md](../.prawduct/artifacts/intent-collaboration-model.md).
- Why nothing aesthetic can fail a build (BLOCKING is reserved for *likely
  errors* — pitch out of range, zero duration — never choices):
  [gate-verdict-policy.md](../.prawduct/artifacts/gate-verdict-policy.md).
- Why helpers are **rulers, never stamps** — a generator removes bookkeeping but
  must never make the musical decision:
  [generator-altitude-policy.md](../.prawduct/artifacts/generator-altitude-policy.md).

**Depth on demand.** The same song can be a five-minute sketch or a deeply
authored piece. The toolkit reduces work; it never caps what's authorable. When
a helper doesn't reach far enough, you drop a level — down to hand-authored notes
if that's what the art needs (the [depth ladder](#going-as-deep-as-you-want)
below). Tools are conveniences, not limits.

---

## The lifecycle

Song-making here is a **loop, not a line** — you'll circle back through compose
and mix many times. But the arc has a natural order, and two of its phases are
*review checkpoints* that are easy to skip and shouldn't be:

| # | Phase | Skill(s) | The expertise behind it |
|---|-------|----------|-------------------------|
| 1 | Frame the intent | `/song-new`, `/song-context` | [onboarding-and-teaching-model.md](../.prawduct/artifacts/onboarding-and-teaching-model.md), [intent-architecture.md](../.prawduct/artifacts/intent-architecture.md) |
| 2 | Pick instrument **chains** | `/song-pick-instruments` | sound design is composition (below) |
| 3 | Compose the parts | `/compose-part` | [melody-model.md](../.prawduct/artifacts/melody-model.md), [performance-model.md](../.prawduct/artifacts/performance-model.md), [arrangement-model.md](../.prawduct/artifacts/arrangement-model.md) |
| 4 | **Read the composition** ⭐ | **`/compose-review`** | melody + recurrence lenses vs declared intent |
| 5 | Materialize in Live | `/ableton-push` | [push-execute-design.md](../.prawduct/artifacts/push-execute-design.md) |
| 6 | Capture + analyze | **`/render-analyze`** (`ableton_render` → `ableton_analysis`, poll loops kept out of context) | [masking-analyzer-goals.md](../.prawduct/artifacts/masking-analyzer-goals.md) |
| 7 | **Read the mix** ⭐ | **`/mix-review`** | masking · loudness · feel · energy vs intent — *needs Max for Live* |
| 8 | Snapshot + iterate | `/song-snapshot` (durable mix bake), `/ableton-pull` (build.py-staging) | — |

The two ⭐ checkpoints are the ones agents forget exist. **They are not
optional polish — they are how the framework's ear gets applied to your work.**

### 1 — Frame the intent
`/song-new` scaffolds `songs/<slug>/` (build.py, captured_session.json, tests,
decisions/, annotations/, attempts/, song.md). Before that, and throughout, the song's
*intent* — key, the central tension, what the chorus does, the energy arc — is
the thing everything else serves. Don't auto-decide it: at an elementary musical
fork the user hasn't directed, **propose and read their reaction** (the third
register). Three recall surfaces, one per question: prior *intent* → `/song-context`;
the audit trail of compose-time decisions → `/decisions`; **what you already tried on a
part and how it turned out** (incl. reverted dead ends) → `/song-attempts`, before you
re-touch a part you've worked before.

### 2 — Pick the instrument chains (sound design *is* composition)
`/song-pick-instruments` picks a *chain* per track — instrument **plus**
post-instrument FX **plus** initial send levels — not a bare instrument. The
saturation, the drum bus, the room reverb send ship *in the snapshot*; they're
authorship, not a mix-time todo. A finished song has the sound it's supposed to
have as part of being finished.

### 3 — Compose the parts (author-as-code)
`/compose-part` writes note-generating code in the song's `build.py` using
`hallucinote.generators`, runs the build (DB through mutators; events fall out),
and scoped-pushes the changed clips. Notes are authored as code and never enter
the agent's context. This is where the line-level craft lives:

- **Melody** is a structural dimension — contour, intervals, harmonic fit,
  motivic economy. There is *no universal "good melody"*: a line is graded
  against a **declared profile**, not a universal substrate.
  → [melody-model.md](../.prawduct/artifacts/melody-model.md)
- **Microtiming feel is authorship**, not a post-hoc humanize pass. Per-part
  push/pull/swing/drag is baked into the pattern at generation time, coordinated
  across instruments where the genre calls for it (human timing is 1/f-correlated,
  not white noise). → [performance-model.md](../.prawduct/artifacts/performance-model.md)
- **Form, energy, and recurrence** — sections, the energy arc, which motifs
  recur where and as which variation — are authored on the arrangement model, not
  raw mutators. → [arrangement-model.md](../.prawduct/artifacts/arrangement-model.md)

### 4 — Read the composition ⭐ `/compose-review`
After a first compositional pass — or whenever you'd ask "does this work?", "is
the hook landing?", "what's missing?" — `/compose-review` recalls the declared
intent, reads the *composition* (sections, density, register, the energy arc)
plus the symbolic **melody lens** (contour, intervals, harmony-fit) and
**recurrence lens** (which motifs return, as which variation), and interprets it
*against intent*: "you wanted the chorus to lift — does it? here's the one thing
holding it back." A producer's question, never a score. This is the
compositional sibling of `/mix-review`, and it runs **before** the mix stage.

### 5 — Materialize in Live `/ableton-push`
`/ableton-push` drives fourteen ordered phases (tempo → meter → tracks → returns
→ scenes → clips → mix → devices → routing → device-sidechain → envelopes →
performed automation → arrangement → cues) against a fresh or partial Live set —
idempotent, with preflight and rollback. → [push-execute-design.md](../.prawduct/artifacts/push-execute-design.md)

### 6 — Capture + analyze `/render-analyze`
`/render-analyze` runs the capture + analysis in one step: `ableton_render`
auto-loads the HallucinoteAnalyzer and runs a WAV capture pass; `ableton_analysis`
builds a **MixReport** from the captures (loudness, master attribution, reverb
verification, per-part timing/feel, masking, energy realization). Both are
realtime / long-running **start + poll** actions (they exceed the 60 s tool-call
timeout — see `ableton://guides/conventions` "Long-running actions = start +
poll"), so `/render-analyze` delegates their poll loops to a subagent and hands
back only the MixReport summary + `report_path` — keeping the plumbing out of
your context. This is the expensive real-time step — it feeds the next checkpoint.

**Capture retention.** Each render writes one take to `songs/<slug>/captures/<ts>/`
— a 32-bit-float WAV per track, return and master, roughly 23 MB per
surface-minute, so a full-length multi-track song costs gigabytes per take. A
rolling window runs automatically **at render start**: it keeps the **2 newest
takes already on disk** and removes the rest, then the render writes its own — so
a song settles at **3 takes** after each render. (`hallucinote captures prune
--keep 2` run on its own leaves 2, because no new take follows it.) Deleting an
old take is safe because the durable measurement is the MixReport in
`songs/<slug>/analysis/` — analysis reads a take once and writes a self-contained
JSON, and baseline comparison (`compare_to`) resolves against those JSONs, never
the audio. Reports are never swept; what a sweep costs is re-analyzing that
specific take with different parameters.

To keep a reference take permanently, pin it — `hallucinote captures pin
songs/<slug>/captures/<ts>` (pinned takes are skipped by every sweep and don't
consume a keep slot). An unpinned take survives the next two renders and
is removed at the start of the third.
`hallucinote captures list` shows what's on disk and `hallucinote captures prune
--song <slug> --dry-run` previews a sweep without deleting.

`HALLUCINOTE_CAPTURE_KEEP` changes the window and `HALLUCINOTE_CAPTURE_SWEEP=0`
turns the automatic sweep off. Both are read by the **MCP server process**, so to
affect the automatic sweep they must be set in the `env` block of this server's
entry in the user's Claude settings — exporting them in a terminal reaches the
CLI but not the server. The server logs `retention sweep disabled` at INFO when
the opt-out reached it, so the setting confirms itself.

### 7 — Read the mix ⭐ `/mix-review`
The single read-side surface over all audio analyses. It reads rendered audio, so
it **needs Max for Live** (Live Suite, or the M4L add-on); `/compose-review` is the
any-edition symbolic read. `/mix-review` recalls the
song's intent, reads the whole MixReport per section, and interprets the
measurements *against* intent — surfacing only the collisions that hurt the
element meant to *win* each section, framed as a producer's question. Masking is
its richest input: masking is the *depth mechanism* of a mix, not a defect — the
question is "is the focal element winning?", not "where do frequencies collide?".
→ [masking-analyzer-goals.md](../.prawduct/artifacts/masking-analyzer-goals.md)

Both review skills **learn revealed intent back** as a markdown annotation, so
they never re-flag a choice you've confirmed.

### 8 — Snapshot + iterate
**The one-bake model (BAK-3M9T).** There is one durable mix bake and one staging
primitive — they write different targets:
- `/song-snapshot` → `captured_session.json` (git-tracked, **durable**). The
  **single mix bake**: params, sends, device chains, and sidechain sources. The
  next `build.py` reproduces your dialed mix from it.
- `/ableton-pull` → the song `.db` (a **regenerable** build artifact). The
  lower-level **build.py-staging** primitive for build.py-owned domains (clip
  notes, automation) you fold into `build.py`. It is NOT a parallel mix bake:
  `replay_capture` re-asserts the snapshot onto the DB every build.

**The contract is enforced (BAK-7D2V).** A mix edit you pull but don't
`/song-snapshot` is no longer silently reverted — as long as the snapshot
carries a `captured_at` stamp, the next `build.py` **refuses to run**
(`StaleSnapshotError`), and `pull_cli` prints a durability notice at pull time.
(A legacy snapshot with no stamp leaves replay no ordering evidence, so it warns
and still reverts; baking once makes the check exact from then on.) So the loop
is **pull → bake → build**: `/ableton-pull` (stage) → `/song-snapshot` (bake,
which writes a fresh capture stamped newer than the pull and so disarms the
guard) → `build.py` (runs clean). `build.py --force-replay` consciously discards
the pulled edits instead. Build.py-owned pulls (notes, envelopes, tempo, cue,
arrangement, tuning) do not themselves arm the guard — that's the sanctioned
staging lane. The exception worth knowing: `score-globals` shares one probe with
master volume/pan ingest, so a "tempo-only" pull arms the guard whenever the
master fader or pan drifted. Arming follows the event kinds a pull actually
emitted, not the domain you asked for — so trust the durability notice.

Then loop back to compose or mix.

As you loop, keep the **attempt ledger** (`songs/<slug>/attempts/`, `kind: attempt`)
current — log each move you *tried* and how it turned out (`outcome` worked/partial/failed,
`resolution` kept/reverted/superseded), **especially the reverted dead ends**, chaining a
correction with `related:` → the move that worked. The two review checkpoints propose these
entries; `/song-attempts` recalls them. This is the per-song memory that stops the next loop
from re-running a move that already failed — distinct from `annotations/` (revealed intent)
and `decisions/` (what you kept and why). Schema + worked example:
[`.prawduct/artifacts/song-conventions.md`](../.prawduct/artifacts/song-conventions.md)
"The attempt ledger".

---

## The expertise behind the tools — five layers

The corpus is a deep, adversarially-verified body of design research. It groups into
five layers; each lens and skill above draws on one or more. Go here when you
want to understand *why*, or to author at a depth the helpers don't reach.

1. **Compositional structure** — what a song is made of and how parts relate;
   form, energy, harmony, motif, recurrence; the dimension taxonomy that decides
   "is X a new axis?". → [arrangement-model.md](../.prawduct/artifacts/arrangement-model.md)
2. **Melodic line** — contour, intervals, expectation, harmonic fit, motivic
   economy; declared-profile-over-universal-substrate.
   → [melody-model.md](../.prawduct/artifacts/melody-model.md)
3. **Performance & feel** — the rendition layer; microtiming, dynamics,
   articulation; the metaperformer pattern; 1/f timing.
   → [performance-model.md](../.prawduct/artifacts/performance-model.md)
4. **Mix & analysis** — masking as a perceptual goal, loudness, reverb, energy
   realization; the producer-question framing.
   → [masking-analyzer-goals.md](../.prawduct/artifacts/masking-analyzer-goals.md)
5. **Intent & collaboration** — the producer stance, the three registers, the
   learn-back loop, and where intent lives (WHAT in build.py / WHY in markdown).
   → [intent-collaboration-model.md](../.prawduct/artifacts/intent-collaboration-model.md),
   [intent-architecture.md](../.prawduct/artifacts/intent-architecture.md)

Orthogonal to these five is **where a song's authorship lives** — generative code
(`build.py`) vs materialized state (`captured_session.json`) vs recorded assets —
and why, plus the LOM read/write walls that bound it.
→ [authorship-model.md](../.prawduct/artifacts/authorship-model.md)

The scope boundaries — what is *deliberately not modeled* (texture-mass music,
unmetered rubato, process-based pieces) and the graceful degradation path to the
raw note floor — are catalogued in
[boundary-patterns.md](../.prawduct/artifacts/boundary-patterns.md).

---

## Going as deep as you want

Depth is a ladder. Most songs live near the top; reach down exactly as far as the
art demands.

1. **Helpers** — `hallucinote.generators` and the skills above. Fast, idiomatic,
   genre-aware. Where most authoring happens.
2. **Review lenses** — `/compose-review` and `/mix-review` apply the framework's
   ear to your work and teach contrast and subtraction by example.
3. **The research** — the five layers above. Read the model when a lens raises a
   question you want to reason about from first principles.
4. **Hand-author** — when a helper doesn't reach far enough, write the notes (or
   the envelope, or the device chain) directly. The toolkit is a convenience, not
   a ceiling; a gap in the helpers is never a reason to scope the art down. Probe
   the platform, then build the capability or hand-build the result.

**Specialized side-paths** (rare; off the mainline so the common case stays
simple):

- **Alternate tunings** (19-EDO, just intonation, Bohlen-Pierce, …) — load the
  `.ascl` in Live, run `/tuning-pull <slug>` to capture it onto the song, then
  author in scale degrees via `hallucinote.tuning.mapper`. The 12-TET path is
  untouched. → [docs/alternate-tunings.md](alternate-tunings.md).

---

## Where things live (the authoring model)

- **WHAT** the song is → `build.py` (note-generating code) → the DB through
  mutators (every write emits an event).
- **WHY** it is that way → git-tracked markdown in `annotations/` and
  `decisions/` (the single authored home for intent; the DB is not an authoring
  surface). → [intent-architecture.md](../.prawduct/artifacts/intent-architecture.md)
- **The sound** → device chains in `captured_session.json` (authorship, per
  phase 2 above).

Operational conventions — directory layout, frontmatter schema, the toolkit
philosophy, drum-kit probing, meter handling — live in
[song-authoring-conventions.md](song-authoring-conventions.md). The skill index
is [skills.md](skills.md); the quick first-song walkthrough is
[quickstart.md](quickstart.md).
