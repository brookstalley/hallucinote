# Bug: `ableton_device(load)` silently no-ops when Live's focused view is Arranger (a render leaves it there)

**Type:** bug — device loading is unusable after a render until the view is switched.
**Severity:** H. It bricks ALL device loads (the device phase of a push, `/song-pick-instruments`, any interactive re-voice) with a confusing "Live did not append a device" error, and the most common trigger is "you just rendered" — which every song does repeatedly.

**Engine / server:** `0.1.0+4372b6734f8d`. Surfaced on `alien` while reverting an instrument.

## Symptom

After a render, EVERY `ableton_device(action='load', node={... track i ...}, kind=...)`
fails:

```
RuntimeError: load: Live did not append a device on track 4 after browser.load_item.
Existing chain: [(empty)]. Most common cause: a device with matching class is already
present at the expected position (Live silently no-ops the load).
```

It fails for any instrument (Operator, Analog, …), into an empty chain, with the correct
track passed. The "matching class already present" hint is a red herring — the chain is
empty. Deletes, parameter sets, lists, introspection all keep working — only
`browser.load_item` no-ops.

## Root cause

`browser.load_item` loads onto Live's **selected track**, and it is **silently a no-op
when the focused view is `Arranger`**. The render finishes with the view on Arranger
(`ableton_session(action='info')` → `"focused_view": "Arranger"`). The load handler does
`song.view.selected_track = parent` then `browser.load_item(item)` — but in Arranger
focus the load does nothing and no device appears anywhere (verified: no strays on any
other track; `hotswap_target` is null; transport stopped; server fingerprint matches the
Remote Script — all ruled out).

**The fix is one line:** `ableton_session(action='set_view', view='session')` immediately
unblocked it — the same load then succeeded on the first try.

## Repro

1. Render anything (`ableton_render`) — leaves `focused_view = "Arranger"`.
2. `ableton_device(action='load', node={parent:{kind:'track',index:N},terminal:'track'}, kind='Operator')` → fails "did not append".
3. `ableton_session(action='set_view', view='session')`.
4. Repeat step 2 → succeeds.

## Suggested fix

- In the device-load handler, **force a load-compatible view before `browser.load_item`**
  (switch to Session or Detail, optionally restore afterward). The handler already sets
  `selected_track`; it should also guarantee the view, since `load_item` is view-sensitive.
- And/or have **`ableton_render` restore the pre-render focused view** (it shouldn't leave
  the session on Arranger as a side effect).
- The "did not append … matching class already present" error should mention the
  Arranger-view cause (the current hint sends you hunting for a phantom duplicate device).

## Impact note

This cost a long debugging detour and left a track instrument-less mid-recovery (I'd
deleted the old instrument before discovering loads were blocked). A device-load that
no-ops *silently* right after the universal "render" step is a sharp edge — worth the
defensive view-set in the handler.
