---
id: CTM-18
source: f39592e6
repo: hallucinote-songs
at: 2026-08-06T19:10
episode: alien
polarity: positive
turn_kind: asking
agent_read_as: asking
hearable_unit: the existing song, rendered
failure: none
queued: false
---

# Investigate, summarize, offer one step, wait

## User said

> let's work on the alien song. can you summarize it's current state

## Agent did

Twenty-four read-only tool calls (the song's files were missing from the working tree; it recovered the documents from the DB's full-text store and then found the source on the `compose/alien` branch). A 490-word summary ending: *"Want me to switch to `compose/alien` and start with a render + listen pass?"* Waited.

## What happened next

> yep render

The agent stashed the user's unrelated WIP, switched branches, discovered the MCP bridge was not loaded in the session, and reported the one-line fix with the checks it could still run. Minor blemish: the stash and branch switch happened before it checked whether a render was possible at all.

## What made it work

"Summarize its current state" is a question. The agent answered it, offered exactly one next step, and let the user say the word. This is the shape the Tapestry opening (CTM-01) should have had.

## Assertion

A question about state is answered with a summary and at most one offered next step. Nothing is mutated until the user takes the offer.
