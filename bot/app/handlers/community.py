from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    Message,
    MessageReactionCountUpdated,
    MessageReactionUpdated,
)

from bot.app.config import Settings
from bot.app.db import Database, utc_now
from bot.app.keyboards import draft_keyboard, simple_back_keyboard, suggestion_keyboard
from bot.app.services.community_content import (
    format_local_datetime,
    parse_local_datetime,
    render_hero,
    render_squad,
    split_csv,
)
from bot.app.services.community_db import (
    EDITORIAL_KINDS,
    add_editorial_item,
    add_game_event,
    add_suggestion,
    analytics_summary,
    count_recent_suggestions,
    get_hero,
    get_suggestion,
    list_editorial_queue,
    list_heroes,
    list_pending_suggestions,
    list_squads,
    list_upcoming_events,
    replace_reaction_totals,
    replace_user_reactions,
    set_editorial_status,
    set_suggestion_status,
    upsert_entity_editorial_item,
    upsert_hero,
    upsert_squad,
)
from bot.app.services.content_db import save_draft_payload

router = Router(name=__name__)


def _message_payload(message: Message) -> str:
    raw = message.text or message.caption or ""
    return raw.partition(" ")[2].strip()


def _is_admin(user_id: int | None, settings: Settings) -> bool:
    return user_id is not None and user_id in settings.admin_ids


def _photo_file_id(message: Message) -> str:
    return message.photo[-1].file_id if message.photo else ""


def _plain_hero_body(
    *,
    role: str,
    strengths: list[str],
    weaknesses: list[str],
    strategy: str,
) -> str:
    lines = [f"🎯 Роль: {role or 'не указана'}"]
    if strengths:
        lines.extend(["", "✅ Сильные стороны", *[f"• {item}" for item in strengths]])
    if weaknesses:
        lines.extend(["", "⚠️ Слабые стороны", *[f"• {item}" for item in weaknesses]])
    if strategy:
        lines.extend(["", "🧠 Стратегия", strategy])
    return "\n".join(lines)


def _plain_squad_body(
    *,
    mode: str,
    members: list[str],
    synergy: str,
    strategy: str,
) -> str:
    lines = [f"🎮 Режим: {mode or 'универсальный'}"]
    if members:
        lines.extend(["", "👥 Герои", *[f"• {item}" for item in members]])
    if synergy:
        lines.extend(["", "🔗 Почему работает", synergy])
    if strategy:
        lines.extend(["", "🧠 Как играть", strategy])
    return "\n".join(lines)


@router.message(Command("heroes"))
async def heroes_command(message: Message, db: Database) -> None:
    payload = _message_payload(message)
    if payload:
        hero = await get_hero(db, payload)
        if hero is None:
            await message.answer("Герой не найден. Проверьте имя.")
            return
        await message.answer(render_hero(hero), reply_markup=simple_back_keyboard())
        return

    heroes = await list_heroes(db, limit=30)
    if not heroes:
        await message.answer("⚔️ База героев пока пустая.")
        return
    lines = ["⚔️ <b>Герои Last Asylum</b>", ""]
    for hero in heroes:
        role = html.escape(str(hero.get("role") or "роль не указана"))
        lines.append(f"• <b>{html.escape(str(hero['name_ru']))}</b> — {role}")
    lines.extend(["", "Подробнее: <code>/heroes Имя героя</code>"])
    await message.answer("\n".join(lines), reply_markup=simple_back_keyboard())


@router.message(Command("squads"))
async def squads_command(message: Message, db: Database) -> None:
    squads = await list_squads(db, limit=20)
    if not squads:
        await message.answer("🧩 База составов пока пустая.")
        return
    for squad in squads[:5]:
        await message.answer(render_squad(squad), reply_markup=simple_back_keyboard())


@router.message(Command("events"))
async def events_command(message: Message, settings: Settings, db: Database) -> None:
    events = await list_upcoming_events(db, limit=10)
    if not events:
        await message.answer("📅 Ближайших событий в календаре пока нет.")
        return
    lines = ["📅 <b>Календарь событий</b>", ""]
    for event in events:
        start = format_local_datetime(
            str(event["starts_at"]),
            offset_hours=settings.editorial_timezone_offset_hours,
        )
        lines.append(f"• <b>{html.escape(str(event['title']))}</b> — {start}")
    await message.answer("\n".join(lines), reply_markup=simple_back_keyboard())


