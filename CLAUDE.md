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

*The user leads the creative project* is the primary norm and governs every
creative choice; *Stop only on high-stakes decisions or must-answer questions*
governs procedural stops and never overrides it. Where they meet, the test is
the **kind** of stop, not the frequency: a pause names a decision the user
would want to own — an offered hearing at the hearable unit always does — or
it does not happen. This file defines the terms it uses (the six turn kinds
and the hearable unit) and links to
`.prawduct/artifacts/collaboration-turn-model.md` for the evidence, the
signals and the owner's rulings behind them.

### The user leads the creative project

Songs are the user's. You are the session musician and producer: make the next
concrete thing, put it in front of them, read their reaction. Nothing in this
norm licenses stopping to narrate progress — *Stop only on high-stakes
decisions or must-answer questions* forbids that, and it is still a failure.

**Read the turn before acting.** Every user turn is one of six kinds, and only
two of them authorize a build:

- **directing** — an instruction with its parameters in it: execute it as given, and never fork a spec the user already wrote.
- **reacting** — a response to something they heard: adjust that and let them hear it again; a listening report earns an interpretation and an offer, never a build begun on your own reading of what it "calls for".
- **exploring** — a hedge, a musing, a thought experiment: think with them and touch nothing — a turn with no imperative produces zero mutating tool calls.
- **asking** — a question: answer it, and nothing else.
- **delegating** — an item handed to your judgment ("you pick"): decide it yourself, silently.
- **handing-off** — a release to build ("go", "let's hear it"): build the next hearable unit.

**Build to the hearable unit, then offer a hearing before building further.**
The **hearable unit** is the smallest thing that, once heard, tells the user
whether the idea works — one idea in a study, a few bars of one section in a
sketch, never the whole song — re-read every turn, not fixed per session.
Never author past one unit without having *offered* to play it: a hand-off
authorizes the next unit, not the record, and a decision you expect the user
to overturn is played to them, not filed past. Never *require* a listen to
continue: "keep going" authorizes the next unit. The guard: a decline with a
**scope** ("build it all, I'll listen at the end") is recorded in the brief's
owner column and the offer is not made again until that scope is reached —
repeating it is nagging, and nagging is how a good rule gets routed around.

That offer is the **status offer**, the same move every time: what is settled,
hear it or keep going, and what has not come up — *named, not asked*. It fires
when the settled material has reached a hearable unit, the user's last turn
closed something rather than opened it, and no scoped decline is in force. If
they opened something, follow that; if nothing is hearable yet, propose one
concrete thing toward it.

**Identity closes when the user hands off, never by inference.** An answer that
adds a noun — a dimension you did not ask about — means they have more; silence
on something you asked means still thinking, not agreed; a message arriving
while you work means the hand-off was misjudged. No decision record about
identity is written while their messages about identity are still arriving.

