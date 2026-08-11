# Browser inventory cache schema

The **machine-local browser inventory cache** lets a composer pick built-in
Live content by name and author a portable `preset_query` **without Live
running** — killing the push-then-recapture loop. It is the offline companion
to the live browser (`ableton_browser`) and the push-time `preset_query`
resolver.

Owner: `src/hallucinote/inventory.py` (read/write/find) +
`hallucinote_mcp.handlers.browser.inventory_handler` (the live walk that feeds
it). Format version: **1** (`SCHEMA_VERSION`).

## Where it lives

```
~/.hallucinote/inventory/cache.json
```

**User-global, never in a repo.** The installed library is a property of
*(this machine, this Live install)* — not of any song or repo. One cache serves
every Hallucinote repo on the machine, and because it lives outside every repo
tree, sharing a repo carries **zero** assumptions about a teammate's installed
content. There is nothing to `.gitignore`; share-safety is structural.

## It is a cache, not a durable index

- It **goes stale** — you install a pack, a preset moves, you upgrade Live.
- It is **refreshed deliberately**, with Live open:
  `"$PY" -m hallucinote.cli inventory refresh` (see [`running-the-engine.md`](running-the-engine.md)).
- Staleness is **advisory, never blocking**. Offline picks warn with the
  cache's age; **push-time resolution stays the source of truth**. If the cache
  is wrong (content uninstalled since the last refresh), the `preset_query`
  fails *loudly at push*, in Live, where it can be confirmed — never as a silent
  wrong load.

## File shape

```jsonc
{
  "schema_version": 1,
  "captured_at": "2026-05-28T17:40:00+00:00", // ISO-8601 UTC; primary staleness signal (age)
  "machine_id": "studio-mini.local",          // socket.gethostname(); informational
  "live_version": "12.1.5",                    // Application.get_version_string(); null if unavailable
  "live_variant": "Suite",                     // Application.get_variant(); secondary staleness signal
  "walk_depth": 8,                             // depth the library was walked (== push resolver depth)
  "roots_covered": ["instruments", "audio_effects", "drums", "..."],
  "roots_partial":  ["packs"],                 // exceeded the breadth cap even after subdivision
  "roots_excluded": ["samples"],               // not requested (resolve live at push)
  "count": 41027,
  "entries": [
    {
      "root": "drums",
      "path": ["drums", "Drum Hits", "Kick", "Kick 909 2.wav"], // root key → leaf name, inclusive
      "name": "Kick 909 2.wav",
      "uri": "query:Drums#Drum%20Hits:Kick:FileId_1912",        // PER-MACHINE FileId — never authored into a snapshot
      "is_loadable": true
    }
  ]
}
```

### Why these fields

- **`entries[*].path`** is the full segment list from the root key to and
  including the leaf name — identical in shape to an `ableton_browser(search)`
  match. Offline resolution scopes `preset_query.path_prefix` against it.
- **`entries[*].uri`** is Live's per-machine `FileId`. The cache keeps it for
  local convenience, but the **snapshot author writes only `preset_query`**
  (root + pattern, portable) — never the FileId. The cache is for *finding*
  content by name; the portable selector is what lands in
  `captured_session.json`.
- **`walk_depth`** records how deep the library was walked. It must be `>=` the
  push-time resolver's depth (`hallucinote_mcp.handlers.device._BROWSER_WALK_DEPTH`),
  pinned by `tests/unit/sync/test_compat.py::test_browser_walk_depth_matches_mcp_side`.
  A shallower cache could miss a loadable push can still reach.
- **`roots_partial` / `roots_excluded`** make incomplete coverage explicit —
  `find()` warns/raises against these rather than reporting a coverage gap as
  "not installed" (**no silent caps**).

## Resolves identically to push

`inventory.find(cache, query)` delegates to
`hallucinote.preset_query.resolve_query`, which is a **mirror** of the push-time
resolver `hallucinote_mcp.handlers.device._resolve_preset_query`:

- same name matcher (`name_matches` ⇄ `_name_matches`, pinned by
  `test_name_matches_matches_mcp_side`),
- same strict **single-match** semantics (0 matches → "no match"; 2+ → ambiguity
  error listing the disambiguating paths),
- the cache walked to the same depth with the same recursion rule (**recurse
  past loadables** — a loadable rack/instrument can contain further loadable
  presets; e.g. `Operator` is loadable yet has factory-preset children).

They are mirrors rather than one shared function because the MCP handlers run
inside Live's Remote Script Python, which does not have the domain `hallucinote`
package installed — so the two halves cannot import each other. The lock-tests
are what keep them honest.

## Scale

A pack-heavy install is tens of thousands of loadables; a single stock
instrument carries hundreds–thousands of factory presets, and the `drums` root
holds thousands of individual hit samples. The cache is therefore built **one
root at a time** via `ableton_browser(action='inventory', root=…)`, which:

- caps each response under the 16 MiB wire frame (`_INVENTORY_MAX_ENTRIES`,
  default 20000) and bounds how long the walk blocks Live's main thread;
- sets `truncated: true` when the cap is hit, so the refresh subdivides the
  root by its top-level child folders (`_MAX_SUBDIVIDE_LEVELS`) and, if a branch
  *still* overflows, records it in `roots_partial` — never a silent truncation;
- excludes `samples` by default (the largest, least relevant root for
  instrument/kit picking).
