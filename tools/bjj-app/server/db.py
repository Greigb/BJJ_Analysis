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
    vault_published_at INTEGER
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
    moment_id TEXT NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
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
"""


_ROLLS_M4_COLUMNS: tuple[tuple[str, str], ...] = (
    ("vault_path", "TEXT"),
    ("vault_your_notes_hash", "TEXT"),
    ("vault_published_at", "INTEGER"),
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


def init_db(db_path: Path) -> None:
    """Create the schema if it doesn't already exist. Safe to call every startup."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_rolls_m4(conn)
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
) -> sqlite3.Row:
    """Insert a roll row and return it. Callers pass an open connection."""
    conn.execute(
        """
        INSERT INTO rolls (
            id, title, date, video_path, duration_s, partner,
            result, scores_json, finalised_at, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
        """,
        (id, title, date, video_path, duration_s, partner, result, created_at),
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
    pose_delta (float or None). `selected_for_analysis` defaults to 0.
    Returns the newly inserted rows in insertion order.
    """
    conn.execute("DELETE FROM moments WHERE roll_id = ?", (roll_id,))
    inserted_ids: list[str] = []
    for m in moments:
        moment_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO moments (
                id, roll_id, frame_idx, timestamp_s, pose_delta, selected_for_analysis
            )
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                moment_id,
                roll_id,
                int(m["frame_idx"]),
                float(m["timestamp_s"]),
                None if m.get("pose_delta") is None else float(m["pose_delta"]),
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

    Each player dict must contain: player ('greig'|'anthony'), position_id (str),
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
    """Return all analyses for a moment. Order is stable: greig first, then anthony."""
    cur = conn.execute(
        """
        SELECT * FROM analyses
        WHERE moment_id = ?
        ORDER BY CASE player WHEN 'greig' THEN 0 ELSE 1 END, created_at
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