@router.message(Command("suggest"))
async def suggest_command(message: Message, db: Database) -> None:
    if message.from_user is None:
        return
    parts = [part.strip() for part in _message_payload(message).split("|")]
    if len(parts) < 3:
        await message.answer(
            "Формат: <code>/suggest TYPE | Заголовок | Текст</code>\n"
            "TYPE: guide, hero, squad, event, alliance"
        )
        return
    kind, title, body = parts[:3]
    kind = kind.casefold()
    if kind not in EDITORIAL_KINDS or not title or not body:
        await message.answer("Некорректная категория, заголовок или текст.")
        return
    if len(title) > 120 or len(body) > 2500:
        await message.answer("Лимит: заголовок до 120, текст до 2500 символов.")
        return
    if await count_recent_suggestions(
        db,
        telegram_id=message.from_user.id,
        hours=24,
    ) >= 3:
        await message.answer("Лимит: не более трёх предложений за 24 часа.")
        return
    suggestion_id = await add_suggestion(
        db,
        telegram_id=message.from_user.id,
        username=message.from_user.username or "",
        kind=kind,
        title=title,
        body=body,
        image_file_id=_photo_file_id(message),
    )
    await message.answer(
        f"✅ Предложение принято и отправлено на модерацию. ID: <code>{suggestion_id}</code>"
    )


