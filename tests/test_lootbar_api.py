from __future__ import annotations

from bot.app.services.lootbar import parse_lootbar_api


def _price_item(
    item_id: int,
    name: str,
    *,
    regular: str,
    promo: str,
    official: str,
    save: str,
) -> dict:
    return {
        "id": item_id,
        "tradable": True,
        "info": {
            "asset_name": name,
            "official_price_map": {"USD": official},
        },
        "discount_info": {
            "badge_text": "8%",
            "coupon": {"name": "New User 8% Off Coupon"},
            "discount_price": promo,
            "display_discount_price": {
                "currency": "USD",
                "price": promo,
            },
        },
        "sell_order": {
            "id": f"T{item_id}",
            "price": regular,
            "display_price": {
                "currency": "USD",
                "price": regular,
                "real_price": promo,
                "save_price": save,
            },
            "lined_price": {
                "currency": "USD",
                "price": official,
            },
        },
    }


def _lite_item(item_id: int, name: str) -> dict:
    return {
        "id": item_id,
        "tradable": True,
        "sku_id": f"1257_{item_id}",
        "info": {"asset_name": name},
        "sell_order": {"id": f"T{item_id}"},
    }


def test_parse_lootbar_api_uses_real_schema() -> None:
    names = [
        "First Top Up Pack",
        "Small Pack",
        "Medium Pack",
        "Hero Pass",
        "999 Banknotes",
    ]
    price_items = [
        _price_item(
            index,
            name,
            regular=str(index + 0.89),
            promo=str(index + 0.82),
            official=str(index + 0.99),
            save="0.17",
        )
        for index, name in enumerate(names, start=1)
    ]
    lite_items = [
        _lite_item(index, name)
        for index, name in enumerate(names, start=1)
    ]

    packages = parse_lootbar_api(price_items, lite_items)

    assert len(packages) == 5

    package = next(
        item
        for item in packages
        if item.name == "999 Banknotes"
    )

    assert package.package_key == "1257_5"
    assert package.regular_price_minor == 589
    assert package.promo_price_minor == 582
    assert package.official_price_minor == 599
    assert package.savings_minor == 17
    assert package.currency == "USD"
    assert package.discount_badge == "8%"
    assert package.coupon_name == "New User 8% Off Coupon"
