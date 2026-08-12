# Known issues and limitations

What doesn't work yet, why we've accepted that for now, and the workaround
where one exists. The [README](../README.md#status) carries the one-line
versions; this page is the detail. Per-release changes are in
[`CHANGELOG.md`](../CHANGELOG.md).

## Removing a sidechain in Live needs a full rebuild

A snapshot that is *silent* about a device's sidechain source is treated as "no
opinion," so a sidechain authored in `build.py` survives every rebuild. The flip
side: if you delete a sidechain *in Live* and re-snapshot, an incremental
rebuild won't clear the old source. To drop it durably, rebuild from a fresh DB,
clear it in `build.py` with `set_device_sidechain(None)`, or write an explicit
null source into the snapshot.

## Human audio can't be read back through the bridge

MIDI and the mix are what Hallucinote builds; a recorded vocal take or a hand-ridden
fader-automation lane lives only in the `.als` — the bridge can't pull it into a
song's source. Audio recording is a boundary, not a feature, today.

## Measured mix review needs Max for Live (Live Suite, or the M4L add-on)

The authoring loop — compose, push, pull, play, and the *symbolic*
`/hallucinote:compose-review` — runs on Live 12 Standard and Suite (see the
Intro/Lite note below). Only the render → analysis → `/hallucinote:mix-review`
path needs Max for Live, which comes with Live Suite or as the separate M4L
add-on for Standard. Without it, review by ear with `/compose-review`. This
split is by design — see [`capability-truth.md`](capability-truth.md).

## Live Intro and Lite are untested

Standard and Suite are the editions Hallucinote is exercised on. Intro (16
tracks) and Lite (8) are Live 12 too, and nothing deliberately excludes them —
but nobody has run the loop there, and two things look likely to bite: the
track ceiling (a four-part song plus return busses and a submaster climbs
faster than you'd think) and the much thinner device palette that
`/hallucinote:song-pick-instruments` picks chains from. If you try it, the
report is genuinely useful.

## Sung vocals aren't synthesized yet

A vocal *melody* sketched as MIDI round-trips in and gets arranged around, and
the symbolic melody lens reads it back. Turning that line into a sung
performance is future work; today a synth carries it. (Writing the topline
itself is yours by design — [`capability-truth.md`](capability-truth.md) has
the reasoning, and the [FAQ](faq.md#what-about-the-melody) the workflow.)

## Mid-song tempo / time-signature changes aren't supported

Changes before bar 1 round-trip cleanly; a mid-song change surfaces a
refuse-and-teach at the call site (a real MCP gap, never silent data loss).

## A few device-parameter enums can't round-trip

Some Live enum parameters have no normalized form on the MCP wire; they're
skipped with a warning rather than set to the wrong value. Continuous
parameters round-trip cleanly.

## A few nested-rack corners are still one level deep

Racks nested inside racks are captured, replayed and pushed to any depth. Three
narrower things aren't there yet: pulling a *sidechain* setting back from a
nested device, pulling a rack that sits on another rack's chain, and the
snapshot-refresh *preview*, which itemizes one level and summarizes deeper
subtrees rather than listing them (a display simplification — the underlying
data round-trips in full).

## Linux is unsupported

Ableton Live ships no Linux build; Wine/CrossOver gets a best-effort install
candidate with warn-and-confirm. macOS and Windows are the supported platforms.
