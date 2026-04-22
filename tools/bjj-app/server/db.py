"""SQLite connection + schema initialisation.

Schema matches the spec at docs/superpowers/specs/2026-04-20-bjj-local-review-app-design.md.
M1 only initialises the schema — no reads/writes from/to these tables yet.
Later milestones populate them.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rolls (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    date TEXT NOT NULL,
    video_path TEXT NOT NULL,
    duration_s REAL,
    partner TEXT,
    result TEXT,
    scores_json TEXT,
    finalised_at INTEGER,
    created_at INTEGER NOT NULL,
    vault_path TEXT,
    vault_your_notes_hash TEXT,
    vault_published_at INTEGER,
    player_a_name TEXT,
    player_b_name TEXT,
    vault_summary_hashes TEXT,
    player_a_description TEXT,
    player_b_description TEXT
);

CREATE TABLE IF NOT EXISTS moments (
    id TEXT PRIMARY KEY,
    roll_id TEXT NOT NULL REFERENCES rolls(id) ON DELETE CASCADE,
    frame_idx INTEGER NOT NULL,
    timestamp_s REAL NOT NULL,
    pose_delta REAL,
    selected_for_analysis INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    moment_id TEXT NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
    player TEXT NOT NULL,
    position_id TEXT NOT NULL,
    confidence REAL,
    description TEXT,
    coach_tip TEXT,
    claude_version TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS annotations (
    id TEXT PRIMARY KEY,
    section_id TEXT NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS claude_cache (
    prompt_hash TEXT,
    frame_hash TEXT,
    response_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (prompt_hash, frame_hash)
);

CREATE TABLE IF NOT EXISTS sections (
    id TEXT PRIMARY KEY,
    roll_id TEXT NOT NULL REFERENCES rolls(id) ON DELETE CASCADE,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    sample_interval_s REAL NOT NULL,
    created_at INTEGER NOT NULL,
    narrative TEXT,
    coach_tip TEXT,
    analysed_at INTEGER
);
"""


_ROLLS_M4_COLUMNS: tuple[tuple[str, str], ...] = (
    ("vault_path", "TEXT"),
    ("vault_your_notes_hash", "TEXT"),
    ("vault_published_at", "INTEGER"),
    ("player_a_name", "TEXT"),
    ("player_b_name", "TEXT"),
    ("vault_summary_hashes", "TEXT"),
)

_ROLLS_M9B2_COLUMNS: tuple[tuple[str, str], ...] = (
    ("player_a_description", "TEXT"),
    ("player_b_description", "TEXT"),
)


