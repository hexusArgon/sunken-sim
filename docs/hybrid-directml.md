# Гибрид GPU+CPU (DirectML)

## Что это
Опциональный воркер local-hybrid. Видеокарта AMD Radeon RX 6800 XT, бэкенд —
**DirectML** (torch-directml), не CUDA. Обычный local-esc не менялся.

Все классы/спеки проходят через `farm/hybrid/registry.py` (матрица статусов).
Общий батч-поиск талантов/глифов/ESC — `farm/hybrid/engine.py`.

## Статусы (v3+)
| статус | смысл | кто |
|---|---|---|
| locked | только CPU, torch не импортируется | mage/arcane |
| hybrid-timeline | CPU-таймлайн + точный timeline-cache, GPU compile, CPU score | mage/fire, mage/frost |
| hybrid-compile | CPU-таймлайн (кэш модуля), GPU compile, CPU score | priest×3, paladin×3, shaman×3, warrior×3, warlock×3, rogue×2, hunter×3, druid×2 |
| cpu-only | local-hybrid (device + v1 stat-parity), бои = simulate модуля | остальные |

Дальше GPU-compile для остальных нужен split simulate → events → compile → score
в sunken_sim. Порт-очередь: `registry.PORT_ORDER` (feral_druid, …). Warrior+Warlock+Rogue+Hunter+Druid done.

### Score depth (kind-GPU vs flat)
| Specs | Score on GPU |
|---|---|
| priest×3, paladin×3, shaman×3, warrior×3 | kind/weight moments (reference) |
| warlock×3, rogue×2, hunter×3, druid×2 | kind/weight moments (upgraded from flat sum) |
| mage fire/frost | kind-compile in timeline hybrid |
| mage arcane | locked CPU |
| remaining cpu-only (feral_druid, …) | not yet |

### Pending (next tasks — not this commit)
1. **Timeline on GPU** — event queue / next-cast state machine on DirectML (all classes).
2. **ESC / stat-kernel on GPU** — matrix greedy between fights (all compile classes).


### Честно про таймлайн на GPU
Состояние боя (кто/когда кастует) по-прежнему на CPU. hybrid-timeline = точный
кэш таймлайна + GPU на взвешенных суммах. Полный перенос state machine на GPU —
отдельный этап (ещё не сделан ни для одного класса).

## Mage Fire / Frost
Код: `farm/hybrid/fight.py`.

## Priest Shadow / Discipline / Holy
Код: `farm/hybrid/priest.py`.

## Paladin Retribution / Protection / Holy
Код: `farm/hybrid/paladin.py` + `sunken_sim/paladin.py` event/score split.
GPU vs CPU rel ≤ 1e-7 (smoke 2026-11-05).

## Shaman Restoration / Enhancement / Elemental
Код: `farm/hybrid/shaman.py` + `sunken_sim/shaman.py` event/score split.
GPU vs CPU rel ≤ 1e-6 (smoke 2026-11-05).

## Warrior Protection / Arms / Fury
Код: `farm/hybrid/warrior.py` + `sunken_sim/warrior.py` event/score split.
Enrage (*1.10) в weight; fury enrage +10 crit — отдельные kind; auto → taken_auto; cleave flat.

## Warlock Demonology / Destruction / Affliction
Код: `farm/hybrid/warlock.py` + `sunken_sim/warlock.py` kind-score timeline.
Events: (when, name, weight, kind); kinds HERO_MAG / HERO_PHYS / HERO_EXEC / FLAT.
Execute baked at pack; GPU moments sum(w)/sum(w*thp)/sum(w*M). CPU score_events = reference.
Parity smoke 2026-11-05: GPU vs CPU abs/rel ≤ 1e-4 (RX 6800 XT DirectML).

## Rogue Subtlety / Combat
Код: `farm/hybrid/rogue.py` + `sunken_sim/rogue.py` kind-score timeline.
Events: (when, name, weight, kind); kinds PHYS / EXEC / MAG / FLAT.
Execute baked at pack; GPU kind-weight moments. CPU score_events = reference.
Parity smoke 2026-11-05: GPU vs CPU abs/rel ≤ 1e-4.

## Hunter Marksmanship / Beast Mastery / Survival
Код: `farm/hybrid/hunter.py` + `sunken_sim/hunter.py` kind-score timeline.
Events: (when, name, weight, kind); kinds PHYS / EXEC / MAG / FLAT.
Execute baked at pack; GPU kind-weight moments. CPU score_events = reference.
Parity smoke 2026-11-05: GPU vs CPU abs/rel ≤ 1e-4.

## Druid Restoration / Balance
Код: `farm/hybrid/druid.py` + `sunken_sim/druid.py` kind-score timeline.
DIAMOND (I00D): timelines() перебирает buttons(spec) bound keys, берёт best total events
(как simulate()). Без DIAMOND — bound_key=None.
Events: (when, name, weight, kind); GPU kind-weight moments. CPU score_events = reference.
Parity smoke 2026-11-05: GPU vs CPU abs/rel ≤ 1e-4 (incl. DIAMOND).

## Arcane Mage
mage/arcane жёстко на CPU (`farm/hybrid/lock.py`). GpuLocked.

## I0E4 Colossal Sledgehammer (2.5.2b)
`own_stun_duration_pct` (+25%) и `stun_hit_damage` (100) парсятся в library.
Paladin Hammer of Justice добавляет Stun-хит на 100. +25% длительности стана
пока не влияет на DPS (нет окон «враг в стане» в симах).

## Запуск
```
cd C:\Users\eseid\sunken-sim
.venv-dml\Scripts\python.exe -m farm.hybrid.registry
.venv-dml\Scripts\python.exe tools\run_hybrid_parity.py --spec fire --n 2000 --finish 3
.venv-dml\Scripts\python.exe tools\run_hybrid_parity.py --hero priest --spec shadow --n 1000 --finish 3
```
FARM_HYBRID_DEVICE: auto / cpu / dml.

## Тесты
```
python -m unittest farm.test_hybrid
.venv-dml\Scripts\python.exe -m unittest farm.test_hybrid
```
