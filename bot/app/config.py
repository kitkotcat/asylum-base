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


def _int_set(name: str) -> frozenset[int]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return frozenset()
    try:
        return frozenset(
            int(item.strip()) for item in raw.split(",") if item.strip()
        )
    except ValueError as exc:
        raise RuntimeError(
            f"{name} должен содержать Telegram ID через запятую"
        ) from exc


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

    values: list[str] = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"Некорректная ссылка в {name}: {value}")
        values.append(value)
    return tuple(values)


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    group_chat_id: int | None
    news_thread_id: int | None
    promo_thread_id: int | None
    topup_thread_id: int | None
    lootbar_affiliate_url: str
    lootbar_page_url: str
    rss_feed_urls: tuple[str, ...]
    parser_interval_minutes: int
    db_path: Path


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не заполнен в .env")

    interval_raw = os.getenv("PARSER_INTERVAL_MINUTES", "30").strip()
    try:
        interval = int(interval_raw)
    except ValueError as exc:
        raise RuntimeError(
            "PARSER_INTERVAL_MINUTES должен быть целым числом"
        ) from exc
    if interval < 5:
        raise RuntimeError(
            "PARSER_INTERVAL_MINUTES должен быть не меньше 5"
        )

    db_path = Path(
        os.getenv("DB_PATH", "bot/data/asylum_base.db").strip()
    )
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path

    return Settings(
        bot_token=token,
        admin_ids=_int_set("ADMIN_IDS"),
        group_chat_id=_optional_int("GROUP_CHAT_ID"),
        news_thread_id=_optional_int("NEWS_THREAD_ID"),
        promo_thread_id=_optional_int("PROMO_THREAD_ID"),
        topup_thread_id=_optional_int("TOPUP_THREAD_ID"),
        lootbar_affiliate_url=_url("LOOTBAR_AFFILIATE_URL"),
        lootbar_page_url=_url("LOOTBAR_PAGE_URL"),
        rss_feed_urls=_urls("RSS_FEED_URLS"),
        parser_interval_minutes=interval,
        db_path=db_path,
    )
