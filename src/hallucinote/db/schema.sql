PRAGMA foreign_keys = ON;

-- =============================================================================
-- Identity model
-- =============================================================================
-- All primary keys are TEXT (UUIDv4 hex, 32 chars), generated in Python by
-- mutations._uuid(). UUIDs let cross-DB merges and event-stream replay be
-- well-defined: an id is the same id everywhere it appears, regardless of
-- which DB created it. The integer `events.seq` provides a local human-
-- readable ordering that is regenerated on import.

CREATE TABLE IF NOT EXISTS songs (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE
                        CHECK (length(name) > 0
                               AND name NOT GLOB '*[^a-z0-9_-]*'),
    title           TEXT,
    key             TEXT,
    timing_mode     TEXT NOT NULL DEFAULT 'native'
                        CHECK (timing_mode IN ('native', 'grid')),
    -- MICROTUNE (TUN-4Q7W): alternate-tuning bolt-on. Both NULL = 12-TET (every
    -- existing + future song's default, the 99.99%) — the core path reads neither.
    -- `tuning_ref` is the song-relative POSIX path to the cached, re-draggable
    -- `.ascl` (songs/<slug>/tunings/<name>.ascl); `tuning_data` is the derived
    -- JSON blob {name, step_count, period_cents, reference_note, step_cents} the
    -- mapper / writer / drift-verify read (no `.ascl` parser ships). Set together
    -- by `set_song_tuning`; see hallucinote.tuning.
    tuning_ref      TEXT,
    tuning_data     TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
-- `name` is the song *slug* — filesystem-safe identifier matching the song's
-- directory and DB filename: `songs/<name>/<name>.db`. Lowercase letters,
-- digits, hyphens, and underscores only; no spaces or special characters.
-- This is a prescriptive convention; see `.prawduct/artifacts/project-preferences.md`.
-- `title` is the optional human-facing display name (free-form text). Tools
-- that show song identity to users should prefer `title` when set, falling
-- back to `name`.
-- Tempo and time signature are no longer scalar columns; see tempo_map and
-- time_signature_map for the multi-point automation that supplants them.
-- `timing_mode='grid'` opts the song into pure-grid (polytempic) encoding
-- where generators handle resolved positions internally.

CREATE TABLE IF NOT EXISTS tracks (
    id                      TEXT PRIMARY KEY,
    song_id                 TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    track_index             INTEGER NOT NULL,
    name                    TEXT NOT NULL,
    instrument_uri          TEXT,
    -- 'return' was reserved historically but real returns live in the
    -- `returns` table; the reservation was structurally dead code (no
    -- code path created it, push/pull both skipped it). Dropped V1
    -- close-out — misuse now surfaces as an integrity error.
    kind                    TEXT NOT NULL DEFAULT 'midi'
                                CHECK (kind IN ('midi','audio','master','group')),
    -- Mixer state. Volume/pan use Live's normalized range (0.0–1.0) matching
    -- the captured_session.json convention; conversion to dB happens at the UI
    -- layer if needed. mute/solo/arm are 0/1 booleans. color is RGB int.
    volume                  REAL CHECK (volume IS NULL OR (volume >= 0.0 AND volume <= 1.0)),
    pan                     REAL CHECK (pan IS NULL OR (pan >= -1.0 AND pan <= 1.0)),
    mute                    INTEGER CHECK (mute IS NULL OR mute IN (0, 1)),
    solo                    INTEGER CHECK (solo IS NULL OR solo IN (0, 1)),
    arm                     INTEGER CHECK (arm IS NULL OR arm IN (0, 1)),
    color                   INTEGER,
    -- RTE-1K9T: track signal routing (output + input) + monitor switch.
    -- Single-valued per track (1:1) -> columns, not a side table (D4),
    -- matching mixer-state-as-columns. The routing TARGET is a SEMANTIC
    -- reference, never Live's display_name: *_routing_kind says WHAT the
    -- target is and *_routing_target_id FKs the destination track when
    -- kind='track' (the submaster bus) -- so it survives renames + re-pushes.
    -- Push resolves the FK -> Live display_name; pull maps display_name back.
    -- ON DELETE SET NULL: deleting a routed-to bus leaves a detectable
    -- dangling state (kind='track', target_id=NULL) push treats as "target
    -- gone", never a cascade-delete of the routing track itself.
    --
    -- CHECK asymmetry (D6): output_routing_kind + monitoring_state are CHECK-
    -- constrained (closed, live-probed-certain domains); input_routing_kind is
    -- NOT (input's domain is open/hardware-bound -- MIDI ports, interface
    -- channels -- and a wrong CHECK is a destructive SQLite migration). The
    -- mutator (set_track_routing) validates input_routing_kind in Python and
    -- owns the cross-field invariant (target_id present <=> kind='track'),
    -- which a column-level CHECK can't express.
    output_routing_kind     TEXT CHECK (output_routing_kind IS NULL OR
                                output_routing_kind IN ('master','track','sends_only','ext_out')),
    output_routing_target_id TEXT REFERENCES tracks(id) ON DELETE SET NULL,
    output_routing_channel  TEXT,
    input_routing_kind      TEXT,
    input_routing_target_id TEXT REFERENCES tracks(id) ON DELETE SET NULL,
    input_routing_channel   TEXT,
    monitoring_state        TEXT CHECK (monitoring_state IS NULL OR
                                monitoring_state IN ('In','Auto','Off')),
    UNIQUE(song_id, track_index)
);
-- `kind` is the discriminator: 'midi' (default), 'audio', 'master', 'group'.
-- Real returns live in the `returns` table (for their distinct shape); the
-- legacy `'return'` reservation on this table was dropped V1 close-out
-- 2026-05-17. 'audio' and 'group' are valid but produce no clip authoring;
-- master tracks live here with `kind='master'` and are special-cased in
-- sync (Live's master is reached via the master strip, not by track index).

CREATE INDEX IF NOT EXISTS idx_tracks_song ON tracks(song_id);

CREATE TABLE IF NOT EXISTS clips (
    id                      TEXT PRIMARY KEY,
    track_id                TEXT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    slot                    INTEGER NOT NULL,
    length_beats            REAL NOT NULL,
    name                    TEXT,
    section_role            TEXT,
    generator_call_json     TEXT,
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- CLP-AUD1 (AUD-1M4V stage 0a): `kind` discriminates 'midi' (default —
    -- every pre-column row is already valid) from 'audio'. Column-level
    -- CHECKs stay minimal by design (SQLite ALTER limits); the cross-field
    -- invariants live in the mutators, dual-layer with the kind-guards:
    -- kind='audio' requires audio_file + an audio host track; kind='midi'
    -- leaves every audio column NULL. `length_beats` stays the authored
    -- placement length for both kinds, never derived audio duration.
    kind                    TEXT NOT NULL DEFAULT 'midi',
    -- Song-relative POSIX path (canonically under assets/), or absolute —
    -- stored exactly as authored, resolved at push/analysis time.
    audio_file              TEXT,
    -- Live clip gain, 0.0-1.0 LINEAR (not dB) -- LOM value domain.
    audio_gain              REAL,
    -- Transpose: semitones (-48..+48) / cents (-50.0..+50.0) -- LOM domains;
    -- mutators validate (see mutations.clips._validate_audio_fields).
    pitch_coarse            INTEGER,
    pitch_fine              REAL,
    warping                 INTEGER,
    -- Live's warp-mode enum int; named constants in mutations.clips.WARP_MODES.
    warp_mode               INTEGER,
    -- Live's dual marker unit: BEATS when warping=1, SECONDS when warping=0.
    -- Consumers must read `warping` before interpreting the markers.
    start_marker            REAL,
    end_marker              REAL,
    -- AUD-7R3M: ONE immutable audio_file, played reversed when set
    -- (NULL/0 = forward, 1 = reversed).
    -- NOT MATERIALIZED AT PUSH. A Live
    -- Clip exposes no settable reverse at all — absent from the 12.4.1
    -- LomTypes gate table AND from a live `describe` of a real audio clip on
    -- 12.4.5 (docs/research/audio-first-class/lom-probe-results.md row 14) —
    -- so the wire carries no `reverse` and the clips phase refuses a row that
    -- sets it rather than silently pushing a clip that plays forward. The
    -- column stays because the INTENT is real; it materializes only as a
    -- reversed DERIVED ASSET — a clip pointed at the reversed file, or a
    -- sampler whose sample is the reversed file. Simpler has no Reverse
    -- parameter either: its reverse() is a destructive method that writes a
    -- derived file (row 19), so the derived asset is the whole story (#237).
    reverse                 INTEGER,
    UNIQUE(track_id, slot)
);

CREATE INDEX IF NOT EXISTS idx_clips_track ON clips(track_id);

CREATE TABLE IF NOT EXISTS notes (
    id                  TEXT PRIMARY KEY,
    clip_id             TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    pitch               INTEGER NOT NULL CHECK (pitch BETWEEN 0 AND 127),
    start_beats         REAL NOT NULL CHECK (start_beats >= 0),
    duration_beats      REAL NOT NULL CHECK (duration_beats > 0),
    velocity            INTEGER NOT NULL CHECK (velocity BETWEEN 0 AND 127),
    mute                INTEGER NOT NULL DEFAULT 0 CHECK (mute IN (0, 1)),
    tags_json           TEXT
);

CREATE INDEX IF NOT EXISTS idx_notes_clip ON notes(clip_id);
CREATE INDEX IF NOT EXISTS idx_notes_clip_start ON notes(clip_id, start_beats);

CREATE TABLE IF NOT EXISTS arrangement_clips (
    id                          TEXT PRIMARY KEY,
    song_id                     TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    track_id                    TEXT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    clip_id                     TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    start_bar                   REAL NOT NULL CHECK (start_bar >= 1.0),
    end_bar                     REAL NOT NULL,
    CHECK (end_bar > start_bar)
);

CREATE INDEX IF NOT EXISTS idx_arrangement_clips_song ON arrangement_clips(song_id);
CREATE INDEX IF NOT EXISTS idx_arrangement_clips_track ON arrangement_clips(track_id);
CREATE INDEX IF NOT EXISTS idx_arrangement_clips_clip ON arrangement_clips(clip_id);

-- =============================================================================
-- Score: sections, tempo map, time-signature map, cue points
-- =============================================================================
-- These four tables round out the Score half so songs can express sectional
-- structure, tempo / meter changes, and arrangement markers. All four are
-- song-scoped and cascade-deleted with the song.
--
-- Bar positions are REAL and 1-based across the codebase (matching Live's
-- MCP tools — see docs/mcp-requirements.md). The first bar of a song is
-- `bar = 1.0`. The sync layer splits fractional bar positions into
-- `(bar: int, beat: float)` for MCP at the boundary. The 1-based invariant
-- is enforced at the schema layer via per-table CHECK constraints below
-- (J-6) and at the sync boundary by `sync.push._split_bar`.
--
-- Section spans are half-open: `[start_bar, end_bar)`. A 16-bar section
-- starting at bar 1 has start_bar=1, end_bar=17 — bars 1..16 inclusive
-- are inside; bar 17 is the next section's start.

CREATE TABLE IF NOT EXISTS sections (
    id              TEXT PRIMARY KEY,
    song_id         TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    start_bar       REAL NOT NULL CHECK (start_bar >= 1.0),
    end_bar         REAL NOT NULL,
    color           INTEGER,
    notes_md        TEXT,
    -- Authored per-section energy intent (0..1 ordinal; ARR-7M3D). NULL when
    -- the section was authored without declaring energy (the DB-only path, or
    -- a pre-column DB migrated in). The energy-realization lens reads non-NULL
    -- rows to rank declared intent against measured per-section intensity;
    -- NULL rows are excluded from the correlation, never coerced to a value.
    energy          REAL CHECK (energy IS NULL OR (energy >= 0.0 AND energy <= 1.0)),
    CHECK (end_bar > start_bar)
);

CREATE INDEX IF NOT EXISTS idx_sections_song ON sections(song_id);

CREATE TABLE IF NOT EXISTS tempo_map (
    id              TEXT PRIMARY KEY,
    song_id         TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    start_bar       REAL NOT NULL CHECK (start_bar >= 1.0),
    tempo_bpm       REAL NOT NULL CHECK (tempo_bpm > 0),
    ramp            TEXT NOT NULL DEFAULT 'hold'
                        CHECK (ramp IN ('linear', 'hold')),
    UNIQUE(song_id, start_bar)
);

CREATE INDEX IF NOT EXISTS idx_tempo_map_song ON tempo_map(song_id, start_bar);

CREATE TABLE IF NOT EXISTS time_signature_map (
    id              TEXT PRIMARY KEY,
    song_id         TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    start_bar       REAL NOT NULL CHECK (start_bar >= 1.0),
    numerator       INTEGER NOT NULL CHECK (numerator > 0),
    denominator     INTEGER NOT NULL CHECK (denominator > 0),
    UNIQUE(song_id, start_bar)
);

CREATE INDEX IF NOT EXISTS idx_time_signature_map_song
    ON time_signature_map(song_id, start_bar);

CREATE TABLE IF NOT EXISTS cue_points (
    id              TEXT PRIMARY KEY,
    song_id         TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    position_bar    REAL NOT NULL CHECK (position_bar >= 1.0),
    name            TEXT,
    color           INTEGER
);

CREATE INDEX IF NOT EXISTS idx_cue_points_song ON cue_points(song_id, position_bar);

-- =============================================================================
-- Mix: returns + sends
-- =============================================================================
-- Returns are functionally distinct from main tracks (no slots, no instrument,
-- target of sends from every audible track) and get their own table. Master is
-- modeled as a `tracks` row with `kind='master'`; only returns are split out.
-- Volume/pan match the same normalized 0.0–1.0 / -1.0–1.0 ranges as tracks.

CREATE TABLE IF NOT EXISTS returns (
    id              TEXT PRIMARY KEY,
    song_id         TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    position        INTEGER NOT NULL,
    volume          REAL CHECK (volume IS NULL OR (volume >= 0.0 AND volume <= 1.0)),
    pan             REAL CHECK (pan IS NULL OR (pan >= -1.0 AND pan <= 1.0)),
    -- mute/solo: nullable bool (matches tracks.mute/solo/arm + returns.volume/pan).
    -- Nullable means "user never set this" -> planner skips emission; once set,
    -- 0/1 round-trip via update_return + _apply_return_info. Migration note:
    -- existing song DBs need `build.py --reset` to pick up these columns
    -- (single-user local context; songs are regenerable). See M+1-4.
    mute            INTEGER CHECK (mute IS NULL OR mute IN (0, 1)),
    solo            INTEGER CHECK (solo IS NULL OR solo IN (0, 1)),
    color           INTEGER,
    UNIQUE(song_id, position)
);

CREATE INDEX IF NOT EXISTS idx_returns_song ON returns(song_id, position);

-- Sends are the (track -> return) connection points carrying the send level.
-- Composite PK enforces one send per (from_track, to_return); changing the
-- level is an upsert. Level is normalized 0.0–1.0 to match track volume.
--
-- Cross-song integrity (track.song_id == return.song_id) is enforced *only* in
-- `mutations.set_send_level`. The FKs guarantee both endpoints exist, not that
-- they belong to the same song. Raw-SQL inserts that bypass mutators would
-- silently corrupt the model — keep the mutator discipline tight.

-- `intended_rt60_s` carries the composer's RT60 intent for a send whose target
-- return is reverb-shaped. NULL when the send isn't reverb-intent (delays,
-- parallel-comp, post-FX bus, undeclared). Audio-analysis `verify_reverb_send`
-- reads non-NULL rows to build the comparison set. Positive when set.
CREATE TABLE IF NOT EXISTS sends (
    from_track_id   TEXT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    to_return_id    TEXT NOT NULL REFERENCES returns(id) ON DELETE CASCADE,
    level           REAL NOT NULL CHECK (level >= 0.0 AND level <= 1.0),
    intended_rt60_s REAL CHECK (intended_rt60_s IS NULL OR intended_rt60_s > 0.0),
    PRIMARY KEY (from_track_id, to_return_id)
);

CREATE INDEX IF NOT EXISTS idx_sends_return ON sends(to_return_id);

-- =============================================================================
-- Mix: device chains, devices, parameters
-- =============================================================================
-- Live's device model: each track/return/master carries a top-level device
-- chain; rack devices (DrumGroupDevice, InstrumentGroupDevice, etc.) own one
-- or more nested chains. We mirror that shape:
--
--   tracks/returns/master ─┐
--                          ├─► device_chains ─► devices ─┐
--                          │   (position=0 for top-level)│
--                          │                             │
--                          └─◄────── (rack devices) ◄────┘
--
-- `device_chains.parent_*` uses three nullable FKs with a CHECK that exactly
-- one is set. Trade-off: query helpers must check the right column, BUT we
-- get free FK enforcement + ON DELETE CASCADE for all three parent kinds.
-- The alternative (generic `parent_kind`+`parent_id` polymorphic columns)
-- would have required mutator-level cascade discipline and broken the
-- chunk-1 invariant that deleting a track cascades to everything it owns.

-- NODE-ADDR Chunk C: per-DrumChain authorship. `choke_group` (0 = none) and
-- `out_note` (MIDI transpose target) live on a DrumChain only (a plain
-- instrument-rack Chain has neither). Both nullable: NULL on every non-drum
-- chain and on drum chains whose value is the Live default (choke 0 /
-- out_note == in_note) — capture stores only non-defaults, push emits only
-- stored (mirrors the Chunk B param filter). Authored via the `chain` terminal.
-- NODE-ADDR Chunk F: per-chain mixer state — `mute`/`solo` (Chain bools, 0/1)
-- and `volume`/`pan` (the ChainMixerDevice's volume/panning DeviceParameter
-- values). Unlike choke/out_note these exist on EVERY chain (plain + drum), not
-- just DrumChains. Same non-default discipline: NULL = the chain's Live/preset
-- default (unmuted/unsoloed, unity volume, centre pan). Chain SENDS (into the
-- rack's own return chains) are a distinct, rarely-populated surface — left as a
-- documented NOT_IMPLEMENTED cell (`send_levels`/chain), not a column here.
CREATE TABLE IF NOT EXISTS device_chains (
    id                      TEXT PRIMARY KEY,
    parent_track_id         TEXT REFERENCES tracks(id) ON DELETE CASCADE,
    parent_return_id        TEXT REFERENCES returns(id) ON DELETE CASCADE,
    parent_rack_device_id   TEXT REFERENCES devices(id) ON DELETE CASCADE,
    position                INTEGER NOT NULL DEFAULT 0,
    choke_group             INTEGER,
    out_note                INTEGER,
    mute                    INTEGER,
    solo                    INTEGER,
    volume                  REAL,
    pan                     REAL,
    CHECK (
        (parent_track_id IS NOT NULL)
      + (parent_return_id IS NOT NULL)
      + (parent_rack_device_id IS NOT NULL) = 1
    )
);

CREATE INDEX IF NOT EXISTS idx_device_chains_track  ON device_chains(parent_track_id);
CREATE INDEX IF NOT EXISTS idx_device_chains_return ON device_chains(parent_return_id);
CREATE INDEX IF NOT EXISTS idx_device_chains_rack   ON device_chains(parent_rack_device_id);

-- Devices live in chains. Arc 4 / D4 convention: `kind` is the BROWSER
-- DISPLAY NAME (= Live's `device.class_display_name`), what the loader's
-- kind-as-given walk matches against in Live's browser tree
-- ("Compressor", "Phaser-Flanger", "EQ Eight", "Operator"). `class_name`
-- (added column) is Live's INTERNAL class identifier ("Compressor2",
-- "PhaserNew", "Eq8", "PluginDevice") — informational + drives plugin
-- discrimination. `display_name` is the user-visible instance label
-- which often equals `kind` for default-loaded built-ins but diverges
-- on preset loads ("Hall" on a Hybrid Reverb) and user renames
-- ("Bass Squish" on a Compressor). `preset_uri` optional.
--
-- Pre-D4 (capture against old conventions): `kind` held the internal
-- class. Re-pull / re-capture rewrites both fields cleanly.
--
-- `position` is 1-based to match the snapshot's `"index"` field everywhere.

CREATE TABLE IF NOT EXISTS devices (
    id              TEXT PRIMARY KEY,
    chain_id        TEXT NOT NULL REFERENCES device_chains(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,
    -- Arc 4 / D4: `kind` is the browser DISPLAY NAME (= Live's
    -- `device.class_display_name`): "Compressor", "Phaser-Flanger",
    -- "EQ Eight", "Operator". The loader's kind-as-given walk matches
    -- against this directly in Live's browser tree.
    kind            TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    -- Arc 4 / D4: Live's INTERNAL class identifier ("Compressor2",
    -- "PhaserNew", "PluginDevice"). Informational + drives plugin
    -- classification (compat-check reads this to detect third-party
    -- plugins). Captured-from-Live writes populate it; hand-authored
    -- snapshots may omit it.
    class_name      TEXT,
    preset_uri      TEXT,
    -- Sweep B: compose-time portable preset selector. JSON-serialized
    -- {root, pattern, mode?, path_prefix?, case_sensitive?}. Resolved at
    -- push time by ableton_device(action='load', preset_query=...) on the
    -- consumer's machine — bypasses per-machine FileId in preset_uri so
    -- snapshots transfer cross-machine.
    preset_query    TEXT,
    -- Arc 7-tail / E3 (W13-A v1.0): resolved browser path from the root
    -- to the loaded item, as a JSON array of strings (e.g.
    -- ["instruments", "Operator", "Bass", "Sub Bass"]). Captured at load
    -- time when the loader walks the browser to find the BrowserItem.
    -- NULL when the device pre-dates E3 capture or was created without
    -- a browser walk. The push planner's fallback resolver scopes
    -- ableton_browser(action='search') by path[0] (root) + path[1:-1]
    -- (path_prefix) so vendor / pack identity discriminates cross-
    -- machine plugin loads when the per-machine FileId in preset_uri
    -- doesn't resolve.
    browser_path_json TEXT,
    -- SMP-7K2D: sample-instrument assignment. When this device is a sampler
    -- (Simpler/Sampler/...), the song-relative POSIX path (canonically under
    -- assets/) or absolute path of its assigned sample — stored exactly as
    -- authored, resolved at push via paths.resolve_audio_path (the SAME
    -- resolver clips.audio_file uses). NULL for every non-sampler device
    -- (mirrors how clips.audio_file is NULL for MIDI clips). Window / reverse /
    -- pitch / gain are NOT columns here — they are device_parameters (static)
    -- or device_parameter envelopes (automated). See
    -- .prawduct/artifacts/plans/SMP-7K2D/archive/design.md.
    audio_file      TEXT,
    -- SDC-7K3M: device sidechain SOURCE routing, symmetric with track-level
    -- input routing (tracks.input_routing_*). A SEMANTIC reference (FK to the
    -- source track, survives renames) — push resolves it to Live's display_name
    -- via set_input_routing, pull captures it via get_input_routing. NULL when
    -- the device has no sidechain source. The S/C On / Gain / Mix params
    -- round-trip separately as device_parameters; this column is the one piece
    -- those can't carry (the source). `channel` is Live's input channel
    -- display_name (Pre FX / Post FX / Post Mixer), NULL = device default.
    sidechain_source_track_id TEXT REFERENCES tracks(id) ON DELETE SET NULL,
    sidechain_source_channel  TEXT,
    UNIQUE(chain_id, position)
);

CREATE INDEX IF NOT EXISTS idx_devices_chain ON devices(chain_id);

-- Only *set* parameters are stored — defaults are implied by absence. This
-- matches the snapshot convention (a Compressor with 30 params lists only
-- the ~6 the user actually moved). `value_display` is the human-readable
-- form ("1.17 kHz" / "Lowpass" / "-7.0 dB"); `value_normalized` is the
-- 0.0–1.0 wire form. Discrete-enum params (Filter Type = "Lowpass") have
-- NULL `value_normalized` — there's no continuous form to write.
--
-- `value_items_json` carries the enum cardinality for discrete-enum params —
-- a JSON array of display names in Live's `value_items` order (the index
-- in that array IS the numeric value Live stores). NULL for continuous
-- params. Captured at pull time from `ableton_device(action='get_parameters',
-- detail='full')`. Used by the enum-aware envelope helper to resolve
-- compose-time enum-name breakpoints into numeric values without forcing
-- the build.py author to hand-list the cardinality on every call.

CREATE TABLE IF NOT EXISTS device_parameters (
    id                  TEXT PRIMARY KEY,
    device_id           TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    value_display       TEXT NOT NULL,
    value_normalized    REAL CHECK (value_normalized IS NULL
                                  OR (value_normalized >= 0.0 AND value_normalized <= 1.0)),
    value_items_json    TEXT,
    -- DEV-4P7R: the raw continuous channel. Live's own param.value, UNCLAMPED
    -- (no [0,1] CHECK) — the only authorable form for a quantized continuous
    -- param whose raw range != [0,1] and whose display is non-monotonic (e.g.
    -- Wavetable LFO S. Rate, raw 8.0 -> "1/2", range [0,21]). Pushed via
    -- set_parameter's raw `value`. NULL for params on the display / normalized /
    -- enum channels. Mutually exclusive with value_normalized + value_items_json
    -- (enforced by set_device_parameter).
    value_raw           REAL,
    UNIQUE(device_id, name)
);

CREATE INDEX IF NOT EXISTS idx_device_parameters_device ON device_parameters(device_id);

-- M1-C: Drum Rack pad-mapping discovery.
--
-- Each row is one non-empty pad on a loaded Drum Rack: which MIDI note
-- triggers which chain (and therefore which sound). Captured by
-- `tools/capture_cli.py` via `ableton_device(action='pad_info', ...)`
-- after the Drum Rack is loaded.
--
-- Stored VERBATIM from Live (chain_name is Live's chain.name as-is, e.g.
-- "Kick Drum" / "Snare Top" / "Closed Hat" / "BD Big") — canonicalization
-- to ("kick" / "snare" / "hat_closed") happens at read time in the Kit
-- class via fuzzy substring match. Storing canonical names on the way IN
-- would lose information if the canonicalization rules change.
--
-- A drum pad triggers exactly one MIDI note (Live's Drum Rack UI maps
-- one note per pad slot), so UNIQUE(device_id, midi_note) holds.
-- Multiple chain_names sharing the same canonical bucket ("Kick 1" +
-- "Kick 2" both → "kick") are fine — the Kit class picks the first match.

CREATE TABLE IF NOT EXISTS drum_pad_mappings (
    id                  TEXT PRIMARY KEY,
    device_id           TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    chain_name          TEXT NOT NULL,
    midi_note           INTEGER NOT NULL CHECK (midi_note >= 0 AND midi_note <= 127),
    UNIQUE(device_id, midi_note)
);

CREATE INDEX IF NOT EXISTS idx_drum_pad_mappings_device ON drum_pad_mappings(device_id);

-- SNP-2H9F: nested-param overrides on a `preset_query` (or `preset_uri`) device.
--
-- A device loaded from a portable preset has only its TOP-LEVEL row in the DB —
-- the preset instantiates the whole nested tree at push time, so there is no
-- nested `devices` row to hang a `device_parameters` row on. A by-ear tweak deep
-- inside such a rack (e.g. a Wavetable LFO sync two levels down) therefore had no
-- durable home: dumping the full `chains` tree to capture it drops the preset's
-- un-parameterizable timbre (the Wavetable waveform is not a DeviceParameter) and
-- bloats the snapshot. This table is that home: each row is one override applied
-- to a descendant of the preset device, keyed by the descent `path` (NodeAddr,
-- relative to the preset device) + the parameter `name`.
--
-- `path_json` is a JSON array of `{chain_index, device_position}` steps (1-based,
-- DEEP-RACK-ADDR), e.g. `[{"chain_index":1,"device_position":1},
-- {"chain_index":1,"device_position":1}]`. Mirrors `device_parameters`' value
-- columns (value_display always set; value_normalized for continuous params;
-- value_items_json for enums). Push re-asserts each override via a node-addressed
-- `set_parameter` after the preset loads — no `create_device_chain`, so nothing
-- duplicates and the preset waveform/samples survive (SNP-2H9F).
--
-- Replace-style: capture/replay/pull store the full non-default override set per
-- device atomically (one DEVICE_PARAM_OVERRIDES_REPLACED event), like
-- drum_pad_mappings. New tables auto-migrate onto existing song DBs via init_db's
-- CREATE TABLE IF NOT EXISTS (no _ADDED_COLUMNS entry — that is for new columns).

CREATE TABLE IF NOT EXISTS device_param_overrides (
    id                  TEXT PRIMARY KEY,
    device_id           TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    path_json           TEXT NOT NULL,
    name                TEXT NOT NULL,
    value_display       TEXT NOT NULL,
    value_normalized    REAL CHECK (value_normalized IS NULL
                                  OR (value_normalized >= 0.0 AND value_normalized <= 1.0)),
    value_items_json    TEXT,
    -- DEV-4P7R: raw continuous channel (see device_parameters.value_raw). The
    -- whole point of param_overrides is a preset device's nested params, so the
    -- quantized-non-unit-range class bites hardest here.
    value_raw           REAL,
    UNIQUE(device_id, path_json, name)
);

CREATE INDEX IF NOT EXISTS idx_device_param_overrides_device ON device_param_overrides(device_id);

-- =============================================================================
-- Mix: automation envelopes + breakpoints
-- =============================================================================
-- Unified shape: one `envelopes` table covers nine target families and one
-- `automation_breakpoints` table carries the (time, value) timeline. The same
-- breakpoint shape works for a clip-CC ramp, a pitch-bend curve, an MPE
-- expression on a single note, a device parameter sweep, a mixer fade, or a
-- send-level ramp.
--
-- target_kind discriminates the target family; the polymorphic FK columns
-- below carry the actual target identity. CASE-based CHECK enforces that the
-- right column is set for each kind (and no others). ON DELETE CASCADE on
-- every target FK so that deleting a clip / note / device / track / return
-- collapses any envelopes that referenced it.
--
-- target_kind => target columns + parameter_path semantics
--   clip_cc           target_clip_id;   parameter_path = CC number string ("64")
--   clip_pitch_bend   target_clip_id;   parameter_path NULL
--   note_expression   target_note_id;   parameter_path = MPE axis ("pitch","pressure","timbre")
--   device_parameter  target_device_id; parameter_path = parameter name ("Threshold")
--   mixer_volume      target_track_id;  parameter_path NULL
--   mixer_pan         target_track_id;  parameter_path NULL
--   send_level        target_track_id + target_send_return_id; parameter_path NULL
--   return_mixer_volume  target_send_return_id; parameter_path NULL (ENV-7G4K:
--   return_mixer_pan     a return track's OWN mixer — performed at push time)
--
-- Pointing device_parameter envelopes at `devices.id` (with the parameter
-- name in `parameter_path`) rather than at `device_parameters.id` lets an
-- envelope exist for a parameter that has no static dialed value — automation
-- can be the parameter's only state. Mutators map kind → expected columns.

CREATE TABLE IF NOT EXISTS envelopes (
    id                      TEXT PRIMARY KEY,
    song_id                 TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    target_kind             TEXT NOT NULL,
    target_clip_id          TEXT REFERENCES clips(id) ON DELETE CASCADE,
    target_note_id          TEXT REFERENCES notes(id) ON DELETE CASCADE,
    target_device_id        TEXT REFERENCES devices(id) ON DELETE CASCADE,
    target_track_id         TEXT REFERENCES tracks(id) ON DELETE CASCADE,
    target_send_return_id   TEXT REFERENCES returns(id) ON DELETE CASCADE,
    parameter_path          TEXT,
    CHECK (
        CASE target_kind
            WHEN 'clip_cc' THEN
                target_clip_id IS NOT NULL
                AND target_note_id IS NULL
                AND target_device_id IS NULL
                AND target_track_id IS NULL
                AND target_send_return_id IS NULL
                AND parameter_path IS NOT NULL
            WHEN 'clip_pitch_bend' THEN
                target_clip_id IS NOT NULL
                AND target_note_id IS NULL
                AND target_device_id IS NULL
                AND target_track_id IS NULL
                AND target_send_return_id IS NULL
            WHEN 'note_expression' THEN
                target_note_id IS NOT NULL
                AND target_clip_id IS NULL
                AND target_device_id IS NULL
                AND target_track_id IS NULL
                AND target_send_return_id IS NULL
                AND parameter_path IS NOT NULL
            WHEN 'device_parameter' THEN
                target_device_id IS NOT NULL
                AND target_clip_id IS NULL
                AND target_note_id IS NULL
                AND target_track_id IS NULL
                AND target_send_return_id IS NULL
                AND parameter_path IS NOT NULL
            WHEN 'mixer_volume' THEN
                target_track_id IS NOT NULL
                AND target_clip_id IS NULL
                AND target_note_id IS NULL
                AND target_device_id IS NULL
                AND target_send_return_id IS NULL
            WHEN 'mixer_pan' THEN
                target_track_id IS NOT NULL
                AND target_clip_id IS NULL
                AND target_note_id IS NULL
                AND target_device_id IS NULL
                AND target_send_return_id IS NULL
            WHEN 'send_level' THEN
                target_track_id IS NOT NULL
                AND target_send_return_id IS NOT NULL
                AND target_clip_id IS NULL
                AND target_note_id IS NULL
                AND target_device_id IS NULL
            WHEN 'return_mixer_volume' THEN
                target_send_return_id IS NOT NULL
                AND target_clip_id IS NULL
                AND target_note_id IS NULL
                AND target_device_id IS NULL
                AND target_track_id IS NULL
            WHEN 'return_mixer_pan' THEN
                target_send_return_id IS NOT NULL
                AND target_clip_id IS NULL
                AND target_note_id IS NULL
                AND target_device_id IS NULL
                AND target_track_id IS NULL
            ELSE 0
        END
    )
);

CREATE INDEX IF NOT EXISTS idx_envelopes_song   ON envelopes(song_id);
CREATE INDEX IF NOT EXISTS idx_envelopes_clip   ON envelopes(target_clip_id);
CREATE INDEX IF NOT EXISTS idx_envelopes_note   ON envelopes(target_note_id);
CREATE INDEX IF NOT EXISTS idx_envelopes_device ON envelopes(target_device_id);
CREATE INDEX IF NOT EXISTS idx_envelopes_track  ON envelopes(target_track_id);

-- Breakpoints describe the envelope's value over time. `time_beats` is in
-- clip-local beats for clip-/note-scoped envelopes and arrangement-local
-- beats for mixer/send/device envelopes (the planner does the conversion at
-- push time per target_kind). `value` is unconstrained at the schema level —
-- ranges vary by target_kind (0..127 for CC, -1..1 for pitch bend, 0..1 for
-- mixer/device, etc.) so the planner / generator validates per kind.
--
-- curve_kind matches Live's segment curve options. 'linear' is the default
-- (straight ramp to the next breakpoint); 'hold' freezes value until the
-- next breakpoint; 'fast' / 'slow' are exponential curves.

CREATE TABLE IF NOT EXISTS automation_breakpoints (
    id              TEXT PRIMARY KEY,
    envelope_id     TEXT NOT NULL REFERENCES envelopes(id) ON DELETE CASCADE,
    time_beats      REAL NOT NULL CHECK (time_beats >= 0.0),
    value           REAL NOT NULL,
    curve_kind      TEXT NOT NULL DEFAULT 'linear'
                        CHECK (curve_kind IN ('linear','hold','fast','slow'))
);

CREATE INDEX IF NOT EXISTS idx_automation_breakpoints_env
    ON automation_breakpoints(envelope_id, time_beats);

-- Performed-automation state (ENV-7G4K). Master/group/return-side envelopes
-- can't ride session clips; push *performs* them into Live's arrangement
-- automation via gesture recording (write-only — no LOM read surface, so
-- there is nothing to diff against Live). The fingerprint is the honesty
-- mechanism: push re-performs an arc only when the authored fingerprint
-- (target addressing + parameter_path + ordered breakpoint list) differs
-- from the one recorded at the last successful perform. Keyed per
-- (envelope, session): a song bound to multiple Live sets carries one
-- fingerprint per set, so pushing to a fresh session performs every arc
-- there instead of false-skipping on another set's record. The table is
-- disposable with the DB — a `build.py --reset` re-performs everything,
-- which is slower but never wrong.

CREATE TABLE IF NOT EXISTS performed_automation (
    id            TEXT PRIMARY KEY,
    envelope_id   TEXT NOT NULL REFERENCES envelopes(id) ON DELETE CASCADE,
    session_id    TEXT NOT NULL REFERENCES ableton_sessions(id) ON DELETE CASCADE,
    fingerprint   TEXT NOT NULL,
    performed_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(envelope_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_performed_automation_session
    ON performed_automation(session_id);

-- Cross-song reuse. Start optional; promote Python constants to rows when >1 song uses them.
CREATE TABLE IF NOT EXISTS kits (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,
    definition_json     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preset_chains (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,
    kind                TEXT NOT NULL,
    definition_json     TEXT NOT NULL
);

-- =============================================================================
-- Higher-level intent: requests
-- =============================================================================
-- A request groups one or more events under a user/LLM intent. Mutators take a
-- request_id kwarg so the audit trail can answer "what did this prompt do?"

CREATE TABLE IF NOT EXISTS requests (
    id              TEXT PRIMARY KEY,
    ts              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    actor           TEXT NOT NULL,
    intent          TEXT NOT NULL,
    payload_json    TEXT,
    song_id         TEXT REFERENCES songs(id) ON DELETE SET NULL,
    -- W8-B: cycle metadata. Populated at create_request time + closed by
    -- M.close_request. `kind` discriminates compose / push / pull /
    -- capture / mutate. `duration_ms` and `outcome` (success / failure /
    -- aborted) close out the cycle.
    kind            TEXT,
    duration_ms     INTEGER,
    outcome         TEXT,
    -- Arc 2 / B3: provenance rationale fields. `prompt_text` carries the
    -- verbatim seed prompt. `parent_id` self-FKs so an MCP auto-`mutate`
    -- request chains to its enclosing `compose` parent (degraded but
    -- always-present provenance). `metadata_json` is a bag of contextual
    -- signals — {model, git_sha, branch, session_id, hostname, ...}.
    prompt_text     TEXT,
    parent_id       TEXT REFERENCES requests(id) ON DELETE SET NULL,
    metadata_json   TEXT
);

CREATE INDEX IF NOT EXISTS idx_requests_song ON requests(song_id);

-- =============================================================================
-- Song metadata layer: markdown_refs + FTS5 index
-- =============================================================================
-- Composer intent + decision rationale live in atomic markdown files under
-- `songs/<name>/decisions/`, `songs/<name>/annotations/`, and the attempt
-- ledger `songs/<name>/attempts/` (kind: attempt — try → outcome → correction,
-- incl. reverted dead ends; ATL-7K3M). Markdown is the
-- source of truth (git-tracked, LLM-native to read); this table is a
-- rebuildable projection that makes the corpus queryable from SQL, with FTS5
-- for prose + tag search. Body text is owned by FTS5; this table carries the
-- queryable metadata.
--
-- See `.prawduct/artifacts/song-conventions.md` for the full frontmatter
-- schema and directory convention. The reindex helper
-- (`tools/reindex_markdown.py` / `markdown_refs.reindex_corpus`) walks the
-- corpus and upserts rows here; rows whose file vanished get tombstoned
-- (`tombstoned_at` non-null) instead of being deleted, so event-side payload
-- paths remain resolvable for historical queries.
--
-- Reindex bypasses the mutator-emits-event discipline by design: it is a
-- projection rebuild from disk, not a domain mutation. The audit-side
-- "this LLM-driven write produced this file" event (MARKDOWN_REF_RECORDED)
-- lives in the W8-B mutator surface; reindex is purely the read-side index.

CREATE TABLE IF NOT EXISTS markdown_refs (
    path                TEXT PRIMARY KEY,
    kind                TEXT NOT NULL
                            CHECK (kind IN ('decision', 'annotation', 'structural-fact', 'attempt')),
    scope               TEXT NOT NULL
                            CHECK (scope IN ('song', 'time', 'track', 'track-time')),
    song_id             TEXT REFERENCES songs(id) ON DELETE SET NULL,
    track_id            TEXT REFERENCES tracks(id) ON DELETE SET NULL,
    bars_json           TEXT,           -- '[start, end]' or '[start]' when scope ∈ {time, track-time}
    tags_json           TEXT,           -- '[str, ...]'
    related_json        TEXT,           -- '[path, ...]'  cross-links to other refs
    -- Attempt-ledger fields (kind: attempt only; NULL on every other kind).
    -- `outcome` = did the move achieve its goal; `resolution` = what we did with
    -- it (superseded pairs with a related_json link to the successor attempt).
    outcome             TEXT CHECK (outcome IS NULL OR outcome IN ('worked', 'partial', 'failed')),
    resolution          TEXT CHECK (resolution IS NULL OR resolution IN ('kept', 'reverted', 'superseded')),
    frontmatter_date    TEXT,           -- ISO 'YYYY-MM-DD' (required for decisions)
    content_hash        TEXT NOT NULL,  -- SHA-256 hex digest of file content (change detection)
    indexed_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    tombstoned_at       TEXT            -- non-null when the file is no longer on disk
);

CREATE INDEX IF NOT EXISTS idx_markdown_refs_song  ON markdown_refs(song_id);
CREATE INDEX IF NOT EXISTS idx_markdown_refs_track ON markdown_refs(track_id);
CREATE INDEX IF NOT EXISTS idx_markdown_refs_kind  ON markdown_refs(kind);

-- FTS5 index over prose body + tag string. Owns its own content (regular FTS5
-- mode — the marginal storage cost is trivial at corpus size, and avoids
-- external-content sync ceremony). `path` is a stored-but-unindexed column so
-- callers can JOIN back to markdown_refs without a rowid coordination dance.
-- Reindex pattern: DELETE WHERE path=? + INSERT (idempotent per-file refresh).
CREATE VIRTUAL TABLE IF NOT EXISTS markdown_refs_fts USING fts5(
    body,
    tags,
    path UNINDEXED,
    tokenize = 'porter unicode61'
);

-- =============================================================================
-- Ableton projection: sessions + links
-- =============================================================================
-- Ableton bindings live OUT of the core rows. A song can be bound to multiple
-- sessions (different Live sets, snapshots, forks); push/pull always operate
-- through a session. Removing the bindings is a session delete, not a core-row
-- change — fork/share stays clean.

CREATE TABLE IF NOT EXISTS ableton_sessions (
    id              TEXT PRIMARY KEY,
    song_id         TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    name            TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_ableton_sessions_song ON ableton_sessions(song_id);

CREATE TABLE IF NOT EXISTS ableton_links (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES ableton_sessions(id) ON DELETE CASCADE,
    db_kind         TEXT NOT NULL,
    db_id           TEXT NOT NULL,
    ableton_index   INTEGER NOT NULL,
    UNIQUE(session_id, db_kind, db_id)
);

CREATE INDEX IF NOT EXISTS idx_ableton_links_session ON ableton_links(session_id);

-- =============================================================================
-- Audit log: events
-- =============================================================================
-- Append-only. Seed for the eventual event-sourcing flip. Every mutator emits
-- exactly one row in the same transaction as its state change.
--
-- id   = UUID hex (canonical identity, stable across DBs)
-- seq  = local monotonic order, regenerated on import (human-readable index)
-- actor / reason / request_id = provenance for the change
--
-- EVT-6H9R: song_id / clip_id / request_id carry STABLE IDs, not live FKs.
-- An append-only audit log must not lose lineage to a cascade — the original
-- ON DELETE SET NULL references meant deleting a clip nulled clip_id on every
-- event that ever touched it. The ids here may dangle (the referenced row can
-- be deleted later); that is the point. Legacy DBs are migrated by
-- `connection._migrate_events_drop_fks` (table-recreate; SQLite can't ALTER
-- an FK away).

CREATE TABLE IF NOT EXISTS events (
    id              TEXT PRIMARY KEY,
    seq             INTEGER NOT NULL UNIQUE,
    ts              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    kind            TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    song_id         TEXT,           -- stable id, no FK (see EVT-6H9R note above)
    clip_id         TEXT,           -- stable id, no FK
    actor           TEXT NOT NULL,
    reason          TEXT,
    request_id      TEXT            -- stable id, no FK
);

CREATE INDEX IF NOT EXISTS idx_events_seq ON events(seq);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
CREATE INDEX IF NOT EXISTS idx_events_song ON events(song_id);
CREATE INDEX IF NOT EXISTS idx_events_clip ON events(clip_id);
CREATE INDEX IF NOT EXISTS idx_events_request ON events(request_id);
