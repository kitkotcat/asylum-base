from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} должен быть целым числом") from exc


def _int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} должен быть целым числом") from exc
    if minimum is not None and value < minimum:
        raise RuntimeError(f"{name} должен быть не меньше {minimum}")
    if maximum is not None and value > maximum:
        raise RuntimeError(f"{name} должен быть не больше {maximum}")
    return value


def _float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name, str(default)).strip().replace(",", ".")
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} должен быть числом") from exc
    if value < minimum:
        raise RuntimeError(f"{name} должен быть не меньше {minimum}")
    return value


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} должен быть true/false")


def _int_set(name: str) -> frozenset[int]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return frozenset()
    try:
        return frozenset(int(item.strip()) for item in raw.split(",") if item.strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} должен содержать Telegram ID через запятую") from exc


def _url(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"{name} должен быть корректной http/https-ссылкой")
    return value


def _urls(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return ()
    result: list[str] = []
    for value in raw.split(","):
        value = value.strip()
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"Некорректная ссылка в {name}: {value}")
        result.append(value)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    group_chat_id: int | None
    news_thread_id: int | None
    promo_thread_id: int | None
    topup_thread_id: int | None
    guides_thread_id: int | None
    heroes_thread_id: int | None
    alliance_thread_id: int | None
    lootbar_affiliate_url: str
    lootbar_page_url: str
    google_play_url: str
    rss_feed_urls: tuple[str, ...]
    parser_interval_minutes: int
    db_path: Path
    publish_mode: str
    auto_publish_deals: bool
    auto_publish_news: bool
    auto_publish_google_play: bool
    auto_publish_promos: bool
    promo_max_posts_per_day: int
    promo_redeem_url: str
    editorial_autopost_enabled: bool
    editorial_max_posts_per_day: int
    hero_autopost_enabled: bool
    hero_max_posts_per_day: int
    hero_min_interval_hours: int
    editorial_timezone_offset_hours: int
    daily_deals_digest_enabled: bool
    daily_deals_digest_hour_utc: int
    daily_admin_report_enabled: bool
    daily_admin_report_hour_utc: int
    max_auto_posts_per_6_hours: int
    deal_cooldown_hours: int
    min_price_drop_percent: float
    min_savings_increase_cents: int
    deals_page_size: int
    community_url: str
    guides_url: str
    tracked_redirect_base_url: str

    def auto_publish_enabled_for(self, kind: str) -> bool:
        if self.publish_mode == "manual":
            return False
        if kind in {"deal", "deal_digest", "topup"}:
            return self.auto_publish_deals
        if kind == "google_play":
            return self.auto_publish_google_play
        if kind == "news":
            return self.auto_publish_news
        if kind == "promo":
            return self.auto_publish_promos
        if kind == "hero":
            return self.editorial_autopost_enabled and self.hero_autopost_enabled
        if kind in {"guide", "squad", "event", "alliance"}:
            return self.editorial_autopost_enabled
        return False


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не заполнен в .env")

    publish_mode = os.getenv("PUBLISH_MODE", "semi_auto").strip().lower()
    if publish_mode not in {"manual", "semi_auto", "auto"}:
        raise RuntimeError("PUBLISH_MODE должен быть manual, semi_auto или auto")

    db_path_raw = os.getenv("DB_PATH", "bot/data/asylum_base.db").strip()
    db_path = Path(db_path_raw)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path

    return Settings(
        bot_token=token,
        admin_ids=_int_set("ADMIN_IDS"),
        group_chat_id=_optional_int("GROUP_CHAT_ID"),
        news_thread_id=_optional_int("NEWS_THREAD_ID"),
        promo_thread_id=_optional_int("PROMO_THREAD_ID"),
        topup_thread_id=_optional_int("TOPUP_THREAD_ID"),
        guides_thread_id=_optional_int("GUIDES_THREAD_ID"),
        heroes_thread_id=_optional_int("HEROES_THREAD_ID"),
        alliance_thread_id=_optional_int("ALLIANCE_THREAD_ID"),
        lootbar_affiliate_url=_url("LOOTBAR_AFFILIATE_URL"),
        lootbar_page_url=_url("LOOTBAR_PAGE_URL"),
        google_play_url=_url("GOOGLE_PLAY_URL"),
        rss_feed_urls=_urls("RSS_FEED_URLS"),
        parser_interval_minutes=_int("PARSER_INTERVAL_MINUTES", 30, minimum=5),
        db_path=db_path,
        publish_mode=publish_mode,
        auto_publish_deals=_bool("AUTO_PUBLISH_DEALS", False),
        auto_publish_news=_bool("AUTO_PUBLISH_NEWS", False),
        auto_publish_google_play=_bool("AUTO_PUBLISH_GOOGLE_PLAY", False),
        auto_publish_promos=_bool("AUTO_PUBLISH_PROMOS", False),
        promo_max_posts_per_day=_int(
            "PROMO_MAX_POSTS_PER_DAY", 2, minimum=1, maximum=10
        ),
        promo_redeem_url=_url("PROMO_REDEEM_URL"),
        editorial_autopost_enabled=_bool("EDITORIAL_AUTOPOST_ENABLED", False),
        editorial_max_posts_per_day=_int(
            "EDITORIAL_MAX_POSTS_PER_DAY", 1, minimum=1, maximum=10
        ),
        hero_autopost_enabled=_bool("HERO_AUTOPOST_ENABLED", False),
        hero_max_posts_per_day=_int(
            "HERO_MAX_POSTS_PER_DAY", 2, minimum=1, maximum=10
        ),
        hero_min_interval_hours=_int(
            "HERO_MIN_INTERVAL_HOURS", 6, minimum=1, maximum=24
        ),
        editorial_timezone_offset_hours=_int(
            "EDITORIAL_TIMEZONE_OFFSET_HOURS", 0, minimum=-12, maximum=14
        ),
        daily_deals_digest_enabled=_bool("DAILY_DEALS_DIGEST_ENABLED", False),
        daily_deals_digest_hour_utc=_int("DAILY_DEALS_DIGEST_HOUR_UTC", 8, minimum=0, maximum=23),
        daily_admin_report_enabled=_bool("DAILY_ADMIN_REPORT_ENABLED", True),
        daily_admin_report_hour_utc=_int("DAILY_ADMIN_REPORT_HOUR_UTC", 20, minimum=0, maximum=23),
        max_auto_posts_per_6_hours=_int("MAX_AUTO_POSTS_PER_6_HOURS", 2, minimum=1, maximum=20),
        deal_cooldown_hours=_int("DEAL_COOLDOWN_HOURS", 24, minimum=1, maximum=720),
        min_price_drop_percent=_float("MIN_PRICE_DROP_PERCENT", 5.0, minimum=0.0),
        min_savings_increase_cents=_int("MIN_SAVINGS_INCREASE_CENTS", 50, minimum=0),
        deals_page_size=_int("DEALS_PAGE_SIZE", 6, minimum=3, maximum=10),
        community_url=_url("COMMUNITY_URL"),
        guides_url=_url("GUIDES_URL"),
        tracked_redirect_base_url=_url("TRACKED_REDIRECT_BASE_URL"),
    )
