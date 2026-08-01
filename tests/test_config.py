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
