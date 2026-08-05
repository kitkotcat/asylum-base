from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from bot.app.services.content import trim_text

KIND_LABELS = {
    "guide": ("📘", "Гайд"),
    "hero": ("⚔️", "Герой"),
    "squad": ("🧩", "Состав и связка"),
    "event": ("📅", "Событие"),
    "alliance": ("🤝", "Альянс"),
}


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]


def format_local_datetime(value: str, *, offset_hours: int) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone(timezone(timedelta(hours=offset_hours)))
    return local.strftime("%d.%m.%Y %H:%M")


def parse_local_datetime(value: str, *, offset_hours: int) -> str:
    parsed = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")
    local_tz = timezone(timedelta(hours=offset_hours))
    return parsed.replace(tzinfo=local_tz).astimezone(timezone.utc).isoformat(timespec="seconds")


def render_hero(hero: Mapping[str, Any]) -> str:
    title = html.escape(str(hero.get("name_ru") or hero.get("name_en") or "Герой"))
    name_en = html.escape(str(hero.get("name_en") or ""))
    role = html.escape(str(hero.get("role") or "не указана"))
    rarity = html.escape(str(hero.get("rarity") or ""))
    faction = html.escape(str(hero.get("faction") or ""))
    strengths = [html.escape(str(item)) for item in hero.get("strengths", [])]
    weaknesses = [html.escape(str(item)) for item in hero.get("weaknesses", [])]
    strategy = html.escape(trim_text(str(hero.get("strategy") or ""), 1200))

    lines = [f"⚔️ <b>{title}</b>"]
    if name_en and name_en.casefold() != title.casefold():
        lines.append(f"<i>{name_en}</i>")
    lines.extend(["", f"🎯 Роль: <b>{role}</b>"])
    if rarity:
        lines.append(f"⭐ Редкость: {rarity}")
    if faction:
        lines.append(f"🛡 Фракция: {faction}")
    if strengths:
        lines.extend(["", "✅ <b>Сильные стороны</b>", *[f"• {item}" for item in strengths]])
    if weaknesses:
        lines.extend(["", "⚠️ <b>Слабые стороны</b>", *[f"• {item}" for item in weaknesses]])
    if strategy:
        lines.extend(["", "🧠 <b>Стратегия</b>", strategy])
    return "\n".join(lines)


def render_squad(squad: Mapping[str, Any]) -> str:
    title = html.escape(str(squad.get("name") or "Состав"))
    mode = html.escape(str(squad.get("mode") or "универсальный"))
    members = [html.escape(str(item)) for item in squad.get("members", [])]
    synergy = html.escape(trim_text(str(squad.get("synergy") or ""), 900))
    strategy = html.escape(trim_text(str(squad.get("strategy") or ""), 1100))

    lines = [f"🧩 <b>{title}</b>", "", f"🎮 Режим: <b>{mode}</b>"]
    if members:
        lines.extend(["", "👥 <b>Герои</b>", *[f"• {item}" for item in members]])
    if synergy:
        lines.extend(["", "🔗 <b>Почему работает</b>", synergy])
    if strategy:
        lines.extend(["", "🧠 <b>Как играть</b>", strategy])
    return "\n".join(lines)


def render_event(event: Mapping[str, Any], *, offset_hours: int) -> str:
    title = html.escape(str(event.get("title") or "Событие"))
    starts_at = format_local_datetime(str(event["starts_at"]), offset_hours=offset_hours)
    ends_raw = event.get("ends_at")
    description = html.escape(trim_text(str(event.get("description") or ""), 1200))
    lines = [f"📅 <b>{title}</b>", "", f"▶️ Начало: <b>{starts_at}</b>"]
    if ends_raw:
        lines.append(
            f"⏹ Завершение: <b>{format_local_datetime(str(ends_raw), offset_hours=offset_hours)}</b>"
        )
    if description:
        lines.extend(["", description])
    return "\n".join(lines)


def render_editorial_caption(draft: Mapping[str, Any]) -> str:
    kind = str(draft.get("kind") or "guide")
    metadata = draft.get("metadata") or {}
    if kind == "hero" and isinstance(metadata.get("hero"), dict):
        return render_hero(metadata["hero"])
    if kind == "squad" and isinstance(metadata.get("squad"), dict):
        return render_squad(metadata["squad"])
    if kind == "event" and isinstance(metadata.get("event"), dict):
        offset = int(metadata.get("timezone_offset_hours") or 0)
        return render_event(metadata["event"], offset_hours=offset)

    icon, label = KIND_LABELS.get(kind, ("📘", "Материал"))
    title = html.escape(str(draft.get("title") or label))
    body = html.escape(trim_text(str(draft.get("summary") or ""), 2500))
    lines = [f"{icon} <b>{title}</b>"]
    if body:
        lines.extend(["", body])
    return "\n".join(lines)
