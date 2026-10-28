# Death Knight

Общие правила боя, предметов и кулдаунов — в `docs/guide.md`. Здесь Death Knight карты Sunken City v2.5.2a. Формулы сняты с триггеров `war3map.j` (DK-блок ~122749–123507, PreDamage_Increase, PreDamage_Heroes, OnDamage_Heroes, OnSpellcast_Heroes, Select_Str_Hero) и объектов `w3a/w3u/w3t` (парсер `/workspace/sunken-ref/rogue/dump_obj.py`).

Сим `sunken_sim/death_knight.py` считает ожидаемый урон за 30 секунд на ранге 1, 6 уровень, 5 целей, броня 15, без очков навыков. Однослотовый прогон: `python3 extract/one_slot_death_knight.py` (пишет `extract/death_knight-one-slot.json`), быстрая проверка: `python3 extract/one_slot_death_knight.py --smoke`. Ключ класса в `search.class_item_codes()` — `DeathKnight`.

## Лист

Death Knight U002 (родитель Udea, ближний бой). Сила 28 + 2,8, ловкость 9 + 0,9, интеллект 13 + 1,3. На 6 уровне 42 силы, 13 ловкости, 19 интеллекта. Основной атрибут — сила. Белый удар 11 + 1d1 = 12 (DCS_Config), плюс `0,75 × STR` (DCS). Взмах 2,0 с (`ua1c`). Тип атаки normal. Мана `120 + 7 × INT` = 253. Здоровье `310 + 15 × STR` = 940 плюс `+N Health` с вещей. Броня `3 + 0,1 × AGI` (war3mapMisc `AgiDefenseBonus=0.1`) + броня вещей — нужна только для Bloodforged Armor.

Blood Tap I09T: `BloodTap_Bonus` 1,00 → 1,35 — множитель всех скейлингов от максимального здоровья.

## Специализации

Уровень A0I0: 1 — Frost, 2 — Blood, 3 — Unholy. В Unholy Empower Rune Weapon A085 заменяется пассивом Plaguebearer A038.

| Спек | Что даёт по урону |
|---|---|
| Frost | Frost Strike `× (1,05 + 0,005 × Mastery)`, затем `+0,10 × MaxMana`. Presence: `+1%` магического урона за каждые 40 текущей маны |
| Blood | Только лечение (Blood Specialization `20 + 3% MaxHP` на каждом касте, Presence-хил). Урона не добавляет |
| Unholy | Нет ERW. Outbreak тикает чаще: `TickRate += 0,10 + 0,005 × Mastery`. Plaguebearer. Presence: Potency `+(мана%) × (3 + 0,4 × уровень)` = до +5,4 |

## Панель

