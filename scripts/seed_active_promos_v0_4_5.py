from __future__ import annotations

import asyncio

from bot.app.config import load_settings
from bot.app.db import Database
from bot.app.services.content_db import init_content_schema, set_promo_metadata


SOURCE = "https://www.minutetactics.com/codes/last-asylum-plague-promo-codes"

PROMOS = (
    {
        "code": "LA20WBZ9",
        "reward": "Награда в игре; точный состав не опубликован",
    },
    {
        "code": "LA15WPN4D",
        "reward": (
            "300 алмазов, 60 ускорений по 5 минут, "
            "30K зерна и 30K древесины"
        ),
    },
    {
        "code": "LA1OW9F7X",
        "reward": (
            "200 алмазов, 40 ускорений по 5 минут, "
            "20K зерна и 20K древесины"
        ),
    },
    {
        "code": "LADCEX1223",
        "reward": (
            "100 алмазов, 12 ускорений по 5 минут, "
            "15K зерна и 15K древесины"
        ),
    },
)


async def main() -> None:
    settings = load_settings()
    db = Database(settings.db_path)
    await db.init()
    await init_content_schema(db)

    for promo in PROMOS:
        promo_id = await db.add_promo(
            str(promo["code"]),
            str(promo["reward"]),
            SOURCE,
        )
        await set_promo_metadata(
            db,
            promo_id,
            region="Global",
            expires_at=None,
            verification_status="verified",
        )
        print(f"UPSERT promo #{promo_id}: {promo['code']}")

    print(f"Verified promos seeded: {len(PROMOS)}")


if __name__ == "__main__":
    asyncio.run(main())
