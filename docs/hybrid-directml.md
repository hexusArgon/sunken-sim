# Гибрид GPU+CPU (DirectML)

## Что это
Опциональный воркер local-hybrid. Видеокарта AMD Radeon RX 6800 XT, бэкенд —
**DirectML** (torch-directml), не CUDA. Обычный local-esc не менялся.

Все классы/спеки проходят через `farm/hybrid/registry.py` (матрица статусов).
Общий батч-поиск талантов/глифов/ESC — `farm/hybrid/engine.py`.

## Флаги по умолчанию (с 2026-11-06)
| флаг | по умолчанию | выключить |
|---|---|---|
| `FARM_HYBRID_CROSS_BUILD` | вкл (мультибилд) | `0` |
| `FARM_HYBRID_ESC_ALGEBRA` | `auto` (Router batched/algebra) | `0` |
| `FARM_HYBRID_ESC_ALGEBRA_DEVICE` | `cpu` | — |
| `FARM_HYBRID_ARCANE_GPU` | вкл | `0` |

Живой farm-замер (`tools/_bench_live_worker.py`, witch_doctor, 24 задачи): off 210.6 s, cross+alg 178.8 s (1.18×), лидерборды идентичны.

## Статусы (v3+)
| статус | смысл | кто |
|---|---|---|
| locked | только CPU, torch не импортируется | mage/arcane |
| hybrid-timeline | (retired for mage) | — |
| hybrid-compile | CPU-таймлайн (без кэша), GPU compile, CPU score | priest×3, shaman×3, warlock×3, rogue×2, hunter×3, druid×2, feral_druid×3 + ledger kind-heroes |
| gpu-timeline | batched next-event timeline + GPU kind-score | warrior/pala/shaman/priest x3, mage fire/frost, rogue x2, druid x2, hunter/warlock/feral/berserker/DK/DH/DS/monk/necro/siren/tide/tinker/wind/wd |
| cpu-only | local-hybrid (device + v1 stat-parity), бои = simulate модуля | остальные |

Дальше GPU-compile для остальных нужен split simulate → events → compile → score
в sunken_sim. Порт-очередь: `registry.PORT_ORDER` (feral_druid, …). Warrior+Warlock+Rogue+Hunter+Druid+FeralDruid done.

### Score depth (kind-GPU vs flat)
| Specs | Score on GPU |
|---|---|
| priest×3, paladin×3, shaman×3, warrior×3 | kind/weight moments (reference) |
| warlock×3, rogue×2, hunter×3, druid×2 | kind/weight moments (upgraded from flat sum) |
| mage fire/frost | gpu-timeline (true TL + kind-compile) |
| mage arcane | locked CPU |
| feral_druid×3 (primal/guardian/savage) | kind/weight moments (PHYS/MAG/EXEC/FLAT) |
| remaining cpu-only | not yet |

### Pending (next tasks)
1. **GPU fight timelines** — done for every unlocked spec (58). Only **mage/arcane**
   stays locked. Kind-heroes (berserker…witch_doctor) included.
2. **ESC / stat-kernel deepen** — `farm/hybrid/stat_kernel.py` on
   `BatchFights.greedy_points`: результат = полный `esc.greedy_points`.
   Structural skips (`healing_power` always; `pet_damage` except pet heroes) не
   играются, но участвуют в выборе со score = текущий DPS (те же tie-break и
   «потратить без прироста»). Skip снимается, если в файлах героя
   (`sunken_sim/<module>.py`, `farm/hybrid/<hero>*.py`, общие) есть чтение
   `stats["attr"]` / `.get("attr")` / `V("attr")`; неизвестный герой → без skip.
   Zero-delta skip удалён 2026-11-05: неточен (demon_hunter/havoc 590.55 vs
   596.84). Регрессия: `farm/hybrid/test_stat_kernel_greedy.py`, свип
   `tools/_esc_greedy_parity.py`.
   Exact event-reuse rescoring still deferred: flat/cleave bake crit/potency into
   raw — needs per-class event algebra next.
