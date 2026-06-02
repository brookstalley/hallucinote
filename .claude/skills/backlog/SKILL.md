---
description: Manage the structured product backlog — pick what to work on next, add/find/list/update items, and migrate legacy items. Use when the user wants to triage, file, or choose backlog work, or says /backlog.
argument-hint: "[pick|add|find|list|update|migrate] ... (e.g. `pick stop-hook stuff under an hour`, `add`, `find sync`, `list --area=critic`, `update STH-K7p2 status=promoted`)"
user-invocable: true
disable-model-invocation: false
context: fork
allowed-tools: Read, Edit, Write, Grep, Glob
---

You manage `.prawduct/backlog.md` — the product's structured backlog. You run in a forked context, so the full backlog never pollutes the main session. Read the file, do the operation, write it back, and return a concise result. **Never** delete items (archive instead) and **never** weaken existing content.

## The format you operate on

Each item:

```
- **[PFX-XXXX]** One-line title
  `effort: M · impact: M · area: stop-hook · source: reflection · added: 2026-05-29 · status: open`

  Optional free-form body (any length).
```

- **ID** `[PFX-XXXX]`: `PFX` = 2–3 uppercase letters naming the work-space, *derived from the item's area* — reuse an existing prefix when one fits so related items share it. Starter set (extend freely): `STH` stop-hook, `CRT` critic, `SYN` sync, `LLM` prompt/LLM, `BKL` backlog, `MIG` migration, `JNT` janitor, `MET` methodology, `DOC` docs, `TST` tests. If `backlog_prefixes:` is declared in `project-state.yaml`, prefer those. `XXXX` = 4 random base36 chars (`A–Z`,`0–9`); generate fresh and confirm it doesn't collide with an existing ID in the file.
- **Metadata bar**: one backticked dot-separated line. Required fields: `effort` (S/M/L), `impact` (S/M/L), `area`, `source` (builder|critic|reflection|janitor|user), `added` (YYYY-MM-DD), `status` (open|promoted|shipped|dropped). Optional: `related:` (related items), `closes:` (another backlog item this one supersedes — item→item), `closed-by:` (the chunk/release that shipped this item — item→release), `reviewed:`. Keep `closes:` and `closed-by:` straight — they point in opposite directions.
- **Sections**: `## Open` (pickable), `## Promoted` (in an active build plan), `## Archive` (shipped/dropped, kept for search). Items move between sections only via explicit `update` calls — never infer status from build plans or change logs.
- **Legacy items** (no metadata bar) are valid; treat them as `effort:? · impact:? · area:untagged · status:open` and rank them lower. Suggest `/backlog migrate` if there are many.

For today's date when stamping `added:`/`reviewed:`, use the current date from your environment context.

## Subcommands

Parse `$ARGUMENTS`: the first token is the subcommand (default to the no-arg summary if empty). Everything after is arguments — accept both `--flag=value` form (for machine callers like the Critic or reflection) and natural-language prose (for humans).

### (no args) — summary + menu
Read the file, then print: counts per section (`N open · N promoted · N archived`), the top 3 `area:` tags by item count, a count of stale items (`status: open` and `added`/`reviewed` >90 days ago), and the action menu (`pick`, `add`, `find`, `list`, `update`, `migrate`).

### add
File a new item. Accepts flags (`--title=`, `--body=`/`--body-file=`, `--area=`, `--effort=`, `--impact=`, `--source=`, `--prefix=`) or interactive prompts for anything missing.
1. **Dedup first.** Search existing items whose `area:` matches or whose title keywords overlap. If any exist, show the top ~3 (`[ID] title — status, added`) and ask: continue, update one of them, or cancel. (When called with complete flags by a machine caller, skip the prompt but still note overlaps in your result.)
2. On confirm, derive a prefix, generate a non-colliding `[PFX-XXXX]`, build the metadata bar (`source` defaults to the caller; `added` = today; `status: open`), and append the item under `## Open`.
3. Return the new ID and a one-line confirmation.

### find <query>
Plaintext + tag search across title, metadata, and body of **all** sections (and `backlog-archive.md` if it exists). Return matching `[ID] title — one-line summary`, most-relevant first. Keep it tight (a handful of results).

