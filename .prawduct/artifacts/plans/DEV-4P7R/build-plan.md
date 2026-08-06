# Build plan — DEV-4P7R: `value_raw` channel for quantized non-unit-range params

Branch: `feat/param-overrides-value-raw` (worktree `.claude/worktrees/value-raw`)
Backlog: **DEV-4P7R** · residual facet of SNP-2H9F (PR #176) · related DPP-7H2K, DEV-9K7N
Report: `backlog DEV-4P7R`
Size: **Medium** · Type: **feature + bugfix** (new persisted channel closing a durability gap)
Critic mode: **cumulative** at PR (single cohesive change; per-build-cycle = chunk then cumulative).

## Confidence check

1. **Problem.** A continuous device-param that is *quantized* AND whose raw range ≠ [0,1]
   AND whose display is non-monotonic (Wavetable `LFO 1 S. Rate`: raw `8.0` → "1/2",
   range `[0,21]`) has **no authorable form** that survives a from-scratch rebuild+push.
   `value_display` is refused at push (`DisplayValueError`, non-monotonic); `value_normalized`
   is clamped to [0,1] at storage and — critically — is pushed through the handler's **raw**
   `value` kwarg anyway (there is no `value_normalized` handler kwarg), so it only round-trips
   when raw range IS [0,1].
2. **Success.** A snapshot entry `{"name": "LFO 1 S. Rate", "value_raw": 8.0}` (top-level
   `params_dialed` or nested `param_overrides`) round-trips DB→push→capture→DB durably; the
   nested swell override survives `build.py --reset` + push without saving the `.als`. Capture
   AND pull auto-emit `value_raw` for the quantized-non-unit-range class instead of the broken
   normalized form. Full suite green.
3. **Out of scope.** (a) Pull-symmetry for nested `param_overrides` — SNP-2H9F already
   defers it (pull lands nested tweaks as transient `device_parameters`); we fix pull for
   TOP-LEVEL params only. (b) Reinterpreting/renaming the existing `value_normalized`
   column (see Decision below — rejected as disproportionate). [Initially also scoped OUT
   "broadening to freq/dB params" — REVERSED during build: see the Scope note in the
   Decision section. After probing, the discriminator is raw range ≠ [0,1] (not
   `is_quantized`), which necessarily covers any non-[0,1] continuous param; that is the
   minimal *correct* rule, and `value_raw` is lossless/always-right for them.]

## Key decision (lock-in — persisted format)

**Add a new `value_raw REAL` column (unclamped) alongside `value_normalized`** rather than
reinterpreting `value_normalized` as raw.

- The handler (`hallucinote_mcp/.../handlers/device.py:1523-1525`) takes, for
  `value_type='continuous'`, EXACTLY ONE of `value` (raw float in `[param.min,param.max]`) or
  `value_display`. There is **no** `value_normalized` kwarg — push already passes the stored
  "normalized" number through `value` (raw). So `value_raw` maps 1:1 to the handler's raw path.
- *Rejected — reinterpret `value_normalized` as raw + drop the [0,1] CHECK.* More coherent in
  theory (one continuous-numeric channel) but a far larger, riskier refactor: it changes the
  meaning of a shipped column present in every song DB, rewrites the capture/pull
  `normalize_param_value` math, and churns many tests — disproportionate to a medium bug with a
  working workaround. Additive `value_raw` is the proportional fix; for genuine [0,1] params the
  existing `value_normalized` stays honest.
- **Channel precedence** in the shared `_param_value_kv`: `enum → value_raw → value_display →
  value_normalized → None`. `value_raw` beats `value_display` so an explicit raw wins even if a
  human-readable display hint is also stored (belt-and-suspenders; the report's "leave display
  empty" caution becomes unnecessary, and the DB row stays readable).
- **Capture/pull auto-emit rule** (single-source helper next to `normalize_param_value`):
  `param_needs_raw_channel(min, max, is_enum) := not is_enum and range is non-degenerate and
  (min != 0.0 or max != 1.0)`. `value_raw` is *always* correct for a continuous param (it's the
  exact probed `.value` dialed as raw), so this rule can never mis-dial; it only routes the
  lossless channel for non-`[0,1]` params (which already round-tripped wrongly via the
  normalized-as-raw path). Enum + constant-range excluded.
- **Discriminator decided by probing the live witness (not assumed).** I first planned to gate
  on `is_quantized`, then probed `LFO 1 S. Rate` on the running swell set:
  `is_enum=False, is_quantized=**False**, min 0, max 21, display "1/2"`. So `is_quantized` is the
  WRONG signal — it's False on the very param this fixes. The principled discriminator is **raw
  range ≠ [0,1]**: for any such non-enum param the normalized channel is pushed as raw (mis-dials)
  and the display may be non-monotonic, so raw is the only always-correct channel. This also
  means NO handler/wire-shape change is needed (no `is_quantized` to expose, no re-vendor).
- **Scope note — this redirects ALL non-`[0,1]` non-enum params to `value_raw`** (e.g. semitone
  transposes), not just the non-monotonic ones, because capture can't run the live setter's
  monotonicity test offline. Matches the report's own proposed scope ("max != 1"). It is the
  minimal *correct* rule (raw is lossless and always right); the prior normalized form for these
  params was a dead value masked by the display channel winning at push.

## The change (one cohesive chunk)

**C1 — `value_raw` channel end-to-end.** Files:

1. `db/schema.sql` — add `value_raw REAL` (no CHECK) to `device_parameters` AND
   `device_param_overrides` CREATE TABLEs.
2. `db/connection.py` `_ADDED_COLUMNS` — append `("device_parameters","value_raw","REAL")` and
   `("device_param_overrides","value_raw","REAL")` (schema-canary requires both paths to match).
3. `db/mutations/devices.py`:
   - `set_device_parameter`: new `value_raw: float | None = None` kwarg; store it; validate
     mutual exclusivity (`value_raw` XOR `value_normalized`; `value_raw` not with `value_items`;
     reject bool). INSERT/UPDATE column.
   - `replace_device_param_overrides`: accept `value_raw` per override; validate same; store;
     **add `value_raw` to the incoming tuple AND `existing_sig`** so the idempotent
     no-op-when-unchanged dedup still holds.
4. `sync/push/devices.py` `_param_value_kv`: new `value_raw` branch after enum, before display.
5. `capture.py`:
   - shared `param_needs_raw_channel(...)` helper (next to `normalize_param_value`).
   - `_param_value_fields`: accept `value_raw` snapshot key (require `value` XOR `value_raw`),
     return a 4-tuple `(value_display, value_normalized, value_items, value_raw)`; suppress the
     BUG4 bare-numeric warning when `value_raw` is the channel.
   - `_override_entry_for_replay` + `_replay_devices` params_dialed call (~L320): thread
     `value_raw` into the mutators.
   - `_snapshot_param_entry`: when `param_needs_raw_channel` fires, emit
     `{"value": <display hint>, "value_raw": <raw>}` (omit `normalized`); else unchanged.
6. `sync/pull/devices.py` `_apply_device_parameters_for_device`: same rule for top-level params —
   emit `value_raw` (not the broken normalized) for the affected class.
7. `docs/snapshot-schema.md` — document `value_raw` on `params_dialed` + `param_overrides`
   (when to use it, precedence); fix the misleading "use normalized" steer for this class.

## Tests (alongside, not after)

- **db mutations** (`tests/unit/db/test_mutations.py`, `test_param_overrides.py`): store/read
  `value_raw` unclamped (e.g. 8.0); exclusivity validation raises; dedup no-op holds when only
  `value_raw` is set (re-replace identical set → no event); idempotency multi-hop.
- **push** (`tests/unit/sync/test_push_devices.py`): a `value_raw` row → `set_parameter` with
  `{"value":"8.0","value_type":"continuous"}`; precedence (raw beats a populated display).
- **capture round-trip** (`tests/unit/capture/test_*`): `_snapshot_param_entry` emits `value_raw`
  for quantized [0,21]; stays unchanged for [0,1] and for enums; `_param_value_fields` accepts
  `{"value_raw":8.0}` (no `value`); full snapshot→replay→DB→push→re-capture round-trip identical.
- **pull** (`tests/unit/sync/test_pull.py`): a quantized non-unit param pulls to a `value_raw`
  row, not a clamped/wrong `value_normalized`.

## Done when

Full suite green (baseline 4037p/2s); round-trip test passes; `/prawduct:critic`
(chunk → cumulative) blocking-free; docs updated; backlog DEV-4P7R → shipped at merge.

## Status — BUILT (2026-06-17), branch `feat/param-overrides-value-raw`

- [x] **C1 — `value_raw` channel end-to-end.** Schema + additive migration (both tables),
  mutators (exclusivity + dedup), push branch (raw before display), capture authoring +
  generation (range-based auto-emit), pull (raw channel + relative-tolerance no-churn), docs.
- Tests: **4057 passed, 2 skipped** (+20 over baseline). Commits `407b752` (feature) +
  `e0b74e0` (Critic-fix). Backlog chore `a606ed7` on develop.
- **Independent Critic:** 1 BLOCKING (B1 — flatten dropped `value_raw` on the `/song-snapshot`
  nested-override path) + 1 WARNING (W1 — absolute-tolerance churn on large raw values), both
  FIXED; verify-resolutions pass = RESOLVED.
- **PENDING — Live operator-verification (not blocking the logic):** the true end-to-end proof
  (bake swell's `LFO 1 S. Rate` override as `value_raw` → `build.py --reset` rebuild → push →
  confirm "1/2" survives without saving the `.als`) needs the dev engine deployed to the running
  Live session (relaunch dev-mode + `/ableton-mcp-install`). The wire behavior (`set_parameter
  value=8.0` → "1/2") is already proven; the symbolic round-trip is covered by tests.
