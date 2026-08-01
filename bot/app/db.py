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
    async def connection(self) -> AsyncIterator[aiosqlite.Connection]:
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("PRAGMA busy_timeout=5000")
        try:
            yield db
        finally:
            await db.close()

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connection() as db:
            await db.executescript(
                """
                PRAGMA journal_mode=WAL;

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
                    FOREIGN KEY (promo_id)
                        REFERENCES promo_codes(id) ON DELETE CASCADE
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
        async with self.connection() as db:
            await db.execute(
                """
                INSERT INTO users(
                    telegram_id, username, first_name,
                    created_at, last_seen_at
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
        async with self.connection() as db:
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
        normalized_code = code.strip().upper()
        async with self.connection() as db:
            await db.execute(
                """
                INSERT INTO promo_codes(
                    code, reward, source, is_active, created_at
                )
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(code) DO UPDATE SET
                    reward=excluded.reward,
                    source=excluded.source,
                    is_active=1
                """,
                (normalized_code, reward, source, utc_now()),
            )
            cursor = await db.execute(
                "SELECT id FROM promo_codes WHERE code = ?",
                (normalized_code,),
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
        async with self.connection() as db:
            cursor = await db.execute(
                """
                SELECT
                    p.id,
                    p.code,
                    p.reward,
                    p.source,
                    COALESCE(SUM(
                        CASE WHEN v.vote = 1 THEN 1 ELSE 0 END
                    ), 0) AS works,
                    COALESCE(SUM(
                        CASE WHEN v.vote = -1 THEN 1 ELSE 0 END
                    ), 0) AS fails
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
        async with self.connection() as db:
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

    async def create_draft(
        self,
        kind: str,
        source_url: str,
        item_uid: str,
        title: str,
        link: str,
        summary: str,
    ) -> int | None:
        async with self.connection() as db:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO content_drafts(
                    kind, source_url, item_uid,
                    title, link, summary, created_at
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

    async def get_draft(self, draft_id: int) -> aiosqlite.Row | None:
        async with self.connection() as db:
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
        async with self.connection() as db:
            await db.execute(
                "UPDATE content_drafts SET status = ? WHERE id = ?",
                (status, draft_id),
            )
            await db.commit()

    async def get_snapshot_hash(self, url: str) -> str | None:
        async with self.connection() as db:
            cursor = await db.execute(
                "SELECT content_hash FROM page_snapshots WHERE url = ?",
                (url,),
            )
            row = await cursor.fetchone()
            return None if row is None else str(row["content_hash"])

    async def save_snapshot_hash(
        self,
        url: str,
        content_hash: str,
    ) -> None:
        async with self.connection() as db:
            await db.execute(
                """
                INSERT INTO page_snapshots(url, content_hash, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    content_hash=excluded.content_hash,
                    updated_at=excluded.updated_at
                """,
                (url, content_hash, utc_now()),
            )
            await db.commit()
