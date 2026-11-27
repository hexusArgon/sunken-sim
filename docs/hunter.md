# Hunter

Общие правила боя, предметов и кулдаунов — в `docs/guide.md`. Здесь Hunter карты Sunken City v2.5.2a. Формулы сняты с триггеров `war3map.j` и объектов `w3a/w3u/w3t` (свой парсер `dump_obj.py`, `library._parse_objects` для w3a сломан).

Сим — точное float64 OpenCL-ядро `farm/hybrid/hunter_cl.py` (Python-модель `sunken_sim/hunter.py` удалена 2026-11-27; до удаления 2760 боёв и 18 доводок заморожены бит-в-бит в `farm/hybrid/fixtures/hunter.json`, проверка — `python3.11 -m unittest farm.hybrid.test_fixtures`). Ожидаемый урон за 30 секунд, 5 целей, броня 15. Однослотовый прогон: `python3.11 tools/one_slot_gpu.py hunter` (пишет `extract/hunter-one-slot.json`). Ключ пула классовых вещей — `"Hunter"`.

## Лист

Hunter H001 (дальний бой, 500). Ловкость 28 + 2,8, сила 10 + 1, интеллект 12 + 1,2. На 6 уровне 42 ловкости, 15 силы, 18 интеллекта. Основной атрибут — ловкость. Белый удар 29 + 1d1 = 30, плюс `0,75 × ловкость` (DCS). Взмах `ua1c` 1,60 с, Marksmanship ×0,90 (Aspect of the Eagle). Мана `120 + 7 × интеллект`, здоровье 230 + сила.

Скорость атаки: бонус вещей плюс 0,4% за ловкость (до +100%), потолок −80% / +400%. Временные: Lock and Load +40% на 4 с, Prowess +20% на 3 с, Helm of Beast Taming +25% под Bestial Wrath.

## Панель

Спек — уровень A098 на `udg_Glyphs_Unit[1]`: 1 — Marksmanship (питомец Huffer), 2 — Beast Mastery (Spike), 3 — Survival (Grylls).

| Способность | Код | База, ранг 1 |
|---|---|---|
| Call Pet | A0ME / A00N / A0MF | 30 с, 30 маны; каст в t = 0 |
| Bestial Wrath | A03X | 15 с, 20 маны, 8 с (Inner Fire A043 на герое и питомце) |
| Serpent Sting | A0E3 | 8 с, 15 маны, дебафф B01C 10 с |
| Multi-Shot | A01V | 7 с, 10 маны, 3 цели (5 с Volley) |
| Steel Trap | A06B | 7 с, 20 маны, срабатывание через 0,5 с, Acid Bomb A06M −3 брони 5 с |
| Aspect of the Eagle | A0HC | пассив |
| Split Shot | пассив Multi-Shot | следующая настоящая атака выпускает вторую стрелу |

Порядок: Call Pet → Bestial Wrath → Serpent Sting → Multi-Shot → Steel Trap, потом автоатака (касты раньше атаки в цикле GCD). Каст общий: эффект через 0,15 с, ещё 0,30 с герой не атакует.

## Урон

DCS = `30 + 0,75 × AGI + урон вещей`; под Bestial Wrath DCS ×`(1 + 0,20 + 0,05 × ранг)` = ×1,25 (×1,40 с Wild Power). Этот DCS входит во все формулы способностей и в базу питомца.

