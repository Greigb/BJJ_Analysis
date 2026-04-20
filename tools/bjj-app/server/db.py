"""SQLite connection + schema initialisation.

Schema matches the spec at docs/superpowers/specs/2026-04-20-bjj-local-review-app-design.md.
M1 only initialises the schema — no reads/writes from/to these tables yet.
Later milestones populate them.
"""
from __future__ import annotations

import sqlite3
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
    created_at INTEGER NOT NULL
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


def init_db(db_path: Path) -> None:
    """Create the schema if it doesn't already exist. Safe to call every startup."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
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
    import uuid

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
