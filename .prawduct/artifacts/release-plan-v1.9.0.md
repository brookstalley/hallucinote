# Release plan — v1.9.0

**vPREV:** v1.8.6 · **vNEW:** v1.9.0 (minor) · **Cut:** 2026-09-11

## What this release is

The **sampling release**. A sample becomes song material: audio clips place,
conform and round-trip through Live; a sampler gets its sample; and a sample is
something the music can be *derived* from — spectral fields carved and vocoded
against the score, a pitch follower turning an F0 contour into tagged notes and
per-note bends, feature events with musical gates. Three new packages
(`assets`, `features`, `spectral`) carry it.

Around that: the render report learns to ask whether the audio is damaged, a
render under a soloed track is refused outright rather than silently mixing the
wrong thing, elicitation becomes a conversation that reads the turn and offers a
hearing, two read-side lenses (psychoacoustic sharpness, drum-hit transient
shape) land, and two rounds of release-blocker sweeps clear every open bug
report — including two defects that were in the release mechanism itself.

**Minor, not patch.** `v1.8.6..develop` is 304 non-merge commits, 481 files,
+78,709/−9,277, three new packages and new product capability across `audio/`,
`sync/push/`, `assets/`, `features/`, `spectral/` and the MCP handlers. The
`RELBLK-V19` scope name records that v1.9 was the intent before the cut.

| Cluster | Substance |
| --- | --- |
| `SMP-6V2K` + `SMP-6V2K-W2` | Sampling, in two waves. Wave 1: audio clips place, conform and round-trip; push acts on the probe's verdicts, so a re-pointed sample is recreated with its ride and an envelope-hosting audio placement duplicates; a probe session settled the reverse contract and recreate semantics against real Live; the audio path ran against Live and the one silent replace it found now speaks. Wave 2: the asset store (ingest, normalize, manifest), feature streams (F0, formants, energy, descriptors, segments, placed beat map), spectral fields symbolic-from-score and measured-from-capture, one-field/one-mask/one-polarity carve and vocode with an honest bass resolution, transforms over a content-addressed derived cache, speech-band intelligibility measured over the bed per spoken turn, the sampler assignment path, pull linking the audio clips it ingests, the pitch follower, feature events with musical gates, a stretch/pitch A/B harness, reverse materializing through the derived cache, and the sample lens. |
| `render-integrity` | The report learns to ask whether the audio is damaged rather than only whether it exists. |
| `RENDERGUARD-0910` | A render under a soloed track or return is **refused** — the capture would otherwise be a confident measurement of the wrong mix — and the manifest now carries per-surface `mixer_state` (solo, mute, volume, `track_id` joinable to `tracks[]`), which is what makes an old report auditable after the Live session has moved on. A master that is not the mix cannot be reported as a changed mix. |
| `RELBLK-V19` | Seven defects that would have shipped, two of them in the release mechanism itself: vendored-content drift the handshake cannot see, a version-pin recovery that pinned to a commit rather than to content, a wrong-kind replace that refused only after deleting the clip, capture excluding an untouched default-scaffold track, the compat check answering for the samples a song actually plays, and the playable region reaching the arrangement copy. |
| `RELBLK-0910` · `BUGSWEEP-0910` · `OPENBUGS-0910` · `CHAIN-RESTORE-STR` | Every open bug report, worked: a chain restore that lands on the right device and a failure that says so; a chain rebuild that could not carry a single string parameter while the fake said it could; two silent lenses — a partial recall that had stopped counting as a recall, and a capture that had stopped reading the wrong beat. |
| `perform-start-position` | Live plays from a start position `current_song_time` never moved — the root cause of the silent perform. |
| `aud-lenses` | Two read-side lenses: psychoacoustic sharpness and drum-hit transient shape. |
| `collab-turn` | Elicitation becomes a conversation: read the turn kind, build to the hearable unit, offer a hearing, and record who owns each open question. |
| `CAPSPAN-491` | A capture that does not span what it declares now says so, instead of being analysed as if it did. |
| `tmp-7b3x` | Meter is a projection concern: the DB records what the song **is**, and the "can't reach Live" refusal moves to the push layer where the projection happens. |
| `MYPY-COMPARE-0911` · `docs-hygiene` · `JANITOR-2026-09` · `governance-file-sizes` · `advisory-clearing` · `effort-s-burndown` · `RELFOLD-0910` · `RELAUDIT-0911` | Hygiene and governance: CI red on a type that turned out to be the honest answer; the doc deep-link parity check covering every link rather than one file; the first Norm Health sweep; a ceiling on the governance files; three post-sync advisories cleared; the `effort:S` backlog burned down; and two passes of release audit that folded in what the release's own work left open and read two candidates back out. |

