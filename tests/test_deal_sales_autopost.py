from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from bot.app.db import Database
from bot.app.services import scheduler
from bot.app.services.content_db import (
    get_draft_with_payload,
    init_content_schema,
    recent_offer_history,
    save_draft_payload,
)
from bot.app.services.deal_sales import (
    build_offer_url,
    current_sales_slot,
    select_sales_offer,
)
from bot.app.services.lootbar import LootbarPackage
from bot.app.services.publisher import publish_draft


def _package(
    key: str,
    name: str,
    *,
    promo: int,
    official: int,
    icon_url: str = "https://example.com/image.png",
) -> LootbarPackage:
    return LootbarPackage(
        package_key=key,
        name=name,
        regular_price_minor=official,
        promo_price_minor=promo,
        official_price_minor=official,
        savings_minor=official - promo,
        currency="USD",
        discount_badge="",
        coupon_name="",
        sell_order_id="order-" + key,
        icon_url=icon_url,
    )


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "deal_sales_autopost_enabled": True,
        "deal_sales_max_posts_per_day": 2,
        "deal_sales_min_interval_hours": 6,
        "deal_sales_repeat_hours": 48,
        "deal_sales_timezone_offset_hours": 5,
        "deal_sales_hours_local": (10, 19),
        "deal_sales_affiliate_url_template": "",
        "lootbar_affiliate_url": "https://example.com/ref?aff=123",
        "lootbar_page_url": "https://example.com/last-asylum",
        "group_chat_id": -1003810338089,
        "topup_thread_id": 6,
        "tracked_redirect_base_url": "",
        "deal_cooldown_hours": 24,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_offer_selection_prefers_discount_and_deduplicates_prices() -> None:
    packages = [
        _package("a", "9999 Banknotes", promo=8010, official=9999),
        _package("b", "Any 99.99 Pack", promo=8010, official=9999),
        _package("c", "Smaller Pack", promo=7000, official=10000),
    ]

    offer = select_sales_offer(packages)
    assert offer is not None
    assert offer.package_key == "c"
    assert offer.discount_percent == 30

    rotated = select_sales_offer(
        packages,
        excluded_package_keys={"c"},
        excluded_price_fingerprints={("USD", 8010, 9999)},
    )
    assert rotated is None


def test_offer_without_real_discount_is_skipped() -> None:
    assert select_sales_offer(
        [_package("same", "No Discount", promo=1000, official=1000)]
    ) is None


def test_offer_url_uses_verified_template_or_affiliate_fallback() -> None:
    offer = select_sales_offer(
        [_package("sku-1", "Pack", promo=800, official=1000)]
    )
    assert offer is not None

    assert build_offer_url(_settings(), offer) == "https://example.com/ref?aff=123"
    template_settings = _settings(
        deal_sales_affiliate_url_template=(
            "https://example.com/buy/{package_key}?order={sell_order_id}&aff=123"
        )
    )
    assert build_offer_url(template_settings, offer) == (
        "https://example.com/buy/sku-1?order=order-sku-1&aff=123"
    )


def test_local_schedule_has_two_configured_slots() -> None:
    due = current_sales_slot(
        now=datetime(2026, 8, 6, 5, 20, tzinfo=timezone.utc),
        timezone_offset_hours=5,
        hours_local=(10, 19),
    )
    not_due = current_sales_slot(
        now=datetime(2026, 8, 6, 6, 20, tzinfo=timezone.utc),
        timezone_offset_hours=5,
        hours_local=(10, 19),
    )

    assert due == "2026-08-06:10"
    assert not_due is None


