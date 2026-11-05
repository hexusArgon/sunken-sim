# Гибрид GPU+CPU (DirectML)

## Что это
Опциональный воркер local-hybrid. Видеокарта AMD Radeon RX 6800 XT, бэкенд —
**DirectML** (	orch-directml), не CUDA. Обычный local-esc не менялся.

Все классы/спеки проходят через arm/hybrid/registry.py (матрица статусов).
Общий батч-поиск талантов/глифов/ESC — arm/hybrid/engine.py.

## Статусы (v3)
| статус | смысл | кто |
|---|---|---|
| locked | только CPU, torch не импортируется | mage/arcane |
| hybrid-timeline | CPU-таймлайн + точный timeline-cache, GPU compile, CPU score | mage/fire, mage/frost |
| hybrid-compile | CPU-таймлайн (кэш модуля), GPU compile, CPU score | priest shadow/discipline/holy |
| cpu-only | local-hybrid (device + v1 stat-parity), бои = simulate модуля | остальные 53 спека |

Дальше GPU-compile для остальных нужен split simulate → events → compile → score
в sunken_sim (как у mage/priest). Порт-очередь в 
egistry.PORT_ORDER: paladin, shaman.

### Честно про таймлайн на GPU
Состояние боя (кто/когда кастует) по-прежнему на CPU. hybrid-timeline = точный
кэш таймлайна + GPU на взвешенных суммах. Полный перенос state machine на GPU —
отдельный этап.

## Mage Fire / Frost (как v2 + cache)
Код: arm/hybrid/fight.py.

### Защита
- Перед джобой: 64 билда CPU vs GPU. Не прошло → вся джоба на CPU.
- В каждом процессе: первые 8 боёв vs CPU. Не прошло → процесс на CPU.
- Ошибка пачки → старый eval_span.
- Допуск: относительная ошибка DPS ≤ 1e-4 (DPS_TOL).

### Сверка (DirectML, top-80 mixed, 5 целей)
| спек | билдов | max abs | max rel | CPU мс/бой | гибрид мс/бой |
|---|---|---|---|---|---|
| fire | 500 | 0.00026 | 2.3e-7 | 13.1 | 5.7 |
| frost | 2000 | — | 1.4e-6 | 19.2 | 5.4 |

(Смоук v2, 3000 чанков fire, 2 воркера: гибрид 387.9 с vs CPU 900.4 с, max rel 6.2e-8.)

## Priest Shadow / Discipline / Holy
Код: arm/hybrid/priest.py. Моменты sum(w), sum(w·t), sum(w·t²) на GPU;
пороги execute и Holy Fire amp — CPU float64.

| спек | билдов | max rel | CPU мс/бой | гибрид мс/бой |
|---|---|---|---|---|
| shadow | 500 | 1.4e-7 | 1.68 | 0.85 |
| discipline | 1000 | 1.5e-7 | 2.09 | 0.79 |
| holy | 1000 | 1.4e-7 | 1.11 | 0.71 |

inish_sextuple (shadow, 2 чанка): те же таланты/глифы/ESC/число боёв, rel ≤ 4.1e-8.

## Arcane Mage
mage/arcane жёстко на CPU (arm/hybrid/lock.py). GpuLocked. Скрипты Arcane не менялись.

## Запуск
`
cd C:\Users\eseid\sunken-sim
.venv-dml\Scripts\python.exe -m farm.hybrid.registry
.venv-dml\Scripts\python.exe tools\run_hybrid_parity.py --spec fire --n 2000 --finish 3
.venv-dml\Scripts\python.exe tools\run_hybrid_parity.py --hero priest --spec shadow --n 1000 --finish 3
.venv-dml\Scripts\python.exe tools\run_hybrid_smoke.py --count 3000 --compare
`
FARM_HYBRID_DEVICE: uto / cpu / dml.

## Тесты
`
python -m unittest farm.test_hybrid
.venv-dml\Scripts\python.exe -m unittest farm.test_hybrid
`
30 тестов OK в .venv-dml (2026-11-05).