def _migrate_rolls_m4(conn: sqlite3.Connection) -> None:
    """Idempotently add M4 columns to an existing rolls table.

    Only needed for databases created before M4 — CREATE TABLE IF NOT EXISTS
    above handles fresh installs. SQLite has no ADD COLUMN IF NOT EXISTS,
    so we inspect PRAGMA table_info and ALTER only when missing.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(rolls)").fetchall()}
    for name, sql_type in _ROLLS_M4_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE rolls ADD COLUMN {name} {sql_type}")


def _migrate_rolls_player_descriptions(conn: sqlite3.Connection) -> None:
    """Idempotently add player_a_description / player_b_description to rolls.

    Freeform text; used to feed Claude a visual-identification hint so the same
    player is consistently tagged player_a across frames (e.g. "navy gi, bald,
    bottom at the start of this roll").
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(rolls)").fetchall()}
    for name, sql_type in _ROLLS_M9B2_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE rolls ADD COLUMN {name} {sql_type}")


def _migrate_analyses_player_enum(conn: sqlite3.Connection) -> None:
    """One-time value migration: rename analyses.player 'greig'→'a', 'anthony'→'b'.

    Idempotent: subsequent calls are no-ops because no rows match the old values.
    """
    conn.execute("UPDATE analyses SET player = 'a' WHERE player = 'greig'")
    conn.execute("UPDATE analyses SET player = 'b' WHERE player = 'anthony'")


def _backfill_default_player_names(conn: sqlite3.Connection) -> None:
    """Default any pre-migration roll to Player A/Player B for the display labels.

    Also rewrites the old hardcoded "Greig"/"Anthony" defaults (seeded by an
    earlier migration) so no user-visible text depends on specific names.
    Idempotent.
    """
    conn.execute(
        "UPDATE rolls SET player_a_name = 'Player A' "
        "WHERE player_a_name IS NULL OR player_a_name = 'Greig'"
    )
    conn.execute(
        "UPDATE rolls SET player_b_name = 'Player B' "
        "WHERE player_b_name IS NULL OR player_b_name = 'Anthony'"
    )


def _migrate_moments_m9(conn: sqlite3.Connection) -> None:
    """Idempotently add M9 fields to moments + create the unique index.

    - Adds `section_id` column if missing.
    - Creates `idx_moments_roll_frame` UNIQUE on (roll_id, frame_idx) if missing.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(moments)").fetchall()}
    if "section_id" not in existing:
        conn.execute(
            "ALTER TABLE moments ADD COLUMN section_id TEXT "
            "REFERENCES sections(id) ON DELETE SET NULL"
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "idx_moments_roll_frame ON moments(roll_id, frame_idx)"
    )


_SECTIONS_M9B_COLUMNS: tuple[tuple[str, str], ...] = (
    ("narrative",   "TEXT"),
    ("coach_tip",   "TEXT"),
    ("analysed_at", "INTEGER"),
)


def _migrate_sections_m9b(conn: sqlite3.Connection) -> None:
    """Idempotently add M9b columns to an existing sections table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(sections)").fetchall()}
    for name, sql_type in _SECTIONS_M9B_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE sections ADD COLUMN {name} {sql_type}")


def _migrate_annotations_m9b(conn: sqlite3.Connection) -> None:
    """Rebuild annotations with section_id FK if still on moment_id FK.

    SQLite can't ALTER FK in place — recreate the table. Pre-M9b rows are
    smoke-test-only, so the migration discards them (spec decision).
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(annotations)").fetchall()}
    if "section_id" in cols and "moment_id" not in cols:
        return  # already migrated
    conn.execute("DROP TABLE IF EXISTS annotations")
    conn.execute(
        "CREATE TABLE annotations ("
        "  id TEXT PRIMARY KEY, "
        "  section_id TEXT NOT NULL REFERENCES sections(id) ON DELETE CASCADE, "
        "  body TEXT NOT NULL, "
        "  created_at INTEGER NOT NULL, "
        "  updated_at INTEGER NOT NULL"
        ")"
    )


def init_db(db_path: Path) -> None:
    """Create the schema if it doesn't already exist. Safe to call every startup."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_rolls_m4(conn)
        _backfill_default_player_names(conn)
        _migrate_analyses_player_enum(conn)
        _migrate_moments_m9(conn)
        _migrate_sections_m9b(conn)
        _migrate_annotations_m9b(conn)
        _migrate_rolls_player_descriptions(conn)
        conn.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with foreign-key enforcement enabled."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def create_roll(
    conn,
    *,
    id: str,
    title: str,
    date: str,
    video_path: str,
    duration_s: float | None,
    partner: str | None,
    result: str,
    created_at: int,
    player_a_name: str = "Player A",
    player_b_name: str = "Player B",
    player_a_description: str | None = None,
    player_b_description: str | None = None,
) -> sqlite3.Row:
    """Insert a roll row and return it. Callers pass an open connection."""
    conn.execute(
        """
        INSERT INTO rolls (
            id, title, date, video_path, duration_s, partner,
            result, scores_json, finalised_at, created_at,
            player_a_name, player_b_name,
            player_a_description, player_b_description
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?)
        """,
        (id, title, date, video_path, duration_s, partner, result, created_at,
         player_a_name, player_b_name,
         player_a_description, player_b_description),
    )
    conn.commit()
    return get_roll(conn, id)  # type: ignore[return-value]


def get_roll(conn, roll_id: str) -> sqlite3.Row | None:
    """Return the roll row, or None if not found."""
    cur = conn.execute("SELECT * FROM rolls WHERE id = ?", (roll_id,))
    return cur.fetchone()


def insert_moments(
    conn,
    *,
    roll_id: str,
    moments: list[dict],
) -> list[sqlite3.Row]:
    """Replace all moments for `roll_id` with the supplied list.

    Each moment dict must contain: frame_idx (int), timestamp_s (float),
    pose_delta (float or None), and may include section_id (str or None).
    Returns the newly inserted rows in insertion order.
    """
    conn.execute("DELETE FROM moments WHERE roll_id = ?", (roll_id,))
    inserted_ids: list[str] = []
    for m in moments:
        moment_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO moments (
                id, roll_id, frame_idx, timestamp_s, pose_delta,
                selected_for_analysis, section_id
            )
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (
                moment_id,
                roll_id,
                int(m["frame_idx"]),
                float(m["timestamp_s"]),
                None if m.get("pose_delta") is None else float(m["pose_delta"]),
                m.get("section_id"),
            ),
        )
        inserted_ids.append(moment_id)
    conn.commit()

    if not inserted_ids:
        return []

    cur = conn.execute(
        f"SELECT * FROM moments WHERE id IN ({','.join('?' * len(inserted_ids))})",
        inserted_ids,
    )
    rows_by_id = {r["id"]: r for r in cur.fetchall()}
    return [rows_by_id[i] for i in inserted_ids]


