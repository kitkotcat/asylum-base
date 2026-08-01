from __future__ import annotations

import html
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.app.config import Settings
from bot.app.db import Database
from bot.app.keyboards import admin_panel, draft_keyboard
from bot.app.services.content_db import (
    daily_stats,
    deactivate_promo_by_code,
    get_draft_with_payload,
    list_pending_drafts,
    set_promo_metadata,
)
from bot.app.services.parsers import render_draft
from bot.app.services.publisher import publish, publish_draft
from bot.app.services.scheduler import (
    RadarBusyError,
    run_radar_once,
    send_daily_admin_report,
)

router = Router(name=__name__)


def _is_admin(user_id: int | None, settings: Settings) -> bool:
    return user_id is not None and user_id in settings.admin_ids


async def _deny(message: Message) -> None:
    await message.answer("Команда доступна только администратору.")


def _admin_id(message: Message) -> int | None:
    return message.from_user.id if message.from_user else None


def _parse_expiry(value: str) -> str | None:
    value = value.strip()
    if not value or value in {"-", "none", "нет"}:
        return None
    parsed = datetime.strptime(value, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )
    return parsed.isoformat(timespec="seconds")


@router.message(Command("admin"))
async def admin_command(message: Message, settings: Settings) -> None:
    if not _is_admin(_admin_id(message), settings):
        await _deny(message)
        return
    await message.answer(
        "⚙️ <b>Админ-панель Asylum Base</b>\n\n"
        f"Режим публикации: <code>{settings.publish_mode}</code>\n"
        f"Автоскидки: <b>{'ON' if settings.auto_publish_deals else 'OFF'}</b>\n"
        f"Автоновости: <b>{'ON' if settings.auto_publish_news else 'OFF'}</b>\n"
        f"Google Play: <b>{'ON' if settings.auto_publish_google_play else 'OFF'}</b>",
        reply_markup=admin_panel(),
    )


@router.message(Command("id"))
async def show_ids(message: Message, settings: Settings) -> None:
    if not _is_admin(_admin_id(message), settings):
        await _deny(message)
        return
    await message.answer(
        "<b>Технические идентификаторы</b>\n"
        f"user_id: <code>{message.from_user.id if message.from_user else '—'}</code>\n"
        f"chat_id: <code>{message.chat.id}</code>\n"
        f"message_thread_id: <code>{message.message_thread_id}</code>"
    )


