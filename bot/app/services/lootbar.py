from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Mapping

import httpx

from bot.app.db import Database
from bot.app.services.content_db import save_draft_payload, save_lootbar_assets
from bot.app.services.parsers import SourceCheckResult

logger = logging.getLogger(__name__)

PRICE_API_URL = "https://api.lootbar.com/api/v2/market/sku/price"
LITE_API_URL = "https://api.lootbar.com/api/v2/market/sku/lite"

GAME_SLUG = "last-asylum-plague"
SERVICE_TYPE = "recharge"
PAGE_SIZE = 40
MAX_PAGES = 10
MIN_EXPECTED_PACKAGES = 5

HTTP_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US",
    "Referer": "https://www.lootbar.com/",
    "User-Agent": (
        "Mozilla/5.0 (compatible; AsylumBaseBot/0.3.0; "
        "+https://github.com/kitkotcat/asylum-base)"
    ),
}

RETRYABLE_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True, slots=True)
class LootbarPackage:
    package_key: str
    name: str
    regular_price_minor: int
    promo_price_minor: int
    official_price_minor: int
    savings_minor: int
    currency: str
    discount_badge: str
    coupon_name: str
    sell_order_id: str
    icon_url: str


def _minor_units(value: Any, *, field_name: str) -> int:
    try:
        decimal_value = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(
            f"LootBar: некорректное значение {field_name}: {value!r}"
        ) from exc

    if decimal_value < 0:
        raise ValueError(
            f"LootBar: отрицательное значение {field_name}: {value!r}"
        )

    return int(
        (decimal_value * 100).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _validate_payload(payload: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError(f"LootBar {label}: ответ не является JSON-объектом")

    data = payload.get("data")

    if not isinstance(data, dict):
        raise RuntimeError(f"LootBar {label}: отсутствует объект data")

    items = data.get("items")

    if not isinstance(items, list):
        raise RuntimeError(f"LootBar {label}: отсутствует список data.items")

    return data


async def _request_json(
    client: httpx.AsyncClient,
    *,
    url: str,
    params: Mapping[str, Any],
    label: str,
    attempts: int = 3,
) -> dict[str, Any]:
    delays = (0.0, 1.0, 3.0)
    last_error: Exception | None = None

    for attempt in range(attempts):
        if attempt:
            await asyncio.sleep(delays[min(attempt, len(delays) - 1)])

        try:
            response = await client.get(url, params=params)

            if (
                response.status_code in RETRYABLE_HTTP_CODES
                and attempt + 1 < attempts
            ):
                continue

            response.raise_for_status()

            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"LootBar {label}: API вернул не JSON"
                ) from exc

            if not isinstance(payload, dict):
                raise RuntimeError(
                    f"LootBar {label}: API вернул неожиданный формат"
                )

            return payload

        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.HTTPStatusError,
            RuntimeError,
        ) as exc:
            last_error = exc

            retryable = isinstance(
                exc,
                (httpx.TimeoutException, httpx.NetworkError),
            )

            if isinstance(exc, httpx.HTTPStatusError):
                retryable = (
                    exc.response.status_code in RETRYABLE_HTTP_CODES
                )

            if isinstance(exc, RuntimeError):
                retryable = False

            if not retryable or attempt + 1 >= attempts:
                break

    raise RuntimeError(
        f"LootBar {label}: запрос не выполнен: {last_error}"
    ) from last_error


