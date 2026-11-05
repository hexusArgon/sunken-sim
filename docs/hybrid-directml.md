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
| hybrid-compile | CPU-таймлайн (без кэша), GPU compile, CPU score | priest×3, paladin×3, shaman×3, warlock×3, rogue×2, hunter×3, druid×2, feral_druid×3 + ledger kind-heroes |
| gpu-timeline | batched next-event timeline + GPU kind-score | warrior×3, paladin×3 |
| cpu-only | local-hybrid (device + v1 stat-parity), бои = simulate модуля | — (реальных спеков нет; только неизвестный hero/spec) |

Дальше GPU-compile для остальных нужен split simulate → events → compile → score
в sunken_sim. Порт-очередь: `registry.PORT_ORDER` (feral_druid, …). Warrior+Warlock+Rogue+Hunter+Druid+FeralDruid done.

### Score depth (kind-GPU vs flat)
| Specs | Score on GPU |
|---|---|
| priest×3, paladin×3, shaman×3, warrior×3 | kind/weight moments (reference) |
| warlock×3, rogue×2, hunter×3, druid×2 | kind/weight moments (upgraded from flat sum) |
| mage fire/frost | kind-compile in timeline hybrid |
| mage arcane | locked CPU |
| feral_druid×3 (primal/guardian/savage) | kind/weight moments (PHYS/MAG/EXEC/FLAT) |
| berserker×3, death_knight×3, demon_hunter×3, dragon_sentinel×3, monk×3, necromancer×3, siren×3, tidewarrior×2, tinker×3, windmaster×3, witch_doctor×2 | ledger kind/weight moments (EXEC/FLAT) |

### Pending (next tasks)
1. **Timeline on GPU** — warrior×3 + paladin×3 done; roll out to shaman/mage fire-frost/others.
2. **ESC / stat-kernel on GPU** — matrix greedy between fights (all compile classes).


### Честно про таймлайн на GPU
Warrior + Paladin: batched next-event state machines in
`farm/hybrid/warrior_gpu_timeline.py` / `paladin_gpu_timeline.py` + shared
`farm/hybrid/timeline_gpu.py`. Clocks run in **float64 on CPU** (DirectML has no
reliable f64); kind-score stays on DirectML. Opt out: `FARM_HYBRID_GPU_TIMELINE=0`.
Mage fire/frost still CPU timeline + exact cache + GPU compile.
Everyone else: CPU timeline + GPU kind-score (hybrid-compile).

## Mage Fire / Frost
Код: `farm/hybrid/fight.py`.

## Priest Shadow / Discipline / Holy
Код: `farm/hybrid/priest.py`.

## Paladin Retribution / Protection / Holy
Код: `farm/hybrid/paladin.py` + `paladin_gpu_timeline.py` + `sunken_sim/paladin.py`.
Status: **gpu-timeline**. Fixed-capacity hammer slots (MAX_HAMMERS=24; 8 overflowed
with Divine Hammer 12s + Divine Toll mid-fight), orbit tables, CS/HoJ/auto priority
clocks. Opt out: `FARM_HYBRID_GPU_TIMELINE=0`.
Parity 2026-11-05: 16 builds × 3 specs = 48/48 GPU timeline+kind vs CPU simulate
(RX 6800 XT DirectML; abs/rel ≤ 1e-4).

## Shaman Restoration / Enhancement / Elemental
Код: `farm/hybrid/shaman.py` + `sunken_sim/shaman.py` event/score split.
GPU vs CPU rel ≤ 1e-6 (smoke 2026-11-05).

## Warrior Protection / Arms / Fury
Код: `farm/hybrid/warrior.py` + `warrior_gpu_timeline.py` + `timeline_gpu.py` +
`sunken_sim/warrior.py` event/score split.
Status: **gpu-timeline**. Batched priority clocks (shout>ww>bt>demo>attack),
Sulfuras pot_scale=0, exact equality for pick_priority (no 1e-7 epsilon).
Enrage (*1.10) в weight; fury enrage +10 crit — отдельные kind; auto → taken_auto; cleave flat.
Parity 2026-11-05: 32 builds × 3 specs = 96/96 GPU timeline+kind vs CPU simulate.

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


## Feral Druid Primal / Guardian / Savage
Код: `farm/hybrid/feral_druid.py` + `sunken_sim/feral_druid.py` kind-score timeline.
Events: (when, name, weight, kind); kinds PHYS / MAG / EXEC / FLAT.
PHYS: phys/crit/taken baked, ×execute; MAG: base+slope×mastery on GPU; EXEC/FLAT as usual.
DIAMOND (I00D): timelines() picks best bound key like simulate().
Parity smoke 2026-11-05: GPU vs CPU abs/rel ≤ 1e-4 (RX 6800 XT DirectML).

## Ledger kind-score: Berserker, Death Knight, Demon Hunter, Dragon Sentinel, Monk, Necromancer, Siren, Tidewarrior, Tinker, Windmaster, Witch Doctor
Код: `sunken_sim/ledger.py` + `farm/hybrid/kindscore.py` (общий `KindFights`), тонкие
`farm/hybrid/<hero>.py`. В `simulate()` модуля `sources` — это `Ledger` (dict + список
событий (when, name, weight, kind)); `Report.events` уходит в GPU.
Kinds: **EXEC** — точки урона, где множитель execute(when) уже был в формуле
(weight = dealt / execute, execute пересчитывается при pack); **FLAT** — всё остальное
как дельта записи (`sources[x] += ...`, auto_pct-масштаб, probe/restore Axe Mastery,
Outbreak ×times, cleave Tidewarrior). Без PHYS/MAG-разложения: crit/taken/мастери
уже внутри weight, на GPU только one-hot(kind) × weight bmm (float32) + CPU sum / FIGHT.
Выбор политики (POLICIES) остаётся в `simulate()` на CPU.
CPU dps старого и нового `simulate` совпадает бит-в-бит (tools/_ledger_parity.py, 31 спек).
Parity smoke 2026-11-05, DirectML (RX 6800 XT), n=300 + finish 2, tol 1e-4:
berserker 1.3e-5/1.0e-5/1.2e-5, death_knight ≤2.8e-6, demon_hunter ≤4.2e-6,
dragon_sentinel ≤8.4e-7, monk ≤1.0e-6, necromancer ≤1.04e-5, siren ≤2.5e-6,
tidewarrior ≤1.6e-6, tinker ≤3.2e-6, windmaster ≤5.0e-6, witch_doctor ≤6.2e-6;
finish — те же talents/glyphs/points. Скорость ≈ CPU (таймлайн остаётся на CPU;
GPU даёт только score). Все спеки: `tools/_kind_parity_all.py`.

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
