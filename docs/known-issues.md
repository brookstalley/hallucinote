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

## Switching branches in the engine checkout breaks the push CLI's bridge

The push CLI spawns its own MCP server side from the plugin's environment, which imports `hallucinote_mcp` from an editable checkout and stamps it with the content fingerprint of that package's wire-bearing files (`_FINGERPRINT_PATHS`: the wire, schema, dispatcher, actions, handlers and Remote Script sources — see `docs/release-process.md`).
The Remote Script vendored into Live carries the fingerprint it was installed from.
Check out a branch whose copy of any of those files differs, even with no local edits, and every CLI probe refuses with a version mismatch until the Remote Script is reinstalled; branches that differ only outside those paths keep working.
The MCP tools inside a running session keep working, because that server process already has the old code in memory, which makes the failure look intermittent.
Do engine work in a git worktree and leave the checkout the Remote Script was installed from where it is, or reinstall the Remote Script (`/hallucinote:ableton-mcp-install`) and restart Live after the switch.

## A dead audio engine looks like a stalled perform, and leaves the tempo slowed

When Live's audio engine is off (an interface asleep, a device lost), the transport reports playing while the playhead stays at its start and every meter reads zero.
The performed-automation pass aborts cleanly ("transport stopped advancing").
In the session where this was observed the set was then found at the slowed record tempo, and a manual tempo change reverted the moment the transport started; the abort path's `finally` does restore `song.tempo`, so the write appears not to take while the engine is down — treat the slowed tempo as a symptom to check for, not a promise.
Restore the engine in Live, then set the tempo, seek to bar 1, confirm the playhead advances, and re-run the pass.
A ten-second play check before any perform or render after a break is cheaper than the abort.

## A recorded take can't be read back through the bridge — but a dragged-in clip can

An audio *clip* is built to round-trip: drop a WAV into a slot in Live and pull stages it
into the song's DB as a real row, with the file it plays and its warp, transpose, gain and
marker settings — the same staging lane a `clip-notes` pull uses, which you then fold into
`build.py` (the DB is regenerable; `build.py --reset` drops what you did not fold). That is
the sketching loop. It is unit-tested and not yet verified against a real set — the honest
rating is in `docs/capability-truth.md`, which wins over this paragraph.

What still lives only in the `.als` is anything Live *recorded* or a human *performed*: a
vocal take captured into a slot, and a hand-ridden fader-automation lane. Recording and
automation ingest are boundaries, not features, today.

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

## Mid-song tempo / time-signature changes don't reach Live

You can author them — the DB records the song's true tempo and meter maps — but
Live 12's MCP exposes tempo and signature only as single global values, so push
sets the bar-1 row and reports loudly that the rest were skipped (a real MCP
gap, never silent data loss).

The two halves have different workarounds, and only one of them is cheap. A
**signature** marker placed by hand in Live is cosmetic for playback — beats are
absolute, so the score and the set still agree on them, and the marker only
fixes bar numbering and the metronome. A hand-drawn **tempo** change is not
cosmetic: it moves the wall clock, which is the whole reason to author one.

Draw it, though, and the rest of the pipeline is already correct — because the
pipeline reads the tempo map you declared and *assumes* you drew it. The
analyzer is handed the declared map (`_collect_tempo_map` -> `BeatSampleMap`,
which integrates across its segments), and `_estimate_span_seconds` says the
same thing out loud: a multi-segment map assumes the operator drew the matching
automation in Live by hand. So the hand-drawn tempo curve is not a cosmetic
patch over the gap — it is the thing that makes the assumption true. Skip it and
every downstream wall-clock number is computed from a tempo the set is not
playing.

Two bar rulers exist — push resolves bar positions through the meter map, while
`hallucinote.arrangement` accumulates whole bars against one uniform
`beats_per_bar` and never reads it — so a placement or cue point sitting *after*
a meter change may be in the wrong place. Push alerts only on rows recorded as
having come from that uniform accumulation, so a deliberately-authored
multi-meter song raises nothing; a row written before the provenance column
existed raises a separate, provisional alert that names re-running
`build.py` as the way to settle it. For a song with a within-song meter change,
author those placements directly rather than relying on that class's bar
arithmetic past the first change.

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

## Windows has less mileage than macOS

Both are supported and the Windows-specific paths — User Library locations, the
Live process lookup, the Remote Script install — are implemented and
unit-tested. macOS is simply where Hallucinote is developed day to day, and CI
runs on Linux with no Ableton at all, so Windows has far fewer real sessions
behind it. Windows-shaped breakage is a bug worth reporting, with your
`preflight` output attached.

## Linux is unsupported

Ableton Live ships no Linux build; Wine/CrossOver gets a best-effort install
candidate with warn-and-confirm. macOS and Windows are the supported platforms.
