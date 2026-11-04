# Гибрид GPU+CPU (DirectML)

## Что это
Опциональный воркер `local-hybrid`. Видеокарта AMD Radeon RX 6800 XT, бэкенд —
**DirectML** (`torch-directml`), не CUDA. Обычный `local-esc` не менялся.

## v2: бои Mage Fire / Frost
Один бой (30 с) делится на три части:
1. **CPU** — таймлайн событий (кто, что и когда кастует). Это старый
   `sunken_sim.mage.simulate`, файл не менялся: события перехватываются вместо `_compile`.
2. **GPU** — компиляция таймлайна пачкой до 512 боёв: множитель от HP героя
   (Furnace / Gladiator / Crimson), execute, физ/маг множители, Pyroblast mastery,
   ~70 взвешенных сумм как в `mage._compile`. float32.
3. **CPU** — `mage._score` по этим суммам (закрытая формула).

Дискретные шаги (индекс таблицы HP, порог 40%, пороги execute) считаются на CPU
в float64, поэтому не «перескакивают». `finish_sextuple` (таланты → глифы →
жадный ESC) батчится: все комбо таланта, все комбо глифов, все +1 шага ESC —
одной пачкой. Правила те же: строгое `>`, при равенстве побеждает первый.

Код: `farm/hybrid/fight.py`. Спеки с GPU-боями: `mage/fire`, `mage/frost`.
Остальные спеки в `local-hybrid` — старые CPU-бои.

### Защита
- Перед джобой: 64 билда CPU vs GPU (`fight_check`). Не прошло → вся джоба на CPU.
- В каждом процессе: первые 8 боёв сверяются с CPU. Не прошло → процесс на CPU.
- Ошибка пачки → эта пачка пересчитывается старым `eval_span`.
- Допуск: относительная ошибка DPS ≤ 1e-4 (`DPS_TOL`).

### Сверка (DirectML, top-80 mixed, 5 целей)
| спек | билдов | max abs | max rel | CPU мс/бой | гибрид мс/бой |
|---|---|---|---|---|---|
| fire | 2000 | 0.00043 | 2.9e-7 | 14.1 | 4.8 |
| frost | 2000 | 0.0016 | 1.4e-6 | 19.8 | 6.7 |

`finish_sextuple` на 3 чанка каждого спека: те же таланты, глифы, очки ESC и число
боёв, rel ≤ 8.3e-8.

Смоук 3000 чанков (fire, 2 воркера): гибрид 387.9 с, CPU 900.4 с. Все 4 доски —
те же чанки, max rel 6.2e-8.

### Честно про скорость
Ускорение ~2.3–3×, не больше: таймлайн остаётся на CPU и теперь занимает ~80%
времени. Чтобы ускорить дальше, нужно переносить сам таймлайн (состояние боя), а это
отдельный этап.

## Arcane Mage
`mage/arcane` жёстко закреплён за старым CPU-симом (`farm/hybrid/lock.py`).
GPU-бои для него не создаются (`GpuFights` бросает `GpuLocked`). Скрипты Arcane не менялись.

## Запуск
```
cd C:\Users\eseid\sunken-sim
.venv-dml\Scripts\python.exe tools\run_hybrid_parity.py --spec fire --n 2000 --finish 3
.venv-dml\Scripts\python.exe tools\run_hybrid_smoke.py --count 3000 --compare
```
Пишет в `farm-data-hybrid-smoke`, 2 CPU-воркера. `--compare` прогоняет тот же
диапазон старым путём и сравнивает доски.

`FARM_HYBRID_DEVICE`: `auto` (по умолчанию) / `cpu` (torch на CPU) / `dml`.

## Тесты
```
python -m unittest farm.test_hybrid
.venv-dml\Scripts\python.exe -m unittest farm.test_hybrid
```