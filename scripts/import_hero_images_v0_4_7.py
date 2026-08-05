from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_ASSETS_DIR = (
    Path(__file__).resolve().parents[1] / "bot" / "assets" / "heroes"
)
MANIFEST_NAME = "manifest.json"
MAX_FILE_BYTES = 10 * 1024 * 1024
MIN_WIDTH = 400
MIN_HEIGHT = 300
MAX_DIMENSION = 4096


@dataclass(frozen=True)
class HeroAsset:
    slug: str
    name: str
    path: Path
    sha256: str
    width: int
    height: int
    size_bytes: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)

    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name}: файл не является корректным PNG")

    width, height = struct.unpack(">II", header[16:24])
    return int(width), int(height)


def load_assets(assets_dir: Path) -> list[HeroAsset]:
    manifest_path = assets_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Не найден manifest: {manifest_path}")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_heroes = payload.get("heroes")

    if not isinstance(raw_heroes, list) or not raw_heroes:
        raise ValueError("manifest.json: heroes должен быть непустым списком")

    assets: list[HeroAsset] = []
    seen_slugs: set[str] = set()
    seen_files: set[str] = set()

    for raw in raw_heroes:
        if not isinstance(raw, dict):
            raise ValueError("manifest.json: каждая запись героя должна быть объектом")

        slug = str(raw.get("slug") or "").strip().lower()
        name = str(raw.get("name") or "").strip()
        filename = str(raw.get("filename") or "").strip()
        expected_sha256 = str(raw.get("sha256") or "").strip().lower()

        if not slug or not name or not filename or len(expected_sha256) != 64:
            raise ValueError(f"manifest.json: неполная запись героя: {raw!r}")
        if slug in seen_slugs:
            raise ValueError(f"manifest.json: повтор slug {slug}")
        if filename in seen_files:
            raise ValueError(f"manifest.json: повтор filename {filename}")

        path = assets_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"{slug}: не найден файл {path}")
        if path.suffix.lower() != ".png":
            raise ValueError(f"{slug}: разрешены только PNG-файлы")

        size_bytes = path.stat().st_size
        if size_bytes <= 0 or size_bytes > MAX_FILE_BYTES:
            raise ValueError(
                f"{slug}: недопустимый размер {size_bytes} байт "
                f"(максимум {MAX_FILE_BYTES})"
            )

        width, height = _png_dimensions(path)
        if width < MIN_WIDTH or height < MIN_HEIGHT:
            raise ValueError(
                f"{slug}: изображение слишком маленькое: {width}x{height}"
            )
        if width > MAX_DIMENSION or height > MAX_DIMENSION:
            raise ValueError(
                f"{slug}: изображение слишком большое: {width}x{height}"
            )

        actual_sha256 = _sha256(path)
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"{slug}: SHA-256 не совпадает\n"
                f"  expected={expected_sha256}\n"
                f"  actual={actual_sha256}"
            )

        declared_width = int(raw.get("width") or width)
        declared_height = int(raw.get("height") or height)
        declared_size = int(raw.get("size_bytes") or size_bytes)

        if (declared_width, declared_height) != (width, height):
            raise ValueError(
                f"{slug}: размеры manifest не совпадают с PNG"
            )
        if declared_size != size_bytes:
            raise ValueError(
                f"{slug}: size_bytes в manifest не совпадает с файлом"
            )

        assets.append(
            HeroAsset(
                slug=slug,
                name=name,
                path=path,
                sha256=actual_sha256,
                width=width,
                height=height,
                size_bytes=size_bytes,
            )
        )
        seen_slugs.add(slug)
        seen_files.add(filename)

    return assets


def inspect_database(
    db_path: Path,
    assets: list[HeroAsset],
    *,
    force: bool,
) -> dict[str, str]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    try:
        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check: {integrity}")

        slugs = [asset.slug for asset in assets]
        placeholders = ", ".join("?" for _ in slugs)
        rows = connection.execute(
            f"""
            SELECT slug, name_en, image_file_id, status
            FROM heroes
            WHERE slug IN ({placeholders})
            ORDER BY slug
            """,
            slugs,
        ).fetchall()

        found = {str(row["slug"]): row for row in rows}
        missing = [slug for slug in slugs if slug not in found]
        if missing:
            raise RuntimeError(
                "В таблице heroes не найдены slug: " + ", ".join(missing)
            )

        inactive = [
            slug
            for slug, row in found.items()
            if str(row["status"]).lower() != "active"
        ]
        if inactive:
            raise RuntimeError(
                "Герои не active: " + ", ".join(sorted(inactive))
            )

        existing = {
            slug: str(row["image_file_id"] or "").strip()
            for slug, row in found.items()
        }
        already_filled = [slug for slug, value in existing.items() if value]
        if already_filled and not force:
            raise RuntimeError(
                "image_file_id уже заполнен для: "
                + ", ".join(sorted(already_filled))
                + ". Для замены нужен --force."
            )

        return existing
    finally:
        connection.close()


