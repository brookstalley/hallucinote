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
    name            TEXT NOT NULL UNIQUE,
    key             TEXT,
    timing_mode     TEXT NOT NULL DEFAULT 'native'
                        CHECK (timing_mode IN ('native', 'grid')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
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
    kind                    TEXT NOT NULL DEFAULT 'midi'
                                CHECK (kind IN ('midi','audio','return','master','group')),
    -- Mixer state. Volume/pan use Live's normalized range (0.0–1.0) matching
    -- the captured_session.json convention; conversion to dB happens at the UI
    -- layer if needed. mute/solo/arm are 0/1 booleans. color is RGB int.
    volume                  REAL CHECK (volume IS NULL OR (volume >= 0.0 AND volume <= 1.0)),
    pan                     REAL CHECK (pan IS NULL OR (pan >= -1.0 AND pan <= 1.0)),
    mute                    INTEGER CHECK (mute IS NULL OR mute IN (0, 1)),
    solo                    INTEGER CHECK (solo IS NULL OR solo IN (0, 1)),
    arm                     INTEGER CHECK (arm IS NULL OR arm IN (0, 1)),
    color                   INTEGER,
    UNIQUE(song_id, track_index)
);
-- `kind` is the discriminator: 'midi' (default), 'audio', 'master', 'group',
-- and 'return' (reserved — returns currently live in the `returns` table for
-- their distinct shape). 'audio' and 'group' are valid in V1 but produce no
-- clip authoring; master tracks live here with `kind='master'` and are
-- special-cased in sync (Live's master is reached via the master strip, not
-- by track index).

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

