from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse

from bot.app.config import Settings
from bot.app.services.lootbar import LootbarPackage


@dataclass(frozen=True, slots=True)
class SalesOffer:
    package_key: str
    name: str
    promo_price_minor: int
    official_price_minor: int
    savings_minor: int
    discount_percent: int
    currency: str
    sell_order_id: str
    icon_url: str

    @property
    def price_fingerprint(self) -> tuple[str, int, int]:
        return (
            self.currency,
            self.promo_price_minor,
            self.official_price_minor,
        )


def discount_percent(*, promo_price_minor: int, official_price_minor: int) -> int:
    if official_price_minor <= 0 or promo_price_minor >= official_price_minor:
        return 0
    percent = (
        Decimal(official_price_minor - promo_price_minor)
        * Decimal(100)
        / Decimal(official_price_minor)
    )
    return int(percent.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def package_to_sales_offer(package: LootbarPackage) -> SalesOffer | None:
    package_key = package.package_key.strip()
    name = package.name.strip()
    currency = package.currency.strip().upper()
    promo = int(package.promo_price_minor)
    official = int(package.official_price_minor)

    if not package_key or not name or not currency:
        return None
    if promo <= 0 or official <= promo:
        return None

    savings = official - promo
    percent = discount_percent(
        promo_price_minor=promo,
        official_price_minor=official,
    )
    if savings <= 0 or percent <= 0:
        return None

    return SalesOffer(
        package_key=package_key,
        name=name,
        promo_price_minor=promo,
        official_price_minor=official,
        savings_minor=savings,
        discount_percent=percent,
        currency=currency,
        sell_order_id=package.sell_order_id.strip(),
        icon_url=package.icon_url.strip(),
    )


def select_sales_offer(
    packages: list[LootbarPackage],
    *,
    excluded_package_keys: set[str] | None = None,
    excluded_price_fingerprints: set[tuple[str, int, int]] | None = None,
) -> SalesOffer | None:
    excluded_keys = excluded_package_keys or set()
    excluded_prices = excluded_price_fingerprints or set()
    unique_prices: dict[tuple[str, int, int], SalesOffer] = {}

    for package in packages:
        offer = package_to_sales_offer(package)
        if offer is None:
            continue
        if offer.package_key in excluded_keys:
            continue
        if offer.price_fingerprint in excluded_prices:
            continue

        current = unique_prices.get(offer.price_fingerprint)
        if current is None or (
            offer.discount_percent,
            offer.savings_minor,
            offer.package_key,
        ) > (
            current.discount_percent,
            current.savings_minor,
            current.package_key,
        ):
            unique_prices[offer.price_fingerprint] = offer

    if not unique_prices:
        return None

    return min(
        unique_prices.values(),
        key=lambda offer: (
            -offer.discount_percent,
            -offer.savings_minor,
            offer.promo_price_minor,
            offer.name.casefold(),
            offer.package_key,
        ),
    )


def current_sales_slot(
    *,
    now: datetime,
    timezone_offset_hours: int,
    hours_local: tuple[int, ...],
) -> str | None:
    local_tz = timezone(timedelta(hours=timezone_offset_hours))
    local_now = now.astimezone(local_tz)
    if local_now.hour not in hours_local:
        return None
    return f"{local_now.date().isoformat()}:{local_now.hour:02d}"


def build_offer_url(settings: Settings, offer: SalesOffer) -> str:
    template = settings.deal_sales_affiliate_url_template.strip()
    if template:
        try:
            url = template.format(
                package_key=offer.package_key,
                sell_order_id=offer.sell_order_id,
            )
        except (KeyError, ValueError) as exc:
            raise RuntimeError(
                "DEAL_SALES_AFFILIATE_URL_TEMPLATE содержит "
                "неподдерживаемый placeholder"
            ) from exc
    else:
        url = settings.lootbar_affiliate_url.strip()

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(
            "Не настроена корректная партнёрская ссылка для продающих постов"
        )
    return url
