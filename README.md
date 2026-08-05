# Asylum Base v0.4.4

Telegram-контентная платформа для русскоязычного сообщества **Last Asylum: Plague**.

Проект собирает новости и предложения, хранит историю изменений, формирует красивые публикации и размещает их в нужных темах Telegram-группы. Автопубликация выключена по умолчанию и включается по источникам через `.env`.

## Что умеет v0.4.4

### Auto Publishing

- мониторинг предложений LootBar через JSON API;
- отдельные карточки только для значимых снижений цены;
- изображение пакета и inline-кнопка с партнёрской ссылкой;
- защита от повторной публикации;
- cooldown для одного пакета;
- лимит автоматических скидочных постов;
- очередь и журнал публикаций;
- ежедневный Top-3 дайджест;
- режимы `manual`, `semi_auto`, `auto`.

### Пользовательский интерфейс

Публичные команды:

- `/start` — компактное inline-меню;
- `/deals` — предложения с пагинацией;
- `/promocodes` — активные промокоды;
- `/news` — последние опубликованные новости;
- `/guides` — навигация по гайдам;
- `/heroes` — база героев и стратегий;
- `/squads` — составы и связки;
- `/events` — календарь событий;
- `/suggest` — предложение материала на модерацию;
- `/help` — понятная справка.

Технические команды скрыты из публичного меню и показываются только администраторам.


### Community Content Platform

- база героев с ролями, сильными и слабыми сторонами;
- база составов и синергий;
- календарь событий с автоматическими напоминаниями;
- управляемый банк контента и расписание повторов;
- дневной лимит автопостов;
- сбор публичных и анонимных Telegram-реакций;
- рейтинг публикаций;
- предложения материалов от участников;
- двухэтапная модерация: предложение → черновик → публикация;
- пауза и возобновление отдельных автопостов.

### Content Engine

- RSS-новости;
- обновления Google Play;
- маршрутизация по Telegram-темам;
- промокоды с регионом и сроком действия;
- автоматическое отключение истёкших кодов;
- ежедневный администраторский отчёт;
- статистика публикаций, ошибок и переходов через меню;
- безопасная ручная модерация черновиков.

## Архитектура

```text
Collectors
  ├─ LootBar JSON API
  ├─ RSS
  └─ Google Play
        ↓
Content Drafts + Payloads
        ↓
Publication Rules
        ↓
Publication Queue
        ↓
Telegram Publisher
        ↓
Publication Log
```

## Безопасные настройки по умолчанию

```dotenv
PUBLISH_MODE=semi_auto
AUTO_PUBLISH_DEALS=false
AUTO_PUBLISH_NEWS=false
AUTO_PUBLISH_GOOGLE_PLAY=false
EDITORIAL_AUTOPOST_ENABLED=false
EDITORIAL_MAX_POSTS_PER_DAY=1
EDITORIAL_TIMEZONE_OFFSET_HOURS=5
DAILY_DEALS_DIGEST_ENABLED=false
```

После деплоя бот продолжит собирать данные и создавать черновики, но не начнёт автоматически публиковать контент, пока флаги не будут включены вручную.

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

Заполните `.env`, затем:

```bash
python -m bot.app.main
```

## Проверки

```bash
python -m compileall bot tests
pytest -q
```

## Основные таблицы

- `content_drafts` — черновики из источников;
- `content_payloads` — изображение, entity key и структурированные данные;
- `publication_queue` — очередь публикации;
- `publication_log` — журнал и защита от дублей;
- `lootbar_packages` — актуальные цены;
- `lootbar_price_history` — история цен;
- `promo_metadata` — регион, срок действия и статус промокода;
- `scheduled_jobs` — защита ежедневных задач от повторного запуска;
- `heroes` — карточки героев;
- `squads` — составы и связки;
- `game_events` — календарь событий;
- `editorial_items` — банк и расписание контента;
- `content_suggestions` — предложения участников;
- `message_reaction_users` и `message_reaction_totals` — аналитика реакций.

## Аналитика переходов

Telegram не сообщает боту о кликах по обычной URL-кнопке. Поэтому без собственного HTTPS redirect точные внешние переходы нужно смотреть в партнёрском кабинете LootBar.

Опционально можно указать:

```dotenv
TRACKED_REDIRECT_BASE_URL=https://example.com/r
```

Redirect-сервис должен принять параметры `to` и `campaign`, записать событие и перенаправить пользователя на партнёрскую ссылку.

## Документация релиза

- [Деплой v0.4.4](docs/DEPLOY_V0.4.4.md)
- [Безопасный деплой v0.3.0](docs/DEPLOY_V0.3.0.md)
- [Приёмочный чек-лист](docs/ACCEPTANCE_V0.3.0.md)
- [Rollback](docs/ROLLBACK_V0.3.0.md)

- [Feature flags](docs/FEATURE_FLAGS.md)
- [Release notes v0.4.4](RELEASE_NOTES_v0.4.4.md)
- [Release notes v0.3.0](RELEASE_NOTES_v0.3.0.md)
