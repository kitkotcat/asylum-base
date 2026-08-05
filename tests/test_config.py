from __future__ import annotations

from bot.app.config import Settings


def test_auto_publish_kind_mapping(tmp_path) -> None:
    settings = Settings(
        bot_token="x",
        admin_ids=frozenset(),
        group_chat_id=None,
        news_thread_id=None,
        promo_thread_id=None,
        topup_thread_id=None,
        guides_thread_id=None,
        heroes_thread_id=None,
        alliance_thread_id=None,
        lootbar_affiliate_url="",
        lootbar_page_url="",
        google_play_url="",
        rss_feed_urls=(),
        parser_interval_minutes=30,
        db_path=tmp_path / "db.sqlite",
        publish_mode="semi_auto",
        auto_publish_deals=True,
        auto_publish_news=False,
        auto_publish_google_play=True,
        auto_publish_promos=True,
        promo_max_posts_per_day=2,
        promo_redeem_url="https://example.com/redeem",
        editorial_autopost_enabled=True,
        editorial_max_posts_per_day=1,
        hero_autopost_enabled=True,
        hero_max_posts_per_day=2,
        hero_min_interval_hours=6,
        editorial_timezone_offset_hours=5,
        daily_deals_digest_enabled=False,
        daily_deals_digest_hour_utc=8,
        daily_admin_report_enabled=True,
        daily_admin_report_hour_utc=20,
        max_auto_posts_per_6_hours=2,
        deal_cooldown_hours=24,
        min_price_drop_percent=5.0,
        min_savings_increase_cents=50,
        deals_page_size=6,
        community_url="",
        guides_url="",
        tracked_redirect_base_url="",
    )
    assert settings.auto_publish_enabled_for("deal") is True
    assert settings.auto_publish_enabled_for("deal_digest") is True
    assert settings.auto_publish_enabled_for("google_play") is True
    assert settings.auto_publish_enabled_for("news") is False
    assert settings.auto_publish_enabled_for("promo") is True
    assert settings.auto_publish_enabled_for("hero") is True
    assert settings.auto_publish_enabled_for("squad") is True
    assert settings.auto_publish_enabled_for("event") is True


def test_hero_autopost_can_be_disabled_without_affecting_editorial(tmp_path) -> None:
    settings = Settings(
        bot_token="x",
        admin_ids=frozenset(),
        group_chat_id=None,
        news_thread_id=None,
        promo_thread_id=None,
        topup_thread_id=None,
        guides_thread_id=None,
        heroes_thread_id=None,
        alliance_thread_id=None,
        lootbar_affiliate_url="",
        lootbar_page_url="",
        google_play_url="",
        rss_feed_urls=(),
        parser_interval_minutes=30,
        db_path=tmp_path / "db.sqlite",
        publish_mode="semi_auto",
        auto_publish_deals=True,
        auto_publish_news=True,
        auto_publish_google_play=True,
        auto_publish_promos=True,
        promo_max_posts_per_day=2,
        promo_redeem_url="https://example.com/redeem",
        editorial_autopost_enabled=True,
        editorial_max_posts_per_day=1,
        hero_autopost_enabled=False,
        hero_max_posts_per_day=2,
        hero_min_interval_hours=6,
        editorial_timezone_offset_hours=5,
        daily_deals_digest_enabled=False,
        daily_deals_digest_hour_utc=8,
        daily_admin_report_enabled=True,
        daily_admin_report_hour_utc=20,
        max_auto_posts_per_6_hours=2,
        deal_cooldown_hours=24,
        min_price_drop_percent=5.0,
        min_savings_increase_cents=50,
        deals_page_size=6,
        community_url="",
        guides_url="",
        tracked_redirect_base_url="",
    )

    assert settings.auto_publish_enabled_for("hero") is False
    assert settings.auto_publish_enabled_for("guide") is True
    assert settings.auto_publish_enabled_for("squad") is True