3. **ESC guarded event algebra (`FARM_HYBRID_ESC_ALGEBRA`, default `auto`)** —
   `farm/hybrid/esc_algebra.py`, Ledger kind-heroes. Один CPU-трейс текущего
   билда: float-ключи `stats_of`, которые меняют trial'ы, заменяются `Sym`;
   арифметика пишется в tape, каждое ветвление по ним (`<`, `==`, `bool`,
   `min/max`, `int/floor`, `float()`) — guard. Ключи, от которых зависит время
   событий (haste/AS), исключаются (blame → retrace), их attr'ы играются.
   Trial'ы считаются векторно (numpy float64, по уровням tape): все guards
   держатся → тот же путь сима → события трейса с новыми весами (те же IEEE-оп).
   Скоринг rescored-строк: `score_engine` = тот же `pack` + `compile_sums`
   (DirectML), CPU-режим `score_cpu` = точная копия `score_events`.
   Трейс живёт через шаги, пока выбор был rescored; иначе retrace.
   Спекуляция: внутри guard-региона greedy проходит шаги вперёд, все
   недоказуемые trial'ы раунда — один `dps_many`; первый шаг, где выиграл
   сыгранный attr, обрывает раунд (лишние бои выбрасываются). `auto`: онлайн-фит
   t = c0 + c1·builds, спекуляция только при c0 > c1·(боёв на шаг). Выбор пути
   меняет только число боёв, не score.
   Fallback: guard fail / нечисловой ключ / чтение `*_points` вне `stats_of` /
   исключение трейса → обычный `dps_many`. В engine любая ошибка → batched.
   Guards и tape — только CPU float64 (DirectML без f64); на GPU только
   kind-score. Тесты `farm/hybrid/test_esc_algebra.py`, бенч
   `tools/_bench_esc_algebra.py --mode cpu|engine`.
   **Выбор стратегии по замеру (default `FARM_HYBRID_ESC_ALGEBRA=auto`)** —
   `esc_device.Router` с плечами batched/algebra на hero/spec: warmup 2+2,
   медиана окна 8, переключение при выигрыше ≥10%, re-probe проигравшего с
   удвоением интервала. Оба плеча точные (очки = full greedy), меняется только
   время: на дешёвых спеках (DH, windmaster/combat, tidewarrior) алгебра
   медленнее batched, router оставляет batched.
   **Device-маршрут алгебры (opt-in `FARM_HYBRID_ESC_ALGEBRA_DEVICE=cpu|gpu|auto`,
   default `cpu`)** — `farm/hybrid/esc_device.py`. `gpu`: guards-замыкание tape
   остаётся CPU float64 (numpy); weight-замыкание (узлы весов событий) считается
   на torch-устройстве в float32: узлы переложены так, что каждая группа уровня —
   непрерывный слайс (`index_select` → op → slice copy; без CPU-fallback на
   DirectML, проверка `tools/_probe_esc_device_dml.py`), затем exec-factor·вес и
   сумма блоками по 64 событий f32 на устройстве, f64 по блокам на хосте.
   Значения приблизительные: если соперник в пределах `TIE_REL=1e-4` от
   победителя шага, приблизительные значения (и возвращаемый best) пересчитываются
   точно (CPU f64 + `score_engine`, батч ≥2 — DirectML bmm при батче 1 даёт
   другой f32-результат). Каждый пересчёт и первый вызов на трейс (кросс-чек) —
   замер ошибки; > `ERR_LIMIT=2.5e-5` → device-маршрут выключается (замер на
   RX 6800 XT: max 3e-6). Буферы (индексы, базовые значения, gather/exec событий)
   — LRU `esc_device.CACHE` (≤8 записей, ≤256 MiB), ключ = (token трейса, device,
   dtype, SCHEMA): новый билд → новый трейс → новый token, чужие веса не
   переиспользуются; `esc_device.reset()`. Маршрут `auto` мерит полное время
   (упаковка, upload, ядра, блокирующий `.cpu()`, хост-редукция; для gpu ещё и
   точные пересчёты). Честно: guards-замыкание покрывает ~90–99% групп tape, так
   что CPU f64 работа почти не уменьшается, а DirectML добавляет запуск ядер;
   замер per-call: gpu в 1.04–28× медленнее cpu (сумма 4.3×), буферы экономят
   ~40% gpu-вызова. Поэтому default `cpu`, `auto` выбирает cpu. Тесты
   `farm/hybrid/test_esc_device.py` (`FARM_HYBRID_TEST_DML=1` — и на DirectML),
   бенчи `tools/_bench_esc_device_micro.py`, `_bench_esc_device.py`,
   `_bench_esc_strategy.py`.


