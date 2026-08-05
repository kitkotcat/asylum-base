from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "import_hero_images_v0_4_7.py"

spec = importlib.util.spec_from_file_location(
    "import_hero_images_v0_4_7",
    SCRIPT_PATH,
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def _create_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE heroes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name_en TEXT NOT NULL,
                image_file_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                updated_at TEXT
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO heroes(slug, name_en)
            VALUES (?, ?)
            """,
            (
                ("marlena", "Marlena"),
                ("cynthia", "Cynthia"),
                ("annie", "Annie"),
                ("harper", "Harper"),
                ("brian", "Brian"),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_assets_and_manifest_are_valid() -> None:
    assets = module.load_assets(ROOT / "bot" / "assets" / "heroes")

    assert [asset.slug for asset in assets] == [
        "marlena",
        "cynthia",
        "annie",
        "harper",
        "brian",
    ]
    assert all(asset.width >= 400 for asset in assets)
    assert all(asset.height >= 300 for asset in assets)
    assert all(len(asset.sha256) == 64 for asset in assets)


def test_database_update_is_atomic_and_exact(tmp_path: Path) -> None:
    db_path = tmp_path / "heroes.db"
    _create_database(db_path)

    assets = module.load_assets(ROOT / "bot" / "assets" / "heroes")
    existing = module.inspect_database(db_path, assets, force=False)

    assert set(existing) == {
        "marlena",
        "cynthia",
        "annie",
        "harper",
        "brian",
    }
    assert all(value == "" for value in existing.values())

    expected = {
        asset.slug: f"telegram-file-id-{asset.slug}"
        for asset in assets
    }
    module.update_database(db_path, expected, force=False)

    connection = sqlite3.connect(db_path)
    try:
        actual = dict(
            connection.execute(
                "SELECT slug, image_file_id FROM heroes"
            ).fetchall()
        )
    finally:
        connection.close()

    assert actual == expected
