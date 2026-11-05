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
1. **Timeline on GPU** — warrior×3 + paladin×3 done (parity green). Remaining CPU timeline:
   mage/priest/rogue GPU TL done; remaining:
   warlock×3, hunter×3, druid×2, feral_druid×3,
   kind-heroes: ALL done (berserker…witch_doctor). Branchy classes that remain
   hybrid-compile (resto shaman etc.) stay CPU timeline + GPU kind-score.
2. **ESC / stat-kernel on GPU** — `farm/hybrid/stat_kernel.py` wired into `BatchFights.greedy_points`:
   batched dps_many trials + safe zero-delta attr skip (attrs that tied baseline after a
   real improving step are dropped). Exact event-reuse rescoring is **not** used yet:
   flat/cleave raws bake crit/potency at emit (warrior). Closed-form kernel needs
   per-class event algebra; next after more GPU timelines.

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

## Priest GPU timeline (shadow / discipline / holy)

farm/hybrid/priest_gpu_timeline.py — batched f64 clocks on CPU, kind-score on DirectML.
Mirrors sunken_sim.shadow._fight_events (CAST_POINT finish queue, SWP Cosmic EV, Radiance/Renew/Image).
Gate: FARM_HYBRID_GPU_TIMELINE. Parity: 	ools/_parity_priest_gpu_tl.py (16 builds × 3 specs, ≤1e-4).
Batch fix: on_swp expiry zeroing must be masked to rows whose tick fires (otherwise sibling rows clear EV weights early).
