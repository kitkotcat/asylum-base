from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import aiosqlite

from bot.app.db import Database, utc_now


async def init_content_schema(db: Database) -> None:
    async with db.connect() as connection:
        await connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS content_payloads (
                draft_id INTEGER PRIMARY KEY,
                image_url TEXT NOT NULL DEFAULT '',
                entity_key TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (draft_id)
                    REFERENCES content_drafts(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS lootbar_package_assets (
                package_key TEXT PRIMARY KEY,
                icon_url TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (package_key)
                    REFERENCES lootbar_packages(package_key)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS publication_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                draft_id INTEGER NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER NOT NULL DEFAULT 100,
                scheduled_at TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (draft_id)
                    REFERENCES content_drafts(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS publication_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_key TEXT NOT NULL UNIQUE,
                draft_id INTEGER,
                kind TEXT NOT NULL,
                entity_key TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                target_chat_id INTEGER,
                thread_id INTEGER,
                telegram_message_id INTEGER,
                target_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                auto_published INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                published_at TEXT NOT NULL,
                FOREIGN KEY (draft_id)
                    REFERENCES content_drafts(id)
                    ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_publication_log_kind_time
            ON publication_log(kind, published_at);

            CREATE INDEX IF NOT EXISTS idx_publication_log_entity_time
            ON publication_log(entity_key, published_at);

            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                job_key TEXT PRIMARY KEY,
                last_run_date TEXT NOT NULL,
                last_run_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS promo_metadata (
                promo_id INTEGER PRIMARY KEY,
                region TEXT NOT NULL DEFAULT 'Global',
                expires_at TEXT,
                verification_status TEXT NOT NULL DEFAULT 'verified',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (promo_id)
                    REFERENCES promo_codes(id)
                    ON DELETE CASCADE
            );
            """
        )
        await connection.commit()


async def save_draft_payload(
    db: Database,
    draft_id: int,
    *,
    image_url: str = "",
    entity_key: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> None:
    async with db.connect() as connection:
        await connection.execute(
            """
            INSERT INTO content_payloads(
                draft_id,
                image_url,
                entity_key,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(draft_id) DO UPDATE SET
                image_url=excluded.image_url,
                entity_key=excluded.entity_key,
                metadata_json=excluded.metadata_json
            """,
            (
                draft_id,
                image_url,
                entity_key,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                utc_now(),
            ),
        )
        await connection.commit()


async def get_draft_with_payload(
    db: Database,
    draft_id: int,
) -> dict[str, Any] | None:
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT
                d.*,
                COALESCE(p.image_url, '') AS image_url,
                COALESCE(p.entity_key, '') AS entity_key,
                COALESCE(p.metadata_json, '{}') AS metadata_json
            FROM content_drafts d
            LEFT JOIN content_payloads p ON p.draft_id = d.id
            WHERE d.id = ?
            """,
            (draft_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        return None

    result = dict(row)
    try:
        metadata = json.loads(str(result.pop("metadata_json", "{}")))
    except json.JSONDecodeError:
        metadata = {}
    result["metadata"] = metadata if isinstance(metadata, dict) else {}
    return result


async def save_lootbar_assets(
    db: Database,
    packages: list[Mapping[str, Any]],
) -> None:
    now = utc_now()
    rows = [
        (
            str(package["package_key"]),
            str(package.get("icon_url", "")),
            now,
        )
        for package in packages
        if package.get("package_key")
    ]
    if not rows:
        return

    async with db.connect() as connection:
        await connection.executemany(
            """
            INSERT INTO lootbar_package_assets(
                package_key,
                icon_url,
                updated_at
            )
            VALUES (?, ?, ?)
            ON CONFLICT(package_key) DO UPDATE SET
                icon_url=excluded.icon_url,
                updated_at=excluded.updated_at
            """,
            rows,
        )
        await connection.commit()


async def list_lootbar_packages_page(
    db: Database,
    source_url: str,
    *,
    page: int,
    page_size: int,
) -> tuple[list[aiosqlite.Row], int]:
    safe_page = max(page, 0)
    offset = safe_page * page_size

    async with db.connect() as connection:
        count_cursor = await connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM lootbar_packages
            WHERE source_url = ? AND is_active = 1
            """,
            (source_url,),
        )
        count_row = await count_cursor.fetchone()
        total = int(count_row["total"] if count_row else 0)

        cursor = await connection.execute(
            """
            SELECT
                p.*,
                COALESCE(a.icon_url, '') AS icon_url
            FROM lootbar_packages p
            LEFT JOIN lootbar_package_assets a
                ON a.package_key = p.package_key
            WHERE p.source_url = ? AND p.is_active = 1
            ORDER BY
                p.savings_minor DESC,
                p.promo_price_minor ASC,
                p.name ASC
            LIMIT ? OFFSET ?
            """,
            (source_url, page_size, offset),
        )
        rows = list(await cursor.fetchall())

    return rows, total


async def list_top_lootbar_packages(
    db: Database,
    source_url: str,
    *,
    limit: int = 3,
) -> list[aiosqlite.Row]:
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT
                p.*,
                COALESCE(a.icon_url, '') AS icon_url,
                CASE
                    WHEN p.official_price_minor > 0
                    THEN (p.savings_minor * 100.0)
                         / p.official_price_minor
                    ELSE 0
                END AS savings_percent
            FROM lootbar_packages p
            LEFT JOIN lootbar_package_assets a
                ON a.package_key = p.package_key
            WHERE p.source_url = ? AND p.is_active = 1
            ORDER BY
                savings_percent DESC,
                p.savings_minor DESC,
                p.promo_price_minor ASC
            LIMIT ?
            """,
            (source_url, limit),
        )
        return list(await cursor.fetchall())


async def enqueue_draft(
    db: Database,
    draft_id: int,
    kind: str,
    *,
    priority: int = 100,
    scheduled_at: str | None = None,
) -> bool:
    now = utc_now()
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            INSERT OR IGNORE INTO publication_queue(
                draft_id,
                kind,
                status,
                priority,
                scheduled_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, 'pending', ?, ?, ?, ?)
            """,
            (draft_id, kind, priority, scheduled_at or now, now, now),
        )
        await connection.commit()
        return cursor.rowcount > 0


async def list_ready_queue(
    db: Database,
    *,
    limit: int = 10,
) -> list[aiosqlite.Row]:
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT *
            FROM publication_queue
            WHERE status = 'pending'
              AND scheduled_at <= ?
            ORDER BY priority ASC, id ASC
            LIMIT ?
            """,
            (utc_now(), limit),
        )
        return list(await cursor.fetchall())


async def mark_queue_status(
    db: Database,
    queue_id: int,
    status: str,
    *,
    error: str | None = None,
    increment_attempts: bool = False,
) -> None:
    async with db.connect() as connection:
        await connection.execute(
            """
            UPDATE publication_queue
            SET
                status = ?,
                last_error = ?,
                attempts = attempts + ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, error, 1 if increment_attempts else 0, utc_now(), queue_id),
        )
        await connection.commit()


def draft_content_key(draft: Mapping[str, Any]) -> str:
    return f"{draft['source_url']}::{draft['item_uid']}"


async def publication_exists(db: Database, content_key: str) -> bool:
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT 1
            FROM publication_log
            WHERE content_key = ? AND status = 'published'
            LIMIT 1
            """,
            (content_key,),
        )
        return await cursor.fetchone() is not None


async def entity_published_recently(
    db: Database,
    entity_key: str,
    *,
    hours: int,
) -> bool:
    if not entity_key:
        return False
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT 1
            FROM publication_log
            WHERE entity_key = ?
              AND status = 'published'
              AND published_at >= ?
            LIMIT 1
            """,
            (entity_key, cutoff),
        )
        return await cursor.fetchone() is not None


async def count_recent_auto_deals(db: Database, *, hours: int = 6) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM publication_log
            WHERE kind IN ('deal', 'deal_digest', 'topup')
              AND status = 'published'
              AND auto_published = 1
              AND published_at >= ?
            """,
            (cutoff,),
        )
        row = await cursor.fetchone()
        return int(row["total"] if row else 0)


async def count_auto_publications_today(
    db: Database,
    *,
    kind: str,
    target_chat_id: int,
    offset_hours: int,
) -> int:
    local_tz = timezone(timedelta(hours=offset_hours))
    local_now = datetime.now(local_tz)
    local_midnight = local_now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    utc_start = local_midnight.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    )
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM publication_log
            WHERE kind = ?
              AND target_chat_id = ?
              AND status = 'published'
              AND auto_published = 1
              AND published_at >= ?
            """,
            (kind, target_chat_id, utc_start),
        )
        row = await cursor.fetchone()
    return int(row["total"] if row else 0)


async def latest_auto_publication_at(
    db: Database,
    *,
    kind: str,
    target_chat_id: int,
) -> str | None:
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT published_at
            FROM publication_log
            WHERE kind = ?
              AND target_chat_id = ?
              AND status = 'published'
              AND auto_published = 1
            ORDER BY published_at DESC, id DESC
            LIMIT 1
            """,
            (kind, target_chat_id),
        )
        row = await cursor.fetchone()
    if row is None or not row["published_at"]:
        return None
    return str(row["published_at"])


async def recent_offer_history(
    db: Database,
    *,
    kind: str,
    target_chat_id: int,
    hours: int,
) -> tuple[set[str], set[tuple[str, int, int]]]:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=hours)
    ).isoformat(timespec="seconds")
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT l.entity_key, COALESCE(p.metadata_json, '{}') AS metadata_json
            FROM publication_log l
            LEFT JOIN content_payloads p ON p.draft_id = l.draft_id
            WHERE l.kind = ?
              AND l.target_chat_id = ?
              AND l.status = 'published'
              AND l.published_at >= ?
            ORDER BY l.published_at DESC, l.id DESC
            """,
            (kind, target_chat_id, cutoff),
        )
        rows = list(await cursor.fetchall())

    package_keys: set[str] = set()
    price_fingerprints: set[tuple[str, int, int]] = set()
    for row in rows:
        entity_key = str(row["entity_key"] or "").strip()
        if entity_key:
            package_keys.add(entity_key)
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(metadata, dict):
            continue
        currency = str(metadata.get("currency") or "").strip().upper()
        try:
            promo = int(metadata.get("promo_price_minor") or 0)
            official = int(metadata.get("official_price_minor") or 0)
        except (TypeError, ValueError):
            continue
        if currency and promo > 0 and official > promo:
            price_fingerprints.add((currency, promo, official))

    return package_keys, price_fingerprints


async def record_publication(
    db: Database,
    *,
    content_key: str,
    draft_id: int | None,
    kind: str,
    entity_key: str,
    title: str,
    target_chat_id: int | None,
    thread_id: int | None,
    telegram_message_id: int | None,
    target_url: str,
    status: str,
    auto_published: bool,
    error: str | None = None,
) -> None:
    async with db.connect() as connection:
        await connection.execute(
            """
            INSERT INTO publication_log(
                content_key,
                draft_id,
                kind,
                entity_key,
                title,
                target_chat_id,
                thread_id,
                telegram_message_id,
                target_url,
                status,
                auto_published,
                error,
                published_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(content_key) DO UPDATE SET
                status=excluded.status,
                target_chat_id=excluded.target_chat_id,
                thread_id=excluded.thread_id,
                telegram_message_id=excluded.telegram_message_id,
                target_url=excluded.target_url,
                auto_published=excluded.auto_published,
                error=excluded.error,
                published_at=excluded.published_at
            """,
            (
                content_key,
                draft_id,
                kind,
                entity_key,
                title,
                target_chat_id,
                thread_id,
                telegram_message_id,
                target_url,
                status,
                1 if auto_published else 0,
                error,
                utc_now(),
            ),
        )
        await connection.commit()


async def list_recent_publications(
    db: Database,
    *,
    kinds: tuple[str, ...],
    limit: int = 5,
) -> list[aiosqlite.Row]:
    placeholders = ",".join("?" for _ in kinds)
    query = f"""
        SELECT *
        FROM publication_log
        WHERE status = 'published'
          AND kind IN ({placeholders})
        ORDER BY published_at DESC
        LIMIT ?
    """
    async with db.connect() as connection:
        cursor = await connection.execute(query, (*kinds, limit))
        return list(await cursor.fetchall())


async def pending_drafts_count(db: Database) -> int:
    async with db.connect() as connection:
        cursor = await connection.execute(
            "SELECT COUNT(*) AS total FROM content_drafts WHERE status = 'pending'"
        )
        row = await cursor.fetchone()
        return int(row["total"] if row else 0)


async def list_pending_drafts(db: Database, *, limit: int = 10) -> list[aiosqlite.Row]:
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT * FROM content_drafts
            WHERE status = 'pending'
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        )
        return list(await cursor.fetchall())


async def job_due(db: Database, job_key: str, *, hour_utc: int) -> bool:
    now = datetime.now(timezone.utc)
    if now.hour < hour_utc:
        return False
    today = now.date().isoformat()
    async with db.connect() as connection:
        cursor = await connection.execute(
            "SELECT last_run_date FROM scheduled_jobs WHERE job_key = ?",
            (job_key,),
        )
        row = await cursor.fetchone()
        return row is None or str(row["last_run_date"]) != today


async def mark_job_run(db: Database, job_key: str) -> None:
    now = datetime.now(timezone.utc)
    async with db.connect() as connection:
        await connection.execute(
            """
            INSERT INTO scheduled_jobs(job_key, last_run_date, last_run_at)
            VALUES (?, ?, ?)
            ON CONFLICT(job_key) DO UPDATE SET
                last_run_date=excluded.last_run_date,
                last_run_at=excluded.last_run_at
            """,
            (job_key, now.date().isoformat(), now.isoformat(timespec="seconds")),
        )
        await connection.commit()


async def set_promo_metadata(
    db: Database,
    promo_id: int,
    *,
    region: str = "Global",
    expires_at: str | None = None,
    verification_status: str = "verified",
) -> None:
    async with db.connect() as connection:
        await connection.execute(
            """
            INSERT INTO promo_metadata(
                promo_id,
                region,
                expires_at,
                verification_status,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(promo_id) DO UPDATE SET
                region=excluded.region,
                expires_at=excluded.expires_at,
                verification_status=excluded.verification_status,
                updated_at=excluded.updated_at
            """,
            (promo_id, region, expires_at, verification_status, utc_now()),
        )
        await connection.commit()


async def list_active_promos_extended(
    db: Database,
    *,
    limit: int = 20,
) -> list[aiosqlite.Row]:
    now = utc_now()
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT
                p.id,
                p.code,
                p.reward,
                p.source,
                COALESCE(m.region, 'Global') AS region,
                m.expires_at,
                COALESCE(m.verification_status, 'verified') AS verification_status,
                COALESCE(SUM(CASE WHEN v.vote = 1 THEN 1 ELSE 0 END), 0) AS works,
                COALESCE(SUM(CASE WHEN v.vote = -1 THEN 1 ELSE 0 END), 0) AS fails
            FROM promo_codes p
            LEFT JOIN promo_metadata m ON m.promo_id = p.id
            LEFT JOIN promo_votes v ON v.promo_id = p.id
            WHERE p.is_active = 1
              AND (m.expires_at IS NULL OR m.expires_at = '' OR m.expires_at > ?)
            GROUP BY p.id
            ORDER BY p.id DESC
            LIMIT ?
            """,
            (now, limit),
        )
        return list(await cursor.fetchall())


async def list_autopublish_promos(
    db: Database,
    *,
    limit: int = 50,
) -> list[aiosqlite.Row]:
    """Return only explicitly verified, active promo codes.

    Legacy rows without promo_metadata are intentionally excluded so an old
    unverified code can never be published automatically.
    """
    now = utc_now()
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT
                p.id,
                p.code,
                p.reward,
                p.source,
                m.region,
                m.expires_at,
                m.verification_status
            FROM promo_codes p
            JOIN promo_metadata m ON m.promo_id = p.id
            WHERE p.is_active = 1
              AND m.verification_status = 'verified'
              AND (m.expires_at IS NULL OR m.expires_at = '' OR m.expires_at > ?)
            ORDER BY p.created_at DESC, p.id DESC
            LIMIT ?
            """,
            (now, limit),
        )
        return list(await cursor.fetchall())


async def count_auto_promos_today(
    db: Database,
    *,
    offset_hours: int = 0,
) -> int:
    local_tz = timezone(timedelta(hours=offset_hours))
    local_now = datetime.now(local_tz)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    utc_start = local_midnight.astimezone(timezone.utc).isoformat(timespec="seconds")
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM publication_log
            WHERE kind = 'promo'
              AND status = 'published'
              AND auto_published = 1
              AND published_at >= ?
            """,
            (utc_start,),
        )
        row = await cursor.fetchone()
        return int(row["total"] if row else 0)