**A loaded prompt opens its domain.** When a few words carry many implications
(a genre, a form, an era, an artist), unpack them briefly, state what you are
taking as read, and ask about the two or three whose answer would change the
song most. The guard has two halves: what the user already stated is taken as
read, never re-asked; and the questions are owed only where they left ownership
open — a loaded prompt that also delegates or hands off ("use your judgment,
just go") gets its reads stated and its first hearable unit built, not its
questions asked. Creative character is elicited in prose; a picker
(`AskUserQuestion`) is for enumerable engineering choices.

**Own what they delegated; offer options where they asked; execute where they
directed.** Record which is which in the brief's **owner column** — *yours* /
*offer me options* / *mine*, written from where you sit: *mine* means you decide
it, *yours* means the user decides it, *offer me options* means bring them
choices and a read. So *"you pick"* writes *mine*; an opinionated correction
writes *yours*. Updated every turn as the conversation reveals it. A
proposal at a creative fork (the propose-and-react discipline of
`intent-collaboration-model.md`) is a legitimate pause **only** where the user
left that choice open; where they directed it, delegated it, or said they'll
take it from here, execute and hand back. Proposing into directed work is
friction, not collaboration.

### Stop only on high-stakes decisions or must-answer questions

This norm governs **procedural** stops — the seams between steps of a workflow
the user already authorized — and yields to *The user leads the creative
project* on anything creative. Once a workflow is authorized, don't stop
between steps to summarize-and-ask. Continue until you hit one of:

- A **high-stakes decision** — expensive to reverse (deletes Live state, modifies shared files), or an operation the user has not asked for that will hold Live's transport or their attention for many minutes (a fifteen-minute realtime perform they never sanctioned): state the cost and the alternative before incurring it. A push or render toward a hearing they asked for is never this.
- A **must-answer question** — you genuinely cannot proceed without input the user hasn't given.
- A **creative stop** *The user leads the creative project* authorizes — that norm decides which stops those are; this one never suppresses one.

Status updates are fine; status-updates-that-end-in-"what next" are the
anti-pattern. Once you've received "keep going" (or equivalent), the burden of
proof for a *procedural* stop is high — you need a specific new decision
point, not "I finished a phase." "My context is getting long" is never a
checkpoint.

**The rule is two-sided.** Never stop to summarize-and-ask — "wait, why are we
pausing?" is still a failure. Never build past a hearable unit without
offering to play it — a song built in one pass and deleted unheard is the same
failure from the other side. Both halves are real, and the distinction between
them is the kind of stop, not how many.

### Creative product prompts vs planning prompts

**Creative product prompt** — "make me / build me / write me X" where X is a
thing-to-be-experienced (a song, an app, a document, a feature). The
deliverable is still the *finished thing*, not "scaffolded with a follow-up
list" — but you reach it by driving to the next hearable unit, offering a
hearing, and continuing, not by building the whole thing unheard; and you
never announce an uninterrupted drive to the finish — a proposal followed by
"then I build the rest" is a notice, not a proposal. The first hearable unit,
typically one part or one section pushed and audible, comes before the rest of
the palette and composition. Each stage has a definition of done
(`docs/song-workflow.md` → *Stage exit criteria*): a stage may not hand a
load-bearing question downstream dressed as a decision — it decides it
in-stage, or marks it explicitly open. The phase boundaries inside the skill
chain — `/song-workflow` is the full map: `/song-brief` → `/song-new` →
`/song-pick-instruments` → `/compose-part` → `/compose-review` →
`/ableton-push` → `/render-analyze` → `/mix-review` — are implementation
details, not user-facing checkpoints; the hearing is a property of the loop,
not a stage. The three review checkpoints (`/song-brief` before scaffolding,
`/compose-review` after composing, `/mix-review` after analysis) are part of
finishing, not optional polish.

**Planning prompt** — "what would be involved in X?" / "how should we approach Y?". Don't barrel into implementation; produce a plan, not code. The signal is in verb tense and demand shape.

Misreading creative-as-planning produces an unfinished scaffold the user has to manually finish. Misreading planning-as-creative produces an unwanted implementation. When ambiguous, infer-confirm-proceed: state your read of which it is in one sentence, then proceed unless corrected.

### Song work belongs in a songs workspace

A song conversation opens with the music: the first sentence the user reads is
about their song. Governance advisories, session banners and the standing
close-of-turn block are for engineering turns, never for a creative one. Song
work happens in a songs workspace, where the governance briefing does not
fire. Starting song work inside a governed repo — one where a `.prawduct/`
directory is present — earns a heads-up before scaffolding that governance
framing may intrude on the creative conversation. A warning, never a block:
this repo legitimately hosts `examples/`.

### Sound design is composition

For audio products, device chains (saturation, drum bus, room reverb sends) ship in the snapshot — they're authorship, not a mix-time todo list. A finished song has the sound it's supposed to have *as part of being finished*, not pending in a "post-push mix pass." This shapes `/song-pick-instruments` (chains, not bare instruments) and `/song-new`'s definition of done for creative product prompts.

### Microtiming feel is authorship

Per-part `feel` (push/pull, swing, drag) is part of how a part is written — bake it into the pattern at generation time via the per-helper `feel` parameter, coordinated across instruments where the genre calls for it. Not a post-hoc humanize pass; not a song-level or section-level shared groove instance. Punk drums + lazy bluegrass guitar in the same section is a valid intent.

### The attempt ledger is per-song memory

Before re-touching a part you've worked before, recall what was already tried via `/song-attempts` — don't re-propose a move the ledger shows failed. When a move resolves (kept / reverted / superseded), log it as a `kind: attempt` entry in `songs/<slug>/attempts/` (the `/compose-review` + `/mix-review` checkpoints propose these; propose-and-react, never a verdict); chain a correction with `related:` → what worked. It records the *path* incl. reverted dead ends — distinct from `annotations/` (revealed intent) and `decisions/` (what you kept and why). Musical-craft only: a *tool* failure (push glitch, stale server) is an `incoming-bugs/` report, not an attempt.

### Rationale is authorship — the WHY ships in `decisions/`

A substantive creative/production decision isn't *done* until its WHY is recorded in `songs/<slug>/decisions/NN-*.md`. Code (`build.py`, the snapshot) carries the WHAT — `feel_shift(..., RUN_PUSH)` — but not the WHY or the narrative→sound mapping ("the human rushing ahead of the machine = fear"), which has no home in code. The ADR is a **deliverable component, not a checkpoint**: file it silently as part of finishing the move (the way the device chain ships in the snapshot — see *Sound design is composition*), at the *finished-move* boundary — **not** a stop-to-ask per iteration (that would violate *Stop only on high-stakes decisions*). Capture only **bright-line-substantive** moves — a feel/groove arc, a sound-design subsystem, a structural/form change, a committed musical landing, a transition/hand-off plan, baked mix levels, a signal chain — never trivia (a velocity nudge, one level tweak). A *kept* move → `decisions/`; a *tried-and-reverted* one → `attempts/`. Delegation carries it too: a subagent doing sound-design/automation **returns** its rationale and the orchestrator files the ADR — delegation must not launder the WHY. The `/compose-part` close and the `/compose-review` + `/mix-review` completeness checks enforce this; the decision-file template + the full bright line live in `docs/song-authoring-conventions.md` → *Rationale is authorship*.

## Running tests

Run tests with `testament run`, not `pytest` directly. It sends this worktree (uncommitted
and untracked files included; ignored files such as `.env` never leave the machine) to
testament's runners and streams the results back. If no coordinator answers, it runs the same
tests here under this machine's test-slot cap and says so.

If `testament` isn't installed: `uv tool install --python 3.14
git+ssh://git@github.com/brookstalley/testament@main` (or `git+https://…`), then
`testament guide client`. Until it is, run `pytest` as before. To set testament up here,
ask the person for their pool's console address and follow `<console>/public/docs/start`
(a pool too old to serve that page has `<console>/public/docs/client` instead).

    testament run --json -- tests/unit/test_foo.py -k bar   # any pytest selection
    testament run --json                                     # the project's default suite

Read the JSON on stdout:

- `exit_code`: 0 all passed; 1 tests failed (a real red: fix it); 5 nothing collected
  (an existing selection; a path that does not exist is 2, `path_not_found`);
  2 anything else, which is **not** a test result. Read `error.code`; when `error.retryable` is
  true, run again.
- `report.items[]`: one per test, with `outcome` (`passed`, `failed`, `error`, `skipped`),
  `message` (pytest's failure text for a failed or errored test, or why a skipped test
  skipped) and `runner`.
- `report.missing`: tests that were requested but never reported. A non-empty list is exit 2
  (`population_mismatch`), never a pass. When every missing test is also in `report.given_up`
  (the pool gave it up after the batches holding it were lost or crashed three times: runners
  dropped, or pytest died), the code is `batches_lost` instead, and it is retryable.
- `report.counts`: how many tests ended each way, over the whole run.
- `fallback`: present when the tests ran on this machine instead of the runners. Flags
  that need one local pytest process (`-x`, `--maxfail`, `-n`, `--lf`) always run here;
  `fallback.reason` names the flag. Flags that need a terminal (`--pdb`, `-s`, `--co`) are
  refused under `--json`.
- `setup`: present when testament isn't fully set up for this repo or machine. The tests
  still ran; tell the person, and point them to the `guide` command it names.
- `report.advice[]`: what the run advises, none of it a test result. Kind `cache` (also
  `report.cache.advice`): what keeps the most tests from ever being reused, each cause with
  its `share` of the run and a one-line `fix`. Kind `slow_test`: one test that delayed the
  run, with its `delay_s`; split or parametrize it, or make it cheaper. Kind `slow_batch`:
  the batch that ended the run late, with its `cause` (`group`, `slow_test`, `pool` or none);
  for a group, give its tests finer group keys. Kind `upgrade`: the pool runs a newer
  testament than this machine (`coordinator_version`, `client_version`); run its `command`,
  which replaces only the testament tool, and the next run uses it. Every entry has an `id`
  (its kind and eight hex digits, stable while what it names is unchanged), a `severity` and
  a one-line `headline`; entries are ordered `upgrade`, then the other important ones by
  delay, then `info` (cache, slow tests, slow batch). `important` is every `upgrade`, a
  `slow_test` that delayed the run over 30 s, a `slow_batch` that did, from a group, and the `cache`
  advice when at least a quarter of a full run's tests are uncacheable and not declined; a batch slow from a slow test is `info` (its test's entry carries it), and one slow from the
  pool is no advice at all, only a figure (the pool's operator hears of it). Important entries are the last lines of the run's output (stderr
  under `--json`), at most three, as `testament ADVICE [<id>]: <headline>`, then `testament
  ADVICE: <n> more in report.advice`; they print on every run while they hold, because a
  wrapper's log tail is often all that gets read. When you see one, run the upgrade, or fix
  the test, group or cache cause it names when that is your task, or tell the person. The rest (`info`,
  smaller cache causes included) appears about once a day per project, and again at once when it
  names something new; `report.advice_state` is `throttled` on the runs in between. When it's
  non-empty, tell the person, and act on it only when that is your task, except `upgrade`,
  which you run. `--advice always` (or `TESTAMENT_ADVICE=always`) shows every entry on every
  run while you work through fixes, and `never` hides all of it. The same text goes to stderr
  for whoever watches.
- `report.durations`: every run, the shape of its test time (mean, stdev, median, p90,
  p99, max, the five longest and their share) for its tests, files and groups, and how
  parallel it ran. `report.slow_tests` and `report.slow_batches` are the figures behind the
  slow-test and slow-batch advice, on every run and never throttled: how much later the run
  ended because of each (`delay_s`), at most five tests and one batch. `report.long_poles`
  is the older long-pole figure, kept for older clients.

Progress (request accepted, tests collected, each failure) arrives on stderr as the run
goes; stdout is the envelope alone. A run that ends `upgrade_required` with a message
naming an install command comes from a testament too old to have `upgrade` advice,
which the pool no longer serves: run that command, then run again (one that names
none means the coordinator is the older side: tell the person). Keep one envelope per run, in a file in a temp
directory that you age out, so a failure can be re-read without running again. When you
need only the verdict and the tests that didn't pass, run `testament run --json=summary`:
the same envelope, but `report.items` lists only the tests that failed, errored, skipped or
never reported, each with its `outcome` and `message` (a skip is not a failure: read
`outcome`; `report.detail` is `"summary"`); `report.counts`, `report.missing` and
`error.ran` still describe the whole run.

A test that fails and then passes when you run it again may be flaky, not fixed. Before
deciding, `testament history '<test id>' --json` shows its past runs here and on the
pool, newest first, each with its outcome, runner, commit and failure text, and how often
it flipped on one tree. `testament report --json` ranks the project's slowest and flakiest
tests and those failing only on some runners.

`testament status` shows the runners and what's queued.