CREATE TABLE IF NOT EXISTS arrangement (
    id                          TEXT PRIMARY KEY,
    song_id                     TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    track_id                    TEXT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    clip_id                     TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    start_bar                   REAL NOT NULL,
    end_bar                     REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_arrangement_song ON arrangement(song_id);
CREATE INDEX IF NOT EXISTS idx_arrangement_track ON arrangement(track_id);
CREATE INDEX IF NOT EXISTS idx_arrangement_clip ON arrangement(clip_id);

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
-- `(bar: int, beat: float)` for MCP at the boundary.
--
-- Section spans are half-open: `[start_bar, end_bar)`. A section running
-- bars 1..16 has start_bar=1, end_bar=16 (16 bars total — bars 1..15 are
-- inside; bar 16 is the next section's start).

CREATE TABLE IF NOT EXISTS sections (
    id              TEXT PRIMARY KEY,
    song_id         TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    start_bar       REAL NOT NULL,
    end_bar         REAL NOT NULL,
    color           INTEGER,
    notes_md        TEXT,
    CHECK (end_bar > start_bar)
);

CREATE INDEX IF NOT EXISTS idx_sections_song ON sections(song_id);

CREATE TABLE IF NOT EXISTS tempo_map (
    id              TEXT PRIMARY KEY,
    song_id         TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    start_bar       REAL NOT NULL,
    tempo_bpm       REAL NOT NULL CHECK (tempo_bpm > 0),
    ramp            TEXT NOT NULL DEFAULT 'hold'
                        CHECK (ramp IN ('linear', 'hold')),
    UNIQUE(song_id, start_bar)
);

CREATE INDEX IF NOT EXISTS idx_tempo_map_song ON tempo_map(song_id, start_bar);

CREATE TABLE IF NOT EXISTS time_signature_map (
    id              TEXT PRIMARY KEY,
    song_id         TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    start_bar       REAL NOT NULL,
    numerator       INTEGER NOT NULL CHECK (numerator > 0),
    denominator     INTEGER NOT NULL CHECK (denominator > 0),
    UNIQUE(song_id, start_bar)
);

CREATE INDEX IF NOT EXISTS idx_time_signature_map_song
    ON time_signature_map(song_id, start_bar);

CREATE TABLE IF NOT EXISTS cue_points (
    id              TEXT PRIMARY KEY,
    song_id         TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    position_bar    REAL NOT NULL,
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

CREATE TABLE IF NOT EXISTS sends (
    from_track_id   TEXT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    to_return_id    TEXT NOT NULL REFERENCES returns(id) ON DELETE CASCADE,
    level           REAL NOT NULL CHECK (level >= 0.0 AND level <= 1.0),
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

CREATE TABLE IF NOT EXISTS device_chains (
    id                      TEXT PRIMARY KEY,
    parent_track_id         TEXT REFERENCES tracks(id) ON DELETE CASCADE,
    parent_return_id        TEXT REFERENCES returns(id) ON DELETE CASCADE,
    parent_rack_device_id   TEXT REFERENCES devices(id) ON DELETE CASCADE,
    position                INTEGER NOT NULL DEFAULT 0,
    CHECK (
        (parent_track_id IS NOT NULL)
      + (parent_return_id IS NOT NULL)
      + (parent_rack_device_id IS NOT NULL) = 1
    )
);

CREATE INDEX IF NOT EXISTS idx_device_chains_track  ON device_chains(parent_track_id);
CREATE INDEX IF NOT EXISTS idx_device_chains_return ON device_chains(parent_return_id);
CREATE INDEX IF NOT EXISTS idx_device_chains_rack   ON device_chains(parent_rack_device_id);

-- Devices live in chains. `kind` is Live's class name (Compressor2, Eq8,
-- DrumGroupDevice, InstrumentGroupDevice, etc.) — the source of truth for
-- "what kind of device is this." `display_name` is the user-set name shown
-- in Live (often equal to kind, but a renamed preset like "Late Nite Kit"
-- keeps that string). `preset_uri` optional, for browser-reload paths.
-- `position` is 1-based to match the snapshot's `"index"` field everywhere.

CREATE TABLE IF NOT EXISTS devices (
    id              TEXT PRIMARY KEY,
    chain_id        TEXT NOT NULL REFERENCES device_chains(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    preset_uri      TEXT,
    UNIQUE(chain_id, position)
);

CREATE INDEX IF NOT EXISTS idx_devices_chain ON devices(chain_id);

-- Only *set* parameters are stored — defaults are implied by absence. This
-- matches the snapshot convention (a Compressor with 30 params lists only
-- the ~6 the user actually moved). `value_display` is the human-readable
-- form ("1.17 kHz" / "Lowpass" / "-7.0 dB"); `value_normalized` is the
-- 0.0–1.0 wire form. Discrete-enum params (Filter Type = "Lowpass") have
-- NULL `value_normalized` — there's no continuous form to write.

CREATE TABLE IF NOT EXISTS device_parameters (
    id                  TEXT PRIMARY KEY,
    device_id           TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    value_display       TEXT NOT NULL,
    value_normalized    REAL CHECK (value_normalized IS NULL
                                  OR (value_normalized >= 0.0 AND value_normalized <= 1.0)),
    UNIQUE(device_id, name)
);

CREATE INDEX IF NOT EXISTS idx_device_parameters_device ON device_parameters(device_id);

-- =============================================================================
-- Mix: automation envelopes + breakpoints
-- =============================================================================
-- Unified shape: one `envelopes` table covers seven target families and one
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
    song_id         TEXT REFERENCES songs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_requests_song ON requests(song_id);

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

CREATE TABLE IF NOT EXISTS events (
    id              TEXT PRIMARY KEY,
    seq             INTEGER NOT NULL UNIQUE,
    ts              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    kind            TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    song_id         TEXT REFERENCES songs(id) ON DELETE SET NULL,
    clip_id         TEXT REFERENCES clips(id) ON DELETE SET NULL,
    actor           TEXT NOT NULL,
    reason          TEXT,
    request_id      TEXT REFERENCES requests(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_events_seq ON events(seq);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
CREATE INDEX IF NOT EXISTS idx_events_song ON events(song_id);
CREATE INDEX IF NOT EXISTS idx_events_clip ON events(clip_id);
CREATE INDEX IF NOT EXISTS idx_events_request ON events(request_id);
