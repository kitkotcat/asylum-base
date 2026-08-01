from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from time import monotonic
from typing import Awaitable, Callable

from aiogram import Bot

from bot.app.config import Settings
from bot.app.db import Database
from bot.app.keyboards import draft_keyboard
from bot.app.services.parsers import (
    SourceCheckResult,
    check_google_play_update,
    check_page_changed,
    collect_rss_feed_drafts,
    render_draft,
)

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


async def notify_admins(
    bot: Bot,
    settings: Settings,
    db: Database,
    draft_ids: tuple[int, ...],
) -> None:
    if not settings.admin_ids:
        logger.warning(
            "ADMIN_IDS пуст: черновики некому отправлять"
        )
        return

    for draft_id in draft_ids:
        draft = await db.get_draft(draft_id)

        if draft is None:
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
                    "Не удалось отправить черновик %s "
                    "администратору %s",
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

    await db.mark_source_started(
        source_key,
        source_url,
    )

    try:
        result = await asyncio.wait_for(
            check(),
            timeout=SOURCE_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        duration_ms = int(
            (monotonic() - started) * 1000
        )
        error_text = (
            f"{type(exc).__name__}: {exc}"
        )

        await db.mark_source_error(
            source_key,
            source_url,
            error=error_text,
            duration_ms=duration_ms,
        )
        logger.exception(
            "Content Radar source failed: %s",
            source_key,
        )

        return (), f"{source_key}: {error_text}"

    duration_ms = int(
        (monotonic() - started) * 1000
    )

    await db.mark_source_success(
        source_key,
        source_url,
        items_count=result.items_count,
        duration_ms=duration_ms,
    )

    return result.draft_ids, None


def _rss_source_key(feed_url: str) -> str:
    digest = hashlib.sha1(
        feed_url.encode("utf-8")
    ).hexdigest()[:8]

    return f"rss:{digest}"


async def run_radar_once(
    bot: Bot,
    settings: Settings,
    db: Database,
    *,
    trigger_name: str = "scheduler",
) -> RadarRunResult:
    if RADAR_LOCK.locked():
        raise RadarBusyError(
            "Content Radar уже выполняет проверку"
        )

    async with RADAR_LOCK:
        run_id = await db.start_radar_run(trigger_name)
        draft_ids: list[int] = []
        errors: list[str] = []

        for feed_url in settings.rss_feed_urls:
            source_drafts, source_error = await _run_source(
                db=db,
                source_key=_rss_source_key(feed_url),
                source_url=feed_url,
                check=lambda feed_url=feed_url: (
                    collect_rss_feed_drafts(
                        db,
                        feed_url,
                    )
                ),
            )
            draft_ids.extend(source_drafts)

            if source_error:
                errors.append(source_error)

        if settings.lootbar_page_url:
            source_drafts, source_error = await _run_source(
                db=db,
                source_key="lootbar",
                source_url=settings.lootbar_page_url,
                check=lambda: check_page_changed(
                    db,
                    settings.lootbar_page_url,
                    kind="topup",
                    title="Изменилась страница LootBar",
                    summary=(
                        "Бот обнаружил изменение страницы "
                        "пополнения. Проверьте цены, наборы "
                        "и условия вручную перед публикацией."
                    ),
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
                check=lambda: check_google_play_update(
                    db,
                    settings.google_play_url,
                ),
            )
            draft_ids.extend(source_drafts)

            if source_error:
                errors.append(source_error)

        unique_draft_ids = tuple(
            dict.fromkeys(draft_ids)
        )

        if unique_draft_ids:
            await notify_admins(
                bot,
                settings,
                db,
                unique_draft_ids,
            )

        run_status = (
            "ok"
            if not errors
            else "partial_error"
        )

        await db.finish_radar_run(
            run_id,
            status=run_status,
            drafts_created=len(unique_draft_ids),
            error_count=len(errors),
        )

        return RadarRunResult(
            draft_ids=unique_draft_ids,
            errors=tuple(errors),
            trigger_name=trigger_name,
        )


async def run_scheduler(
    bot: Bot,
    settings: Settings,
    db: Database,
) -> None:
    await asyncio.sleep(10)

    while True:
        try:
            await run_radar_once(
                bot,
                settings,
                db,
                trigger_name="scheduler",
            )
        except RadarBusyError:
            logger.info(
                "Content Radar scheduler skipped: "
                "check is already running"
            )
        except Exception:
            logger.exception(
                "Unexpected Content Radar failure"
            )

        await asyncio.sleep(
            settings.parser_interval_minutes * 60
        )