@router.message(Command("hero_add"))
async def hero_add_command(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        await message.answer("Команда доступна только администратору.")
        return
    parts = [part.strip() for part in _message_payload(message).split("|")]
    if len(parts) < 6 or not parts[0]:
        await message.answer(
            "Формат:\n"
            "<code>/hero_add Имя RU | Имя EN | Роль | Сильные через запятую | "
            "Слабые через запятую | Стратегия | Редкость | Фракция | Источник</code>"
        )
        return
    name_ru, name_en, role, strengths_raw, weaknesses_raw, strategy = parts[:6]
    rarity = parts[6] if len(parts) > 6 else ""
    faction = parts[7] if len(parts) > 7 else ""
    source_url = parts[8] if len(parts) > 8 else ""
    strengths = split_csv(strengths_raw)
    weaknesses = split_csv(weaknesses_raw)
    image_file_id = _photo_file_id(message)
    hero_id = await upsert_hero(
        db,
        name_ru=name_ru,
        name_en=name_en,
        role=role,
        rarity=rarity,
        faction=faction,
        strengths=strengths,
        weaknesses=weaknesses,
        strategy=strategy,
        image_file_id=image_file_id,
        source_url=source_url,
    )
    editorial_id = await upsert_entity_editorial_item(
        db,
        kind="hero",
        entity_key=f"hero:{hero_id}",
        title=name_ru,
        body=_plain_hero_body(
            role=role,
            strengths=strengths,
            weaknesses=weaknesses,
            strategy=strategy,
        ),
        image_file_id=image_file_id,
        source_url=source_url,
        next_publish_at=utc_now(),
        repeat_days=30,
    )
    await message.answer(
        f"✅ Герой сохранён: <code>{hero_id}</code>. "
        f"Автопост: <code>{editorial_id}</code>."
    )


@router.message(Command("squad_add"))
async def squad_add_command(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        await message.answer("Команда доступна только администратору.")
        return
    parts = [part.strip() for part in _message_payload(message).split("|")]
    if len(parts) < 5:
        await message.answer(
            "Формат: <code>/squad_add Название | Режим | Герои через запятую | "
            "Связка | Стратегия | Источник</code>"
        )
        return
    name, mode, members_raw, synergy, strategy = parts[:5]
    source_url = parts[5] if len(parts) > 5 else ""
    members = split_csv(members_raw)
    image_file_id = _photo_file_id(message)
    squad_id = await upsert_squad(
        db,
        name=name,
        mode=mode,
        members=members,
        synergy=synergy,
        strategy=strategy,
        image_file_id=image_file_id,
        source_url=source_url,
    )
    editorial_id = await upsert_entity_editorial_item(
        db,
        kind="squad",
        entity_key=f"squad:{squad_id}",
        title=name,
        body=_plain_squad_body(
            mode=mode,
            members=members,
            synergy=synergy,
            strategy=strategy,
        ),
        image_file_id=image_file_id,
        source_url=source_url,
        next_publish_at=utc_now(),
        repeat_days=30,
    )
    await message.answer(
        f"✅ Состав сохранён: <code>{squad_id}</code>. "
        f"Автопост: <code>{editorial_id}</code>."
    )


@router.message(Command("event_add"))
async def event_add_command(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        await message.answer("Команда доступна только администратору.")
        return
    parts = [part.strip() for part in _message_payload(message).split("|")]
    if len(parts) < 4:
        await message.answer(
            "Формат: <code>/event_add Название | 2026-08-20 18:00 | "
            "2026-08-21 18:00 или - | Описание | Источник</code>"
        )
        return
    try:
        starts_at = parse_local_datetime(
            parts[1], offset_hours=settings.editorial_timezone_offset_hours
        )
        ends_at = None if parts[2] in {"", "-"} else parse_local_datetime(
            parts[2], offset_hours=settings.editorial_timezone_offset_hours
        )
    except ValueError:
        await message.answer("Дата должна быть в формате YYYY-MM-DD HH:MM.")
        return
    title, description = parts[0], parts[3]
    source_url = parts[4] if len(parts) > 4 else ""
    event_id = await add_game_event(
        db,
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        description=description,
        source_url=source_url,
    )
    start_dt = datetime.fromisoformat(starts_at)
    announce_at = max(datetime.now(timezone.utc), start_dt - timedelta(hours=24))
    event_body_lines = [
        "▶️ Начало: "
        + format_local_datetime(
            starts_at,
            offset_hours=settings.editorial_timezone_offset_hours,
        )
    ]
    if ends_at:
        event_body_lines.append(
            "⏹ Завершение: "
            + format_local_datetime(
                ends_at,
                offset_hours=settings.editorial_timezone_offset_hours,
            )
        )
    if description:
        event_body_lines.extend(["", description])
    editorial_id = await upsert_entity_editorial_item(
        db,
        kind="event",
        entity_key=f"event:{event_id}",
        title=title,
        body="\n".join(event_body_lines),
        source_url=source_url,
        next_publish_at=announce_at.isoformat(timespec="seconds"),
        repeat_days=0,
    )
    await message.answer(
        f"✅ Событие сохранено: <code>{event_id}</code>. "
        f"Напоминание: <code>{editorial_id}</code>."
    )


@router.message(Command("content_add"))
async def content_add_command(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        await message.answer("Команда доступна только администратору.")
        return
    parts = [part.strip() for part in _message_payload(message).split("|")]
    if len(parts) < 5:
        await message.answer(
            "Формат: <code>/content_add TYPE | 2026-08-20 12:00 | "
            "Повтор дней (0=один раз) | Заголовок | Текст | Источник</code>"
        )
        return
    kind = parts[0].casefold()
    try:
        scheduled_at = parse_local_datetime(
            parts[1], offset_hours=settings.editorial_timezone_offset_hours
        )
        repeat_days = int(parts[2])
    except ValueError:
        await message.answer("Проверьте дату и количество дней повтора.")
        return
    if kind not in EDITORIAL_KINDS or repeat_days < 0:
        await message.answer("Некорректный тип или период повтора.")
        return
    source_url = parts[5] if len(parts) > 5 else ""
    editorial_id = await add_editorial_item(
        db,
        kind=kind,
        entity_key=f"manual:{kind}:{parts[3]}",
        title=parts[3],
        body=parts[4],
        image_file_id=_photo_file_id(message),
        source_url=source_url,
        next_publish_at=scheduled_at,
        repeat_days=repeat_days,
    )
    await message.answer(f"✅ Контент поставлен в очередь. ID: <code>{editorial_id}</code>")


@router.message(Command("content_queue"))
async def content_queue_command(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        await message.answer("Команда доступна только администратору.")
        return
    rows = await list_editorial_queue(db, limit=20)
    if not rows:
        await message.answer("Очередь контента пуста.")
        return
    lines = ["🗓 <b>Очередь контента</b>", ""]
    for row in rows:
        local_time = format_local_datetime(
            str(row["next_publish_at"]),
            offset_hours=settings.editorial_timezone_offset_hours,
        )
        lines.append(
            f"#{row['id']} <code>{row['kind']}</code> — "
            f"{html.escape(str(row['title']))} — {local_time} — повтор {row['repeat_days']} дн."
        )
    await message.answer("\n".join(lines))


@router.message(Command("content_pause"))
async def content_pause_command(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        await message.answer("Команда доступна только администратору.")
        return
    try:
        editorial_id = int(_message_payload(message))
    except ValueError:
        await message.answer("Формат: <code>/content_pause ID</code>")
        return
    changed = await set_editorial_status(db, editorial_id, status="paused")
    await message.answer("⏸ Контент остановлен." if changed else "ID не найден.")


@router.message(Command("content_resume"))
async def content_resume_command(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        await message.answer("Команда доступна только администратору.")
        return
    try:
        editorial_id = int(_message_payload(message))
    except ValueError:
        await message.answer("Формат: <code>/content_resume ID</code>")
        return
    changed = await set_editorial_status(db, editorial_id, status="approved")
    await message.answer("▶️ Контент возвращён в очередь." if changed else "ID не найден.")


@router.message(Command("suggestions"))
async def suggestions_command(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        await message.answer("Команда доступна только администратору.")
        return
    rows = await list_pending_suggestions(db, limit=20)
    if not rows:
        await message.answer("Предложений на модерации нет.")
        return
    for row in rows:
        author = f"@{row['username']}" if row["username"] else str(row["telegram_id"])
        text = (
            f"💡 <b>Предложение #{row['id']}</b>\n"
            f"Автор: <code>{html.escape(author)}</code>\n"
            f"Тип: <code>{row['kind']}</code>\n\n"
            f"<b>{html.escape(str(row['title']))}</b>\n"
            f"{html.escape(str(row['body']))}"
        )
        await message.answer(text, reply_markup=suggestion_keyboard(int(row["id"])))


@router.callback_query(F.data.startswith("suggest:"))
async def suggestion_callback(
    callback: CallbackQuery,
    settings: Settings,
    db: Database,
) -> None:
    if not _is_admin(callback.from_user.id, settings):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    try:
        _, action, raw_id = (callback.data or "").split(":")
        suggestion_id = int(raw_id)
    except (ValueError, TypeError):
        await callback.answer("Некорректные данные", show_alert=True)
        return
    suggestion = await get_suggestion(db, suggestion_id)
    if suggestion is None or str(suggestion["status"]) != "pending":
        await callback.answer("Предложение уже обработано", show_alert=True)
        return
    if action == "reject":
        await set_suggestion_status(db, suggestion_id, status="rejected")
        await callback.answer("Отклонено")
    elif action == "approve":
        draft_id = await db.create_draft(
            kind=str(suggestion["kind"]),
            source_url=f"internal://suggestion/{suggestion_id}",
            item_uid=f"suggestion:{suggestion_id}",
            title=str(suggestion["title"]),
            link="",
            summary=str(suggestion["body"]),
        )
        if draft_id is None:
            await callback.answer("Черновик уже существует", show_alert=True)
            return
        await save_draft_payload(
            db,
            draft_id,
            image_url=str(suggestion["image_file_id"] or ""),
            entity_key=f"suggestion:{suggestion_id}",
            metadata={
                "suggestion_id": suggestion_id,
                "author_id": int(suggestion["telegram_id"]),
            },
        )
        await set_suggestion_status(
            db,
            suggestion_id,
            status="approved",
            draft_id=draft_id,
        )
        await callback.answer("Создан черновик")
        if callback.message is not None:
            await callback.message.answer(
                f"📝 Создан черновик <code>{draft_id}</code>:\n\n"
                f"<b>{html.escape(str(suggestion['title']))}</b>\n"
                f"{html.escape(str(suggestion['body']))}",
                reply_markup=draft_keyboard(draft_id),
            )
    else:
        await callback.answer("Неизвестное действие", show_alert=True)
        return
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.message(Command("analytics"))
async def analytics_command(message: Message, settings: Settings, db: Database) -> None:
    if not _is_admin(message.from_user.id if message.from_user else None, settings):
        await message.answer("Команда доступна только администратору.")
        return
    stats = await analytics_summary(db, limit=5)
    lines = [
        "📊 <b>Контент-аналитика</b>",
        "",
        f"Героев: <b>{stats.get('heroes', 0)}</b>",
        f"Составов: <b>{stats.get('squads', 0)}</b>",
        f"Событий: <b>{stats.get('events', 0)}</b>",
        f"В очереди: <b>{stats.get('queued_editorial', 0)}</b>",
        f"Предложений: <b>{stats.get('suggestions', 0)}</b>",
        f"На модерации: <b>{stats.get('pending_suggestions', 0)}</b>",
        f"Реакций: <b>{stats.get('reactions', 0)}</b>",
    ]
    top_posts = stats.get("top_posts") or []
    if top_posts:
        lines.extend(["", "🔥 <b>Лучшие публикации</b>"])
        for row in top_posts:
            lines.append(
                f"• {html.escape(str(row['title']))} — {int(row['reactions'])} реакций"
            )
    await message.answer("\n".join(lines))


@router.message_reaction()
async def reaction_updated(event: MessageReactionUpdated, settings: Settings, db: Database) -> None:
    if settings.group_chat_id is not None and event.chat.id != settings.group_chat_id:
        return
    if event.user is not None:
        actor_key = f"user:{event.user.id}"
    elif event.actor_chat is not None:
        actor_key = f"chat:{event.actor_chat.id}"
    else:
        return
    await replace_user_reactions(
        db,
        chat_id=event.chat.id,
        message_id=event.message_id,
        actor_key=actor_key,
        reactions=event.new_reaction,
    )


@router.message_reaction_count()
async def reaction_count_updated(
    event: MessageReactionCountUpdated,
    settings: Settings,
    db: Database,
) -> None:
    if settings.group_chat_id is not None and event.chat.id != settings.group_chat_id:
        return
    await replace_reaction_totals(
        db,
        chat_id=event.chat.id,
        message_id=event.message_id,
        reactions=event.reactions,
    )


@router.callback_query(F.data == "menu:heroes")
async def heroes_callback(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    if callback.message is None:
        return
    heroes = await list_heroes(db, limit=30)
    if not heroes:
        await callback.message.edit_text(
            "⚔️ База героев пока пустая.",
            reply_markup=simple_back_keyboard(),
        )
        return
    lines = ["⚔️ <b>Герои Last Asylum</b>", ""]
    for hero in heroes:
        role = html.escape(str(hero.get("role") or "роль не указана"))
        lines.append(f"• <b>{html.escape(str(hero['name_ru']))}</b> — {role}")
    lines.extend(["", "Подробнее: <code>/heroes Имя героя</code>"])
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=simple_back_keyboard(),
    )


@router.callback_query(F.data == "menu:squads")
async def squads_callback(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    if callback.message is None:
        return
    squads = await list_squads(db, limit=10)
    if not squads:
        await callback.message.edit_text(
            "🧩 База составов пока пустая.",
            reply_markup=simple_back_keyboard(),
        )
        return
    lines = ["🧩 <b>Составы и связки</b>", ""]
    for squad in squads:
        members = ", ".join(str(item) for item in squad.get("members", []))
        lines.append(
            f"• <b>{html.escape(str(squad['name']))}</b> — "
            f"{html.escape(members or str(squad.get('mode') or ''))}"
        )
    lines.append("\nПолные карточки: <code>/squads</code>")
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=simple_back_keyboard(),
    )


@router.callback_query(F.data == "menu:events")
async def events_callback(
    callback: CallbackQuery,
    settings: Settings,
    db: Database,
) -> None:
    await callback.answer()
    if callback.message is None:
        return
    events = await list_upcoming_events(db, limit=10)
    if not events:
        await callback.message.edit_text(
            "📅 Ближайших событий в календаре пока нет.",
            reply_markup=simple_back_keyboard(),
        )
        return
    lines = ["📅 <b>Календарь событий</b>", ""]
    for event in events:
        start = format_local_datetime(
            str(event["starts_at"]),
            offset_hours=settings.editorial_timezone_offset_hours,
        )
        lines.append(f"• <b>{html.escape(str(event['title']))}</b> — {start}")
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=simple_back_keyboard(),
    )


@router.callback_query(F.data == "menu:suggest")
async def suggest_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is not None:
        await callback.message.edit_text(
            "💡 <b>Предложить материал</b>\n\n"
            "Отправьте:\n"
            "<code>/suggest TYPE | Заголовок | Текст</code>\n\n"
            "TYPE: guide, hero, squad, event, alliance",
            reply_markup=simple_back_keyboard(),
        )
