# examples/ — the in-repo demo workspace

This is a Hallucinote **song workspace** (the `hallucinote.toml` marker makes it
one) carrying the demo song that anchors the end-to-end walkthrough:

- [`punk-fate/`](punk-fate/) — Beethoven's Fifth as 115 seconds of basement
  punk, authored end-to-end from the one-sentence prompt in its
  `annotations/01-the-brief.md`. The walkthrough built from that session is
  [`docs/tour.md`](../docs/tour.md).

`python examples/punk-fate/build.py` rebuilds the song's database from source
with no Live running — its shape tests run in this repo's default suite, so
the demo is CI-built documentation, not a snapshot that can rot.

An earlier demo song was retired after serving its real purpose — rebuilding
it from scratch surfaced six framework defects, all fixed in v1.8.0 (see
[`CHANGELOG.md`](../CHANGELOG.md)). Its successor here was re-authored from a
sparse prompt through the full `/song-brief` elicitation flow, so it
demonstrates the real workflow rather than a rehearsed one.

To make your own songs, don't use this directory — create your own workspace
(see the [README](../README.md#your-first-song)).
