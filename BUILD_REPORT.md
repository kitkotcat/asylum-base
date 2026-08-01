# Build report — Asylum Base v0.3.0

## Выполнено в сборочной среде

- Python syntax compilation: passed;
- import graph smoke with lightweight dependency stubs: passed;
- SQLite content schema smoke: passed;
- publication queue and duplicate-protection smoke: passed;
- deal caption formatting smoke: passed;
- LootBar API fixture parsing smoke: passed;
- significant price-drop draft detection smoke: passed.

## Ограничение проверки

Полный `pytest -q` не был выполнен в сборочной среде: среда не имела сетевого доступа для установки runtime-зависимостей проекта (`aiogram`, `aiosqlite`, `httpx`, `feedparser`, `beautifulsoup4`).

Перед merge обязательно выполнить в локальной `.venv` проекта:

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m compileall bot tests scripts
pytest -q
```