@router.message(Command("promo_add"))
async def promo_add(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(_admin_id(message), settings):
        await _deny(message)
        return
    payload = (message.text or "").partition(" ")[2].strip()
    parts = [part.strip() for part in payload.split("|")]
    if len(parts) < 3 or not all(parts[:3]):
        await message.answer(
            "Формат:\n"
            "<code>/promo_add CODE | Награда | Источник | 2026-12-31 | Global</code>\n"
            "Дата и регион необязательны."
        )
        return
    code, reward, source = parts[:3]
    try:
        expires_at = _parse_expiry(parts[3]) if len(parts) >= 4 else None
    except ValueError:
        await message.answer("Дата должна быть в формате YYYY-MM-DD.")
        return
    region = parts[4] if len(parts) >= 5 and parts[4] else "Global"
    promo_id = await db.add_promo(code, reward, source)
    await set_promo_metadata(
        db,
        promo_id,
        region=region,
        expires_at=expires_at,
        verification_status="verified",
    )
    await message.answer(f"✅ Промокод сохранён. ID: <code>{promo_id}</code>")


@router.message(Command("promo_expire"))
async def promo_expire(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(_admin_id(message), settings):
        await _deny(message)
        return
    code = (message.text or "").partition(" ")[2].strip()
    if not code:
        await message.answer("Формат: <code>/promo_expire CODE</code>")
        return
    changed = await deactivate_promo_by_code(db, code)
    await message.answer("✅ Промокод отключён." if changed else "Промокод не найден.")


async def _radar_status_text(settings: Settings, db: Database) -> str:
    last_run = await db.get_last_radar_run()
    sources = await db.list_source_statuses()
    lines = [
        "📡 <b>Content Platform</b>",
        "",
        f"Режим: <code>{settings.publish_mode}</code>",
        f"Интервал Radar: <b>{settings.parser_interval_minutes} мин.</b>",
        f"RSS: <b>{len(settings.rss_feed_urls)}</b>",
        f"LootBar: <b>{'ON' if settings.lootbar_page_url else 'OFF'}</b>",
        f"Google Play: <b>{'ON' if settings.google_play_url else 'OFF'}</b>",
        f"Автоскидки: <b>{'ON' if settings.auto_publish_deals else 'OFF'}</b>",
        f"Автоновости: <b>{'ON' if settings.auto_publish_news else 'OFF'}</b>",
        f"Дайджест: <b>{'ON' if settings.daily_deals_digest_enabled else 'OFF'}</b>",
    ]
    if last_run is not None:
        lines.extend(
            [
                "",
                "<b>Последний запуск</b>",
                f"Статус: <code>{html.escape(str(last_run['status']))}</code>",
                f"Черновиков: <b>{last_run['drafts_created']}</b>",
                f"Ошибок: <b>{last_run['error_count']}</b>",
                f"Завершён: <code>{html.escape(str(last_run['finished_at']))}</code>",
            ]
        )
    if sources:
        lines.extend(["", "<b>Источники</b>"])
        for source in sources:
            icon = "✅" if source["status"] == "ok" else "❌" if source["status"] == "error" else "⏳"
            lines.append(
                f"{icon} <code>{html.escape(str(source['source_key']))}</code> — "
                f"{source['last_items_count']} объектов, {source['last_duration_ms']} мс"
            )
            if source["last_error"]:
                lines.append(f"└ {html.escape(str(source['last_error']))[:240]}")
    return "\n".join(lines)


@router.message(Command("radar_status"))
async def radar_status(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(_admin_id(message), settings):
        await _deny(message)
        return
    await message.answer(await _radar_status_text(settings, db))


async def _run_radar_message(message: Message, settings: Settings, db: Database) -> None:
    status_message = await message.answer("🔎 Проверяю источники…")
    try:
        result = await run_radar_once(
            bot=message.bot,
            settings=settings,
            db=db,
            trigger_name="manual",
        )
    except RadarBusyError:
        await status_message.edit_text("⏳ Content Radar уже выполняет проверку.")
        return
    lines = [
        "✅ Проверка завершена.",
        f"Новых черновиков: <b>{len(result.draft_ids)}</b>",
        f"Автопубликаций: <b>{result.auto_published}</b>",
        f"Ошибок источников: <b>{len(result.errors)}</b>",
    ]
    if result.errors:
        lines.extend(["", *[f"• {html.escape(error)[:350]}" for error in result.errors]])
    await status_message.edit_text("\n".join(lines))


@router.message(Command("radar_check"))
async def radar_check(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(_admin_id(message), settings):
        await _deny(message)
        return
    await _run_radar_message(message, settings, db)


@router.message(Command("report"))
async def report(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(_admin_id(message), settings):
        await _deny(message)
        return
    stats = await daily_stats(db)
    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"Пользователей: <b>{stats['users']}</b>\n"
        f"Переходов через меню сегодня: <b>{stats['clicks_today']}</b>\n"
        f"Публикаций сегодня: <b>{stats['published_today']}</b>\n"
        f"Ошибок публикации: <b>{stats['failed_today']}</b>\n"
        f"Черновиков: <b>{stats['pending_drafts']}</b>\n"
        f"Активных промокодов: <b>{stats['active_promos']}</b>"
    )


@router.message(Command("post"))
async def manual_post(message: Message, settings: Settings) -> None:
    if not _is_admin(_admin_id(message), settings):
        await _deny(message)
        return
    payload = (message.text or "").partition(" ")[2].strip()
    kind, separator, text = payload.partition("|")
    kind = kind.strip().lower()
    text = text.strip()
    if not separator or kind not in {"news", "promo", "topup"} or not text:
        await message.answer("Формат: <code>/post news | Текст публикации</code>")
        return
    await publish(message.bot, settings, kind, html.escape(text))
    await message.answer("✅ Пост опубликован.")


async def _show_pending(message: Message, db: Database) -> None:
    drafts = await list_pending_drafts(db, limit=10)
    if not drafts:
        await message.answer("📝 Нет черновиков на проверке.")
        return
    await message.answer(f"📝 Черновиков на проверке: <b>{len(drafts)}</b>")
    for row in drafts:
        text = render_draft(str(row["title"]), str(row["summary"]), str(row["link"]))
        await message.answer(text, reply_markup=draft_keyboard(int(row["id"])), disable_web_page_preview=True)


@router.callback_query(F.data.startswith("admin:"))
async def admin_callback(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    if not _is_admin(callback.from_user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    action = (callback.data or "").partition(":")[2]
    await callback.answer()
    if callback.message is None:
        return
    if action == "radar":
        await _run_radar_message(callback.message, settings, db)
    elif action == "drafts":
        await _show_pending(callback.message, db)
    elif action == "report":
        await send_daily_admin_report(callback.bot, settings, db)
    elif action == "status":
        await callback.message.answer(await _radar_status_text(settings, db))


@router.callback_query(F.data.startswith("draft:"))
async def moderate_draft(callback: CallbackQuery, settings: Settings, db: Database) -> None:
    if not _is_admin(callback.from_user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    try:
        _, action, raw_id = (callback.data or "").split(":")
        draft_id = int(raw_id)
    except (ValueError, TypeError):
        await callback.answer("Некорректные данные", show_alert=True)
        return
    draft = await get_draft_with_payload(db, draft_id)
    if draft is None:
        await callback.answer("Черновик не найден", show_alert=True)
        return
    if str(draft["status"]) != "pending":
        await callback.answer("Черновик уже обработан", show_alert=True)
        return
    if action == "reject":
        await db.set_draft_status(draft_id, "rejected")
        await callback.answer("Черновик отклонён")
    elif action == "approve":
        await publish_draft(callback.bot, settings, db, draft_id, auto_published=False)
        await callback.answer("Опубликовано")
    else:
        await callback.answer("Неизвестное действие", show_alert=True)
        return
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)
