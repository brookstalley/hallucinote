# Known issues and limitations

Limitations we know about and have consciously accepted for now — each with its
workaround where one exists. The [README](../README.md#status) carries the
one-line versions; this page is the detail. Per-release changes are in
[`CHANGELOG.md`](../CHANGELOG.md).

## Removing a sidechain in Live needs a full rebuild

A snapshot that is *silent* about a device's sidechain source is treated as "no
opinion," so a sidechain authored in `build.py` survives every rebuild. The flip
side: if you delete a sidechain *in Live* and re-snapshot, an incremental
rebuild won't clear the old source. To drop it durably, rebuild from a fresh DB,
clear it in `build.py` with `set_device_sidechain(None)`, or write an explicit
null source into the snapshot.

## Human audio can't be read back through the bridge

Claude authors MIDI and the mix; a recorded vocal take or a hand-ridden
fader-automation lane lives only in the `.als` — the bridge can't pull it into a
song's source. Audio recording is a boundary, not a feature, today.

## Measured mix review needs Max for Live (Suite)

The authoring loop — compose, push, pull, play, and the *symbolic*
`/hallucinote:compose-review` — runs on any Live 12 edition. Only the render →
analysis → `/hallucinote:mix-review` path needs Max for Live, so on Standard you
review by ear with `/compose-review`. This split is by design — see
[`capability-truth.md`](capability-truth.md).

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
