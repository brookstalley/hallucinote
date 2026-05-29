---
description: Query a song's compose-time audit log (requests) for prior LLM prompts and decision rationale. Complementary to /song-context.
argument-hint: "[topic keywords] [--limit N] [--song SLUG]"
user-invocable: true
disable-model-invocation: false
context: fork
allowed-tools: Bash, Read
---

You are retrieving prior compose-time decisions from a song's audit log. This keeps the caller's context clean by returning only matching rows.

## When to invoke

Run `/decisions` proactively before any non-trivial composition or arrangement work, in addition to `/song-context`. The two are complementary:

- **`/song-context`** searches the deliberate-decision corpus: `decisions/<date>-slug.md` ADRs and `annotations/slug.md` files (markdown-primary, FTS5-indexed). Use to find "what was decided here, with rationale."
- **`/decisions`** searches the audit log: `requests.prompt_text` and `requests.metadata_json.decision_rationale`. Use to find "what prompted this state — what was the LLM asked to do, and what reasoning did it record at the time?"

Concrete cases where `/decisions` is the right tool:

- **Defensive** — "we softened the chorus bass on 2026-05-26 — are you sure you want to undo that?" The LLM's reasoning is in `metadata_json.decision_rationale` on the request that touched the bass; nowhere else.
- **Generative** — "the bridge echoes the intro's dim7 — let's echo a few notes too." The original "echo" prompt + rationale lives on the intro compose request.
- **Forensic** — "what did the last compose pass change?" Better answered by `list_requests_for_song` + `get_events_for_request`, but `/decisions` surfaces the WHY behind the WHAT.

Skip retrieval for purely mechanical edits (typos, renaming a clip) where prior rationale won't change the answer.

## How it works

Two request fields scanned in one SQL pass, song-scoped:

- `requests.prompt_text` — verbatim seed prompt for compose / push / pull / mutate cycles.
- `requests.metadata_json.decision_rationale` — the LLM's reasoning, by convention.

Multi-keyword semantics: **AND** — every keyword must appear in the row. The query LIKEs against the row's searchable text.

Each result row renders as a `prompt + rationale` markdown section. Durable, prose-shaped composer intent lives in the markdown corpus (`decisions/` + `annotations/`) — reach for `/song-context` for that.

## Invocation

$ARGUMENTS

**Step 1 — Identify the active song.** See `/song-context` Step 1 for the preflight rule. Use the song's DB at `songs/<name>/<name>.db`.

**Step 2 — Run the query.** Invoke `tools/decisions_cli.py` via Bash:

```bash
# Single keyword
python3 tools/decisions_cli.py --db songs/falling-walking/falling-walking.db "bridge"

# Multi-keyword (positional, space-separated — AND semantics)
python3 tools/decisions_cli.py --db songs/falling-walking/falling-walking.db "bridge counter-melody"

# Multi-keyword (explicit list)
python3 tools/decisions_cli.py --db songs/falling-walking/falling-walking.db --keywords "bridge,dim7"

# Cap the result count
python3 tools/decisions_cli.py --db songs/falling-walking/falling-walking.db "sidechain" --limit 5
```

**Step 3 — Display the result.** The script outputs markdown — show it to the caller as-is. If a result looks load-bearing for the caller's current task, treat it as constraint context (the previous decision's rationale is part of the song's intent), not a checklist.

## The discipline

`/decisions` is only useful if compose-time requests carry their reasoning. At compose time, write your reasoning into `requests.metadata_json.decision_rationale`:

```python
M.create_request(
    conn,
    actor="llm",
    intent="compose-bridge-counter-melody",
    song_id=song_id,
    kind="compose",
    prompt_text="Add a counter-melody to the bridge that echoes the intro",
    metadata={
        "model": "claude-opus-4-7",
        "decision_rationale": (
            "Echoed the intro's first four notes a fifth up — the bridge "
            "needed to feel connected to the opening without repeating it. "
            "Stayed inside the dim7 to preserve the bridge's tension."
        ),
    },
)
```

The mechanical changes ride on the events under this request; the WHY rides on `decision_rationale`. Without rationale, `/decisions` can still find the prompt but loses half its value.

## Important

- This is a **read-only lookup**. Do not modify any files.
- Empty result → say "no prior decisions for this query" and suggest a broader keyword set. Don't summarize-from-nothing.
- Cross-song search is not supported — songs are independent corpora (per project memory `project_cross_song_reuse`, shared layers come later via dedicated tables, not by cross-DB queries).
- For deeper provenance (every event touched by a request, full request list, request event summary), use the Python query surface directly: `Q.list_requests_for_song`, `Q.get_events_for_request`, `Q.get_request_event_summary`.
