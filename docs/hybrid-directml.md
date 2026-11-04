# Гибрид GPU+CPU (DirectML)

## Что это
Опциональный воркер `local-hybrid`. Видеокарта: AMD Radeon RX 6800 XT, поэтому
бэкенд — **DirectML** (`torch-directml`), не CUDA.

## Что работает сейчас (v1)
- Определение устройства: DirectML, если стоит и работает, иначе CPU.
- На GPU — только подготовка данных: суммы статов предметов по пачке билдов.
  Это **не бой и не DPS**. Результат сверяется с CPU; при расхождении — только CPU.
- **Все бои** — старый CPU-сим (`farm.runner.run_job`). DPS тот же, что у `local-esc`.
- Нет DirectML → тихо работает на CPU.

## Arcane Mage
`mage/arcane` жёстко закреплён за старым CPU-симом (`farm/hybrid/lock.py`).
Даже через `local-hybrid` он уходит в `farm.runner.run_job` без GPU.
Скрипты Arcane (`tools/run_mage_arcane_top80_esc.py`, resume) не менялись.

## Как запустить смоук
GPU-окружение отдельное, чтобы не ломать основной Python (там torch 2.14 CPU,
а `torch-directml` тянет свой torch):
```
cd C:\Users\eseid\sunken-sim
.venv-dml\Scripts\python.exe tools\run_hybrid_smoke.py --hero mage --spec fire --count 2000
```
Пишет в `farm-data-hybrid-smoke`, 2 CPU-воркера. Первая строка — `hybrid`:
устройство, время CPU/GPU, `parity`.

Переменная `FARM_HYBRID_DEVICE`: `auto` (по умолчанию) / `cpu` / `dml`.

## Тесты
```
python -m unittest farm.test_hybrid
.venv-dml\Scripts\python.exe -m unittest farm.test_hybrid
```

## Дальше
Чтобы GPU реально ускорял, нужно перенести сам бой в пачки (`kernel.py`) и
сверить DPS с CPU на выборке билдов. До сверки бои остаются на CPU.