from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Awaitable, Callable

from aiogram import Bot

from bot.app.config import Settings
from bot.app.db import Database
from bot.app.keyboards import draft_keyboard
from bot.app.services.content import money
from bot.app.services.content_db import (
    count_recent_auto_deals,
    daily_stats,
    enqueue_draft,
    expire_promos,
    get_draft_with_payload,
    job_due,
    list_ready_queue,
    list_top_lootbar_packages,
    mark_job_run,
    mark_queue_status,
    save_draft_payload,
)
from bot.app.services.lootbar import check_lootbar_packages
from bot.app.services.parsers import (
    SourceCheckResult,
    check_google_play_update,
    collect_rss_feed_drafts,
    render_draft,
)
from bot.app.services.publisher import publish_draft

logger = logging.getLogger(__name__)

RADAR_LOCK = asyncio.Lock()
SOURCE_TIMEOUT_SECONDS = 55


class RadarBusyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RadarRunResult:
    draft_ids: tuple[int, ...]
    errors: tuple[str, ...]
    trigger_name: str
    auto_published: int = 0


async def _notify_admin_text(bot: Bot, settings: Settings, text: str) -> None:
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.exception("Не удалось отправить сообщение администратору %s", admin_id)


async def notify_admins(
    bot: Bot,
    settings: Settings,
    db: Database,
    draft_ids: tuple[int, ...],
) -> None:
    if not settings.admin_ids:
        logger.warning("ADMIN_IDS пуст: черновики некому отправлять")
        return

    for draft_id in draft_ids:
        draft = await get_draft_with_payload(db, draft_id)
        if draft is None or str(draft["status"]) != "pending":
            continue
        text = render_draft(
            title=str(draft["title"]),
            summary=str(draft["summary"]),
            link=str(draft["link"]),
        )
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(
                    admin_id,
                    text,
                    reply_markup=draft_keyboard(draft_id),
                    disable_web_page_preview=True,
                )
            except Exception:
                logger.exception(
                    "Не удалось отправить черновик %s администратору %s",
                    draft_id,
                    admin_id,
                )


async def _run_source(
    *,
    db: Database,
    source_key: str,
    source_url: str,
    check: Callable[[], Awaitable[SourceCheckResult]],
) -> tuple[tuple[int, ...], str | None]:
    started = monotonic()
    await db.mark_source_started(source_key, source_url)
    try:
        result = await asyncio.wait_for(check(), timeout=SOURCE_TIMEOUT_SECONDS)
    except Exception as exc:
        duration_ms = int((monotonic() - started) * 1000)
        error_text = f"{type(exc).__name__}: {exc}"
        await db.mark_source_error(
            source_key,
            source_url,
            error=error_text,
            duration_ms=duration_ms,
        )
        logger.exception("Content Radar source failed: %s", source_key)
        return (), f"{source_key}: {error_text}"

    duration_ms = int((monotonic() - started) * 1000)
    await db.mark_source_success(
        source_key,
        source_url,
        items_count=result.items_count,
        duration_ms=duration_ms,
    )
    return result.draft_ids, None


def _rss_source_key(feed_url: str) -> str:
    digest = hashlib.sha1(feed_url.encode("utf-8")).hexdigest()[:8]
    return f"rss:{digest}"


def _auto_eligible(settings: Settings, draft: dict) -> bool:
    kind = str(draft.get("kind") or "")
    if not settings.auto_publish_enabled_for(kind):
        return False
    metadata = draft.get("metadata") or {}
    if kind == "deal" and settings.publish_mode == "semi_auto":
        return bool(metadata.get("auto_eligible"))
    return True


async def route_drafts(
    bot: Bot,
    settings: Settings,
    db: Database,
    draft_ids: tuple[int, ...],
) -> tuple[int, tuple[int, ...]]:
    manual_ids: list[int] = []
    queued_count = 0

    for draft_id in draft_ids:
        draft = await get_draft_with_payload(db, draft_id)
        if draft is None:
            continue

        if not _auto_eligible(settings, draft):
            manual_ids.append(draft_id)
            continue

        kind = str(draft["kind"])
        if kind in {"deal", "deal_digest", "topup"}:
            recent_count = await count_recent_auto_deals(db, hours=6)
            if recent_count + queued_count >= settings.max_auto_posts_per_6_hours:
                manual_ids.append(draft_id)
                continue

        if await enqueue_draft(db, draft_id, kind, priority=20 if kind == "deal" else 50):
            queued_count += 1

    if manual_ids:
        await notify_admins(bot, settings, db, tuple(manual_ids))

    published = await process_publication_queue(bot, settings, db)
    return published, tuple(manual_ids)


