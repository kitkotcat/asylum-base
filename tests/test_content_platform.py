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