async def expire_promos(db: Database) -> int:
    now = utc_now()
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            UPDATE promo_codes
            SET is_active = 0
            WHERE id IN (
                SELECT promo_id
                FROM promo_metadata
                WHERE expires_at IS NOT NULL
                  AND expires_at != ''
                  AND expires_at <= ?
            )
              AND is_active = 1
            """,
            (now,),
        )
        await connection.commit()
        return max(cursor.rowcount, 0)


async def deactivate_promo_by_code(db: Database, code: str) -> bool:
    async with db.connect() as connection:
        cursor = await connection.execute(
            "UPDATE promo_codes SET is_active = 0 WHERE code = ?",
            (code.upper(),),
        )
        await connection.commit()
        return cursor.rowcount > 0


async def daily_stats(db: Database) -> dict[str, int]:
    today = datetime.now(timezone.utc).date().isoformat()
    async with db.connect() as connection:
        queries = {
            "users": "SELECT COUNT(*) AS total FROM users",
            "clicks_today": "SELECT COUNT(*) AS total FROM referral_clicks WHERE created_at >= ?",
            "published_today": "SELECT COUNT(*) AS total FROM publication_log WHERE status='published' AND published_at >= ?",
            "failed_today": "SELECT COUNT(*) AS total FROM publication_log WHERE status='failed' AND published_at >= ?",
            "pending_drafts": "SELECT COUNT(*) AS total FROM content_drafts WHERE status='pending'",
            "active_promos": "SELECT COUNT(*) AS total FROM promo_codes WHERE is_active=1",
        }
        result: dict[str, int] = {}
        for key, query in queries.items():
            params = (today,) if "?" in query else ()
            cursor = await connection.execute(query, params)
            row = await cursor.fetchone()
            result[key] = int(row["total"] if row else 0)
        return result
