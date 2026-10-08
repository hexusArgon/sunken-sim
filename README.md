# Sunken City sim

Симулятор боя Sunken City. Карта лежит в `maps/`. Скрипты читают её из репозитория, не из папки на одном компьютере.

## Запуск сима

Нужен Python 3.11.

```
python extract/run_hp.py
```

Поиск жреца Shadow на 5 целях. Результат пишется в `extract/target-sims.json`.

Паладин: `python extract/one_slot_paladin.py`. Специализации Retribution, Protection и Holy. В Discord это `hero: paladin`.

## Несколько компьютеров

Каждая машина клонирует репозиторий и запускает своего воркера. Ключ Discord бота в `.env`, образец в `.env.example`.

```
python -m pip install -r requirements.txt
python run_farm.py
```

Или `npm start`, или `docker compose up -d --build`.

Команда в Discord называется именем этого компьютера. Без `start` и `end` она пишет размер пространства. С ними считает чанки включительно и присылает JSON с топ-10 по DPS.

## Данные

Снимки листа лежат в `_snapshots/` как текст и CSV. Файл `.env` не коммитится.
