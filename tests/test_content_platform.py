from __future__ import annotations

import asyncio
from pathlib import Path

from bot.app.db import Database
from bot.app.services.content import clean_condition, render_deal_caption
from bot.app.services.content_db import (
    draft_content_key,
    enqueue_draft,
    get_draft_with_payload,
    init_content_schema,
    list_ready_queue,
    publication_exists,
    record_publication,
    save_draft_payload,
)


def test_coupon_condition_does_not_duplicate_percent() -> None:
    assert clean_condition("10%", "New User 10% OFF Coupon") == "New User 10% OFF Coupon"
    assert clean_condition("8%", "Welcome Coupon") == "8% Welcome Coupon"


def test_deal_caption_contains_prices_and_disclosure() -> None:
    text = render_deal_caption(
        {
            "title": "999 Banknotes",
            "metadata": {
                "name": "999 Banknotes",
                "promo_price_minor": 801,
                "regular_price_minor": 889,
                "official_price_minor": 999,
                "savings_minor": 198,
                "currency": "USD",
                "discount_badge": "10%",
                "coupon_name": "New User 10% OFF Coupon",
            },
        }
    )
    assert "$8.01" in text
    assert "$8.89" in text
    assert "$9.99" in text
    assert "Партнёрская ссылка" in text
    assert text.count("10%") == 1


def test_publication_queue_and_duplicate_protection(tmp_path: Path) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "content.db")
        await db.init()
        await init_content_schema(db)

        draft_id = await db.create_draft(
            kind="deal",
            source_url="https://example.com/source",
            item_uid="price-change:1",
            title="Test deal",
            link="https://example.com/ref",
            summary="summary",
        )
        assert draft_id is not None

        await save_draft_payload(
            db,
            draft_id,
            image_url="https://example.com/image.png",
            entity_key="sku-1",
            metadata={"auto_eligible": True},
        )
        draft = await get_draft_with_payload(db, draft_id)
        assert draft is not None
        assert draft["entity_key"] == "sku-1"
        assert draft["metadata"]["auto_eligible"] is True

        assert await enqueue_draft(db, draft_id, "deal") is True
        assert await enqueue_draft(db, draft_id, "deal") is False
        queue = await list_ready_queue(db)
        assert len(queue) == 1

        content_key = draft_content_key(draft)
        assert await publication_exists(db, content_key) is False
        await record_publication(
            db,
            content_key=content_key,
            draft_id=draft_id,
            kind="deal",
            entity_key="sku-1",
            title="Test deal",
            target_chat_id=-100,
            thread_id=18,
            telegram_message_id=101,
            target_url="https://example.com/ref",
            status="published",
            auto_published=True,
        )
        assert await publication_exists(db, content_key) is True

    asyncio.run(scenario())


def test_start_sends_menu_after_removing_legacy_keyboard() -> None:
    from types import SimpleNamespace

    from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardRemove

    from bot.app.handlers.common import start

    class FakeDatabase:
        async def upsert_user(self, **_kwargs: object) -> None:
            return None

    class FakeCleanupMessage:
        def __init__(self) -> None:
            self.deleted = False

        async def delete(self) -> None:
            self.deleted = True

    class FakeMessage:
        def __init__(self) -> None:
            self.from_user = SimpleNamespace(
                id=1,
                username="tester",
                first_name="Test",
            )
            self.calls: list[tuple[str, object]] = []
            self.cleanup = FakeCleanupMessage()

        async def answer(self, text: str, *, reply_markup: object = None):
            self.calls.append((text, reply_markup))
            if len(self.calls) == 1:
                return self.cleanup
            return SimpleNamespace()

    async def scenario() -> None:
        message = FakeMessage()
        settings = SimpleNamespace(community_url="https://t.me/example")

        await start(message, settings, FakeDatabase())

        assert len(message.calls) == 2
        assert isinstance(message.calls[0][1], ReplyKeyboardRemove)
        assert message.cleanup.deleted is True
        assert "Asylum Base" in message.calls[1][0]
        assert isinstance(message.calls[1][1], InlineKeyboardMarkup)

    asyncio.run(scenario())


def test_promos_keyboard_has_navigation_without_loading_placeholder() -> None:
    from bot.app.handlers.promo import render_promo_text
    from bot.app.keyboards import promos_keyboard

    promo = {
        "code": "WELCOME10",
        "reward": "100 Banknotes",
        "region": "Global",
        "expires_at": None,
        "verification_status": "verified",
        "source": "Official community",
        "works": 3,
        "fails": 0,
    }
    text = render_promo_text(promo, page=0, total=2)
    keyboard = promos_keyboard(promo_id=7, page=0, total_pages=2)

    assert "Загружаю" not in text
    assert "WELCOME10" in text
    assert "1 из 2" in text
    assert keyboard.inline_keyboard[0][-1].callback_data == "promos:p:1"
    assert keyboard.inline_keyboard[1][0].callback_data == "promo:vote:7:1"