| Источник | Формула | Тип |
|---|---|---|
| Автоатака | DCS; под Bestial Wrath белая часть ×(1 + Inner Fire 0,33, +0,25 с Wild Power) | Physical атака, крит героя |
| Serpent Sting | `85 × ранг + 0,85 × DCS + 0,40 × AGI` | Physical |
| Тики Sting | глобальный таймер 1,0 с (с Poisoned Arrows `1/(1+0,05×Potency)`), по каждой цели с B01C: `5 × ранг + 0,10 × DCS` | Physical от героя; в BM — от дамми ATTACK_NORMAL (считается как урон питомца) |
| Multi-Shot | по стреле `10 + 60 × ранг + 0,70 × DCS + 0,30 × AGI`; ×1,10 Volley, ×1,10 Mongoose, ×1,25 Elven Recurve Bow | Physical; с Steel Arrowheads / Steel Quiver 30%×удача — Pierce-атака с критом |
| Survival: второй залп | через 0,5 с, ×0,50 | как Multi-Shot |
| Split Shot | `(0,45 + 0,05 × ранг) × DCS` = 0,50 DCS, шанс взвода 30% (×1,5 на крите) × удача | Pierce-атака |
| Steel Trap | `40 + 1,20 × DCS + 0,50 × AGI`, одна цель | Physical |
| Marksmanship | крит настоящей атаки: `40 + 3 × Mastery` | без типа |
| Maul (Grylls) | 20%×удача на атаку Grylls: `15 + 1,50 × DCS` | Physical от героя |
| Howl of the Packleader | заряд (до 3) за каждый каст BW/Sting/Multi/Trap: `20 + 0,25 × AGI + 0,50 × Mastery` за заряд, тратится на атаке питомца | BM — в атаку питомца, иначе Physical от героя |

Броня цели: 15 − пробивание вещей (только урон героя) − 4 за B01C (весь урон игрока, ранг Sting ≤ 2) − 3 за Acid Bomb. Aspect of the Eagle: +min(0,13, дистанция/50/100) ко всему урону игрока Hunter; на дистанции 500 — +10%, проверки на выученность нет.

Крит героя: шанс вещей + 10 (Trueshot) + 20 (Quill Frenzy), множитель `2 + рейтинг` (+ `0,25 + 0,15 × шанс/100` с Unmatched Percision). Windrunner's Quiver: любой каст взводит флаг, следующая атака героя — гарантированный крит ×(1 + шанс/100).

## Питомцы

База `Pet_DamageBase + R2I(Scaling × DCS героя) + 1d1`, отдельный взмах, тип атаки свой. Pet Damage % (`+N% Pet Damage` с вещей) и Aspect +10% умножают весь урон питомца. Крит питомцев — блок summons: 0% базы, +25 Beastfury I0OH, +7 Mark of the Wild I06B, +20 Spike; множитель 2,0 (+0,2 I05W, +0,3 Spike, + Unmatched). Trueshot на питомцев не переносится.

| Питомец | Спек | База / скейл | Взмах | Особое |
|---|---|---|---|---|
| Huffer | MM | 4 / 0,30 | 1,45 | Quill Spray: ещё до 2 шипов по другим целям; каждые 15 попаданий — Quill Frenzy герою (+20% крита, 5 с). Dire Beasts: Frenzy +40% AS 12 с из 20 |
| Spike | BM | 9 / 0,50 | 1,50 | 20% крита, ×2,3. Dire Beasts: Shred 20% (×2 на крите) × удача — `50 + 0,50 × DCS` |
| Grylls | Survival | 17 / 0,90 | 1,70 | Maul (см. выше). Dire Beasts: Roar +20% урона постоянно |

Bestial Wrath на питомце: Inner Fire ×(1 + 0,33), вне BM — половина. Beast Mastery: питомцу +10% + 0,8% за Mastery скорости атаки, тики Sting от дамми. Survival: каждый тик по цели с B01C с шансом `5 + 0,2 × Mastery`% (без удачи) снимает 1 с со всех кулдаунов Agi.

## Таланты

| Талант | Код | Модель |
|---|---|---|
| Talon Strikes | I03P | взмах питомцев ×0,90; каждая атака питомца снимает 2% (текущий — 6%) оставшегося кулдауна способностей |
| Unleash the Beasts | I0K8 | Call Pet зовёт ещё двух питомцев на `6 + 0,1 × INT` = 7,8 с |
| Traplayer | I092 | 25%×удача на стрелу Multi-Shot (12,5% во втором залпе) ставит Steel Trap |
| Hydra Shots | I02X | Potency `+3 + 0,04 × DCS` |
| Lock and Load | I0KD | крит героя: 35%×удача → +40% скорости атаки 4 с |
| Howl of the Packleader | I0T3 | заряды Howl (см. «Урон») |
| Trueshot Aura | I0K9 | +10% крита герою |
| Wild Power | I0KB | BW: Inner Fire +25%, DCS ×1,40 вместо ×1,25, −3 с кулдауна |
| Volley | I0KC | Multi-Shot ×1,10 и 5 целей |
| Windrunner's Quiver | I0K6 | после каста следующая атака — гарантированный крит ×(1 + шанс) |
| Killer Instinct | I03M | Sting и Multi-Shot под BW: кулдаун −1,5 с |
| Steel Arrowheads | I03H | 30%×удача стрел Multi-Shot — Pierce-атаки |
| Flanking Strike | I02D | +15% Attack_Increase атакам героя и текущего питомца по общей цели (в симе цель 0) |
| Dire Beasts | I0KA | способности питомцев (см. таблицу) |
| Mongoose Bite | I0O3 | Multi-Shot ×1,10 (не тяжёлые цели), атаки героя +10% |
| Scent of Blood | I0K7 | урон питомцев +28% по целям ниже 40% HP |
| Unmatched Percision | I0T4 | рейтинг крита `+0,25 + 0,15 × шанс/100` (герой и питомцы) |
| Poisoned Arrows | I0T5 | атаки героя вешают B01C; тики чаще на `5% × Potency` |