async def _fetch_all_items(
    client: httpx.AsyncClient,
    *,
    url: str,
    label: str,
    extra_params: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    total_pages = 1

    for page_num in range(1, MAX_PAGES + 1):
        params: dict[str, Any] = {
            "page_num": page_num,
            "page_size": PAGE_SIZE,
            "sort_by": "price.asc",
            "game": GAME_SLUG,
            "service_type": SERVICE_TYPE,
            "attribute": "{}",
            "_l": "en",
        }

        if extra_params:
            params.update(extra_params)

        payload = await _request_json(
            client,
            url=url,
            params=params,
            label=f"{label} page {page_num}",
        )
        data = _validate_payload(payload, label=label)
        page_items = data["items"]

        all_items.extend(
            item
            for item in page_items
            if isinstance(item, dict)
        )

        raw_total_pages = data.get("total_page", 1)

        try:
            total_pages = max(int(raw_total_pages), 1)
        except (TypeError, ValueError):
            total_pages = 1

        if page_num >= total_pages:
            break

    if total_pages > MAX_PAGES:
        raise RuntimeError(
            "LootBar: API сообщил слишком много страниц "
            f"({total_pages}); установлен лимит {MAX_PAGES}"
        )

    return all_items


def _official_price(
    *,
    info: Mapping[str, Any],
    lined_price: Mapping[str, Any],
    currency: str,
    fallback_minor: int,
) -> int:
    lined_value = lined_price.get("price")

    if lined_value not in (None, ""):
        return _minor_units(
            lined_value,
            field_name="sell_order.lined_price.price",
        )

    official_map = info.get("official_price_map")

    if isinstance(official_map, dict):
        official_value = official_map.get(currency)

        if official_value not in (None, ""):
            return _minor_units(
                official_value,
                field_name=f"info.official_price_map.{currency}",
            )

    return fallback_minor


def parse_lootbar_api(
    price_items: Iterable[Mapping[str, Any]],
    lite_items: Iterable[Mapping[str, Any]],
) -> list[LootbarPackage]:
    lite_by_id: dict[int, Mapping[str, Any]] = {}

    for item in lite_items:
        try:
            item_id = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue

        lite_by_id[item_id] = item

    packages: dict[str, LootbarPackage] = {}

    for price_item in price_items:
        try:
            item_id = int(price_item["id"])
        except (KeyError, TypeError, ValueError):
            continue

        lite_item = lite_by_id.get(item_id)

        if lite_item is None:
            logger.warning(
                "LootBar: PRICE item %s отсутствует в LITE",
                item_id,
            )
            continue

        if price_item.get("tradable") is False:
            continue

        info = _dict(price_item.get("info"))
        sell_order = _dict(price_item.get("sell_order"))
        display_price = _dict(sell_order.get("display_price"))
        lined_price = _dict(sell_order.get("lined_price"))
        discount_info = _dict(price_item.get("discount_info"))
        display_discount_price = _dict(
            discount_info.get("display_discount_price")
        )
        coupon = _dict(discount_info.get("coupon"))

        name = _string(info.get("asset_name"))
        sku_id = _string(lite_item.get("sku_id"))
        sell_order_id = _string(sell_order.get("id"))

        if not name or not sku_id or not sell_order_id:
            continue

        currency = (
            _string(display_price.get("currency"))
            or _string(display_discount_price.get("currency"))
            or _string(lined_price.get("currency"))
            or "USD"
        )

        regular_raw = (
            display_price.get("price")
            or sell_order.get("price")
            or sell_order.get("unit_price")
        )

        promo_raw = (
            display_price.get("real_price")
            or display_discount_price.get("price")
            or discount_info.get("discount_price")
            or regular_raw
        )

        if regular_raw in (None, "") or promo_raw in (None, ""):
            continue

        regular_minor = _minor_units(
            regular_raw,
            field_name="regular price",
        )
        promo_minor = _minor_units(
            promo_raw,
            field_name="promo price",
        )
        official_minor = _official_price(
            info=info,
            lined_price=lined_price,
            currency=currency,
            fallback_minor=regular_minor,
        )

        savings_raw = display_price.get("save_price")

        if savings_raw not in (None, ""):
            savings_minor = _minor_units(
                savings_raw,
                field_name="save price",
            )
        else:
            savings_minor = max(official_minor - promo_minor, 0)

        if promo_minor > regular_minor:
            raise RuntimeError(
                f"LootBar: promo price выше обычной цены для {name}"
            )

        if regular_minor > official_minor:
            raise RuntimeError(
                f"LootBar: обычная цена выше официальной для {name}"
            )

        calculated_savings = max(official_minor - promo_minor, 0)

        if abs(calculated_savings - savings_minor) > 1:
            savings_minor = calculated_savings

        package = LootbarPackage(
            package_key=sku_id,
            name=name,
            regular_price_minor=regular_minor,
            promo_price_minor=promo_minor,
            official_price_minor=official_minor,
            savings_minor=savings_minor,
            currency=currency,
            discount_badge=_string(discount_info.get("badge_text")),
            coupon_name=_string(coupon.get("name")),
            sell_order_id=sell_order_id,
            icon_url=_string(info.get("icon")),
        )
        packages[sku_id] = package

    result = sorted(
        packages.values(),
        key=lambda package: (
            package.promo_price_minor,
            package.name.casefold(),
        ),
    )

    if len(result) < MIN_EXPECTED_PACKAGES:
        raise RuntimeError(
            "LootBar API: получено слишком мало валидных пакетов "
            f"({len(result)}). База не обновлена."
        )

    return result


async def fetch_lootbar_packages() -> list[LootbarPackage]:
    timeout = httpx.Timeout(timeout=30.0, connect=10.0)

    async with httpx.AsyncClient(
        headers=HTTP_HEADERS,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        price_items, lite_items = await asyncio.gather(
            _fetch_all_items(
                client,
                url=PRICE_API_URL,
                label="PRICE",
                extra_params={"dispatch_seller": 0},
            ),
            _fetch_all_items(
                client,
                url=LITE_API_URL,
                label="LITE",
            ),
        )

    return parse_lootbar_api(price_items, lite_items)


def _format_money(minor: int | None, currency: str) -> str:
    if minor is None:
        return "—"

    symbols = {
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "RUB": "₽",
    }
    symbol = symbols.get(currency, f"{currency} ")
    value = Decimal(minor) / Decimal(100)

    return f"{symbol}{value:.2f}"


def render_lootbar_changes(
    events: list[dict[str, Any]],
) -> str:
    lines = [
        "LootBar изменил пакеты, цены или условия скидки:",
        "",
    ]

    for event in events[:12]:
        change_type = str(event["change_type"])
        name = str(event["name"])
        currency = str(event["currency"])

        old_promo = _format_money(
            event.get("old_promo_price_minor"),
            currency,
        )
        new_promo = _format_money(
            event.get("promo_price_minor"),
            currency,
        )
        regular = _format_money(
            event.get("regular_price_minor"),
            currency,
        )
        official = _format_money(
            event.get("official_price_minor"),
            currency,
        )
        coupon_name = _string(event.get("coupon_name"))

        if change_type == "added":
            lines.append(
                f"➕ {name}: {new_promo} по акции; "
                f"обычная {regular}; официальная {official}"
            )
        elif change_type == "removed":
            lines.append(
                f"➖ {name}: пакет исчез "
                f"(последняя акционная цена {old_promo})"
            )
        elif change_type == "restored":
            lines.append(
                f"♻️ {name}: снова доступен за {new_promo}"
            )
        elif change_type == "promotion_changed":
            condition = coupon_name or "условия не указаны"
            lines.append(
                f"🏷 {name}: изменились условия акции — {condition}"
            )
        else:
            direction = "📉"

            if (
                event.get("old_promo_price_minor") is not None
                and event.get("promo_price_minor") is not None
                and int(event["promo_price_minor"])
                > int(event["old_promo_price_minor"])
            ):
                direction = "📈"

            lines.append(
                f"{direction} {name}: {old_promo} → {new_promo}; "
                f"обычная {regular}; официальная {official}"
            )

    hidden_count = len(events) - 12

    if hidden_count > 0:
        lines.extend(["", f"И ещё изменений: {hidden_count}."])

    lines.extend(
        [
            "",
            "Важно: акционная цена может зависеть от купона "
            "или статуса пользователя. Проверьте условия "
            "на LootBar перед публикацией.",
        ]
    )

    return "\n".join(lines)


async def check_lootbar_packages(
    db: Database,
    *,
    page_url: str,
    affiliate_url: str,
    min_price_drop_percent: float = 5.0,
    min_savings_increase_cents: int = 50,
) -> SourceCheckResult:
    packages = await fetch_lootbar_packages()
    package_dicts = [asdict(package) for package in packages]
    by_key = {package.package_key: package for package in packages}

    is_baseline, events = await db.sync_lootbar_packages(
        page_url,
        package_dicts,
        remove_after_misses=3,
    )
    await save_lootbar_assets(db, package_dicts)

    if is_baseline or not events:
        return SourceCheckResult(
            draft_ids=(),
            items_count=len(packages),
        )

    created_ids: list[int] = []

    for event in events:
        change_type = str(event.get("change_type") or "")
        package_key = str(event.get("package_key") or "")
        package = by_key.get(package_key)

        old_promo_raw = event.get("old_promo_price_minor")
        new_promo_raw = event.get("promo_price_minor")
        old_savings_raw = event.get("old_official_price_minor")

        auto_eligible = False
        price_drop_percent = 0.0
        savings_increase = 0

        if (
            change_type == "price_changed"
            and old_promo_raw is not None
            and new_promo_raw is not None
            and int(new_promo_raw) < int(old_promo_raw)
        ):
            old_promo = int(old_promo_raw)
            new_promo = int(new_promo_raw)
            price_drop_percent = (old_promo - new_promo) * 100.0 / max(old_promo, 1)

            old_official = int(event.get("old_official_price_minor") or event.get("official_price_minor") or 0)
            old_savings = max(old_official - old_promo, 0)
            new_savings = int(event.get("savings_minor") or 0)
            savings_increase = new_savings - old_savings
            auto_eligible = (
                price_drop_percent >= min_price_drop_percent
                or savings_increase >= min_savings_increase_cents
            )

        review_worthy = auto_eligible or change_type in {"added", "restored"}
        if not review_worthy or package is None:
            continue

        signature_payload = {
            "package_key": package.package_key,
            "change_type": change_type,
            "promo": package.promo_price_minor,
            "regular": package.regular_price_minor,
            "official": package.official_price_minor,
            "coupon": package.coupon_name,
        }
        signature = hashlib.sha256(
            json.dumps(signature_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        title = (
            f"Цена снизилась: {package.name}"
            if change_type == "price_changed"
            else f"Новое предложение: {package.name}"
            if change_type == "added"
            else f"Предложение снова доступно: {package.name}"
        )
        summary = render_lootbar_changes([event])
        draft_id = await db.create_draft(
            kind="deal",
            source_url=page_url,
            item_uid=f"lootbar-deal:{signature}",
            title=title,
            link=affiliate_url or page_url,
            summary=summary,
        )
        if draft_id is None:
            continue

        await save_draft_payload(
            db,
            draft_id,
            image_url=package.icon_url,
            entity_key=package.package_key,
            metadata={
                **asdict(package),
                "change_type": change_type,
                "old_promo_price_minor": old_promo_raw,
                "price_drop_percent": round(price_drop_percent, 2),
                "savings_increase_minor": savings_increase,
                "auto_eligible": auto_eligible,
            },
        )
        created_ids.append(draft_id)

    return SourceCheckResult(
        draft_ids=tuple(created_ids),
        items_count=len(packages),
    )