def update_database(
    db_path: Path,
    file_ids: dict[str, str],
    *,
    force: bool,
) -> None:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("BEGIN IMMEDIATE")

        for slug, file_id in file_ids.items():
            if force:
                cursor = connection.execute(
                    """
                    UPDATE heroes
                    SET image_file_id = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE slug = ?
                      AND status = 'active'
                    """,
                    (file_id, slug),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE heroes
                    SET image_file_id = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE slug = ?
                      AND status = 'active'
                      AND COALESCE(image_file_id, '') = ''
                    """,
                    (file_id, slug),
                )

            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"{slug}: обновлено строк {cursor.rowcount}, ожидалась 1"
                )

        placeholders = ", ".join("?" for _ in file_ids)
        rows = connection.execute(
            f"""
            SELECT slug, image_file_id
            FROM heroes
            WHERE slug IN ({placeholders})
            """,
            list(file_ids),
        ).fetchall()
        actual = {
            str(row["slug"]): str(row["image_file_id"] or "")
            for row in rows
        }

        if actual != file_ids:
            raise RuntimeError(
                "Проверка после UPDATE не пройдена: "
                f"expected={file_ids!r}, actual={actual!r}"
            )

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


async def upload_assets(
    assets: list[HeroAsset],
    *,
    bot_token: str,
    target_chat_id: int,
    message_thread_id: int | None,
    keep_messages: bool,
) -> dict[str, str]:
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.types import FSInputFile

    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    file_ids: dict[str, str] = {}

    try:
        for index, asset in enumerate(assets, start=1):
            message = await bot.send_photo(
                chat_id=target_chat_id,
                message_thread_id=message_thread_id,
                photo=FSInputFile(asset.path),
                caption=(
                    "🛠 <b>Техническая загрузка изображения</b>\n"
                    f"{index}/{len(assets)} · {asset.name}"
                ),
                disable_notification=True,
            )

            if not message.photo:
                raise RuntimeError(
                    f"{asset.slug}: Telegram не вернул photo"
                )

            file_id = message.photo[-1].file_id
            if not file_id:
                raise RuntimeError(
                    f"{asset.slug}: Telegram вернул пустой file_id"
                )

            file_ids[asset.slug] = file_id
            print(f"UPLOAD {asset.slug}: OK")

            if not keep_messages:
                try:
                    await bot.delete_message(
                        chat_id=target_chat_id,
                        message_id=message.message_id,
                    )
                    print(f"DELETE {asset.slug}: OK")
                except Exception as error:
                    print(
                        f"WARNING {asset.slug}: временное сообщение "
                        f"не удалено: {error}"
                    )
    finally:
        await bot.session.close()

    if len(file_ids) != len(assets):
        raise RuntimeError(
            f"Загружено {len(file_ids)} из {len(assets)} изображений"
        )

    return file_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Проверяет и пакетно импортирует изображения героев "
            "в Telegram и SQLite."
        )
    )
    parser.add_argument(
        "--assets-dir",
        type=Path,
        default=DEFAULT_ASSETS_DIR,
        help=f"Каталог изображений (по умолчанию: {DEFAULT_ASSETS_DIR})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Загрузить изображения и обновить базу. Без флага — dry-run.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Разрешить замену уже заполненных image_file_id.",
    )
    parser.add_argument(
        "--keep-upload-messages",
        action="store_true",
        help="Не удалять технические сообщения после получения file_id.",
    )
    return parser.parse_args()


async def main() -> None:
    from bot.app.config import load_settings
    from bot.app.services.publisher import thread_id_for_kind

    args = parse_args()
    assets_dir = args.assets_dir.resolve()
    assets = load_assets(assets_dir)

    settings = load_settings()
    db_path = Path(settings.db_path)
    existing = inspect_database(
        db_path,
        assets,
        force=args.force,
    )

    print("=== HERO IMAGE IMPORT v0.4.7 ===")
    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"Assets directory: {assets_dir}")
    print(f"Database: {db_path}")
    print(f"Heroes: {len(assets)}")

    for asset in assets:
        previous = "SET" if existing[asset.slug] else "EMPTY"
        print(
            f"  {asset.slug}: {asset.width}x{asset.height} | "
            f"{asset.size_bytes} bytes | DB={previous} | SHA256=OK"
        )

    if not args.apply:
        print("Dry-run: OK")
        print("No Telegram uploads or database changes were made")
        return

    if settings.group_chat_id is None:
        raise RuntimeError("GROUP_CHAT_ID не настроен")

    admin_ids = sorted(int(value) for value in settings.admin_ids)
    if admin_ids:
        target_chat_id = admin_ids[0]
        message_thread_id = None
        target_name = "private admin chat"
    else:
        target_chat_id = int(settings.group_chat_id)
        message_thread_id = thread_id_for_kind(settings, "hero")
        target_name = "heroes topic"

    print(f"Upload target: {target_name} ({target_chat_id})")

    file_ids = await upload_assets(
        assets,
        bot_token=settings.bot_token,
        target_chat_id=target_chat_id,
        message_thread_id=message_thread_id,
        keep_messages=args.keep_upload_messages,
    )

    update_database(
        db_path,
        file_ids,
        force=args.force,
    )

    print("Database update: OK")
    print(f"Imported images: {len(file_ids)}/{len(assets)}")
    print("Hero image import v0.4.7: OK")


if __name__ == "__main__":
    asyncio.run(main())
