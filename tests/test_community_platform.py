from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from bot.app.db import Database
from bot.app.services.community_content import parse_local_datetime
from bot.app.services.community_db import (
    add_editorial_item,
    add_game_event,
    add_suggestion,
    analytics_summary,
    count_recent_suggestions,
    get_hero,
    init_community_schema,
    list_due_editorial_items,
    list_pending_suggestions,
    list_upcoming_events,
    mark_editorial_dispatched,
    replace_reaction_totals,
    replace_user_reactions,
    upsert_entity_editorial_item,
    upsert_hero,
    upsert_squad,
)
from bot.app.services.content_db import init_content_schema
from bot.app.services.publisher import thread_id_for_kind


def test_community_schema_and_content_bank(tmp_path: Path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "community.db")
        await db.init()
        await init_content_schema(db)
        await init_community_schema(db)

        hero_id = await upsert_hero(
            db,
            name_ru="Артур",
            name_en="Arthur",
            role="защита",
            strengths=["выживаемость"],
            weaknesses=["низкий урон"],
            strategy="Ставить на первую линию.",
        )
        assert hero_id > 0
        hero = await get_hero(db, "Arthur")
        assert hero is not None
        assert hero["name_ru"] == "Артур"
        assert hero["strengths"] == ["выживаемость"]

        squad_id = await upsert_squad(
            db,
            name="Защитная тройка",
            mode="PvE",
            members=["Артур", "Фрея", "Элейн"],
            synergy="Танк, урон и поддержка.",
            strategy="Держать Артура впереди.",
        )
        assert squad_id > 0

        starts_at = parse_local_datetime("2026-08-20 18:00", offset_hours=5)
        event_id = await add_game_event(
            db,
            title="Тестовое событие",
            starts_at=starts_at,
            ends_at=None,
            description="Проверка календаря.",
        )
        assert event_id > 0
        events = await list_upcoming_events(
            db,
            now="2026-08-01T00:00:00+00:00",
        )
        assert len(events) == 1

        editorial_id = await upsert_entity_editorial_item(
            db,
            kind="hero",
            entity_key=f"hero:{hero_id}",
            title="Артур",
            body="Карточка героя",
            next_publish_at="2026-08-01T00:00:00+00:00",
            repeat_days=30,
        )
        same_id = await upsert_entity_editorial_item(
            db,
            kind="hero",
            entity_key=f"hero:{hero_id}",
            title="Артур обновлён",
            body="Новая карточка",
            next_publish_at="2026-08-02T00:00:00+00:00",
            repeat_days=30,
        )
        assert same_id == editorial_id

        due = await list_due_editorial_items(
            db,
            now="2026-08-03T00:00:00+00:00",
        )
        assert len(due) == 1
        await mark_editorial_dispatched(
            db,
            editorial_id,
            dispatched_at="2026-08-03T00:00:00+00:00",
        )
        due_after = await list_due_editorial_items(
            db,
            now="2026-08-03T00:00:00+00:00",
        )
        assert due_after == []

        suggestion_id = await add_suggestion(
            db,
            telegram_id=123,
            username="tester",
            kind="guide",
            title="Идея",
            body="Текст идеи",
        )
        assert suggestion_id > 0
        suggestions = await list_pending_suggestions(db)
        assert len(suggestions) == 1
        assert await count_recent_suggestions(
            db, telegram_id=123, hours=24
        ) == 1

    asyncio.run(scenario())


def test_reaction_analytics_supports_public_and_anonymous(tmp_path: Path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "analytics.db")
        await db.init()
        await init_content_schema(db)
        await init_community_schema(db)

        emoji = SimpleNamespace(emoji="🔥", custom_emoji_id=None, type="emoji")
        await replace_user_reactions(
            db,
            chat_id=-100,
            message_id=10,
            actor_key="user:1",
            reactions=[emoji],
        )
        public_stats = await analytics_summary(db)
        assert public_stats["reactions"] == 1

        reaction_count = SimpleNamespace(type=emoji, total_count=7)
        await replace_reaction_totals(
            db,
            chat_id=-100,
            message_id=10,
            reactions=[reaction_count],
        )
        anonymous_stats = await analytics_summary(db)
        assert anonymous_stats["reactions"] == 7

    asyncio.run(scenario())


def test_editorial_routes_use_existing_topics() -> None:
    settings = SimpleNamespace(
        heroes_thread_id=8,
        news_thread_id=4,
        guides_thread_id=10,
        alliance_thread_id=14,
    )
    assert thread_id_for_kind(settings, "hero") == 8
    assert thread_id_for_kind(settings, "squad") == 8
    assert thread_id_for_kind(settings, "event") == 4
    assert thread_id_for_kind(settings, "guide") == 10
    assert thread_id_for_kind(settings, "alliance") == 14


def test_one_time_editorial_item_archives_after_dispatch(tmp_path: Path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "one-time.db")
        await db.init()
        await init_content_schema(db)
        await init_community_schema(db)
        item_id = await add_editorial_item(
            db,
            kind="event",
            title="Событие",
            body="Напоминание",
            next_publish_at="2026-08-01T00:00:00+00:00",
            repeat_days=0,
        )
        await mark_editorial_dispatched(
            db,
            item_id,
            dispatched_at="2026-08-01T00:00:00+00:00",
        )
        assert await list_due_editorial_items(
            db,
            now="2026-08-02T00:00:00+00:00",
        ) == []

    asyncio.run(scenario())
