from __future__ import annotations

import html
import re
from decimal import Decimal
from typing import Any, Mapping


def money(minor: int | None, currency: str) -> str:
    if minor is None:
        return "—"
    symbols = {"USD": "$", "EUR": "€", "GBP": "£", "RUB": "₽"}
    symbol = symbols.get(currency, f"{currency} ")
    value = Decimal(int(minor)) / Decimal(100)
    return f"{symbol}{value:.2f}"


def clean_condition(badge: str, coupon: str) -> str:
    badge = badge.strip()
    coupon = coupon.strip()
    if not coupon:
        return badge
    normalized_coupon = coupon.casefold().replace("off", "")
    normalized_badge = badge.casefold().replace("off", "")
    if badge and normalized_badge.strip(" %") in normalized_coupon:
        return coupon
    return " ".join(part for part in (badge, coupon) if part)


def trim_text(value: str, limit: int = 700) -> str:
    normalized = re.sub(r"\s+", " ", value or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def render_deal_caption(draft: Mapping[str, Any]) -> str:
    metadata = draft.get("metadata") or {}
    name = html.escape(str(metadata.get("name") or draft.get("title") or "Предложение"))
    currency = str(metadata.get("currency") or "USD")
    promo = money(metadata.get("promo_price_minor"), currency)
    regular = money(metadata.get("regular_price_minor"), currency)
    official = money(metadata.get("official_price_minor"), currency)
    savings = money(metadata.get("savings_minor"), currency)
    condition = clean_condition(
        str(metadata.get("discount_badge") or ""),
        str(metadata.get("coupon_name") or ""),
    )

    lines = [
        f"🔥 <b>{name}</b>",
        "",
        f"Цена по акции: <b>{promo}</b>",
        f"Без купона: {regular}",
        f"Официальная цена: <s>{official}</s>",
        f"💰 Экономия: <b>{savings}</b>",
    ]
    if condition:
        lines.extend(["", f"🏷 Условие: {html.escape(condition)}"])
    lines.extend(
        [
            "",
            "<i>Цена и условия могут измениться. Проверьте итоговую стоимость перед оплатой.</i>",
            "",
            "<i>Партнёрская ссылка.</i>",
        ]
    )
    return "\n".join(lines)


def render_digest_caption(draft: Mapping[str, Any]) -> str:
    metadata = draft.get("metadata") or {}
    items = metadata.get("items") or []
    lines = ["🔥 <b>Лучшие предложения дня в Last Asylum</b>", ""]
    for index, item in enumerate(items[:3], start=1):
        currency = str(item.get("currency") or "USD")
        name = html.escape(str(item.get("name") or "Пакет"))
        promo = money(item.get("promo_price_minor"), currency)
        official = money(item.get("official_price_minor"), currency)
        savings = money(item.get("savings_minor"), currency)
        lines.extend(
            [
                f"{index}️⃣ <b>{name}</b>",
                f"{promo} вместо {official}",
                f"Экономия: {savings}",
                "",
            ]
        )
    lines.extend(
        [
            "Проверьте условия купона и итоговую цену перед оплатой.",
            "",
            "<i>Партнёрская ссылка.</i>",
        ]
    )
    return "\n".join(lines)


def render_news_caption(draft: Mapping[str, Any]) -> str:
    title = html.escape(str(draft.get("title") or "Новость Last Asylum"))
    summary = html.escape(trim_text(str(draft.get("summary") or ""), 850))
    lines = [f"📰 <b>{title}</b>"]
    if summary:
        lines.extend(["", summary])
    lines.extend(["", "Подробности — по кнопке ниже."])
    return "\n".join(lines)


def render_google_play_caption(draft: Mapping[str, Any]) -> str:
    title = html.escape(str(draft.get("title") or "Обновление Last Asylum"))
    summary = html.escape(trim_text(str(draft.get("summary") or ""), 950))
    return "\n".join(
        [
            f"🛠 <b>{title}</b>",
            "",
            summary,
            "",
            "Проверьте полное описание обновления в Google Play.",
        ]
    )


def render_public_caption(draft: Mapping[str, Any]) -> str:
    kind = str(draft.get("kind") or "news")
    if kind in {"deal", "topup"}:
        return render_deal_caption(draft)
    if kind == "deal_digest":
        return render_digest_caption(draft)
    if kind == "google_play":
        return render_google_play_caption(draft)
    if kind in {"guide", "hero", "squad", "event", "alliance"}:
        from bot.app.services.community_content import render_editorial_caption

        return render_editorial_caption(draft)
    return render_news_caption(draft)
