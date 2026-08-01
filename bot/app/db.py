from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import aiosqlite


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = await aiosqlite.connect(self.path)
        connection.row_factory = aiosqlite.Row

        try:
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.execute("PRAGMA foreign_keys=ON")
            await connection.execute("PRAGMA busy_timeout=5000")
            yield connection
        finally:
            await connection.close()

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        async with self.connect() as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS referral_clicks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    campaign TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS promo_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    reward TEXT NOT NULL,
                    source TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS promo_votes (
                    promo_id INTEGER NOT NULL,
                    telegram_id INTEGER NOT NULL,
                    vote INTEGER NOT NULL CHECK(vote IN (-1, 1)),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (promo_id, telegram_id),
                    FOREIGN KEY (promo_id) REFERENCES promo_codes(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS source_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_url TEXT NOT NULL,
                    item_uid TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_url, item_uid)
                );

                CREATE TABLE IF NOT EXISTS content_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    item_uid TEXT NOT NULL,
                    title TEXT NOT NULL,
                    link TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    UNIQUE(source_url, item_uid)
                );

                CREATE TABLE IF NOT EXISTS page_snapshots (
                    url TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS radar_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    drafts_created INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS radar_source_status (
                    source_key TEXT PRIMARY KEY,
                    source_url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_started_at TEXT,
                    last_success_at TEXT,
                    last_error_at TEXT,
                    last_error TEXT,
                    last_items_count INTEGER NOT NULL DEFAULT 0,
                    last_duration_ms INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            await db.commit()

    async def upsert_user(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
    ) -> None:
        now = utc_now()

        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO users(
                    telegram_id, username, first_name, created_at, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    last_seen_at=excluded.last_seen_at
                """,
                (telegram_id, username, first_name, now, now),
            )
            await db.commit()

    async def log_referral_click(
        self,
        telegram_id: int,
        campaign: str,
    ) -> None:
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO referral_clicks(
                    telegram_id, campaign, created_at
                )
                VALUES (?, ?, ?)
                """,
                (telegram_id, campaign, utc_now()),
            )
            await db.commit()

    async def add_promo(
        self,
        code: str,
        reward: str,
        source: str,
    ) -> int:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                INSERT INTO promo_codes(code, reward, source, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    reward=excluded.reward,
                    source=excluded.source,
                    is_active=1
                RETURNING id
                """,
                (code.upper(), reward, source, utc_now()),
            )
            row = await cursor.fetchone()
            await db.commit()

            if row is None:
                raise RuntimeError("Не удалось сохранить промокод")

            return int(row["id"])

    async def list_active_promos(
        self,
        limit: int = 10,
    ) -> list[aiosqlite.Row]:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT
                    p.id,
                    p.code,
                    p.reward,
                    p.source,
                    COALESCE(
                        SUM(CASE WHEN v.vote = 1 THEN 1 ELSE 0 END),
                        0
                    ) AS works,
                    COALESCE(
                        SUM(CASE WHEN v.vote = -1 THEN 1 ELSE 0 END),
                        0
                    ) AS fails
                FROM promo_codes p
                LEFT JOIN promo_votes v ON v.promo_id = p.id
                WHERE p.is_active = 1
                GROUP BY p.id
                ORDER BY p.id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return list(await cursor.fetchall())

    async def vote_promo(
        self,
        promo_id: int,
        telegram_id: int,
        vote: int,
    ) -> None:
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO promo_votes(
                    promo_id, telegram_id, vote, created_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(promo_id, telegram_id) DO UPDATE SET
                    vote=excluded.vote,
                    created_at=excluded.created_at
                """,
                (promo_id, telegram_id, vote, utc_now()),
            )
            await db.commit()

    async def has_source_items(self, source_url: str) -> bool:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT 1
                FROM source_items
                WHERE source_url = ?
                LIMIT 1
                """,
                (source_url,),
            )
            return await cursor.fetchone() is not None

    async def source_item_exists(
        self,
        source_url: str,
        item_uid: str,
    ) -> bool:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT 1
                FROM source_items
                WHERE source_url = ? AND item_uid = ?
                """,
                (source_url, item_uid),
            )
            return await cursor.fetchone() is not None

    async def save_source_item(
        self,
        source_url: str,
        item_uid: str,
    ) -> None:
        async with self.connect() as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO source_items(
                    source_url, item_uid, created_at
                )
                VALUES (?, ?, ?)
                """,
                (source_url, item_uid, utc_now()),
            )
            await db.commit()

    async def create_draft(
        self,
        kind: str,
        source_url: str,
        item_uid: str,
        title: str,
        link: str,
        summary: str,
    ) -> int | None:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO content_drafts(
                    kind,
                    source_url,
                    item_uid,
                    title,
                    link,
                    summary,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    source_url,
                    item_uid,
                    title,
                    link,
                    summary,
                    utc_now(),
                ),
            )
            await db.commit()

            if cursor.rowcount == 0:
                return None

            return int(cursor.lastrowid)

    async def get_draft(
        self,
        draft_id: int,
    ) -> aiosqlite.Row | None:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM content_drafts WHERE id = ?",
                (draft_id,),
            )
            return await cursor.fetchone()

    async def set_draft_status(
        self,
        draft_id: int,
        status: str,
    ) -> None:
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE content_drafts
                SET status = ?
                WHERE id = ?
                """,
                (status, draft_id),
            )
            await db.commit()

    async def get_snapshot_hash(
        self,
        url: str,
    ) -> str | None:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT content_hash
                FROM page_snapshots
                WHERE url = ?
                """,
                (url,),
            )
            row = await cursor.fetchone()

            return None if row is None else str(row["content_hash"])

    async def save_snapshot_hash(
        self,
        url: str,
        content_hash: str,
    ) -> None:
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO page_snapshots(
                    url, content_hash, updated_at
                )
                VALUES (?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    content_hash=excluded.content_hash,
                    updated_at=excluded.updated_at
                """,
                (url, content_hash, utc_now()),
            )
            await db.commit()

    async def start_radar_run(self, trigger_name: str) -> int:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                INSERT INTO radar_runs(
                    trigger_name, status, started_at
                )
                VALUES (?, 'running', ?)
                """,
                (trigger_name, utc_now()),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def finish_radar_run(
        self,
        run_id: int,
        *,
        status: str,
        drafts_created: int,
        error_count: int,
    ) -> None:
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE radar_runs
                SET
                    status = ?,
                    finished_at = ?,
                    drafts_created = ?,
                    error_count = ?
                WHERE id = ?
                """,
                (
                    status,
                    utc_now(),
                    drafts_created,
                    error_count,
                    run_id,
                ),
            )
            await db.commit()

    async def mark_source_started(
        self,
        source_key: str,
        source_url: str,
    ) -> None:
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO radar_source_status(
                    source_key,
                    source_url,
                    status,
                    last_started_at
                )
                VALUES (?, ?, 'running', ?)
                ON CONFLICT(source_key) DO UPDATE SET
                    source_url=excluded.source_url,
                    status='running',
                    last_started_at=excluded.last_started_at
                """,
                (source_key, source_url, utc_now()),
            )
            await db.commit()

    async def mark_source_success(
        self,
        source_key: str,
        source_url: str,
        *,
        items_count: int,
        duration_ms: int,
    ) -> None:
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO radar_source_status(
                    source_key,
                    source_url,
                    status,
                    last_success_at,
                    last_error,
                    last_items_count,
                    last_duration_ms
                )
                VALUES (?, ?, 'ok', ?, NULL, ?, ?)
                ON CONFLICT(source_key) DO UPDATE SET
                    source_url=excluded.source_url,
                    status='ok',
                    last_success_at=excluded.last_success_at,
                    last_error=NULL,
                    last_items_count=excluded.last_items_count,
                    last_duration_ms=excluded.last_duration_ms
                """,
                (
                    source_key,
                    source_url,
                    utc_now(),
                    items_count,
                    duration_ms,
                ),
            )
            await db.commit()

    async def mark_source_error(
        self,
        source_key: str,
        source_url: str,
        *,
        error: str,
        duration_ms: int,
    ) -> None:
        safe_error = error.strip()[:800]

        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO radar_source_status(
                    source_key,
                    source_url,
                    status,
                    last_error_at,
                    last_error,
                    last_duration_ms
                )
                VALUES (?, ?, 'error', ?, ?, ?)
                ON CONFLICT(source_key) DO UPDATE SET
                    source_url=excluded.source_url,
                    status='error',
                    last_error_at=excluded.last_error_at,
                    last_error=excluded.last_error,
                    last_duration_ms=excluded.last_duration_ms
                """,
                (
                    source_key,
                    source_url,
                    utc_now(),
                    safe_error,
                    duration_ms,
                ),
            )
            await db.commit()

    async def get_last_radar_run(
        self,
    ) -> aiosqlite.Row | None:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM radar_runs
                ORDER BY id DESC
                LIMIT 1
                """
            )
            return await cursor.fetchone()

    async def list_source_statuses(
        self,
    ) -> list[aiosqlite.Row]:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM radar_source_status
                ORDER BY source_key
                """
            )
            return list(await cursor.fetchall())
