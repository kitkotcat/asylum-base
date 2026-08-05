from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

import aiosqlite

from bot.app.db import Database, utc_now

EDITORIAL_KINDS = frozenset({"guide", "hero", "squad", "event", "alliance"})
SUGGESTION_KINDS = EDITORIAL_KINDS


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9а-яё]+", "-", value.casefold(), flags=re.IGNORECASE)
    return normalized.strip("-") or "item"


def _json_list(values: Iterable[str]) -> str:
    return json.dumps([value.strip() for value in values if value.strip()], ensure_ascii=False)


def _load_list(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


async def init_community_schema(db: Database) -> None:
    async with db.connect() as connection:
        await connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS heroes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name_ru TEXT NOT NULL,
                name_en TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT '',
                rarity TEXT NOT NULL DEFAULT '',
                faction TEXT NOT NULL DEFAULT '',
                strengths_json TEXT NOT NULL DEFAULT '[]',
                weaknesses_json TEXT NOT NULL DEFAULT '[]',
                strategy TEXT NOT NULL DEFAULT '',
                image_file_id TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_heroes_status_name
            ON heroes(status, name_ru);

            CREATE TABLE IF NOT EXISTS squads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT '',
                members_json TEXT NOT NULL DEFAULT '[]',
                synergy TEXT NOT NULL DEFAULT '',
                strategy TEXT NOT NULL DEFAULT '',
                image_file_id TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_squads_status_name
            ON squads(status, name);

            CREATE TABLE IF NOT EXISTS game_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                ends_at TEXT,
                description TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_game_events_status_start
            ON game_events(status, starts_at);

            CREATE TABLE IF NOT EXISTS editorial_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                entity_key TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                image_file_id TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'approved',
                next_publish_at TEXT NOT NULL,
                repeat_days INTEGER NOT NULL DEFAULT 0,
                last_published_at TEXT,
                publish_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK(kind IN ('guide', 'hero', 'squad', 'event', 'alliance')),
                CHECK(repeat_days >= 0)
            );

            CREATE INDEX IF NOT EXISTS idx_editorial_due
            ON editorial_items(status, next_publish_at);

            CREATE TABLE IF NOT EXISTS content_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                image_file_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                moderation_note TEXT NOT NULL DEFAULT '',
                draft_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK(kind IN ('guide', 'hero', 'squad', 'event', 'alliance')),
                FOREIGN KEY (draft_id)
                    REFERENCES content_drafts(id)
                    ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_suggestions_status_time
            ON content_suggestions(status, created_at);

            CREATE TABLE IF NOT EXISTS message_reaction_users (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                actor_key TEXT NOT NULL,
                reaction_key TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(chat_id, message_id, actor_key, reaction_key)
            );

            CREATE INDEX IF NOT EXISTS idx_reaction_users_message
            ON message_reaction_users(chat_id, message_id);

            CREATE TABLE IF NOT EXISTS message_reaction_totals (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                reaction_key TEXT NOT NULL,
                total_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(chat_id, message_id, reaction_key)
            );

            CREATE INDEX IF NOT EXISTS idx_reaction_totals_message
            ON message_reaction_totals(chat_id, message_id);
            """
        )
        await connection.commit()


async def upsert_hero(
    db: Database,
    *,
    name_ru: str,
    name_en: str = "",
    role: str = "",
    rarity: str = "",
    faction: str = "",
    strengths: Iterable[str] = (),
    weaknesses: Iterable[str] = (),
    strategy: str = "",
    image_file_id: str = "",
    source_url: str = "",
) -> int:
    now = utc_now()
    slug = slugify(name_en or name_ru)
    async with db.connect() as connection:
        await connection.execute(
            """
            INSERT INTO heroes(
                slug, name_ru, name_en, role, rarity, faction,
                strengths_json, weaknesses_json, strategy,
                image_file_id, source_url, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name_ru=excluded.name_ru,
                name_en=excluded.name_en,
                role=excluded.role,
                rarity=excluded.rarity,
                faction=excluded.faction,
                strengths_json=excluded.strengths_json,
                weaknesses_json=excluded.weaknesses_json,
                strategy=excluded.strategy,
                image_file_id=excluded.image_file_id,
                source_url=excluded.source_url,
                status='active',
                updated_at=excluded.updated_at
            """,
            (
                slug,
                name_ru.strip(),
                name_en.strip(),
                role.strip(),
                rarity.strip(),
                faction.strip(),
                _json_list(strengths),
                _json_list(weaknesses),
                strategy.strip(),
                image_file_id.strip(),
                source_url.strip(),
                now,
                now,
            ),
        )
        cursor = await connection.execute("SELECT id FROM heroes WHERE slug = ?", (slug,))
        row = await cursor.fetchone()
        await connection.commit()
    if row is None:
        raise RuntimeError("Не удалось сохранить героя")
    return int(row["id"])


async def get_hero(db: Database, query: str) -> dict[str, Any] | None:
    value = query.strip()
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT * FROM heroes
            WHERE status = 'active'
              AND (
                    slug = ?
                 OR name_ru = ? COLLATE NOCASE
                 OR name_en = ? COLLATE NOCASE
                 OR name_ru LIKE ? COLLATE NOCASE
                 OR name_en LIKE ? COLLATE NOCASE
              )
            ORDER BY
                CASE WHEN slug = ? THEN 0 ELSE 1 END,
                name_ru
            LIMIT 1
            """,
            (slugify(value), value, value, f"%{value}%", f"%{value}%", slugify(value)),
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    result = dict(row)
    result["strengths"] = _load_list(result.pop("strengths_json", "[]"))
    result["weaknesses"] = _load_list(result.pop("weaknesses_json", "[]"))
    return result


async def list_heroes(db: Database, *, limit: int = 30) -> list[dict[str, Any]]:
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT * FROM heroes
            WHERE status = 'active'
            ORDER BY name_ru
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["strengths"] = _load_list(item.pop("strengths_json", "[]"))
        item["weaknesses"] = _load_list(item.pop("weaknesses_json", "[]"))
        result.append(item)
    return result


async def upsert_squad(
    db: Database,
    *,
    name: str,
    mode: str,
    members: Iterable[str],
    synergy: str,
    strategy: str,
    image_file_id: str = "",
    source_url: str = "",
) -> int:
    now = utc_now()
    slug = slugify(name)
    async with db.connect() as connection:
        await connection.execute(
            """
            INSERT INTO squads(
                slug, name, mode, members_json, synergy, strategy,
                image_file_id, source_url, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name=excluded.name,
                mode=excluded.mode,
                members_json=excluded.members_json,
                synergy=excluded.synergy,
                strategy=excluded.strategy,
                image_file_id=excluded.image_file_id,
                source_url=excluded.source_url,
                status='active',
                updated_at=excluded.updated_at
            """,
            (
                slug,
                name.strip(),
                mode.strip(),
                _json_list(members),
                synergy.strip(),
                strategy.strip(),
                image_file_id.strip(),
                source_url.strip(),
                now,
                now,
            ),
        )
        cursor = await connection.execute("SELECT id FROM squads WHERE slug = ?", (slug,))
        row = await cursor.fetchone()
        await connection.commit()
    if row is None:
        raise RuntimeError("Не удалось сохранить состав")
    return int(row["id"])


async def list_squads(db: Database, *, limit: int = 30) -> list[dict[str, Any]]:
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT * FROM squads
            WHERE status = 'active'
            ORDER BY name
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["members"] = _load_list(item.pop("members_json", "[]"))
        result.append(item)
    return result


async def add_game_event(
    db: Database,
    *,
    title: str,
    starts_at: str,
    ends_at: str | None,
    description: str,
    source_url: str = "",
) -> int:
    now = utc_now()
    event_key = f"{slugify(title)}:{starts_at}"
    async with db.connect() as connection:
        await connection.execute(
            """
            INSERT INTO game_events(
                event_key, title, starts_at, ends_at, description,
                source_url, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(event_key) DO UPDATE SET
                title=excluded.title,
                ends_at=excluded.ends_at,
                description=excluded.description,
                source_url=excluded.source_url,
                status='active',
                updated_at=excluded.updated_at
            """,
            (
                event_key,
                title.strip(),
                starts_at,
                ends_at,
                description.strip(),
                source_url.strip(),
                now,
                now,
            ),
        )
        cursor = await connection.execute(
            "SELECT id FROM game_events WHERE event_key = ?",
            (event_key,),
        )
        row = await cursor.fetchone()
        await connection.commit()
    if row is None:
        raise RuntimeError("Не удалось сохранить событие")
    return int(row["id"])


async def list_upcoming_events(
    db: Database,
    *,
    now: str | None = None,
    limit: int = 20,
) -> list[aiosqlite.Row]:
    current = now or utc_now()
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT * FROM game_events
            WHERE status = 'active'
              AND COALESCE(ends_at, starts_at) >= ?
            ORDER BY starts_at
            LIMIT ?
            """,
            (current, limit),
        )
        return list(await cursor.fetchall())


async def add_editorial_item(
    db: Database,
    *,
    kind: str,
    title: str,
    body: str,
    next_publish_at: str,
    repeat_days: int = 0,
    entity_key: str = "",
    image_file_id: str = "",
    source_url: str = "",
    status: str = "approved",
) -> int:
    if kind not in EDITORIAL_KINDS:
        raise ValueError(f"Неподдерживаемый тип контента: {kind}")
    if repeat_days < 0:
        raise ValueError("repeat_days не может быть отрицательным")
    now = utc_now()
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            INSERT INTO editorial_items(
                kind, entity_key, title, body, image_file_id, source_url,
                status, next_publish_at, repeat_days, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kind,
                entity_key.strip(),
                title.strip(),
                body.strip(),
                image_file_id.strip(),
                source_url.strip(),
                status,
                next_publish_at,
                repeat_days,
                now,
                now,
            ),
        )
        await connection.commit()
        return int(cursor.lastrowid)




async def upsert_entity_editorial_item(
    db: Database,
    *,
    kind: str,
    entity_key: str,
    title: str,
    body: str,
    next_publish_at: str,
    repeat_days: int = 0,
    image_file_id: str = "",
    source_url: str = "",
) -> int:
    if kind not in EDITORIAL_KINDS:
        raise ValueError(f"Неподдерживаемый тип контента: {kind}")
    if not entity_key:
        return await add_editorial_item(
            db,
            kind=kind,
            title=title,
            body=body,
            next_publish_at=next_publish_at,
            repeat_days=repeat_days,
            image_file_id=image_file_id,
            source_url=source_url,
        )
    now = utc_now()
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT id
            FROM editorial_items
            WHERE kind = ?
              AND entity_key = ?
              AND status IN ('approved', 'paused')
            ORDER BY id DESC
            LIMIT 1
            """,
            (kind, entity_key),
        )
        row = await cursor.fetchone()
        if row is None:
            cursor = await connection.execute(
                """
                INSERT INTO editorial_items(
                    kind, entity_key, title, body, image_file_id, source_url,
                    status, next_publish_at, repeat_days, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'approved', ?, ?, ?, ?)
                """,
                (
                    kind,
                    entity_key,
                    title.strip(),
                    body.strip(),
                    image_file_id.strip(),
                    source_url.strip(),
                    next_publish_at,
                    repeat_days,
                    now,
                    now,
                ),
            )
            editorial_id = int(cursor.lastrowid)
        else:
            editorial_id = int(row["id"])
            await connection.execute(
                """
                UPDATE editorial_items
                SET title = ?,
                    body = ?,
                    image_file_id = ?,
                    source_url = ?,
                    status = 'approved',
                    next_publish_at = ?,
                    repeat_days = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    title.strip(),
                    body.strip(),
                    image_file_id.strip(),
                    source_url.strip(),
                    next_publish_at,
                    repeat_days,
                    now,
                    editorial_id,
                ),
            )
        await connection.commit()
        return editorial_id


async def set_editorial_status(
    db: Database,
    editorial_id: int,
    *,
    status: str,
) -> bool:
    if status not in {"approved", "paused", "archived"}:
        raise ValueError("Некорректный статус контента")
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            UPDATE editorial_items
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, utc_now(), editorial_id),
        )
        await connection.commit()
        return cursor.rowcount > 0


async def list_due_editorial_items(
    db: Database,
    *,
    now: str | None = None,
    limit: int = 5,
) -> list[aiosqlite.Row]:
    current = now or utc_now()
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT * FROM editorial_items
            WHERE status = 'approved'
              AND next_publish_at <= ?
            ORDER BY
                CASE WHEN kind = 'event' THEN 0 ELSE 1 END,
                next_publish_at,
                id
            LIMIT ?
            """,
            (current, limit),
        )
        return list(await cursor.fetchall())