### Честно про таймлайн на GPU
Warrior + Paladin: batched next-event state machines in
`farm/hybrid/warrior_gpu_timeline.py` / `paladin_gpu_timeline.py` + shared
`farm/hybrid/timeline_gpu.py`. Clocks run in **float64 on CPU** (DirectML has no
reliable f64); kind-score stays on DirectML. Opt out: `FARM_HYBRID_GPU_TIMELINE=0`.
Mage fire/frost: true GPU timeline (see below).
Everyone else: CPU timeline + GPU kind-score (hybrid-compile).

## Mage Fire / Frost
Код: `farm/hybrid/fight.py` + `mage_gpu_timeline.py` + `sunken_sim/mage.py`.
Status: **gpu-timeline** (pending+choose, MAX_BOMB_CHAINS=4, MAX_HYDRA=256 + expired reclaim).
Staff CD-reset only stacks on Overpowered/pads (CPU gate). Opt out: `FARM_HYBRID_GPU_TIMELINE=0`.
Parity 2026-11-05: 8×fire + 8×frost = 16/16 vs CPU simulate (RX 6800 XT DirectML).

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
Код: `farm/hybrid/shaman.py` + `shaman_gpu_timeline.py` + `sunken_sim/shaman.py`.
Status: **gpu-timeline** for all specs (pending+choose + MAX_SPIRITS=32).
Opt out: `FARM_HYBRID_GPU_TIMELINE=0`.


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
File: farm/hybrid/rogue.py + farm/hybrid/rogue_gpu_timeline.py.

Status: **gpu-timeline** (pending+choose; Vendetta release, Vanish pressure, Subterfuge mana rewind).
Parity 2026-11-05: 16 builds × 2 specs = 32/32 GPU timeline+kind vs CPU simulate (abs≤1e-3 or rel≤1e-4).


## Hunter Marksmanship / Beast Mastery / Survival
GPU timeline: `farm/hybrid/hunter_gpu_timeline.py` (pending+choose, pets, dither). Parity `tools/_parity_hunter_gpu_tl.py` 16×3 ≤1e-4.
Код: `farm/hybrid/hunter.py` + `sunken_sim/hunter.py` kind-score timeline.
Events: (when, name, weight, kind); kinds PHYS / EXEC / MAG / FLAT.
Execute baked at pack; GPU kind-weight moments. CPU score_events = reference.
Parity smoke 2026-11-05: GPU vs CPU abs/rel ≤ 1e-4.

## Druid Restoration / Balance
Код: `farm/hybrid/druid.py` + `druid_gpu_timeline.py` + `sunken_sim/druid.py`.
Status: **gpu-timeline** (pending heap -> slots ordered (time, push order); wisps/starfalls
as expiring slot tables; f64 clocks on CPU, kind-score on DirectML). Rows = build x bound key.
Opt out: `FARM_HYBRID_GPU_TIMELINE=0`.
Parity 2026-11-05: 64 builds x 2 specs = 128/128 (abs<=1e-3 or rel<=1e-4); events
structurally identical to CPU, max diff ~2e-15 (wisp sum order).
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