### list [--filter=...]
Tabular view: `ID · title · effort · impact · area · status`. **Default filter: `status=open` AND `added` within 90 days** (so a 200-item backlog doesn't dump). `--all` overrides; filter on any metadata field (`--area=`, `--status=`, `--effort=`, etc.). Sort by status then recency.

### update PFX-XXXX <field=value> [...]
Change metadata or body of one item. Common: `status=promoted|shipped|dropped` (moves the item to the matching section — `promoted`→`## Promoted`, `shipped`/`dropped`→`## Archive`), `area=`, `effort=`, `reviewed=`. On `status=shipped`, accept an optional `closed-by=<change-log tag or chunk id>` and write it into the **metadata bar** as `closed-by: <ref>` (not the body) for traceability. Always set `reviewed:` to today on any touch. Confirm the item exists first; if the ID isn't found, say so and suggest `/backlog find`.

### pick [filters / free-text]
Return **1–3 ranked candidates** with a one-line rationale each — the answer to "what should I work on right now?" Most invocations carry context; the bare call is the fallback.

**Parse the request (you are the parser — no rigid grammar).** Map the user's words to three optional filters:
- **area** — any tag the project uses (`sync`, `critic`, `stop-hook`, …).
- **budget** — how much time, mapped to `effort`: `15m`/`30m`/`under an hour`/`quick` → prefer `S`; `a couple hours`/`this afternoon` → `S`–`M`; `half-day`/`big` → up to `L`.
- **type** — `quick-win` (high `impact`, low `effort`), `warmup` (low-stakes, context-loading — small/legacy/cleanup items), `focus` (larger items, `effort: L`, needs uninterrupted attention).

Accept flag form for machine callers (`--area=sync --budget=30m --type=quick-win`) and prose for humans (`pick stop-hook stuff under an hour`, `something I can do in 15 minutes`, `a warmup task`, `anything sync-related`).

**Confirm-back ceiling (Q3).** If the query carries constraints beyond area/budget/type, or your interpretation is uncertain, echo the filter you parsed and ask before running — e.g. *"I read this as: area=stop-hook, budget≈1h. Continue, or refine?"* Don't silently guess on ambiguous input.

**Ranking.**
1. **Exclude** `status: promoted` (already in flight) and archived items by default.
2. **Apply** the parsed filters as the candidate pool. If filters empty too small a pool, widen and say so.
3. **Score** each candidate: `impact / effort` (map `S=1, M=2, L=3`; missing → treat as `2`, i.e. unknown-middle), nudged up by recency (newer `added`/`reviewed` ranks slightly higher) and **down** for untagged/legacy items (no metadata bar). This is a deliberately simple heuristic — don't over-engineer it before there's usage data to tune it.
4. **Return** the top 1–3 as `[ID] title` + a one-line *why* (e.g. *"high-impact sync fix, ~2h, no dependencies"*).

**Build-plan-aware (Q6) — the primary mid-work case.** Before ranking, read `active_build_plan` from `.prawduct/project-state.yaml`. If it points to a plan, read that plan and infer its scope/area focus (its `scope:` tag, chunk areas, the files it touches). Then **prioritize open items whose `area:` or subject overlaps the active plan**, framed as *"related to what you're working on"* — knocking out an adjacent item while the context is loaded is the highest-value pick. Show overlapping candidates first; if fewer than the requested count, fill from the general ranking. `--standalone` disables this and deliberately suggests context-switch work instead. If no plan is active, skip straight to the general ranking.

**Worked examples** (parsed filter → behavior):
- `pick stop-hook stuff under an hour` → `{area: stop-hook, budget: S–M}` → open stop-hook items, effort S/M, top 2–3 by score.
- `pick a warmup task` → `{type: warmup}` → small/legacy/cleanup items, low stakes, recency-weighted.
- `pick` (bare, plan active) → no filters → build-plan-overlapping open items first, then general `impact/effort` ranking.
- `pick something quick and high-impact` → `{type: quick-win}` → high-impact + low-effort items.

### migrate
Convert legacy unstructured items to the structured format and fold the old sections into Open/Promoted/Archive. **Idempotent** (only touches items lacking a metadata bar) and **never destructive** (bodies are preserved verbatim; items are never deleted). This is the action the `legacy-backlog-format` post-sync advisory recommends.

1. Read `.prawduct/backlog.md`. Identify legacy items — top-level bullets with no `effort: … · status: …` metadata bar. If there are none, report "already migrated" and stop.
2. Walk them in **batches of ~10**. For each item show its title + first ~2 lines of body and your **inferred metadata**:
   - `source` from existing parenthetical markers (`(critic)`/`(reflection)`/`(builder)`/`(migrated)` → the matching source; else `user`).
   - `area` inferred from title/body keywords; reuse tags already present in the file.
   - a derived `[PFX-XXXX]` id (prefix from the area; fresh non-colliding suffix).
   - `effort`/`impact` left as `?` when not inferable — don't invent them.
   Present the batch and let the user accept as-is, edit inline (e.g. supply `effort impact`), or skip individual items. When run non-interactively, apply your inferences and report what you assumed.
3. On accept, rewrite each item to the structured shape (id + metadata bar + original body unchanged), placing it in the section matching its `status` (default `open`).
4. **Fold sections**: map legacy headings onto the canonical three — `## Active — next up` and `## Queue` → `## Open` (use judgment if "Active" items were truly in-flight → `## Promoted`); preserve any already-`[RESOLVED]`/shipped items by moving them to `## Archive` with `status: shipped`. (`/backlog migrate --sections` does only this heading conversion without re-touching item metadata.)
5. **On completion** (all legacy items structured + sections folded), write `backlog_format_version: 2` as a top-level key in `.prawduct/project-state.yaml`. This is the resolution-condition fact the `legacy-backlog-format` probe consults — setting it auto-resolves the advisory on the next sync (and, because project-state.yaml is committed, for every teammate). If migration is partial (user skipped items), do **not** set it yet — say how many remain.
6. Report: items migrated, sections folded, whether `backlog_format_version` was set, and how many (if any) remain legacy.

$ARGUMENTS