## Release classification

Every release-pending scope ships. Nothing is held back, and nothing is
partially promoted — the release is a wholesale promotion of `develop`.

| scope | disposition | blocker |
| --- | --- | --- |
| RELAUDIT-0911 | ships |  |
| MYPY-COMPARE-0911 | ships |  |
| RELFOLD-0910 | ships |  |
| OPENBUGS-0910 | ships |  |
| RENDERGUARD-0910 | ships | limits named below (#552, #482) |
| RELBLK-0910 | ships |  |
| CHAIN-RESTORE-STR | ships |  |
| BUGSWEEP-0910 | ships |  |
| RELBLK-V19 | ships |  |
| SMP-6V2K-W2 | ships | plan Chunk 17 operator-gated; see below |
| SMP-6V2K | ships |  |
| docs-hygiene | ships |  |
| tmp-7b3x | ships |  |
| CAPSPAN-491 | ships |  |
| JANITOR-2026-09 | ships |  |
| render-integrity | ships |  |
| perform-start-position | ships |  |
| governance-file-sizes | ships |  |
| aud-lenses | ships |  |
| collab-turn | ships |  |
| advisory-clearing | ships |  |
| effort-s-burndown | ships |  |

Seven of these scopes have no build-plan file and `check-releasability` warns on
each. That is answered, per scope, in
[`planless-scopes-disposition.md`](planless-scopes-disposition.md) — each is a
legitimate no-plan, not a missing one.

## Re-vendor impact

**Re-vendor: REQUIRED.**

    git diff v1.8.6..develop --name-only | grep -E \
      'hallucinote_mcp/src/hallucinote_mcp/(wire|schema|dispatcher)\.py|/(actions|handlers|remote_script)/'

Returns **19 files** at the cut — including `wire.py`, `dispatcher.py`,
`remote_script/dispatch.py`, seven files under `actions/` and eight under
`handlers/`. The handshake fingerprint therefore changes.

What that means for a marketplace consumer: the plugin half auto-updates when
`main` is pushed, so their MCP server computes a **new** `server_version` while
the Remote Script still sitting in their Live User Library computes the old one.
**Every bridge call fails with a version mismatch** until they re-run
`/ableton-mcp-install` and **fully quit and reopen Ableton Live** (`/mcp` alone
is not enough — Live caches Control Surface modules at launch). This is the
consumer-facing fact of the release and it leads the CHANGELOG upgrade note.

The advisory question also returns hits (`client.py`, `install_ops.py`,
`install_paths.py`, `provenance.py`, `analyzer/setup.py`, four resource guides,
`server_side/`), which is consistent: the vendored set is a superset of the
handshake set, so a hard flip always implies an advisory one.

## Step 3 — nine plans archived, two left live

`plan-backfill --apply` archived nine finished plans, each fully ticked and
verified against its own `## Status` before the move (step 10's warning —
`plan-backfill` archives by *scope*, not by completeness):
`build-plan-aud-sharpness-transients`, `build-plan-render-integrity`,
`CAPSPAN-491`, `JANITOR-2026-09`, `RELBLK-V19`, `RELFOLD-0910`,
`RENDERGUARD-0910`, `SMP-6V2K`, `TMP-7B3X`.

Two stay live, both deliberately:

- **`build-plan-backlog-wave-1.md`** — no release records it; work in flight.
- **`plans/SMP-6V2K-W2/build-plan.md`** — the tool **refused** it, correctly: 1
  of 17 Status items is unticked (Chunk 17, the operator-gated Live session —
  sampler live, reverse live, the #509 and Sampler probes). The scope shipped;
  the plan did not finish with it, so archiving it would declare an unrun Live
  session done.

`active_build_plan` was already empty before the cut and stays empty — nothing
that archived was named by it.

## Known limits this release ships, named rather than silent

The bar the first release audit set for the solo guard was *ship the limitation
named, or fix it — shipping it unmentioned is the bad option.* Three qualify:

1. **#552 — the master strip is never walked.** `_mixer_state._read()` covers
   `song.tracks` and `song.return_tracks`, so a soloed chain inside a master rack
   is invisible to the refusal and `manifest.mixer_state` has no master row. Not
   the one-line fix it looks like: Live's master carries no `solo` attribute, so
   a naive master row reads `solo: None` and `_refuse_under_solo` — which
   deliberately refuses on an unreadable flag — would refuse **every** render.
   M-effort, `stage:design`, correctly out of this release. Already named in the
   `RELFOLD-0910` change-log entry, `architecture.md` § *What is deliberately not
   modeled*, `boundary-patterns.md`, and `_soloed_chains`' own docstring.
2. **#482 — a blocking gate over a sum with known limits.** `RENDERGUARD` made
   `sum_reconciliation` a *blocking* finding, while #482's R1/R2 (a return with a
   non-unity fader is summed at full pre-fader level and inflates the residual)
   is deliberately held back so each change proves the other. The consequence is
   real and stated rather than discovered: the release ships a blocking gate that
   can read high for a benign reason.
3. **The journal version trap.** `JOURNAL_VERSION` goes 1 → 2, so a journal left
   by a pre-release crash meets the operator as two refusals — `push execute`
   classifies the unreadable phase as mid-flight and points at `--resume auto`,
   which then refuses on the version. Neither destroys anything and both name the
   file. The exit is: read the journal, rebuild the chain from the DB
   (`chain-rebuild` with no `--resume`), delete the journal. Rollback has the
   mirror trap and the same exit.

## Still open after this cut

- **The Live-side claims rest on two sittings and nothing else.** Per the owner
  ruling of 2026-09-10 recorded at the head of
  [`operator-verification.md`](../operator-verification.md),
  `operator_verification_required` is deliberately **absent** from
  `project-state.yaml` for this release: the gate exits 0 because the requirement
  is off, not because anything was verified. 35 boxes across 7 sections sit
  unticked. Two matter most and **neither was sat for this cut** — both need an
  attended Live session with a single writer:
  - the **#291 witness**, which failed twice, whose two defects (#532, #533) are
    now fixed and which has **never been re-run**: nothing has proven
    chain-rebuild's restore against a real chain;
  - **RENDERGUARD box 7**, which prices the stem-sum false positive — the
    #482 exposure above, unmeasured.

  This is a per-release decision, not standing policy. Arming the gate was
  explicitly left open for a later release.
- **`change-log.md` is 134 KB against a 55 KB ceiling.** The roll moved every
  entry it legitimately could — the six v1.8.5/v1.8.6 entries — but this
  release's own 25 entries are ~123 KB on their own, and archiving an entry whose
  release notes have not been published yet would strip the release's record out
  of the only file any gate reads. The next cut can roll the v1.9.0 block once
  these notes exist. Stated here rather than left as a silent advisory.
- **#489's R5 upstream report is still unsent.** Egress crosses an owner
  boundary; not an agent action.
- **`incoming-bugs/2026-09-10-windowed-render-master-capture-13db-low.md`** is
  discharged (all three suggested fixes shipped) and should be archived out of
  the drop-box, with the `compare_to` take-retention note filed separately if it
  is wanted.
