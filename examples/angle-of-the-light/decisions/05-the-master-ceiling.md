---
date: 2026-08-07
kind: decision
scope: song
tags: [mix, mastering, gain-staging, production, signal-chain]
---

## Context

The first render of the finished arrangement clipped hard: **+5.02 dBTP true peak
with 40 overshoots**, integrated loudness −10.1 LUFS. Two independent
measurements agreed (the MixReport analyzer and an `ffmpeg ebur128` pass), so it
was the mix, not a measurement artifact.

The diagnosis matters more than the number, because it rules out the obvious
suspects. **Every individual stem was already under 0 dBTP** — loudest Kit Rock
−0.79, then Bass −1.98, Brass Stab −2.13, Pad −2.98 — and the master fader sat at
unity. Nothing clipped on its own. Twelve stems each mixed to a sensible level
simply *summed* past full scale, and there was nothing on the master to catch it.

The overshoots confirmed it by location: they clustered where the arrangement is
densest — verse 22, chorus-reprise 13, riser 3, bridge 1, chorus 1. The intro,
which is one layered chord, never overshot at all.

## Decision

A **Limiter on the master**, `Input Gain −4.0 dB`, `Ceiling −1.0 dB`.

The two settings do different jobs and the split is the decision:

- **The −4 dB input trim does the real work.** It lowers the whole sum before
  anything is limited, so the peaks arrive close to the ceiling rather than 6 dB
  above it.
- **The ceiling only catches transients.** With the trim in place the limiter has
  roughly 2 dB of work left, on brief peaks, rather than 6 dB of continuous
  gain-reduction.

Measured result:

| | Before | After |
|---|---|---|
| True peak | +5.02 dBTP | **−0.74 dBTP** |
| Overshoots | 40 | **0** |
| Integrated | −10.1 LUFS | −14.2 LUFS |
| **Loudness range** | 7.8 LU | **7.7 LU** |

## Why

**The LRA is the number that justifies the split.** A limiter asked to remove
6 dB would have flattened the piece — and this song's whole argument is dynamic:
a six-bar layered intro, a rigid mechanical bridge, a chorus that has to *lift*,
and a collapse. Loudness range moved 7.8 → 7.7 LU, which is nothing. The
transients survived; only the overshoots went.

Trimming alone was the alternative and was rejected. It would have fixed the
clipping, but it leaves nothing guarding the ceiling — any later change that adds
density (a re-voiced chorus, a louder brass answer) puts the overshoots straight
back, silently, and the next render would have to rediscover them. The limiter
makes the ceiling a property of the song rather than of one particular arrangement.

Rebalancing the twelve stems downward was also rejected: the per-stem levels ARE
the mix, they were authored deliberately, and scaling them all by the same amount
is a master trim wearing a disguise — with twelve places to get it wrong instead
of one.

−14.2 LUFS is where the trim happened to land, not a target that was aimed at. It
is close to the usual streaming figure, which is convenient, but the piece is 50
seconds long and is not being delivered to a platform; the number that was
actually chosen is the ceiling.

## Narrative to sound

The brief asked for production that is "slick for the most part" while the
mechanical bridge stays "raw; small room, fewer effects. Like a punk rocker left
alone with a 4 track."

A master ceiling serves both halves rather than fighting the second one. Slick is
not loud — it is *controlled*, and an unclipped sum is the baseline for that. And
because the limiter is only catching peaks rather than compressing continuously,
the bridge's rawness is untouched: it is a sparse, quiet section that never
approaches the ceiling, so the limiter is functionally absent there. The device
that makes the dense sections behave is silent exactly where the song wants to
sound unpoliced.

## Durability

The chain lives in `captured_session.json` under `song.master.devices`, not in
`build.py` — per the repo's split, a device chain is materialized state, not a
generative rule. Verified by rebuilding: `build.py` replays the snapshot and the
Limiter comes back with both parameters intact, so a rebuild cannot silently drop
the ceiling.

Decided by: agent, in response to a measured defect rather than a taste call. The
clipping was not a matter of preference; the −4/−1 split, and the reasoning that
the trim rather than the ceiling should do the work, is the part that was chosen.
