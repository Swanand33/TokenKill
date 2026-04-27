from __future__ import annotations

from pathlib import Path
from typing import Optional

import aiosqlite

from tokenkill.models import CostEvent, Provider, Session, TokenUsage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    started_at TEXT NOT NULL,
    last_activity TEXT NOT NULL,
    total_cost_usd REAL DEFAULT 0.0,
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    event_count INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cost_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    tool_name TEXT,
    file_path TEXT,
    request_hash TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_events_session ON cost_events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON cost_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_hash ON cost_events(request_hash);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(str(self._path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    def _require_conn(self) -> aiosqlite.Connection:
        if not self._conn:
            raise RuntimeError("Database not connected — call connect() first")
        return self._conn

    async def upsert_session(self, session: Session) -> None:
        conn = self._require_conn()
        await conn.execute(
            """
            INSERT INTO sessions (id, project, started_at, last_activity,
                total_cost_usd, total_input_tokens, total_output_tokens, event_count, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                last_activity = excluded.last_activity,
                total_cost_usd = excluded.total_cost_usd,
                total_input_tokens = excluded.total_input_tokens,
                total_output_tokens = excluded.total_output_tokens,
                event_count = excluded.event_count,
                is_active = excluded.is_active
            """,
            (
                session.id,
                session.project,
                session.started_at.isoformat(),
                session.last_activity.isoformat(),
                session.total_cost_usd,
                session.total_input_tokens,
                session.total_output_tokens,
                session.event_count,
                1 if session.is_active else 0,
            ),
        )
        await conn.commit()

    async def insert_event(self, event: CostEvent) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            """
            INSERT INTO cost_events
                (session_id, timestamp, provider, model,
                 input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
                 cost_usd, tool_name, file_path, request_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.session_id,
                event.timestamp.isoformat(),
                event.provider.value,
                event.model,
                event.usage.input_tokens,
                event.usage.output_tokens,
                event.usage.cache_creation_tokens,
                event.usage.cache_read_tokens,
                event.cost_usd,
                event.tool_name,
                event.file_path,
                event.request_hash,
            ),
        )
        await conn.commit()
        return cursor.lastrowid or 0

    async def get_session(self, session_id: str) -> Optional[Session]:
        conn = self._require_conn()
        async with conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return _row_to_session(row)

    async def get_recent_sessions(self, limit: int = 20) -> list[Session]:
        conn = self._require_conn()
        rows = []
        async with conn.execute(
            "SELECT * FROM sessions ORDER BY last_activity DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_session(r) for r in rows]

    async def get_events_for_session(self, session_id: str) -> list[CostEvent]:
        conn = self._require_conn()
        rows = []
        async with conn.execute(
            "SELECT * FROM cost_events WHERE session_id = ? ORDER BY timestamp ASC",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_event(r) for r in rows]

    async def get_recent_hashes(self, session_id: str, limit: int = 50) -> list[str]:
        conn = self._require_conn()
        async with conn.execute(
            """SELECT request_hash FROM cost_events
               WHERE session_id = ? AND request_hash IS NOT NULL
               ORDER BY timestamp DESC LIMIT ?""",
            (session_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_file_read_count(
        self, session_id: str, file_path: str, within_minutes: int = 10
    ) -> int:
        conn = self._require_conn()
        async with conn.execute(
            """SELECT COUNT(*) FROM cost_events
               WHERE session_id = ? AND file_path = ?
               AND timestamp >= datetime('now', ? || ' minutes')""",
            (session_id, file_path, f"-{within_minutes}"),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_project_cost(self, project: str) -> float:
        conn = self._require_conn()
        async with conn.execute(
            "SELECT COALESCE(SUM(total_cost_usd), 0.0) FROM sessions WHERE project = ?",
            (project,),
        ) as cursor:
            row = await cursor.fetchone()
        return float(row[0]) if row else 0.0


def _row_to_session(row: aiosqlite.Row) -> Session:
    from datetime import datetime

    return Session(
        id=row["id"],
        project=row["project"],
        started_at=datetime.fromisoformat(row["started_at"]),
        last_activity=datetime.fromisoformat(row["last_activity"]),
        total_cost_usd=row["total_cost_usd"],
        total_input_tokens=row["total_input_tokens"],
        total_output_tokens=row["total_output_tokens"],
        event_count=row["event_count"],
        is_active=bool(row["is_active"]),
    )


def _row_to_event(row: aiosqlite.Row) -> CostEvent:
    from datetime import datetime

    return CostEvent(
        id=row["id"],
        session_id=row["session_id"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        provider=Provider(row["provider"]),
        model=row["model"],
        usage=TokenUsage(
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            cache_creation_tokens=row["cache_creation_tokens"],
            cache_read_tokens=row["cache_read_tokens"],
        ),
        cost_usd=row["cost_usd"],
        tool_name=row["tool_name"],
        file_path=row["file_path"],
        request_hash=row["request_hash"],
    )