async def list_editorial_queue(db: Database, *, limit: int = 20) -> list[aiosqlite.Row]:
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT * FROM editorial_items
            WHERE status IN ('approved', 'paused')
            ORDER BY next_publish_at, id
            LIMIT ?
            """,
            (limit,),
        )
        return list(await cursor.fetchall())


async def mark_editorial_dispatched(
    db: Database,
    editorial_id: int,
    *,
    dispatched_at: str | None = None,
) -> None:
    now = dispatched_at or utc_now()
    async with db.connect() as connection:
        cursor = await connection.execute(
            "SELECT repeat_days FROM editorial_items WHERE id = ?",
            (editorial_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return
        repeat_days = int(row["repeat_days"])
        if repeat_days > 0:
            next_publish = (
                datetime.fromisoformat(now).astimezone(timezone.utc)
                + timedelta(days=repeat_days)
            ).isoformat(timespec="seconds")
            status = "approved"
        else:
            next_publish = now
            status = "archived"
        await connection.execute(
            """
            UPDATE editorial_items
            SET status = ?,
                next_publish_at = ?,
                last_published_at = ?,
                publish_count = publish_count + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (status, next_publish, now, now, editorial_id),
        )
        await connection.commit()


async def count_editorial_publications_today(
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
            WHERE kind IN ('guide', 'hero', 'squad', 'event', 'alliance')
              AND status = 'published'
              AND auto_published = 1
              AND published_at >= ?
            """,
            (utc_start,),
        )
        row = await cursor.fetchone()
        return int(row["total"] if row else 0)


async def count_recent_suggestions(
    db: Database,
    *,
    telegram_id: int,
    hours: int = 24,
) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(
        timespec="seconds"
    )
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM content_suggestions
            WHERE telegram_id = ?
              AND created_at >= ?
            """,
            (telegram_id, cutoff),
        )
        row = await cursor.fetchone()
        return int(row["total"] if row else 0)