## Demon Hunter Havoc / Vengeance / Devourer
Status: **gpu-timeline**. Python-float clocks + per-row pending heap (Eye Beam 0.03 ticks /
Collapsing Star delay); cast_time = CAST_POINT+CAST_BACKSWING (CPU pre-sum). Sulfuras → CPU.
Code: `farm/hybrid/demon_hunter_gpu_timeline.py` + wire `farm/hybrid/demon_hunter.py`.
Parity 2026-11-05: 8 builds × 3 specs = 24/24 GPU timeline+kind vs CPU simulate (abs≤1e-3 or rel≤1e-4).


## Dragon Sentinel Ruby / Obsidian / Emerald
Status: **gpu-timeline**. Best-of POLICIES (Lifebinder × Dragon Form) with CPU-exact
event heap; cast_time pre-sum. Sulfuras → CPU.
Code: `farm/hybrid/dragon_sentinel_gpu_timeline.py` + wire `farm/hybrid/dragon_sentinel.py`.
Parity 2026-11-05: 8 builds × 3 specs = 24/24 GPU timeline+kind vs CPU simulate (abs≤1e-3 or rel≤1e-4).


## Monk Windwalker / Brewmaster / Mistweaver
Status: **gpu-timeline**. Best-of POLICIES with CPU-exact fight loop; cast_time pre-sum.
Sulfuras → CPU. Code: `farm/hybrid/monk_gpu_timeline.py` + wire `farm/hybrid/monk.py`.
Parity 2026-11-05: 8 builds × 3 specs = 24/24 GPU timeline+kind vs CPU simulate (abs≤1e-3 or rel≤1e-4).


## Necromancer Bone / Blood / Essence
Status: **gpu-timeline**. Best-of POLICIES (Transfusion × Raise Dead); cast_time pre-sum.
Sulfuras → CPU. Code: `farm/hybrid/necromancer_gpu_timeline.py` + wire `farm/hybrid/necromancer.py`.
Parity 2026-11-05: 8 builds × 3 specs = 24/24 GPU timeline+kind vs CPU simulate (abs≤1e-3 or rel≤1e-4).


## Siren Sharpshooter / Watershaper / Seagrace
Status: **gpu-timeline**. Best-of POLICIES (Liquid Arrows × Song); cast_time pre-sum.
Sulfuras → CPU. Code: `farm/hybrid/siren_gpu_timeline.py` + wire `farm/hybrid/siren.py`.
Parity 2026-11-05: 8 builds × 3 specs = 24/24 (abs≤1e-3 or rel≤1e-4).

## Tidewarrior Myrmidon / Guardian
Status: **gpu-timeline**. Best-of POLICIES (Serpentine Fury × Call of the Sea recall); cast_time pre-sum.
Sulfuras → CPU. Code: `farm/hybrid/tidewarrior_gpu_timeline.py` + wire `farm/hybrid/tidewarrior.py`.
Parity 2026-11-05: 8 builds × 2 specs = 16/16.

## Tinker Engineering / Demolitions / Nanotech
Status: **gpu-timeline**. Best-of POLICIES (Reinforce × Exosuit); cast_time pre-sum.
Sulfuras → CPU. Code: `farm/hybrid/tinker_gpu_timeline.py` + wire `farm/hybrid/tinker.py`.
Parity 2026-11-05: 8 builds × 3 specs = 24/24.

## Windmaster Upheaval / Storm / Combat
Status: **gpu-timeline**. Single-policy simulate (no POLICIES); cast_time pre-sum.
Sulfuras → CPU. Code: `farm/hybrid/windmaster_gpu_timeline.py` + wire `farm/hybrid/windmaster.py`.
Parity 2026-11-05: 8 builds × 3 specs = 24/24.

## Witch Doctor Voodoo / Poison
Status: **gpu-timeline**. Best-of POLICIES (Soul Possession × spider/toad first); cast_time pre-sum.
Sulfuras → CPU. Code: `farm/hybrid/witch_doctor_gpu_timeline.py` + wire `farm/hybrid/witch_doctor.py`.
Parity 2026-11-05: 8 builds × 2 specs = 16/16.

## Arcane Mage
mage/arcane по умолчанию идёт через GPU-таймлайн (`farm/hybrid/lock.py`).

