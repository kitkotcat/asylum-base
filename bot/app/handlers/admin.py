from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.app.config import Settings
from bot.app.db import Database
from bot.app.services.parsers import render_public_post
from bot.app.services.publisher import publish
from bot.app.services.scheduler import (
    RadarBusyError,
    run_radar_once,
)

router = Router(name=__name__)


def _is_admin(
    user_id: int | None,
    settings: Settings,
) -> bool:
    return (
        user_id is not None
        and user_id in settings.admin_ids
    )


@router.message(Command("promo_add"))
async def promo_add(
    message: Message,
    settings: Settings,
    db: Database,
) -> None:
    user_id = (
        message.from_user.id
        if message.from_user
        else None
    )

    if not _is_admin(user_id, settings):
        await message.answer(
            "Команда доступна только администратору."
        )
        return

    payload = (
        message.text or ""
    ).partition(" ")[2].strip()
    parts = [
        part.strip()
        for part in payload.split("|")
    ]

    if len(parts) != 3 or not all(parts):
        await message.answer(
            "Формат:\n"
            "<code>/promo_add CODE | "
            "Награда | Источник</code>"
        )
        return

    code, reward, source = parts
    promo_id = await db.add_promo(
        code,
        reward,
        source,
    )

    await message.answer(
        "✅ Промокод сохранён. "
        f"ID: <code>{promo_id}</code>"
    )


@router.message(Command("radar_status"))
async def radar_status(
    message: Message,
    settings: Settings,
    db: Database,
) -> None:
    user_id = (
        message.from_user.id
        if message.from_user
        else None
    )

    if not _is_admin(user_id, settings):
        await message.answer(
            "Команда доступна только администратору."
        )
        return

    last_run = await db.get_last_radar_run()
    sources = await db.list_source_statuses()

    lines = [
        "📡 <b>Content Radar</b>",
        "",
        f"RSS-источников: <b>"
        f"{len(settings.rss_feed_urls)}</b>",
        "LootBar monitor: <b>"
        f"{'ON' if settings.lootbar_page_url else 'OFF'}"
        "</b>",
        "Google Play monitor: <b>"
        f"{'ON' if settings.google_play_url else 'OFF'}"
        "</b>",
        f"Интервал: <b>"
        f"{settings.parser_interval_minutes} мин.</b>",
    ]

    if last_run is not None:
        lines.extend(
            [
                "",
                "<b>Последний запуск</b>",
                "Статус: "
                f"<code>{html.escape(str(last_run['status']))}"
                "</code>",
                "Триггер: "
                f"<code>{html.escape(str(last_run['trigger_name']))}"
                "</code>",
                "Черновиков: "
                f"<b>{last_run['drafts_created']}</b>",
                "Ошибок: "
                f"<b>{last_run['error_count']}</b>",
                "Завершён: "
                f"<code>{html.escape(str(last_run['finished_at']))}"
                "</code>",
            ]
        )

    if sources:
        lines.extend(
            [
                "",
                "<b>Источники</b>",
            ]
        )

        for source in sources:
            icon = (
                "✅"
                if source["status"] == "ok"
                else "❌"
                if source["status"] == "error"
                else "⏳"
            )
            lines.append(
                f"{icon} <code>"
                f"{html.escape(str(source['source_key']))}"
                "</code> — "
                f"{html.escape(str(source['status']))}, "
                f"{source['last_duration_ms']} мс"
            )

            if source["last_error"]:
                lines.append(
                    "└ "
                    f"{html.escape(str(source['last_error']))[:240]}"
                )

    await message.answer("\n".join(lines))


