# Feature flags v0.3.0

## Рекомендуемый первый запуск

```dotenv
PUBLISH_MODE=semi_auto
AUTO_PUBLISH_DEALS=false
AUTO_PUBLISH_NEWS=false
AUTO_PUBLISH_GOOGLE_PLAY=false
AUTO_PUBLISH_PROMOS=false
PROMO_MAX_POSTS_PER_DAY=2
DAILY_DEALS_DIGEST_ENABLED=false
DAILY_ADMIN_REPORT_ENABLED=true
```

## Режимы

### `manual`

Все новые материалы отправляются администраторам как черновики. Автопубликации нет независимо от остальных флагов.

### `semi_auto`

Автоматически публикуются только явно разрешённые источники. Для LootBar дополнительно требуется значимое снижение цены по порогам:

```dotenv
MIN_PRICE_DROP_PERCENT=5
MIN_SAVINGS_INCREASE_CENTS=50
```

Новые и восстановленные пакеты остаются на ручной модерации.

### `auto`

Разрешённые флагами источники публикуются автоматически. Для скидок всё равно действуют cooldown, duplicate protection и rate limit.

## Антиспам

```dotenv
MAX_AUTO_POSTS_PER_6_HOURS=2
DEAL_COOLDOWN_HOURS=24
```

Когда лимит исчерпан, материал не теряется: он остаётся черновиком для ручной проверки.

## Промокоды v0.4.5

```dotenv
AUTO_PUBLISH_PROMOS=true
PROMO_MAX_POSTS_PER_DAY=2
PROMO_REDEEM_URL=https://gevents.globallap.com/gamecode/index.html?gameId=440
```

Автоматически публикуются только активные коды с явным статусом `verified`
в таблице `promo_metadata`. Старые записи без метаданных, кандидаты и коды со
статусом `likely` автоматически не публикуются. Изменение награды, региона или
срока создаёт новую версию публикации; неизменный код повторно не отправляется.