async def process_publication_queue(
    bot: Bot,
    settings: Settings,
    db: Database,
) -> int:
    published = 0
    for queue_item in await list_ready_queue(db, limit=10):
        queue_id = int(queue_item["id"])
        draft_id = int(queue_item["draft_id"])
        await mark_queue_status(db, queue_id, "processing", increment_attempts=True)
        try:
            result = await publish_draft(
                bot,
                settings,
                db,
                draft_id,
                auto_published=True,
            )
            await mark_queue_status(db, queue_id, "published")
            if result is not None:
                published += 1
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            await mark_queue_status(db, queue_id, "failed", error=error)
            await _notify_admin_text(
                bot,
                settings,
                f"❌ Автопубликация черновика <code>{draft_id}</code> не выполнена:\n{html.escape(error)[:700]}",
            )
            logger.exception("Publication queue item failed: %s", queue_id)
    return published


def _deal_digest_signature(items: list[dict[str, object]]) -> str:
    normalized = [
        {
            "package_key": str(item.get("package_key") or ""),
            "name": str(item.get("name") or ""),
            "promo_price_minor": int(item.get("promo_price_minor") or 0),
            "official_price_minor": int(item.get("official_price_minor") or 0),
            "savings_minor": int(item.get("savings_minor") or 0),
            "currency": str(item.get("currency") or ""),
        }
        for item in items
    ]
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _latest_published_digest_signature(db: Database) -> str | None:
    async with db.connect() as connection:
        cursor = await connection.execute(
            """
            SELECT p.metadata_json
            FROM publication_log l
            JOIN content_payloads p ON p.draft_id = l.draft_id
            WHERE l.kind = 'deal_digest'
              AND l.status = 'published'
            ORDER BY l.published_at DESC, l.id DESC
            LIMIT 1
            """
        )
        row = await cursor.fetchone()

    if row is None:
        return None

    try:
        metadata = json.loads(str(row["metadata_json"] or "{}"))
    except (json.JSONDecodeError, TypeError):
        return None

    stored_signature = metadata.get("signature")
    if isinstance(stored_signature, str) and stored_signature:
        return stored_signature

    stored_items = metadata.get("items")
    if not isinstance(stored_items, list):
        return None

    valid_items = [item for item in stored_items if isinstance(item, dict)]
    return _deal_digest_signature(valid_items) if valid_items else None


async def create_daily_deals_digest(settings: Settings, db: Database) -> int | None:
    if not settings.lootbar_page_url or not settings.lootbar_affiliate_url:
        return None
    today = datetime.now(timezone.utc).date().isoformat()
    packages = await list_top_lootbar_packages(db, settings.lootbar_page_url, limit=3)
    if not packages:
        return None

    items = [
        {
            "package_key": str(row["package_key"]),
            "name": str(row["name"]),
            "promo_price_minor": int(row["promo_price_minor"]),
            "official_price_minor": int(row["official_price_minor"]),
            "savings_minor": int(row["savings_minor"]),
            "currency": str(row["currency"]),
        }
        for row in packages
    ]
    signature = _deal_digest_signature(items)
    if await _latest_published_digest_signature(db) == signature:
        logger.info("Daily deals digest is unchanged; publication skipped")
        return None

    draft_id = await db.create_draft(
        kind="deal_digest",
        source_url=settings.lootbar_page_url,
        item_uid=f"daily-deals:{today}:{signature[:16]}",
        title=f"Лучшие предложения дня — {today}",
        link=settings.lootbar_affiliate_url,
        summary="Ежедневная подборка трёх лучших предложений LootBar.",
    )
    if draft_id is None:
        return None
    await save_draft_payload(
        db,
        draft_id,
        entity_key=f"daily-deals:{signature}",
        metadata={
            "items": items,
            "signature": signature,
            "auto_eligible": True,
        },
    )
    return draft_id


