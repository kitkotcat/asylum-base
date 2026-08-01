# Rollback v0.3.0

Новые таблицы изолированы и не изменяют существующие данные v0.2.3. Для отката достаточно вернуть код и резервную копию базы.

```bash
cd ~/apps/asylum-base
sudo systemctl stop asylum-base.service

git switch main
git reset --hard v0.2.3

cp ~/backups/asylum_base_before_v0.3.0_YYYY-MM-DD_HH-MM-SS.db \
  bot/data/asylum_base.db
rm -f bot/data/asylum_base.db-wal bot/data/asylum_base.db-shm

sudo systemctl start asylum-base.service
sudo systemctl is-active asylum-base.service
sudo journalctl -u asylum-base.service --since "5 minutes ago" --no-pager -l
```

Не выполняйте `git reset --hard` на машине с несохранёнными локальными изменениями. На production перед откатом убедитесь, что `git status --short` пуст.