@router.message(Command("radar_check"))
async def radar_check(
    message: Message,
    settings: Settings,
    db: Database,
) -> None:
    user_id = (
        message.from_user.id
        if message.from_user
        else None
    )

    if not _is_admin(user_id, settings):
        await message.answer(
            "Команда доступна только администратору."
        )
        return

    status_message = await message.answer(
        "🔎 Проверяю источники…"
    )

    try:
        result = await run_radar_once(
            bot=message.bot,
            settings=settings,
            db=db,
            trigger_name="manual",
        )
    except RadarBusyError:
        await status_message.edit_text(
            "⏳ Content Radar уже выполняет проверку. "
            "Повторите команду позже."
        )
        return

    response = [
        "✅ Проверка завершена.",
        f"Новых черновиков: "
        f"<b>{len(result.draft_ids)}</b>",
        f"Ошибок источников: "
        f"<b>{len(result.errors)}</b>",
    ]

    if result.errors:
        response.extend(
            [
                "",
                "<b>Ошибки</b>",
                *[
                    f"• {html.escape(error)[:350]}"
                    for error in result.errors
                ],
            ]
        )

    response.extend(
        [
            "",
            "При первом запуске бот создаёт "
            "базовую отметку и не присылает "
            "старые материалы.",
        ]
    )

    await status_message.edit_text(
        "\n".join(response)
    )


@router.message(Command("post"))
async def manual_post(
    message: Message,
    settings: Settings,
) -> None:
    user_id = (
        message.from_user.id
        if message.from_user
        else None
    )

    if not _is_admin(user_id, settings):
        await message.answer(
            "Команда доступна только администратору."
        )
        return

    payload = (
        message.text or ""
    ).partition(" ")[2].strip()
    kind, separator, text = payload.partition("|")
    kind = kind.strip().lower()
    text = text.strip()

    if (
        not separator
        or kind not in {"news", "promo", "topup"}
        or not text
    ):
        await message.answer(
            "Формат:\n"
            "<code>/post news | Текст новости</code>\n"
            "<code>/post promo | Текст промо</code>\n"
            "<code>/post topup | Текст предложения</code>"
        )
        return

    try:
        await publish(
            bot=message.bot,
            settings=settings,
            kind=kind,
            text=html.escape(text),
        )
    except RuntimeError as exc:
        await message.answer(
            f"⚠️ {html.escape(str(exc))}"
        )
        return

    await message.answer("✅ Пост опубликован.")


@router.callback_query(F.data.startswith("draft:"))
async def moderate_draft(
    callback: CallbackQuery,
    settings: Settings,
    db: Database,
) -> None:
    if not _is_admin(
        callback.from_user.id,
        settings,
    ):
        await callback.answer(
            "Недостаточно прав",
            show_alert=True,
        )
        return

    if callback.data is None:
        return

    try:
        _, action, draft_id_raw = (
            callback.data.split(":")
        )
        draft_id = int(draft_id_raw)
    except (ValueError, TypeError):
        await callback.answer(
            "Некорректные данные",
            show_alert=True,
        )
        return

    draft = await db.get_draft(draft_id)

    if draft is None:
        await callback.answer(
            "Черновик не найден",
            show_alert=True,
        )
        return

    if str(draft["status"]) != "pending":
        await callback.answer(
            "Черновик уже обработан",
            show_alert=True,
        )
        return

    if action == "reject":
        await db.set_draft_status(
            draft_id,
            "rejected",
        )
        await callback.answer("Черновик отклонён")

        if callback.message is not None:
            await callback.message.edit_reply_markup(
                reply_markup=None
            )

        return

    if action != "approve":
        await callback.answer(
            "Неизвестное действие",
            show_alert=True,
        )
        return

    text = render_public_post(
        title=str(draft["title"]),
        summary=str(draft["summary"]),
        link=str(draft["link"]),
    )

    try:
        await publish(
            bot=callback.bot,
            settings=settings,
            kind=str(draft["kind"]),
            text=text,
        )
    except RuntimeError as exc:
        await callback.answer(
            str(exc),
            show_alert=True,
        )
        return

    await db.set_draft_status(
        draft_id,
        "published",
    )
    await callback.answer("Опубликовано")

    if callback.message is not None:
        await callback.message.edit_reply_markup(
            reply_markup=None
        )