| Способность | Код | База, ранг 1 |
|---|---|---|
| Death Grip | A03W | 10 с. Стоит 10% текущего HP. +5% max маны (15%, если у цели есть мана; у манекена — 5%). Таунт |
| Empower Rune Weapon | A085 | 14 с. Сбрасывает кулдаун последнего каста (`DK_LastCast`). Не Unholy |
| Blood Strike | A0G1 | 7 с. Blood Plague B08P 4 с на цель, +1 к max HP за каст (не после ERW-сброса) |
| Unholy Fury | A03V | 12 с (в объекте нет `acdn`, взят кулдаун из подсказки). AoE 300 — все 5 целей, вешает Outbreak 8 с. Стоит 15% HP |
| Frost Strike | A0IE | 8 с (−1 Might of the Lich King, −2 Coldbringer's Armor). Замораживает цель на 1,5 с (Bfro) |
| Presence | A0I9 | пассив, в бою тянет `(1,5 + 2 × уровень)` = 13,5 маны/с |

Все способности 0 маны (`amcs` = 0). Порядок: Unholy Fury, Frost Strike, Blood Strike, Death Grip, потом автоатака; ERW жмётся сразу, если у последнего каста осталось больше 2 с кулдауна (на практике сбрасывает Unholy Fury). Каст общий: эффект через 0,15 с, ещё 0,30 с герой не атакует.

## Урон

Все заклинания — `NextDamageType = Magical` (ветка Magical в PreDamage_Increase), броня манекена режет и их.

| Источник | Формула | Тип |
|---|---|---|
| Автоатака | `DCS = 12 + 0,75 × STR + урон вещей` | Physical, крит героя |
| Death Grip | `20 + 10 × уровень героя + 0,10 × MaxHP × BT`; Obliterate `+0,75 × DCS` | Magical |
| Blood Strike | `70 × ранг − 10 + 0,10 × MaxHP × BT`; Obliterate `+0,75 × DCS`; Maw of the Damned `+0,35 × лечение`, лечение = `20 + 0,10 × MaxHP × BT` (×2 Siphoning Sword) | Magical |
| Unholy Fury | `50 + 0,05 × MaxHP × BT` по каждой цели; Obliterate `+0,50 × DCS` | Magical |
| Frost Strike | `(70 + 0,05 × MaxHP × BT + 0,15 × MaxMana) × 1,20 (Lich King) + 1,00 × DCS (Obliterate)`, Frost-спек см. выше | Magical |
| Outbreak | глобальный таймер, каждые `1,25 / TickRate` с бьёт всех с B06E: `5 × ранг(A03V) + 0,008 × MaxHP × BT`. TickRate = 1 (+Unholy) (+0,25 Belt of the Plaguebearer). Virulent Plague: шанс `(12 + 0,5 × Potency)% × удача` тикнуть дважды | Magical |
| Blood Plague | на цели с B08P любой урон DK-игрока `+(2 + ранг A0G1)` = +3 плоско; Decomposition ещё `+3 + 0,08 × DCS` | плоская прибавка до множителей |
| Plaguebearer (Unholy) | любой не-DISEASE урон DK-игрока: шанс `5% × 1,25 (Pestilence) × удача` (÷2, если на цели нет Outbreak) повесить Outbreak; если Outbreak уже был — взрыв `20 + 0,015 × MaxHP × BT` | DISEASE, без магической ветки |
| Unholy Strikes I0EV | после Death Grip и Frost Strike 2 удара `15 + 0,40 × STR` | Magical |
| Breath of Sindragosa I0CR | на Frost Strike: змей 2 с, 600 вперёд, каждую цель в 200 один раз `20 + 0,05 × MaxMana + 0,05 × MaxHP × BT`; по замороженной ×1,5, остальным Chill 5 с | Magical |
| Army of the Dead I0CS | каждый 3-й каст (кроме ERW) — гуль 16 с: `10 + R2I(0,35 × DCS)`, взмах 1,65. Не в Blood: 10% × удача повесить Outbreak или Chill 4 с | Physical призыва |
| Bloodworms I03W | каждый каст (с ERW) — червь 7 с: `5 + R2I(0,12 × DCS + 0,005 × MaxHP × BT)`, взмах 1,5. 20% × удача: DK бьёт `2 × урон червя` | Physical / Magical |

### Множители

- Магическая ветка: `1 + magic add вещей + Sulfuron + Spellbinder + Frost Presence (0,01 × мана/40) + Bloodforged Armor (0,05 + 0,01 × броня DK, с Bone Shield +4)`, затем Glass Cannon ×1,15.
- DamageIncrease (весь урон DK-игрока, включая призывы): Frost Strike изучен → `+15%` по замороженной цели, иначе `+8%` по охлаждённой. Grim Reaper I07Z `+6%` за каждый из B08P, B06E, Bfro, B011, B08Q на цели.
- Marrowrend I09S: Blood Strike вешает B08Q −5 брони на 5 с и Bone Shield.
- Razorice I0DS: каждая атака героя −0,30 с с кулдауна Frost Strike (у призывов 15% × удача).
- Крит заклинаний только с вещами `spell_crit`, как у остальных классов.

## Голый DPS (5 целей, 30 с)

| Спек | DPS | Основа |
|---|---|---|
| Frost | 147,4 | Unholy Fury 62,6 · Outbreak 24,8 · Blood Strike 17,0 · Frost Strike 16,3 · авто 14,7 · Death Grip 11,9 |
| Blood | 140,7 | то же без Frost-бонусов |
| Unholy | 124,1 | Outbreak 31,1 · Unholy Fury 31,3 (нет ERW) · Plaguebearer 4,3 |

ERW почти всегда сбрасывает Unholy Fury — это дубль AoE раз в 14 с, поэтому Frost/Blood голыми выше Unholy.

## IGNORED

Не дают урона по манекену и в прогоне не участвуют: Blood Feast I0CU (лечение, и Mask of the Blood Hungerer I0NJ — только её статы), Will of the Necropolis I0G9 (защита), Anti-Magic Zone I03G (защита), страницы I0MD / I0MC. Также не моделируются: лечение Blood-спека и Presence, таунт Death Grip, стоимость HP, −18% урона от Outbreak (Cri3), замедление Chill.

## Пробелы модели

- Шансы (Plaguebearer, Decomposition, червь, гуль, Razorice у призывов) — детерминированное накопление вероятности, не RNG.
- Призывы бьют сразу при появлении и всегда по основной цели; подход не учитывается. Бонусы вещей героя к ним не применяются, крита нет.
- Breath of Sindragosa задевает все 5 целей (кучка в линии 600 × 200).
- Удвоенный урон червя проходит магическую ветку без Potency.
- DamageIncrease считается отдельным множителем поверх магической ветки.
- Взрыв Plaguebearer (DAMAGE_TYPE_DISEASE без NextDamageType) — без магической ветки, но с бронёй и DamageIncrease.
- Presence выжигает ману за ~20 с (реген ≈2,5/с против 13,5/с), поэтому Frost-бонус и Unholy-Potency к середине боя почти нулевые.
- Кулдаун Unholy Fury 12 с взят из подсказки.
