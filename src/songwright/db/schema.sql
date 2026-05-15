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
    tempo           REAL,
    time_signature  TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS tracks (
    id                      TEXT PRIMARY KEY,
    song_id                 TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    track_index             INTEGER NOT NULL,
    name                    TEXT NOT NULL,
    instrument_uri          TEXT,
    UNIQUE(song_id, track_index)
);

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