def test_recent_history_blocks_package_and_same_price_variant(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        db = Database(tmp_path / "history.db")
        await db.init()
        await init_content_schema(db)

        draft_id = await db.create_draft(
            kind="deal_sales",
            source_url="https://example.com/source",
            item_uid="slot-1",
            title="Pack A",
            link="https://example.com/ref",
            summary="summary",
        )
        assert draft_id is not None
        await save_draft_payload(
            db,
            draft_id,
            entity_key="sku-a",
            metadata={
                "currency": "USD",
                "promo_price_minor": 8010,
                "official_price_minor": 9999,
            },
        )

        async with db.connect() as connection:
            await connection.execute(
                """
                INSERT INTO publication_log(
                    content_key, draft_id, kind, entity_key, title,
                    target_chat_id, thread_id, telegram_message_id,
                    target_url, status, auto_published, error, published_at
                )
                VALUES (?, ?, 'deal_sales', 'sku-a', 'Pack A', ?, 6, 101,
                        ?, 'published', 1, NULL, ?)
                """,
                (
                    "source::slot-1",
                    draft_id,
                    -1003810338089,
                    "https://example.com/ref",
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
            await connection.commit()

        keys, prices = await recent_offer_history(
            db,
            kind="deal_sales",
            target_chat_id=-1003810338089,
            hours=48,
        )
        assert keys == {"sku-a"}
        assert prices == {("USD", 8010, 9999)}

    asyncio.run(scenario())


def test_dispatch_publishes_exactly_one_fresh_offer(monkeypatch) -> None:
    class FakeDatabase:
        def __init__(self) -> None:
            self.created: list[dict[str, object]] = []

        async def create_draft(self, **kwargs: object) -> int:
            self.created.append(dict(kwargs))
            return 77

    async def scenario() -> None:
        db = FakeDatabase()
        saved: list[dict[str, object]] = []
        enqueued: list[tuple[int, str]] = []
        fetch_calls = 0

        async def count(*args, **kwargs) -> int:
            return 0

        async def latest(*args, **kwargs) -> None:
            return None

        async def history(*args, **kwargs):
            return set(), set()

        async def fetch():
            nonlocal fetch_calls
            fetch_calls += 1
            return [
                _package("a", "Pack A", promo=8010, official=9999),
                _package("b", "Pack B", promo=7000, official=10000),
            ]

        async def save(*args, **kwargs) -> None:
            saved.append(dict(kwargs))

        async def enqueue(_db, draft_id, kind, priority=100) -> bool:
            enqueued.append((draft_id, kind))
            return True

        async def process(*args, **kwargs) -> int:
            return 1

        monkeypatch.setattr(scheduler, "count_auto_publications_today", count)
        monkeypatch.setattr(scheduler, "latest_auto_publication_at", latest)
        monkeypatch.setattr(scheduler, "recent_offer_history", history)
        monkeypatch.setattr(scheduler, "fetch_lootbar_packages", fetch)
        monkeypatch.setattr(scheduler, "save_draft_payload", save)
        monkeypatch.setattr(scheduler, "enqueue_draft", enqueue)
        monkeypatch.setattr(scheduler, "process_publication_queue", process)

        published = await scheduler.dispatch_deal_sales(
            SimpleNamespace(),
            _settings(),
            db,
            now=datetime(2026, 8, 6, 5, 15, tzinfo=timezone.utc),
        )

        assert published == 1
        assert fetch_calls == 1
        assert len(db.created) == 1
        assert db.created[0]["kind"] == "deal_sales"
        assert enqueued == [(77, "deal_sales")]
        assert len(saved) == 1
        assert saved[0]["entity_key"] == "b"
        assert saved[0]["metadata"]["discount_percent"] == 30

    asyncio.run(scenario())


def test_daily_limit_and_interval_skip_without_fetch(monkeypatch) -> None:
    async def scenario() -> None:
        fetch_calls = 0

        async def count(*args, **kwargs) -> int:
            return 2

        async def fetch():
            nonlocal fetch_calls
            fetch_calls += 1
            return []

        monkeypatch.setattr(scheduler, "count_auto_publications_today", count)
        monkeypatch.setattr(scheduler, "fetch_lootbar_packages", fetch)

        result = await scheduler.dispatch_deal_sales(
            SimpleNamespace(),
            _settings(),
            SimpleNamespace(),
            now=datetime(2026, 8, 6, 5, 10, tzinfo=timezone.utc),
        )
        assert result == 0
        assert fetch_calls == 0

        async def under_limit(*args, **kwargs) -> int:
            return 0

        async def recent(*args, **kwargs) -> str:
            return (
                datetime(2026, 8, 6, 5, 10, tzinfo=timezone.utc)
                - timedelta(hours=2)
            ).isoformat()

        monkeypatch.setattr(
            scheduler,
            "count_auto_publications_today",
            under_limit,
        )
        monkeypatch.setattr(scheduler, "latest_auto_publication_at", recent)

        result = await scheduler.dispatch_deal_sales(
            SimpleNamespace(),
            _settings(),
            SimpleNamespace(),
            now=datetime(2026, 8, 6, 5, 10, tzinfo=timezone.utc),
        )
        assert result == 0
        assert fetch_calls == 0

    asyncio.run(scenario())


def test_failed_fresh_source_creates_no_post(monkeypatch) -> None:
    class FakeDatabase:
        async def create_draft(self, **kwargs: object) -> int:
            raise AssertionError("draft must not be created")

    async def scenario() -> None:
        async def fail_fetch():
            raise RuntimeError("LootBar unavailable")

        monkeypatch.setattr(scheduler, "fetch_lootbar_packages", fail_fetch)
        draft_id = await scheduler.create_deal_sales_draft(
            _settings(),
            FakeDatabase(),
            slot_key="2026-08-06:10",
            checked_at=datetime.now(timezone.utc),
        )
        assert draft_id is None

    asyncio.run(scenario())


def test_image_failure_falls_back_to_text_in_topup_topic(tmp_path: Path) -> None:
    class FakeBot:
        def __init__(self) -> None:
            self.photo_calls = 0
            self.message_calls: list[dict[str, object]] = []

        async def send_photo(self, **kwargs: object):
            self.photo_calls += 1
            raise RuntimeError("bad image")

        async def send_message(self, **kwargs: object):
            self.message_calls.append(dict(kwargs))
            return SimpleNamespace(message_id=501)

    async def scenario() -> None:
        db = Database(tmp_path / "fallback.db")
        await db.init()
        await init_content_schema(db)
        draft_id = await db.create_draft(
            kind="deal_sales",
            source_url="https://example.com/source",
            item_uid="slot:10",
            title="Pack A",
            link="https://example.com/ref",
            summary="summary",
        )
        assert draft_id is not None
        await save_draft_payload(
            db,
            draft_id,
            image_url="invalid-telegram-image",
            entity_key="sku-a",
            metadata={
                "name": "Pack A",
                "promo_price_minor": 800,
                "official_price_minor": 1000,
                "savings_minor": 200,
                "discount_percent": 20,
                "currency": "USD",
            },
        )

        bot = FakeBot()
        sent = await publish_draft(
            bot,
            _settings(),
            db,
            draft_id,
            auto_published=False,
        )

        assert sent is not None
        assert bot.photo_calls == 1
        assert len(bot.message_calls) == 1
        assert bot.message_calls[0]["message_thread_id"] == 6
        keyboard = bot.message_calls[0]["reply_markup"]
        assert keyboard.inline_keyboard[0][0].text == "🔥 Купить со скидкой"
        assert keyboard.inline_keyboard[0][0].url == "https://example.com/ref"

    asyncio.run(scenario())