def append_moments(
    conn,
    *,
    roll_id: str,
    moments: list[dict],
) -> list[sqlite3.Row]:
    """Append moments to a roll without deleting prior rows (append semantics).

    Each moment dict must contain: frame_idx (int), timestamp_s (float),
    pose_delta (float or None), and may include section_id (str or None).
    Returns the newly inserted rows in insertion order.

    Use this instead of insert_moments when prior moments must be preserved
    (e.g. the M9b per-section pipeline where each section is a separate call).
    """
    inserted_ids: list[str] = []
    for m in moments:
        moment_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO moments (
                id, roll_id, frame_idx, timestamp_s, pose_delta,
                selected_for_analysis, section_id
            )
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (
                moment_id,
                roll_id,
                int(m["frame_idx"]),
                float(m["timestamp_s"]),
                None if m.get("pose_delta") is None else float(m["pose_delta"]),
                m.get("section_id"),
            ),
        )
        inserted_ids.append(moment_id)
    conn.commit()

    if not inserted_ids:
        return []

    cur = conn.execute(
        f"SELECT * FROM moments WHERE id IN ({','.join('?' * len(inserted_ids))})",
        inserted_ids,
    )
    rows_by_id = {r["id"]: r for r in cur.fetchall()}
    return [rows_by_id[i] for i in inserted_ids]


def get_moments(conn, roll_id: str) -> list[sqlite3.Row]:
    """Return all moments for a roll in timestamp order."""
    cur = conn.execute(
        "SELECT * FROM moments WHERE roll_id = ? ORDER BY timestamp_s",
        (roll_id,),
    )
    return list(cur.fetchall())


def cache_get(conn, *, prompt_hash: str, frame_hash: str) -> dict | None:
    """Return the cached Claude response for this (prompt, frame) pair, or None."""
    cur = conn.execute(
        "SELECT response_json FROM claude_cache WHERE prompt_hash = ? AND frame_hash = ?",
        (prompt_hash, frame_hash),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return json.loads(row["response_json"])


def cache_put(
    conn,
    *,
    prompt_hash: str,
    frame_hash: str,
    response: dict,
) -> None:
    """Upsert a cached response. Re-putting on the same key replaces the value."""
    conn.execute(
        """
        INSERT INTO claude_cache (prompt_hash, frame_hash, response_json, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(prompt_hash, frame_hash) DO UPDATE SET
            response_json = excluded.response_json,
            created_at    = excluded.created_at
        """,
        (prompt_hash, frame_hash, json.dumps(response), int(time.time())),
    )
    conn.commit()


def insert_analyses(
    conn,
    *,
    moment_id: str,
    players: list[dict],
    claude_version: str,
) -> list[sqlite3.Row]:
    """Replace all analyses for `moment_id` with one row per entry in `players`.

    Each player dict must contain: player ('a'|'b'), position_id (str),
    confidence (float | None), description (str | None), coach_tip (str | None).
    """
    conn.execute("DELETE FROM analyses WHERE moment_id = ?", (moment_id,))
    inserted_ids: list[str] = []
    now = int(time.time())
    for p in players:
        analysis_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO analyses (
                id, moment_id, player, position_id, confidence,
                description, coach_tip, claude_version, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis_id,
                moment_id,
                p["player"],
                p["position_id"],
                None if p.get("confidence") is None else float(p["confidence"]),
                p.get("description"),
                p.get("coach_tip"),
                claude_version,
                now,
            ),
        )
        inserted_ids.append(analysis_id)
    conn.commit()

    if not inserted_ids:
        return []
    cur = conn.execute(
        f"SELECT * FROM analyses WHERE id IN ({','.join('?' * len(inserted_ids))})",
        inserted_ids,
    )
    rows_by_id = {r["id"]: r for r in cur.fetchall()}
    return [rows_by_id[i] for i in inserted_ids]


def get_analyses(conn, moment_id: str) -> list[sqlite3.Row]:
    """Return all analyses for a moment. Order is stable: player_a first, then player_b."""
    cur = conn.execute(
        """
        SELECT * FROM analyses
        WHERE moment_id = ?
        ORDER BY CASE player WHEN 'a' THEN 0 ELSE 1 END, created_at
        """,
        (moment_id,),
    )
    return list(cur.fetchall())


def set_vault_state(
    conn,
    *,
    roll_id: str,
    vault_path: str,
    vault_your_notes_hash: str,
    vault_published_at: int,
) -> None:
    """Record the outcome of a successful publish on the roll row."""
    conn.execute(
        """
        UPDATE rolls
           SET vault_path = ?,
               vault_your_notes_hash = ?,
               vault_published_at = ?
         WHERE id = ?
        """,
        (vault_path, vault_your_notes_hash, vault_published_at, roll_id),
    )
    conn.commit()


