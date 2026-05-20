# Collaboration — Sharing Songs Between Machines

**Audience.** A composer wants to hand a Hallucinote song to a collaborator (mixer, co-producer, mastering engineer) on a different machine. This document walks the round-trip and names the three portability cases that have load-bearing implications.

**Status.** This document covers what v0.9 can deliver. v1.0 closes Case A; v0.9 ships Case B detection and is explicit that Case C is permanently out of scope. See `.prawduct/artifacts/build-plan.md` for the wave status.

---

## What you're actually sharing

A Hallucinote song is a **directory under `songs/<slug>/`** in this repository. The minimum a collaborator needs:

```
songs/<slug>/
├── <slug>.md                   # composer intent + decisions context
├── build.py                    # the generative spec — runs to materialize the DB
├── captured_session.json       # the mix snapshot — devices, params, sends
├── REQUIREMENTS.md             # third-party plugin shopping list (W13-B)
├── annotations/                # markdown notes for the composer/agent
├── decisions/                  # design-decision history
└── tests/                      # per-song structural assertions
```

Plus the DB itself (`<slug>-<branch>.db` or `<slug>.db`), which is **gitignored** by default — collaborators regenerate it locally by running `python songs/<slug>/build.py`.

What you're **not** sharing: the `<slug> Project/` directory (Ableton's actual `.als` and audio assets). That belongs in the consumer's working copy of Ableton; Hallucinote only describes the song, it doesn't ship binary Live state.

---

## The round-trip, step by step

### 1. Clone the repository

The composer commits and pushes. The collaborator clones:

```bash
git clone <repo-url>
cd hallucinote
pip install -e .[dev]
```

If you forked a single song out of a larger Hallucinote repository, the collaborator can either clone the whole repo (full Hallucinote available) or copy just the song directory into their own Hallucinote install. The song is self-contained relative to the platform; nothing in `songs/<slug>/` references other songs.

### 2. Check the requirements

Before pushing the song into Ableton, the collaborator reads `songs/<slug>/REQUIREMENTS.md`. This file is the **shopping list** the composer left behind — it enumerates any third-party VST/AU plugins the song needs, with every use site (track + chain position) noted.

Three things `REQUIREMENTS.md` does NOT carry:

- **Versions.** Live's plugin scanner matches by name, not version. If the file says "Serum," any installed Serum counts.
- **Sample packs.** Live's Core Library presets ("Late Nite Kit", "Atmosphere Pad") and third-party sample packs (Splice content, manufacturer libraries) are not enumerated. See Case C below.
- **The composer's actual binary.** Hallucinote never bundles plugins. Install them yourself from the vendor.

If the song has no third-party requirements, `REQUIREMENTS.md` says so explicitly. Many Hallucinote songs lean on Live's built-in devices (Operator, Wavetable, Drum Rack, etc.) — those need no install.

### 3. Build the DB

```bash
python songs/<slug>/build.py
```

This produces the SQLite DB at `songs/<slug>/<slug>-<branch>.db` (per-branch convention, W12-A) or `songs/<slug>/<slug>.db` outside a git repo. The DB is the source of truth for everything Hallucinote does: clips, notes, arrangement, automation, devices, mix state.

### 4. Open a fresh Ableton Live set

