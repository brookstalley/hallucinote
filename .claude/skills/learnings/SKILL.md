---
description: Look up project learnings and preferences relevant to your current task — returns only what matters, keeping context clean
argument-hint: "[topic description] e.g., 'updating tests', 'building MCP endpoint', 'pydantic models'"
user-invocable: true
disable-model-invocation: false
context: fork
allowed-tools: Read, Agent
---

You are looking up project knowledge relevant to a specific task. This skill keeps the caller's context clean by returning only what matters.

## How It Works

$ARGUMENTS

**If no topic was provided:** Read `.prawduct/learnings.md` directly and display the section header index with rule counts — a quick overview of what knowledge exists.

**If a topic was provided:** Spawn a subagent (via the Agent tool) to search all knowledge files and return a concise, relevant summary. Use this prompt for the subagent:

> You are a project knowledge lookup agent. Read these files from the project directory:
>
> 1. `.prawduct/learnings.md` — concise rules from past mistakes (always exists)
> 2. `.prawduct/learnings-detail.md` — deeper root cause analysis (may not exist)
> 3. `.prawduct/artifacts/project-preferences.md` — project conventions and choices (may not exist)
>
> The caller is working on: **[topic from arguments]**
>
> Return ONLY the content relevant to that work. Structure your response:
>
> **Relevant Rules** — quote matching rules from learnings.md directly, grouped by their section header. Include the section header for context.
>
> **Key Context** — from learnings-detail.md, only if it adds actionable information beyond the concise rule. Skip this section entirely if the rules are self-sufficient.
>
> **Relevant Preferences** — matching conventions from project-preferences.md. Skip this section entirely if the file doesn't exist or nothing matches.
>
> If nothing is relevant across any file, say: "No learnings or preferences found for [topic]."
>
> Keep your response under 500 tokens. Be concise — the caller will read this in their main context window.

**After the subagent returns:** Display its response to the user. Do not add commentary or expand on it — the response is ready to use as-is.

## Important

- This is a **read-only lookup**. Do not modify any files.
- The subagent's value is **filtering** — it reads ~4K+ tokens of knowledge files and returns ~200-500 tokens of what matters.
- When invoked by methodology guidance ("run `/learnings [topic]` before planning"), treat the result as constraints that inform your work, not a checklist to follow mechanically.