def get_vault_state(conn, roll_id: str) -> dict | None:
    """Return the roll's vault_path/hash/published_at, or None if the roll doesn't exist."""
    cur = conn.execute(
        "SELECT vault_path, vault_your_notes_hash, vault_published_at FROM rolls WHERE id = ?",
        (roll_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {
        "vault_path": row["vault_path"],
        "vault_your_notes_hash": row["vault_your_notes_hash"],
        "vault_published_at": row["vault_published_at"],
    }


def insert_annotation(
    conn,
    *,
    section_id: str,
    body: str,
    created_at: int,
) -> sqlite3.Row:
    """Append a new annotation to a section. Returns the inserted row."""
    annotation_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO annotations (id, section_id, body, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (annotation_id, section_id, body, created_at, created_at),
    )
    conn.commit()
    cur = conn.execute("SELECT * FROM annotations WHERE id = ?", (annotation_id,))
    return cur.fetchone()


def get_annotations_by_section(conn, section_id: str) -> list[sqlite3.Row]:
    """Return all annotations for a section ordered by created_at ascending."""
    cur = conn.execute(
        "SELECT * FROM annotations WHERE section_id = ? ORDER BY created_at",
        (section_id,),
    )
    return list(cur.fetchall())


def get_annotations_by_roll(conn, roll_id: str) -> list[sqlite3.Row]:
    """Return all annotations for a roll, joined with their section's time range.

    Ordered for vault rendering: by section start_s ascending, then by
    created_at ascending within each section.
    Each row carries: id, section_id, body, created_at, updated_at, start_s, end_s.
    """
    cur = conn.execute(
        """
        SELECT a.id, a.section_id, a.body, a.created_at, a.updated_at,
               s.start_s, s.end_s
          FROM annotations a
          JOIN sections s ON s.id = a.section_id
         WHERE s.roll_id = ?
         ORDER BY s.start_s ASC, a.created_at ASC
        """,
        (roll_id,),
    )
    return list(cur.fetchall())


def set_summary_state(
    conn,
    *,
    roll_id: str,
    scores_payload: dict,
    finalised_at: int,
) -> None:
    """Write the parsed summary payload + finalised_at to the rolls row."""
    conn.execute(
        "UPDATE rolls SET scores_json = ?, finalised_at = ? WHERE id = ?",
        (json.dumps(scores_payload), finalised_at, roll_id),
    )
    conn.commit()


def set_vault_summary_hashes(
    conn,
    *,
    roll_id: str,
    hashes: dict | None,
) -> None:
    """Record per-section hash dict for the summary-owned vault sections.

    Pass None to clear (e.g. for a roll that's been un-finalised — currently no
    code path does this, but the helper accepts it for completeness).
    """
    value = json.dumps(hashes) if hashes is not None else None
    conn.execute(
        "UPDATE rolls SET vault_summary_hashes = ? WHERE id = ?",
        (value, roll_id),
    )
    conn.commit()


def insert_section(
    conn,
    *,
    roll_id: str,
    start_s: float,
    end_s: float,
    sample_interval_s: float,
) -> sqlite3.Row:
    """Insert one section. Returns the full row."""
    section_id = uuid.uuid4().hex
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO sections (
            id, roll_id, start_s, end_s, sample_interval_s, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (section_id, roll_id, float(start_s), float(end_s), float(sample_interval_s), now),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM sections WHERE id = ?", (section_id,)
    ).fetchone()
    return row


def get_sections_by_roll(conn, roll_id: str) -> list[sqlite3.Row]:
    """Return all sections for a roll, ordered by start_s ascending."""
    cur = conn.execute(
        "SELECT * FROM sections WHERE roll_id = ? ORDER BY start_s ASC, created_at ASC",
        (roll_id,),
    )
    return cur.fetchall()


def delete_section_and_moments(conn, *, section_id: str, frames_dir: Path) -> None:
    """Delete a section, all its moments, and their frame files on disk.

    `frames_dir` is the directory that holds `frame_NNNNNN.jpg` files for the roll.
    Missing files are tolerated silently (never leave a DB delete blocked on a
    missing disk file).
    """
    rows = conn.execute(
        "SELECT frame_idx FROM moments WHERE section_id = ?", (section_id,)
    ).fetchall()
    conn.execute("DELETE FROM moments WHERE section_id = ?", (section_id,))
    conn.execute("DELETE FROM sections WHERE id = ?", (section_id,))
    conn.commit()
    for row in rows:
        path = frames_dir / f"frame_{int(row['frame_idx']):06d}.jpg"
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def update_section_analysis(
    conn,
    *,
    section_id: str,
    narrative: str,
    coach_tip: str,
    analysed_at: int,
) -> None:
    """Write Claude's per-section narrative + coach_tip + completion timestamp."""
    conn.execute(
        "UPDATE sections "
        "   SET narrative = ?, coach_tip = ?, analysed_at = ? "
        " WHERE id = ?",
        (narrative, coach_tip, analysed_at, section_id),
    )
    conn.commit()