A new empty `.als`. Don't push the song on top of someone else's work — push is additive (it doesn't delete Live state) and you'll get a jumbled set.

### 5. Run the push skill

In Claude Code, with the project loaded:

```
/ableton-push <slug>
```

The skill walks the song into Live across ten ordered phases. **Before the first phase**, it now runs a compat check (W13-B v0.9.0):

- The skill probes Live for the installed-plugin list via the MCP browser.
- It runs `python -m hallucinote.sync.compat check <slug> --installed-plugins …`.
- If the report flags any third-party plugin as missing (in the DB but not in Live's plugin scanner) or unverified (couldn't probe — Live wasn't responsive), the skill stops and asks you to confirm.

If you confirm "no, install missing plugins first": go install them, then rerun. If you confirm "yes, push anyway": push will fail at device-load for the missing plugins (the chain stays empty; nothing is substituted), but other devices, clips, arrangement, automation, and cue points still apply. You can fix the empty chains by hand in Live afterward.

### 6. Producing the song

After push, you have a real `.als` mirroring the composer's intent. From there, ordinary Ableton workflow: arrange, mix, render. If you want changes to flow back into the song's DB (e.g., a fader move the composer wants to preserve), use the `/ableton-pull` skill.

---

## The three portability cases

Cross-machine song handoff has three distinct technical problems. Hallucinote treats them differently.

### Case A — Same plugin, different catalog id

**Symptom.** The composer's Live and the collaborator's Live both have Serum installed, but Live's internal FileId — the catalog handle stored in `preset_uri` — differs because each machine's plugin scan happens independently. Push tries to load by FileId and Live can't find it.

**Status.** v1.0. The W13-A capture-and-load path (snapshot records `(class, display_name, manufacturer, pack_name, params_dialed)`; push falls back from FileId to a browser search; params re-apply after load) is on the v1.0 roadmap. Until then, Case A surfaces as either a load failure for the specific device or a wrong-preset load — the composer would notice on the verification listen.

**Mitigation in v0.9.** For native Live devices, this case is rare in practice — Live's built-in `preset_uri` values are typically stable across installs. For third-party plugins, the W13-B compat check at least flags the plugin as required so the collaborator knows what should be loaded.

### Case B — Plugin not installed

**Symptom.** The song's DB references a plugin (say, Spitfire LABS) that the collaborator has never installed on their machine. The push would fail at device-load with a Live error pointing at the missing plugin.

**Status.** v0.9.0 — solved at preflight. The `/ableton-push` skill runs `compat check` before any phase executes; if any plugin is missing, the skill refuses-and-confirms with the collaborator. `REQUIREMENTS.md` documents what to install.

**The non-goal.** Hallucinote will **never** substitute plugins. If you need Spitfire LABS and don't have it, the answer is "install Spitfire LABS," not "let me pick a similar-sounding native Live instrument and silently swap." Substitution corrupts the composer's intent in ways that are visible only to the composer's ear — the wrong choice would ship without the collaborator knowing it was wrong.

### Case C — Sample packs, content libraries, missing audio assets

**Symptom.** The song uses Live's "Late Nite Kit" from Live's Core Library Pack, or a Splice loop, or a sample from a third-party content pack. None of those are enumerated as "plugins"; they're audio content referenced by Live presets.

**Status.** **Explicit non-goal.** Hallucinote does not ship audio. It does not check whether you have a specific Live Pack installed. It does not track sample-pack dependencies. If the composer leaned on a specific Drum Rack preset that depends on samples in a third-party pack, the collaborator who doesn't have that pack will hear silence (or default samples) for those slots when they push.

**Why.** Sample packs are large binary artifacts under licenses that vary by vendor. Hallucinote is a metadata layer, not an asset distribution system. Bundling samples is out of scope; checking for sample-pack presence would require deep Live introspection we don't have. The right tool for sample-pack sharing is the vendor's distribution channel (Ableton Pack installer, Splice client, etc.).

**Mitigation.** The composer can document content dependencies in `<slug>.md` ("uses Live Core Library Pack 1") for collaborators to read manually. The compat check does not enforce this.

---

## Re-binding sessions across clones

The `ableton_sessions` table binds a song's DB to a specific Live set via `session_id`. When a collaborator clones the song fresh, no session yet exists for their machine. The push skill handles this automatically:

- If you pass `/ableton-push <slug>` with no session id, the skill detects the gap and offers `--auto-session` (W9-B). This creates an `ableton_sessions` row for the collaborator's local Live set and returns a fresh session id.
- The collaborator typically wants **one** session per Live set: reuse the returned id for subsequent pushes of the same song. The skill prompts the next time too, so it's fine to start over if you lose track.

The composer's session id is irrelevant to the collaborator — sessions are per-machine bindings, not portable identifiers. Don't try to "copy" a session id across machines; create a new one.

---

## What the composer should do before sharing

A short checklist for handoff hygiene.

1. **Regenerate `REQUIREMENTS.md`** after material device changes: `python -m hallucinote.sync.compat write-requirements <slug>`. Commit the result.
2. **Refresh `captured_session.json`** if the mix has moved since the snapshot. See the `/song-snapshot` skill for the diff-and-confirm workflow (W12-B).
3. **Verify the song builds clean** in a fresh checkout. Delete the local DB (`rm songs/<slug>/<slug>*.db*`) and run `python songs/<slug>/build.py`. The tests in `songs/<slug>/tests/` should pass.
4. **Document content dependencies in `<slug>.md`** if the song needs a specific Live Pack or sample library. Compat check won't catch these (Case C).
5. **Commit and push.** The collaborator clones; the round-trip above takes over.

---

## What's NOT in this v0.9 walkthrough

These belong in v1.0 or beyond and are surfaced as backlog items:

- Case A robust handling (W13-A).
- Automated regeneration of `REQUIREMENTS.md` as part of build.py or `/song-snapshot`.
- Compat-check coverage of Live Pack presence (would require a Live-side capability probe we don't yet have).
- Inline iteration support — the `hallucinote://` DB read surface that lets collaborators inspect songs from within an MCP session without running `python3 -c "…"` (W11).

See `.prawduct/backlog.md` for the open items.
