---
name: getting-started
description: Orient a new Hallucinote user — check the install (uv, the MCP bridge, the Ableton Remote Script, the Max for Live analyzer), say plainly what works with and without Max for Live, and propose the next step (install if needed, then a new or existing song). Use on first run, or when someone asks how to get started / set up Hallucinote / "what now?".
user-invocable: true
disable-model-invocation: false
---

# /getting-started

You orient someone new to Hallucinote: check what's set up, tell them plainly what works (and what needs Max for Live), and **propose** the next step. Do NOT run the installer or scaffold a song on your own — offer, and let them choose. Keep it warm and short; this is a conversation, not a wizard.

## 1. Check the install

Run the preflight report:

```bash
python -m hallucinote_mcp.cli preflight
```

It's JSON. Read these blocks:
- **`uv`** — the bundled MCP server is launched with uv. If it's missing, that's the first fix (`brew install uv` on macOS, `winget install astral-sh.uv` on Windows).
- **`remote_script`** — the Ableton Control Surface script. `candidates[*].matches_mcp_server: true` means Live's copy matches the running server.
- **`analyzer`** — the HallucinoteAnalyzer (a Max for Live device). Present + matching → render/mix analysis is available. Absent → see the Max for Live note below.
- **`live.installed_versions`** — which Live installs were found.

If Live is open, confirm the bridge actually talks to it: `ableton_session(action='info')`. A real response (tempo, tracks, master) proves the Remote Script is assigned to a Control Surface slot and the server is connected. A hang or "no connection" means Live isn't running, the Control Surface slot isn't assigned, or Claude Code needs a restart after assigning it — see `/ableton-mcp-install` and the README troubleshooting.

The composing **engine** (the `hallucinote` package `build.py` imports) ships in the plugin's uv env — the same env as the bridge — so there's nothing separate to install. Engine commands run via the plugin's own interpreter (`ableton://server/info` → `python`); see [`docs/running-the-engine.md`](../../docs/running-the-engine.md).

## 2. Say what works — honestly, Max for Live included

Tell them in plain language where they stand:
- **Everything works without Max for Live**: compose, arrange, sound-design, push to Live, pull edits back, and `/compose-review` (the symbolic composition review).
- **`/mix-review` and audio rendering use Max for Live** (Live Suite, or the M4L add-on) — that's what the analyzer is. If the `analyzer` block is absent and they don't have Max for Live, that half isn't available; don't imply it is.

## 3. Propose the next step — offer, don't act

Read the state and propose ONE next step as an offer, then let the conversation carry it (rely on context — don't force a fixed script):
- **Remote Script / analyzer missing and they want Live set up** → offer: *"Want me to walk you through `/ableton-mcp-install`?"* It has interactive checkpoints (quit Live first), so let them drive it — don't run it unprompted.
- **Set up and ready** → offer the fork: *"Want to start a new song, or open one you already have?"* — new → `/song-new`; existing → name it and push it. The full lifecycle map is `/song-workflow`.
- **Just exploring** → point at the README and `ableton://guides/getting-started`.

End on the offer. The user chooses; you flow from there.
