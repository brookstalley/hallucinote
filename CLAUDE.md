# CLAUDE.md — Hallucinote

<!-- PRAWDUCT:ANCHOR — static governance pointer managed by the prawduct plugin. Keep it small and version-free: principles, methodology, and the active version live in the plugin and are injected at session start. -->

## Governance (Prawduct)

This repo is governed by **Prawduct**, installed as a Claude Code plugin — not as
committed framework files. The principles, methodology, Critic protocol, and PR
review live in the plugin and are read on demand (run `/prawduct:methodology`);
they are intentionally not copied into this repo.

**Before writing any code, STOP and read the build cycle: `/prawduct:building`.**
Skipping it is the #1 governance failure.

The hardest rules (everything else is in the plugin):

- **Tests are contracts** — fix the code, never weaken a test.
- **No "pre-existing" exception** — fix what you find, or flag why you can't.
- **Never silently drop a requirement** — say so explicitly.
- **Run `/prawduct:critic` after medium+ work** — never write Critic findings
  yourself; the independence is the value.

**Enforcement is structural:** the plugin's Stop hook runs at session end and
**blocks** if code changed against an active build plan with no Critic findings.
The session-start banner shows the active version and what changed — this anchor
stays version-free.

## Hallucinote Behavioral Norms

### Stop only on high-stakes decisions or must-answer questions

Once a workflow is authorized, don't stop between steps to summarize-and-ask. Continue until you hit one of:

- A **high-stakes decision** — expensive to reverse (deletes Live state, modifies shared files, creative lock-in like "what key is this song in").
- A **must-answer question** — you genuinely cannot proceed without input the user hasn't given.

Status updates are fine; status-updates-that-end-in-"what next" are the anti-pattern. Once you've received "keep going" (or equivalent) once, the burden of proof for stopping again is high — you need a *specific* new decision point, not "I finished a phase."

**Pedagogical carve-out.** A *collaborative musical proposal* at a creative fork the user hasn't directed — "E minor with the chorus landing on a release, or do you hear it brighter?" — IS a legitimate stop (it's a creative lock-in), and is distinct from the summarize-and-ask anti-pattern. The test: are you surfacing a real, redirectable choice the user would want to own, or just narrating progress? The former is the propose-and-react discipline (see `intent-collaboration-model.md`'s third register); the latter is the anti-pattern. **Precedence dominates this carve-out:** it covers only choices the user genuinely left open. If they directed the choice — or signalled they'll handle it themselves ("I'll take it from there", "just the skeleton") — *execute and hand back*; do not fork a spec they already gave, and do not stop to propose downstream details they explicitly deferred. Proposing into directed work is friction, not collaboration.

### Creative product prompts vs planning prompts

**Creative product prompt** — "make me / build me / write me X" where X is a thing-to-be-experienced (a song, an app, a document, a feature). The implicit deliverable is the *finished thing*, not "scaffolded with a follow-up list." Drive the workflow end-to-end (scaffold → compose → sound design → mix → verify) before declaring done. The phase boundaries inside the agent's skill chain (`/song-new` → `/song-pick-instruments` → `/ableton-push` → compose → re-push → mix) are implementation details, not user-facing checkpoints. **But "drive end-to-end" is not "decide everything silently":** when you reach an elementary musical choice the user hasn't directed (key, the central tension, what the chorus does), don't auto-accompany — *propose* it and read their reaction (the propose-and-react discipline). Driving through means not stopping to summarize; it does not mean making creative locks-ins on the user's behalf without surfacing them.

**Planning prompt** — "what would be involved in X?" / "how should we approach Y?". Don't barrel into implementation; produce a plan, not code. The signal is in verb tense and demand shape.

Misreading creative-as-planning produces an unfinished scaffold the user has to manually finish. Misreading planning-as-creative produces an unwanted implementation. When ambiguous, infer-confirm-proceed: state your read of which it is in one sentence, then proceed unless corrected.

### Sound design is composition

For audio products, device chains (saturation, drum bus, room reverb sends) ship in the snapshot — they're authorship, not a mix-time todo list. A finished song has the sound it's supposed to have *as part of being finished*, not pending in a "post-push mix pass." This shapes `/song-pick-instruments` (chains, not bare instruments) and `/song-new`'s definition of done for creative product prompts.

### Microtiming feel is authorship

Per-part `feel` (push/pull, swing, drag) is part of how a part is written — bake it into the pattern at generation time via the per-helper `feel` parameter, coordinated across instruments where the genre calls for it. Not a post-hoc humanize pass; not a song-level or section-level shared groove instance. Punk drums + lazy bluegrass guitar in the same section is a valid intent.
