from __future__ import annotations

import hashlib
import html
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

from bot.app.db import Database

logger = logging.getLogger(__name__)


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
    text = BeautifulSoup(value or "", "html.parser").get_text(
        " ", strip=True
    )
    return re.sub(r"\s+", " ", text).strip()[:limit]


async def _fetch_text(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; AsylumBaseBot/0.1; "
            "+https://github.com/kitkotcat/asylum-base)"
        )
    }
    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        headers=headers,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def collect_rss_drafts(
    db: Database,
    feed_urls: tuple[str, ...],
) -> list[int]:
    created_ids: list[int] = []

    for feed_url in feed_urls:
        try:
            xml = await _fetch_text(feed_url)
            feed = feedparser.loads(xml)

            for entry in feed.entries[:10]:
                title = _plain_text(
                    str(entry.get("title", "Без заголовка")), 250
                )
                link = _safe_http_url(
                    str(entry.get("link", "")), feed_url
                )
                raw_uid = str(
                    entry.get("id")
                    or entry.get("guid")
                    or link
                    or title
                )
                uid = hashlib.sha256(
                    raw_uid.encode("utf-8")
                ).hexdigest()
                summary = _plain_text(
                    str(
                        entry.get("summary")
                        or entry.get("description")
                        or ""
                    ),
                    900,
                )

                draft_id = await db.create_draft(
                    kind="news",
                    source_url=feed_url,
                    item_uid=uid,
                    title=title,
                    link=link,
                    summary=summary,
                )
                if draft_id is not None:
                    created_ids.append(draft_id)
        except Exception:
            logger.exception("Не удалось обработать RSS: %s", feed_url)

    return created_ids


async def check_page_changed(
    db: Database,
    url: str,
) -> int | None:
    if not url:
        return None

    page = await _fetch_text(url)
    soup = BeautifulSoup(page, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    normalized = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    content_hash = hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()

    previous_hash = await db.get_snapshot_hash(url)
    await db.save_snapshot_hash(url, content_hash)

    if previous_hash is None or previous_hash == content_hash:
        return None

    return await db.create_draft(
        kind="topup",
        source_url=url,
        item_uid=f"page-change:{content_hash}",
        title="Изменилась страница LootBar",
        link=url,
        summary=(
            "Бот обнаружил изменение страницы. Проверьте цены, "
            "наборы и условия вручную перед публикацией."
        ),
    )


def render_draft(title: str, summary: str, link: str) -> str:
    parts = [f"📝 <b>{html.escape(title)}</b>"]
    if summary:
        parts.append(html.escape(summary))
    parts.append(
        f'🔗 <a href="{html.escape(link, quote=True)}">'
        "Открыть источник</a>"
    )
    return "\n\n".join(parts)


def render_public_post(title: str, summary: str, link: str) -> str:
    parts = [f"📢 <b>{html.escape(title)}</b>"]
    if summary:
        parts.append(html.escape(summary))
    parts.append(
        f'🔗 <a href="{html.escape(link, quote=True)}">Источник</a>'
    )
    return "\n\n".join(parts)