async def add_suggestion(
    db: Database,
    *,
    telegram_id: int,
    username: str,
    kind: str,
    title: str,
    body: str,
    image_file_id: str = "",
) -> int:
    if kind not in SUGGESTION_KINDS:
        raise ValueError(f"Неподдерживаемая категория: {kind}")
    now = utc_now()
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            INSERT INTO content_suggestions(
                telegram_id, username, kind, title, body,
                image_file_id, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                telegram_id,
                username.strip(),
                kind,
                title.strip(),
                body.strip(),
                image_file_id.strip(),
                now,
                now,
            ),
        )
        await connection.commit()
        return int(cursor.lastrowid)


async def get_suggestion(db: Database, suggestion_id: int) -> aiosqlite.Row | None:
    async with db.connect() as connection:
        cursor = await connection.execute(
            "SELECT * FROM content_suggestions WHERE id = ?",
            (suggestion_id,),
        )
        return await cursor.fetchone()


async def list_pending_suggestions(db: Database, *, limit: int = 20) -> list[aiosqlite.Row]:
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT * FROM content_suggestions
            WHERE status = 'pending'
            ORDER BY created_at
            LIMIT ?
            """,
            (limit,),
        )
        return list(await cursor.fetchall())


async def set_suggestion_status(
    db: Database,
    suggestion_id: int,
    *,
    status: str,
    draft_id: int | None = None,
    moderation_note: str = "",
) -> None:
    async with db.connect() as connection:
        await connection.execute(
            """
            UPDATE content_suggestions
            SET status = ?,
                draft_id = COALESCE(?, draft_id),
                moderation_note = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, draft_id, moderation_note, utc_now(), suggestion_id),
        )
        await connection.commit()