def test_content_topic_routes_are_explicit() -> None:
    from types import SimpleNamespace

    import pytest

    from bot.app.services.publisher import thread_id_for_kind

    settings = SimpleNamespace(
        news_thread_id=4,
        promo_thread_id=6,
        topup_thread_id=18,
        guides_thread_id=10,
        heroes_thread_id=8,
        alliance_thread_id=14,
    )

    assert thread_id_for_kind(settings, "news") == 4
    assert thread_id_for_kind(settings, "guide") == 10
    assert thread_id_for_kind(settings, "hero") == 8
    assert thread_id_for_kind(settings, "alliance") == 14

    with pytest.raises(RuntimeError, match="Неизвестный тип"):
        thread_id_for_kind(settings, "unknown")


def test_content_topic_route_requires_configuration() -> None:
    from types import SimpleNamespace

    import pytest

    from bot.app.services.publisher import thread_id_for_kind

    settings = SimpleNamespace(guides_thread_id=None)

    with pytest.raises(RuntimeError, match="GUIDES_THREAD_ID"):
        thread_id_for_kind(settings, "guide")


def test_daily_digest_only_changes_when_top_three_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from bot.app.services import scheduler
    from bot.app.services.content_db import (
        draft_content_key,
        get_draft_with_payload,
        record_publication,
    )

    class DayOne(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 5, 8, 0, tzinfo=timezone.utc)

    class DayTwo(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 6, 8, 0, tzinfo=timezone.utc)

    async def scenario() -> None:
        db = Database(tmp_path / "digest.db")
        await db.init()
        await init_content_schema(db)

        source_url = "https://example.com/last-asylum"
        now = "2026-08-05T08:00:00+00:00"
        rows = [
            ("sku-1", "Pack 1", 8010, 9999, 1989),
            ("sku-2", "Pack 2", 4010, 4999, 989),
            ("sku-3", "Pack 3", 1610, 1999, 389),
        ]
        async with db.connect() as connection:
            await connection.executemany(
                """
                INSERT INTO lootbar_packages(
                    package_key,
                    source_url,
                    name,
                    regular_price_minor,
                    promo_price_minor,
                    official_price_minor,
                    savings_minor,
                    currency,
                    discount_badge,
                    coupon_name,
                    sell_order_id,
                    is_active,
                    missing_count,
                    first_seen_at,
                    last_seen_at,
                    last_changed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'USD', '', '', ?, 1, 0, ?, ?, ?)
                """,
                [
                    (
                        package_key,
                        source_url,
                        name,
                        promo_price,
                        promo_price,
                        official_price,
                        savings,
                        f"order-{index}",
                        now,
                        now,
                        now,
                    )
                    for index, (
                        package_key,
                        name,
                        promo_price,
                        official_price,
                        savings,
                    ) in enumerate(rows, start=1)
                ],
            )
            await connection.commit()

        settings = SimpleNamespace(
            lootbar_page_url=source_url,
            lootbar_affiliate_url="https://example.com/ref",
        )

        monkeypatch.setattr(scheduler, "datetime", DayOne)
        first_id = await scheduler.create_daily_deals_digest(settings, db)
        assert first_id is not None

        first = await get_draft_with_payload(db, first_id)
        assert first is not None
        await record_publication(
            db,
            content_key=draft_content_key(first),
            draft_id=first_id,
            kind="deal_digest",
            entity_key=str(first["entity_key"]),
            title=str(first["title"]),
            target_chat_id=-100,
            thread_id=18,
            telegram_message_id=100,
            target_url=str(first["link"]),
            status="published",
            auto_published=True,
        )

        monkeypatch.setattr(scheduler, "datetime", DayTwo)
        assert await scheduler.create_daily_deals_digest(settings, db) is None

        async with db.connect() as connection:
            await connection.execute(
                """
                UPDATE lootbar_packages
                SET promo_price_minor = 7900,
                    savings_minor = 2099
                WHERE package_key = 'sku-1'
                """
            )
            await connection.commit()

        changed_id = await scheduler.create_daily_deals_digest(settings, db)
        assert changed_id is not None
        changed = await get_draft_with_payload(db, changed_id)
        assert changed is not None
        assert changed["metadata"]["signature"] != first["metadata"]["signature"]

    asyncio.run(scenario())