async def send_daily_admin_report(bot: Bot, settings: Settings, db: Database) -> None:
    stats = await daily_stats(db)
    last_run = await db.get_last_radar_run()
    lines = [
        "📊 <b>Asylum Base — ежедневный отчёт</b>",
        "",
        f"Пользователей: <b>{stats['users']}</b>",
        f"Переходов через меню сегодня: <b>{stats['clicks_today']}</b>",
        f"Публикаций сегодня: <b>{stats['published_today']}</b>",
        f"Ошибок публикации: <b>{stats['failed_today']}</b>",
        f"Черновиков на проверке: <b>{stats['pending_drafts']}</b>",
        f"Активных промокодов: <b>{stats['active_promos']}</b>",
    ]
    if last_run is not None:
        lines.extend(
            [
                "",
                f"Последний Radar: <code>{html.escape(str(last_run['status']))}</code>",
                f"Ошибок источников: <b>{last_run['error_count']}</b>",
            ]
        )
    await _notify_admin_text(bot, settings, "\n".join(lines))


async def run_daily_jobs(bot: Bot, settings: Settings, db: Database) -> None:
    await expire_promos(db)

    if settings.daily_deals_digest_enabled and await job_due(
        db, "daily-deals-digest", hour_utc=settings.daily_deals_digest_hour_utc
    ):
        draft_id = await create_daily_deals_digest(settings, db)
        if draft_id is not None:
            if settings.auto_publish_enabled_for("deal_digest"):
                await enqueue_draft(db, draft_id, "deal_digest", priority=40)
                await process_publication_queue(bot, settings, db)
            else:
                await notify_admins(bot, settings, db, (draft_id,))
        await mark_job_run(db, "daily-deals-digest")

    if settings.daily_admin_report_enabled and await job_due(
        db, "daily-admin-report", hour_utc=settings.daily_admin_report_hour_utc
    ):
        await send_daily_admin_report(bot, settings, db)
        await mark_job_run(db, "daily-admin-report")


async def run_radar_once(
    bot: Bot,
    settings: Settings,
    db: Database,
    *,
    trigger_name: str = "scheduler",
) -> RadarRunResult:
    if RADAR_LOCK.locked():
        raise RadarBusyError("Content Radar уже выполняет проверку")

    async with RADAR_LOCK:
        run_id = await db.start_radar_run(trigger_name)
        draft_ids: list[int] = []
        errors: list[str] = []

        for feed_url in settings.rss_feed_urls:
            source_drafts, source_error = await _run_source(
                db=db,
                source_key=_rss_source_key(feed_url),
                source_url=feed_url,
                check=lambda feed_url=feed_url: collect_rss_feed_drafts(db, feed_url),
            )
            draft_ids.extend(source_drafts)
            if source_error:
                errors.append(source_error)

        if settings.lootbar_page_url:
            source_drafts, source_error = await _run_source(
                db=db,
                source_key="lootbar",
                source_url=settings.lootbar_page_url,
                check=lambda: check_lootbar_packages(
                    db,
                    page_url=settings.lootbar_page_url,
                    affiliate_url=settings.lootbar_affiliate_url,
                    min_price_drop_percent=settings.min_price_drop_percent,
                    min_savings_increase_cents=settings.min_savings_increase_cents,
                ),
            )
            draft_ids.extend(source_drafts)
            if source_error:
                errors.append(source_error)

        if settings.google_play_url:
            source_drafts, source_error = await _run_source(
                db=db,
                source_key="google_play",
                source_url=settings.google_play_url,
                check=lambda: check_google_play_update(db, settings.google_play_url),
            )
            draft_ids.extend(source_drafts)
            if source_error:
                errors.append(source_error)

        unique_draft_ids = tuple(dict.fromkeys(draft_ids))
        auto_published = 0
        if unique_draft_ids:
            auto_published, _ = await route_drafts(bot, settings, db, unique_draft_ids)

        await db.finish_radar_run(
            run_id,
            status="ok" if not errors else "partial_error",
            drafts_created=len(unique_draft_ids),
            error_count=len(errors),
        )
        return RadarRunResult(
            draft_ids=unique_draft_ids,
            errors=tuple(errors),
            trigger_name=trigger_name,
            auto_published=auto_published,
        )


async def run_scheduler(bot: Bot, settings: Settings, db: Database) -> None:
    await asyncio.sleep(10)
    while True:
        try:
            await process_publication_queue(bot, settings, db)
            await run_radar_once(bot, settings, db, trigger_name="scheduler")
            await run_daily_jobs(bot, settings, db)
        except RadarBusyError:
            logger.info("Content Radar scheduler skipped: check is already running")
        except Exception:
            logger.exception("Unexpected scheduler failure")
        await asyncio.sleep(settings.parser_interval_minutes * 60)
