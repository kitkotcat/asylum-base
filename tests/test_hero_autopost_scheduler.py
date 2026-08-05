from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from bot.app.services import scheduler


class FakeDatabase:
    def __init__(self) -> None:
        self.created: list[str] = []

    async def create_draft(
        self,
        *,
        kind: str,
        source_url: str,
        item_uid: str,
        title: str,
        link: str,
        summary: str,
    ) -> int:
        self.created.append(kind)
        return len(self.created)


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "editorial_autopost_enabled": True,
        "editorial_timezone_offset_hours": 5,
        "group_chat_id": -1003810338089,
        "editorial_max_posts_per_day": 1,
        "hero_autopost_enabled": True,
        "hero_max_posts_per_day": 2,
        "hero_min_interval_hours": 6,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _item(editorial_id: int, kind: str) -> dict[str, object]:
    return {
        "id": editorial_id,
        "kind": kind,
        "next_publish_at": "2026-08-05T00:00:00+00:00",
        "source_url": "",
        "title": f"Item {editorial_id}",
        "body": "Body",
        "image_file_id": "telegram-file-id" if kind == "hero" else "",
        "entity_key": f"{kind}:{editorial_id}",
    }


def test_recent_hero_is_blocked_but_nonhero_still_publishes(monkeypatch) -> None:
    async def scenario() -> None:
        db = FakeDatabase()
        queued: list[str] = []
        marked: list[int] = []

        async def count_today(*args, kinds, **kwargs) -> int:
            return 0

        async def latest(*args, **kwargs) -> str:
            return datetime.now(timezone.utc).isoformat(timespec="seconds")

        async def due(*args, **kwargs):
            return [_item(1, "hero"), _item(2, "guide")]

        async def save(*args, **kwargs) -> None:
            return None

        async def enqueue(db, draft_id, kind, priority=100) -> bool:
            queued.append(kind)
            return True

        async def mark(db, editorial_id) -> None:
            marked.append(editorial_id)

        async def process(*args, **kwargs) -> int:
            return len(queued)

        monkeypatch.setattr(scheduler, "count_editorial_publications_today", count_today)
        monkeypatch.setattr(
            scheduler,
            "latest_auto_editorial_publication_at",
            latest,
        )
        monkeypatch.setattr(scheduler, "list_due_editorial_items", due)
        monkeypatch.setattr(scheduler, "save_draft_payload", save)
        monkeypatch.setattr(scheduler, "enqueue_draft", enqueue)
        monkeypatch.setattr(scheduler, "mark_editorial_dispatched", mark)
        monkeypatch.setattr(scheduler, "process_publication_queue", process)

        published = await scheduler.dispatch_due_editorial_content(
            SimpleNamespace(),
            _settings(),
            db,
        )

        assert published == 1
        assert queued == ["guide"]
        assert marked == [2]

    asyncio.run(scenario())


def test_hero_and_nonhero_have_separate_daily_quotas(monkeypatch) -> None:
    async def scenario() -> None:
        db = FakeDatabase()
        queued: list[str] = []

        async def count_today(*args, kinds, **kwargs) -> int:
            return 0

        async def latest(*args, **kwargs) -> None:
            return None

        async def due(*args, **kwargs):
            return [
                _item(1, "hero"),
                _item(2, "guide"),
                _item(3, "squad"),
                _item(4, "hero"),
            ]

        async def save(*args, **kwargs) -> None:
            return None

        async def enqueue(db, draft_id, kind, priority=100) -> bool:
            queued.append(kind)
            return True

        async def mark(*args, **kwargs) -> None:
            return None

        async def process(*args, **kwargs) -> int:
            return len(queued)

        monkeypatch.setattr(scheduler, "count_editorial_publications_today", count_today)
        monkeypatch.setattr(
            scheduler,
            "latest_auto_editorial_publication_at",
            latest,
        )
        monkeypatch.setattr(scheduler, "list_due_editorial_items", due)
        monkeypatch.setattr(scheduler, "save_draft_payload", save)
        monkeypatch.setattr(scheduler, "enqueue_draft", enqueue)
        monkeypatch.setattr(scheduler, "mark_editorial_dispatched", mark)
        monkeypatch.setattr(scheduler, "process_publication_queue", process)

        published = await scheduler.dispatch_due_editorial_content(
            SimpleNamespace(),
            _settings(),
            db,
        )

        assert published == 2
        assert queued == ["hero", "guide"]

    asyncio.run(scenario())