GPU-таймлайн Arcane совпадает с CPU-симом: Evocation, тики маны, шанс сброса, стаки Arcane Blast. Проверка: `tools/_parity_mage_arcane.py` (N=8/32, режим STARVE и Evocation), тесты `farm/hybrid/test_mage_arcane.py`.
Вернуть на CPU: `FARM_HYBRID_ARCANE_GPU=0` (тогда GpuLocked).

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

## Priest GPU timeline (shadow / discipline / holy)

farm/hybrid/priest_gpu_timeline.py — batched f64 clocks on CPU, kind-score on DirectML.
Mirrors sunken_sim.shadow._fight_events (CAST_POINT finish queue, SWP Cosmic EV, Radiance/Renew/Image).
Gate: FARM_HYBRID_GPU_TIMELINE. Parity: 	ools/_parity_priest_gpu_tl.py (16 builds × 3 specs, ≤1e-4).
Batch fix: on_swp expiry zeroing must be masked to rows whose tick fires (otherwise sibling rows clear EV weights early).


## ESC-алгебра: flat-герои (2026-11-06)

К 11 Ledger-героям добавлены warrior, hunter, paladin, rogue, warlock (`FLAT_SOURCE_HEROES`). Для них события берутся из `report.sources` как KIND_FLAT, а мемо `_TIMELINE` на время трассировки отключается, чтобы ключ не читал ESC-поля. Parity `tools/_esc_algebra_parity.py`: 28/28 точно. Haste, attack speed и мана меняют таймлайн, поэтому для них бои остаются.


Hunter временно исключён из `FLAT_SOURCE_HEROES`: на beast_mastery и marksmanship алгебра обнуляла `pet_damage` (9 очков) и клала их в `healing_power`/`crit`, из-за чего DPS лидера падал примерно на 1.9% и 3.5% против полного перебора. Survival совпадал. Включать hunter обратно только после того, как `pet_damage` попадёт в символьное выражение.


## ESC-алгебра: used-leaves, auto в cross-build, теги (2026-11-06)

Пересчёт без боя разрешён только если каждый изменившийся стат реально входит в веса событий (`weight_keys`). Обёрнутый, но не использованный лист (например hunter `pet_damage`, если его запиннили в конкретное число) идёт в обычный бой. Hunter снова в `FLAT_SOURCE_HEROES`.

К алгебре через `sheet`/`character` как `stats_of` подключены mage, shaman, druid, feral_druid и priest (модуль `shadow`). У mage/priest трассировка идёт с `use_history=False` и `simulate(..., spec=spec)`.

`FARM_HYBRID_ESC_ALGEBRA=auto` теперь сравнивает batched и algebra и в `finish_many` (кросс-билд), а не только в одиночном `greedy_points`. Спеки вроде tidewarrior, где алгебра была медленнее, после прогрева уходят на обычный перебор.

В `AlgebraStats.attr_kind` каждый ESC-атрибут помечается как `rescore` (пересчёт без боя), `fight` (таймлайн / нет в выражении), `mixed` или `skip`. `reused_rounds` считает шаги, которые переиспользовали предыдущий след событий.

DirectML для самой алгебры по-прежнему `FARM_HYBRID_ESC_ALGEBRA_DEVICE=cpu` по умолчанию; GPU-маршрут включается только если замер показывает выигрыш и ошибка f32 ниже порога.

Замер _bench_esc_device.py --heroes warrior,hunter,shaman --n 1 --repeat 2 (2026-11-06): сумма wall ref 67.07 с, cpu-алгебра 46.48 с (1.44×), gpu-алгебра 55.54 с (1.21×), auto 47.30 с (1.42×) и осталась на cpu. DirectML-проба (_probe_esc_device_dml.py) без fallback. GPU-маршрут алгебры не включаем по умолчанию.

mage и priest получили stats_of (sheet / character), но в FLAT_SOURCE_HEROES не входят: на каталожном билде алгебра взяла damage/mana вместо crit/potency.
