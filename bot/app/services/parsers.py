from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

from bot.app.db import Database

logger = logging.getLogger(__name__)

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AsylumBaseBot/0.2.1; "
        "+https://github.com/kitkotcat/asylum-base)"
    )
}


@dataclass(frozen=True, slots=True)
class ParsedItem:
    source_url: str
    uid: str
    title: str
    link: str
    summary: str


def _safe_http_url(value: str, fallback: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    return fallback


def _plain_text(value: str, limit: int = 900) -> str:
    text = BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _parse_feed_sync(feed_url: str) -> list[ParsedItem]:
    feed = feedparser.parse(feed_url)
    if getattr(feed, "bozo", False) and not feed.entries:
        raise RuntimeError(f"RSS не прочитан: {getattr(feed, 'bozo_exception', 'unknown')}")

    items: list[ParsedItem] = []
    for entry in feed.entries[:20]:
        title = _plain_text(str(entry.get("title", "Без заголовка")), 250)
        link = _safe_http_url(str(entry.get("link", "")), feed_url)
        raw_uid = str(entry.get("id") or entry.get("guid") or link or title)
        uid = hashlib.sha256(raw_uid.encode("utf-8")).hexdigest()
        summary = _plain_text(str(entry.get("summary") or entry.get("description") or ""), 900)
        items.append(ParsedItem(feed_url, uid, title, link, summary))
    return items


async def collect_rss_drafts(db: Database, feed_urls: tuple[str, ...]) -> list[int]:
    created_ids: list[int] = []

    for feed_url in feed_urls:
        try:
            items = await asyncio.to_thread(_parse_feed_sync, feed_url)
            is_first_scan = not await db.has_source_items(feed_url)

            for item in items:
                if await db.source_item_exists(item.source_url, item.uid):
                    continue

                if not is_first_scan:
                    draft_id = await db.create_draft(
                        kind="news",
                        source_url=item.source_url,
                        item_uid=item.uid,
                        title=item.title,
                        link=item.link,
                        summary=item.summary,
                    )
                    if draft_id is not None:
                        created_ids.append(draft_id)

                await db.save_source_item(item.source_url, item.uid)

            if is_first_scan:
                logger.info("RSS baseline saved without drafts: %s (%s items)", feed_url, len(items))
        except Exception:
            logger.exception("Не удалось обработать RSS: %s", feed_url)

    return created_ids


async def _fetch_html(url: str) -> str:
    async with httpx.AsyncClient(
        timeout=25,
        follow_redirects=True,
        headers=HTTP_HEADERS,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def check_page_changed(
    db: Database,
    url: str,
    *,
    kind: str,
    title: str,
    summary: str,
) -> int | None:
    if not url:
        return None

    page_html = await _fetch_html(url)
    soup = BeautifulSoup(page_html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    normalized = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    previous_hash = await db.get_snapshot_hash(url)
    await db.save_snapshot_hash(url, content_hash)

    if previous_hash is None:
        logger.info("Page baseline saved without draft: %s", url)
        return None
    if previous_hash == content_hash:
        return None

    return await db.create_draft(
        kind=kind,
        source_url=url,
        item_uid=f"page-change:{content_hash}",
        title=title,
        link=url,
        summary=summary,
    )


def _google_play_signature(page_html: str) -> tuple[str, str, str]:
    soup = BeautifulSoup(page_html, "html.parser")
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in soup.get_text("\n", strip=True).splitlines()
        if line.strip()
    ]

    updated_on = ""
    whats_new = ""

    for index, line in enumerate(lines):
        if line == "Updated on" and index + 1 < len(lines):
            updated_on = lines[index + 1]
        if line in {"What’s new", "What's new"}:
            collected: list[str] = []
            for candidate in lines[index + 1:]:
                if candidate in {"Flag as inappropriate", "App support"}:
                    break
                collected.append(candidate)
                if len(" ".join(collected)) >= 700:
                    break
            whats_new = " ".join(collected).strip()

    if not updated_on and not whats_new:
        raise RuntimeError("Google Play: не удалось извлечь Updated on / What's new")

    payload = json.dumps(
        {"updated_on": updated_on, "whats_new": whats_new},
        ensure_ascii=False,
        sort_keys=True,
    )
    signature = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return signature, updated_on or "не указана", whats_new or "описание отсутствует"


async def check_google_play_update(db: Database, url: str) -> int | None:
    if not url:
        return None

    page_html = await _fetch_html(url)
    signature, updated_on, whats_new = _google_play_signature(page_html)
    previous_hash = await db.get_snapshot_hash(url)
    await db.save_snapshot_hash(url, signature)

    if previous_hash is None:
        logger.info("Google Play baseline saved without draft: %s", url)
        return None
    if previous_hash == signature:
        return None

    return await db.create_draft(
        kind="news",
        source_url=url,
        item_uid=f"google-play:{signature}",
        title="Обновление Last Asylum: Plague в Google Play",
        link=url,
        summary=(
            f"Дата обновления: {updated_on}\n"
            f"Что нового: {whats_new}\n\n"
            "Проверьте описание перед публикацией."
        ),
    )


def render_draft(title: str, summary: str, link: str) -> str:
    safe_title = html.escape(title)
    safe_summary = html.escape(summary)
    safe_link = html.escape(link, quote=True)
    parts = [f"📝 <b>{safe_title}</b>"]
    if safe_summary:
        parts.append(safe_summary)
    parts.append(f'🔗 <a href="{safe_link}">Открыть источник</a>')
    return "\n\n".join(parts)


def render_public_post(title: str, summary: str, link: str) -> str:
    safe_title = html.escape(title)
    safe_summary = html.escape(summary)
    safe_link = html.escape(link, quote=True)
    parts = [f"📢 <b>{safe_title}</b>"]
    if safe_summary:
        parts.append(safe_summary)
    parts.append(f'🔗 <a href="{safe_link}">Источник</a>')
    return "\n\n".join(parts)
