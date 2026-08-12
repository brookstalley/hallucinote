# Release plan — v1.8.6

**vPREV:** v1.8.5 · **vNEW:** v1.8.6 (patch) · **Cut:** 2026-08-12

## What this release is

The **demo release**. The README opens with a two-minute video of a prompt
becoming a finished arrangement playing in Live, so a visitor can hear what the
tool does before installing anything. Behind it: the prose norm's absolute
reading restored by owner ruling and swept through the positioning corpus, the
release process taught to publish a GitHub Release, and the owner's own README
copy edits merged from `main`.

**Patch, not minor:** no product capability changed. Every file in
`v1.8.5..develop` is `.md` apart from `.prawduct/project-state.yaml` (a
governance record) and the four version surfaces at the cut itself. No
executable code path changes.

| Cluster | Substance |
| --- | --- |
| `docs-positive-framing` | The prose norm *write what a thing IS* was narrowed **twice in one day by the agent**, each time right after review found shipping prose violating it, and both narrowings were recorded as pending owner veto rather than ratified. The owner ruled: narrowing 1 **rejected** (the absolute reading stands — a contrast-definition is banned whatever it describes), narrowing 2 **ratified** (prior art may be named as lineage, never ranked against). The owner also set the norm's **scope** for the first time — positioning prose only — and later ratified the two remaining carve-outs (a prescriptive rule may prohibit; verbatim quotation is untouchable), leaving four carve-outs and nothing pending. ~45 contrast constructions rewritten positively across the six in-scope files. The Critic then found the row's discriminating test **self-invalidating** — "would removing the negated half leave the subject undefined?" cleared "Ableton is the speaker, not the score", the exact sentence the row bans — replaced with the foil test across all four carriers. Also: semantic line breaks (one sentence per line) across the six files, applied mechanically with a transform that refused to write any file whose word stream changed. |
| `docs-launch-readiness` | **#329 shipped.** The 2:13 demo video is embedded in the README as an inline player. Committing the `.mp4` would not have produced one — GitHub strips `<video>` pointing at repository files and blocks `raw.githubusercontent.com` from serving video — so it is hosted on the user-attachments CDN at zero repo weight, leaving the 12 MB `docs/assets` budget untouched. Acceptance verified rather than asserted: envelope correlation +0.993 against the stitched renders with matching RMS, the ±1024-sample per-state offset measured at 0.80–0.95, caveat legible at three timestamps. The owner's README copy edits (`f10c92d`, committed directly to `main`) merged back, taken as authored with only the line-break mechanics reconciled. |
| `release-process-docs` | The repo carried six annotated tags and **zero GitHub Releases** — the ten-step procedure ended at *Verify*, so anyone landing on the repo saw no release at all. Step 11 now covers publishing: draft first (a published Release notifies watchers and is the most outward-facing artifact the process produces), `--verify-tag` so a typo fails rather than inventing a tag, the `untagged-<hash>` draft URL that otherwise reads as a bug, and the fact that release notes are reader-facing positioning prose governed by the prose norm. v1.8.5 was published retroactively. |

## Release classification

| scope | disposition | blocker |
| --- | --- | --- |
| docs-positive-framing | ships |  |
| docs-launch-readiness | ships |  |
| release-process-docs | ships |  |

## Re-vendor impact

**Re-vendor: not required.**

    git diff v1.8.5..develop --name-only | grep -E \
      'hallucinote_mcp/src/hallucinote_mcp/(wire|schema|dispatcher)\.py|/(actions|handlers|remote_script)/'

Returns nothing (verified at the cut). No file under `hallucinote_mcp/` is
touched at all this release. The handshake fingerprint is unchanged, so
marketplace consumers get the new docs and the demo through the ordinary plugin
auto-update and need do nothing in Ableton Live: no `/ableton-mcp-install`, no
Live restart.

## Step 3 — nothing archives at this cut

`plan-backfill --apply` reports **0 plans archived**, leaving four in place
(`ARR-PROJ`, `ENV-8K2R`, `ENV-9P4T`, `SYN-8Q3F`) — none of their scopes is
tagged by this release. The build plan this release's own work ran under
(`.prawduct/artifacts/build-plan.md`, all three chunks ticked) declares no
`scope:` field, so `plan-backfill` cannot claim it by scope; it is left live
deliberately rather than hand-archived, and `active_build_plan` stays **empty**
as it was before the cut.

## Two owner decisions carried into this release

Recorded here as well as in the change-log so a future docs review reads them as
decided rather than re-opening them as contradictions:

1. **The README and `docs/tour.md` quote the punk-fate prompt differently, and
   both stay.** The README says "rhythm guitar, and vocals emulated by a lead
   guitar"; the tour quotes the session log verbatim as "lead guitar, and vocals
   on a staccato synth". The README's version describes what the song became
   (chapter 15 turns track 4 into a lead guitar) rather than what was typed.
   Raised as exactly the class of contradiction the v1.8.5 pass closed; the
   owner ruled to keep both.
2. **"What you end up with is an ordinary Ableton set you finish yourself" is
   deliberately gone from the README.** The FAQ still answers the question in
   full.

## Still open after this cut

- **The repo is private.** Every install path in the README, the CI badge and
  the SECURITY advisory link resolve only once it is public. This release does
  not change that.
- **#463** — the demo-video device-chain pickup shot needs a capture session
  with Live's detail view focused; a re-record, not a re-encode.
- **#462** — a mechanical tripwire for the prose norm, `stage: design`: the open
  question is how to catch the banned shapes without an exemption list long
  enough to hollow the norm out.
- **#458** — no measured per-song cost figure is published anywhere, because
  none is measured. Do not let anyone estimate a number into that gap.
