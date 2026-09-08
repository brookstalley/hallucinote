---
id: CTM-08
source: 721b002c
repo: hallucinote
at: 2026-08-07T21:35
episode: the-argument (attempt 2)
polarity: negative
turn_kind: exploring
agent_read_as: delegating
hearable_unit: n/a — a product conversation
failure: menu-over-listening
queued: false
---

# Answering "one thing at a time" with another form

## User said

> …that was a giant wall of text with a LOT of proposals and explanations. How can we update hallucinote to make that kind of discovry more interactive and iterative rather than one huge list? People will want to be asked one thing at a time, or given things to consider.

## Agent did

A 340-word analysis concluding *"the one-turn rule isn't the problem"*, then an `AskUserQuestion` picker: *"Pickers, still one turn (Recommended)" / "One turn + bounded deepening" / "Fully sequential Q&A"*. The user rejected the picker.

## What happened next

> we need to optimzie for product experience, not the demo. […] So I think conversation is the right way... this stuff is too nuanced to be multiple choice. But it should be more efficient. […] I think the most successul interaction would be for the agent to note those things, come up with its own mental model of the song, then ask questions. Just like a real compose or session musicion would if I came to them with that brief. "Sounds interesting -- do you have any chords or harmonic structure in mind?" "What are you thinking for production?…"

## The tell

The user had just said the problem was too many pre-argued options. The reply was a set of pre-argued options with a recommended one. Also: the user was thinking out loud about the product ("how can we…"), which is exploring, not a request for a decision.

## The right move

Think with them: name the session-musician shape they were reaching for, and ask what a good first question would have been for *this* brief.

## Assertion

When a user describes an interaction as too list-like or too pre-decided, the reply is a conversation, not a structured choice. `AskUserQuestion` is reserved for genuinely enumerable engineering decisions.
