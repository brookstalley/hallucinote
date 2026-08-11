# Hallucinote docs

Every doc in this directory, grouped by who it's for. Start at the top; the
further down you go, the more internal it gets. (A parity test keeps this index
complete — a doc added without a row here fails the suite.)

## Making music

| Doc | What it covers |
|---|---|
| [`quickstart.md`](quickstart.md) | Your first song, end to end, in ~10 minutes |
| [`tour.md`](tour.md) | Watch a real song get made — one session, ten beats, with the evidence |
| [`skills.md`](skills.md) | The full menu of things you can ask for |
| [`song-workflow.md`](song-workflow.md) | The song-making lifecycle — stages, checkpoints, and the research behind the tools |
| [`song-authoring-conventions.md`](song-authoring-conventions.md) | How a song's `build.py` works — read this to inspect or hand-edit a song |
| [`collaboration.md`](collaboration.md) | Sharing songs between machines and collaborators |
| [`known-issues.md`](known-issues.md) | What's not supported yet, with workarounds |
| [`faq.md`](faq.md) | Short answers to common questions |
| [`running-the-engine.md`](running-the-engine.md) | Running the `hallucinote` CLI (it lives inside the plugin's environment) |
| [`alternate-tunings.md`](alternate-tunings.md) | Composing microtonal / non-12-TET songs (niche; 12-TET songs never touch this) |
| [`VISION.md`](VISION.md) | Why Hallucinote works the way it does |

## Reference

| Doc | What it covers |
|---|---|
| [`snapshot-schema.md`](snapshot-schema.md) | The `captured_session.json` mix-snapshot format |
| [`browser-cache-schema.md`](browser-cache-schema.md) | The machine-local Live browser inventory cache |
| [`capability-truth.md`](capability-truth.md) | The honest capability table the agent answers "what can you do?" from |
| [`song-new-checklist.md`](song-new-checklist.md) | The elicitation dimension catalogue `/song-brief` draws on |
| [`terminology.md`](terminology.md) | Precise meanings for overloaded terms (session, arrangement, clip) across layers |

## Maintainers & design notes

| Doc | What it covers |
|---|---|
| [`release-process.md`](release-process.md) | How a Hallucinote version is cut |
| [`engine-pin.md`](engine-pin.md) | Why the engine and bridge share one environment |
| [`dev-vs-use-coexistence.md`](dev-vs-use-coexistence.md) | Developing Hallucinote and making music on the same machine |
| [`polyrhythms.md`](polyrhythms.md) | Design/status of the cross-rhythm detection in mix analysis |
| [`dubler.md`](dubler.md) | Design note for not-yet-shipped Dubler/MPE pitch round-trip |
| [`research/`](research/) | Raw research corpus (probe drivers, producer/mastering practice) behind the audio models |
| [`archive/`](archive/README.md) | Historical docs, preserved for audit |
