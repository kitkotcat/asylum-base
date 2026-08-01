# Безопасный деплой v0.3.0

## 1. До merge

```bash
git switch -c feat/content-platform-v0.3.0
python -m compileall bot tests
pytest -q
git status --short
```

Убедитесь, что в Git не попали `.env`, база SQLite, токены и приватные ключи.

## 2. Резервная копия VPS

```bash
cd ~/apps/asylum-base
mkdir -p ~/backups

DB_PATH="$HOME/apps/asylum-base/bot/data/asylum_base.db"
BACKUP_PATH="$HOME/backups/asylum_base_before_v0.3.0_$(date +%Y-%m-%d_%H-%M-%S).db"

.venv/bin/python - "$DB_PATH" "$BACKUP_PATH" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(sys.argv[1])
target = sqlite3.connect(sys.argv[2])
try:
    source.backup(target)
    target.commit()
finally:
    target.close()
    source.close()
print(sys.argv[2])
PY
```

Проверьте:

```bash
.venv/bin/python - "$BACKUP_PATH" <<'PY'
import sqlite3
import sys
conn = sqlite3.connect(sys.argv[1])
try:
    print(conn.execute("PRAGMA integrity_check").fetchone()[0])
finally:
    conn.close()
PY
```

## 3. Остановка и обновление

```bash
sudo systemctl stop asylum-base.service
sudo systemctl is-active asylum-base.service || true
pgrep -af 'bot.app.main' || echo "Bot stopped: OK"

git switch main
git pull --ff-only origin main
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m compileall -q bot
```

## 4. Миграция без запуска бота

Новые таблицы создаются через `init_content_schema()` при старте. Сначала проверьте миграцию на копии базы:

```bash
cp "$BACKUP_PATH" /tmp/asylum-v0.3.0-dry-run.db
DB_PATH=/tmp/asylum-v0.3.0-dry-run.db .venv/bin/python scripts/check_v0_3_0_schema.py
```

После успешного dry-run выполните для рабочей базы:

```bash
.venv/bin/python scripts/check_v0_3_0_schema.py
```

## 5. Первый запуск без автопостинга

В `.env` оставьте:

```dotenv
PUBLISH_MODE=semi_auto
AUTO_PUBLISH_DEALS=false
AUTO_PUBLISH_NEWS=false
AUTO_PUBLISH_GOOGLE_PLAY=false
DAILY_DEALS_DIGEST_ENABLED=false
```

Запуск:

```bash
sudo systemctl start asylum-base.service
sleep 3
sudo systemctl is-active asylum-base.service
sudo journalctl -u asylum-base.service --since "5 minutes ago" --no-pager -l
```

## 6. Пошаговое включение

1. Проверить `/start`, `/deals`, `/promocodes`, `/news`, `/guides`.
2. Выполнить `/radar_check`.
3. Опубликовать один тестовый черновик вручную.
4. Включить `AUTO_PUBLISH_DEALS=true`.
5. Через сутки включить дайджест.
6. Новости и Google Play включать отдельно после проверки шаблонов.