def reaction_key(reaction: object) -> str:
    emoji = getattr(reaction, "emoji", None)
    if emoji:
        return f"emoji:{emoji}"
    custom = getattr(reaction, "custom_emoji_id", None)
    if custom:
        return f"custom:{custom}"
    reaction_type = getattr(reaction, "type", None)
    return f"type:{reaction_type or 'paid'}"


async def replace_user_reactions(
    db: Database,
    *,
    chat_id: int,
    message_id: int,
    actor_key: str,
    reactions: Iterable[object],
) -> None:
    now = utc_now()
    keys = sorted({reaction_key(item) for item in reactions})
    async with db.connect() as connection:
        await connection.execute(
            """
            DELETE FROM message_reaction_users
            WHERE chat_id = ? AND message_id = ? AND actor_key = ?
            """,
            (chat_id, message_id, actor_key),
        )
        if keys:
            await connection.executemany(
                """
                INSERT INTO message_reaction_users(
                    chat_id, message_id, actor_key, reaction_key, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                [(chat_id, message_id, actor_key, key, now) for key in keys],
            )
        await connection.commit()


async def replace_reaction_totals(
    db: Database,
    *,
    chat_id: int,
    message_id: int,
    reactions: Iterable[object],
) -> None:
    now = utc_now()
    rows = [
        (
            chat_id,
            message_id,
            reaction_key(getattr(item, "type", item)),
            int(getattr(item, "total_count", 0)),
            now,
        )
        for item in reactions
    ]
    async with db.connect() as connection:
        await connection.execute(
            "DELETE FROM message_reaction_totals WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        )
        if rows:
            await connection.executemany(
                """
                INSERT INTO message_reaction_totals(
                    chat_id, message_id, reaction_key, total_count, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
        await connection.commit()


async def analytics_summary(db: Database, *, limit: int = 10) -> dict[str, Any]:
    async with db.connect() as connection:
        totals_cursor = await connection.execute(
            """
            WITH anonymous_by_message AS (
                SELECT chat_id, message_id, SUM(total_count) AS total
                FROM message_reaction_totals
                GROUP BY chat_id, message_id
            ),
            public_by_message AS (
                SELECT chat_id, message_id, COUNT(*) AS total
                FROM message_reaction_users
                GROUP BY chat_id, message_id
            ),
            reaction_messages AS (
                SELECT chat_id, message_id FROM anonymous_by_message
                UNION
                SELECT chat_id, message_id FROM public_by_message
            ),
            reaction_total AS (
                SELECT COALESCE(SUM(
                    CASE
                        WHEN COALESCE(a.total, 0) > 0 THEN a.total
                        ELSE COALESCE(p.total, 0)
                    END
                ), 0) AS total
                FROM reaction_messages m
                LEFT JOIN anonymous_by_message a
                  ON a.chat_id = m.chat_id AND a.message_id = m.message_id
                LEFT JOIN public_by_message p
                  ON p.chat_id = m.chat_id AND p.message_id = m.message_id
            )
            SELECT
                (SELECT COUNT(*) FROM content_suggestions) AS suggestions,
                (SELECT COUNT(*) FROM content_suggestions WHERE status='pending') AS pending_suggestions,
                (SELECT COUNT(*) FROM editorial_items WHERE status='approved') AS queued_editorial,
                (SELECT COUNT(*) FROM heroes WHERE status='active') AS heroes,
                (SELECT COUNT(*) FROM squads WHERE status='active') AS squads,
                (SELECT COUNT(*) FROM game_events WHERE status='active') AS events,
                (SELECT total FROM reaction_total) AS reactions
            """
        )
        totals_row = await totals_cursor.fetchone()

        top_cursor = await connection.execute(
            """
            WITH anonymous_by_message AS (
                SELECT chat_id, message_id, SUM(total_count) AS total
                FROM message_reaction_totals
                GROUP BY chat_id, message_id
            ),
            public_by_message AS (
                SELECT chat_id, message_id, COUNT(*) AS total
                FROM message_reaction_users
                GROUP BY chat_id, message_id
            )
            SELECT
                l.title,
                l.kind,
                l.telegram_message_id,
                CASE
                    WHEN COALESCE(a.total, 0) > 0 THEN a.total
                    ELSE COALESCE(p.total, 0)
                END AS reactions
            FROM publication_log l
            LEFT JOIN anonymous_by_message a
              ON a.chat_id = l.target_chat_id
             AND a.message_id = l.telegram_message_id
            LEFT JOIN public_by_message p
              ON p.chat_id = l.target_chat_id
             AND p.message_id = l.telegram_message_id
            WHERE l.status = 'published'
            ORDER BY reactions DESC, l.published_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        top_rows = [dict(row) for row in await top_cursor.fetchall()]

    totals = dict(totals_row) if totals_row is not None else {}
    totals["top_posts"] = top_rows
    return totals