Игнорируются: страницы I0MD / I0MC (интерфейс). Чисто защитных талантов у Hunter нет.

## Предметы класса

| Предмет | Код | Эффект |
|---|---|---|
| Steel Quiver | I0T6 | +15 урона, +5% haste, +5% удачи, включает Steel Arrowheads |
| Trap Layer's Gloves | I0T7 | +12 урона, +100 маны, +8% haste, Sting ставит Steel Trap |
| Elven Recurve Bow | I0T8 | +14 урона, +12 AGI, Multi-Shot ×1,25 |
| Helm of Beast Taming | I0T9 | +10 урона, +8% урона питомца, +8 Mastery, BW +25% AS (и питомцу) |

## Голый DPS (5 целей, 30 с)

| Спек | DPS |
|---|---|
| Marksmanship | 190,3 |
| Beast Mastery | 175,8 |
| Survival | 210,5 |

Лучшие таланты одним слотом: Volley (228 / 214 / 268), Windrunner's Quiver (231 / 201 / 241), Wild Power (215 / 202 / 240). Классовые вещи: Elven Recurve Bow 261 / 235 / 288 — в первой десятке всех вещей.

## Допущения

- Дистанция до цели 500 → Aspect +10%. Цели стоят, ловушки срабатывают сразу после 0,5 с.
- Шансы — веса (с 2026-11-14; до этого детерминированный накопитель `_Dither`). Lock and Load, оба Prowess, Serpent Sting и рана Steel Trap — распределения времени окончания (`hunter._Window`, до 8 точек), Split Shot — вероятность взвода на следующую атаку, Maul / Shred / Traplayer — урон с весом шанса. Броня цели под Sting и раной — ожидание по двум независимым шансам. Крит Windrunner — вероятность взвода.
- Флангинг всегда активен (герой и питомец бьют цель 0). Roar Grylls — постоянные +20%.
- Survival-сброс и Talon Strikes уменьшают оставшиеся кулдауны BW / Sting / Multi / Trap (не Call Pet).
- Поведение под I06B «+18% урона призывов» не моделируется (только +7% крита питомцам).

Аномалии — `docs/hunter-anomalies.md`.

## Изменения 2026-11-14

- Battle Frenzy и Silent Messenger — проки боя (`sunken_sim.attack_procs`), как у остальных GPU-классов. До этого Battle Frenzy был плоскими +10% скорости атаки, Silent Messenger не учитывался.
- Крит заклинаний (Nightfall ×1,65, Netherspike ×1,50, + рейтинг) на всплеске Sulfuras: это единственный магический урон героя. Все способности Hunter карта наносит физическим уроном или атакой (`PreDamage_Dummies` перенаправляет урон дамми на героя), поэтому крит заклинаний на них не действует. На сборках Sulfuras + Nightfall в среднем +1,7…+3,7% DPS, максимум +8%.
- Удача с вещей — только строки статов (`shadow.item_luck`), как у остальных классов (Cenarion Helm: 10% вместо 18%).
- GPU: точное ядро `farm/hybrid/hunter_cl.py` (float64, бит в бит с симом). Отрицательная броня цели (Elemental Orb + Silent Messenger под Sting и раной) берётся из таблицы значений `shadow.armor_taken`, без возврата строки в Python.
