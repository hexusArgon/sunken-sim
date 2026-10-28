# Windmaster

Общие правила боя, предметов и кулдаунов — в `docs/guide.md`. Здесь Windmaster карты Sunken City v2.5.2a. Формулы сняты с триггеров `war3map.j` и объектов `w3a/w3u/w3t` (свой парсер `dump_obj.py`, `library._parse_objects` для w3a сломан).

Сим `sunken_sim/windmaster.py` считает ожидаемый урон за 30 секунд на ранге 1, 6 уровень, 5 целей, броня 15, без очков навыков. Однослотовый прогон: `python3 extract/one_slot_windmaster.py` (пишет `extract/windmaster-one-slot.json`), быстрая проверка: `python3 extract/one_slot_windmaster.py --smoke`. Ключ пула классовых вещей — `"Windmaster"` (135 магазинных, 189 дропа, 8 легендарок; классовые I0RH, I0RI, I0RJ, I0RK).

## Лист

Windmaster O00Y (ближний бой, 80, SIEGE). Ловкость 26 + 2,6, сила 13 + 1,2, интеллект 11 + 1,1 → 39 / 19 / 16 на 6 уровне. Белый удар `ua1b` 35 + 1d1 = 36, плюс `0,75 × AGI`, плюс Attack Damage вещей, плюс 2 за стак Tornado (A078, до 12, держатся в бою) — это DCS. Взмах 1,60 с. Мана `120 + 7 × INT`, здоровье 250.

Скорость атаки: вещи + 0,4% за ловкость (до +100%), Lightning Rush +15% (×1,75 с Windflow), Gathering Storm +4% за уровень A03Z выше первого (до +40%), Wind Shift +40%.

## Панель

Спек — уровень A0CC на `udg_Glyphs_Unit[1]`: 1 — Upheaval, 2 — Storm, 3 — Combat.

| Способность | Код | Ранг 1 |
|---|---|---|
| Skyslash | A0KT | 6 с, 10 маны; бафф B03L 4 с, следующая атака бьёт доп. удар |
| Tornado | A092 | 12 с (−2 Greater Tornado), 20 маны; живёт `7 + 0,20 × Potency` с, болт раз в 0,75 с (0,5 с A0E1) |
| Lightning Rush | A01T | 9 с (−1,5 Eye of the Storm), 15 маны; удар через `дистанция/1200 + 0,15` с по всем в 250 |
| Windstorm | A0QE | 12 с, 20 маны; форма O01K на 4 с (Storm `4/(1+CDR)`), тик `0,5 / BTR` с |
| Wind Walk (Combat вместо Windstorm) | A08D | 35 с, 35 маны; B08H 10 с: атаки +54 урона, +20% крита |
| Storm Cloud | A0CL | 3 с, 0 маны; кастуется только с Illusions |

Порядок в симе: Wind Walk → Tornado → Lightning Rush → Skyslash → Windstorm → Storm Cloud, потом автоатака. Windstorm последним: форма блокирует остальные спеллы и атаку (атаки O01K обнуляет Damage_Modifiers); при Windstorm первым Upheaval даёт 276,6 вместо 350,5 DPS. Каст общий: эффект через 0,15 с, ещё 0,30 с без атак.

## Урон

| Источник | Формула | Тип |
|---|---|---|
| Автоатака | DCS | SIEGE-атака, крит |
| Skyslash | `(60 + 40 × ранг) + 1,0 × DCS` поверх белого удара; Skyfury ×2 после Tornado (флаг), иначе ×1,10 | Storm: ×1,25 Physical не-атака + Cyclone; иначе SIEGE-атака с критом |
| Tornado, болт | `25 + 0,30 × AGI + 0,10 × DCS` (Storm `+0,30 × DCS`), одна цель, +1 стак | Physical |
| Lightning Rush | `75 × ранг + 1,20 × DCS`; Storm ×`(1,05 + 0,006 × M)`; Windwalker Leggings ×1,25 | Physical, все цели |
| Windstorm, тик | `(3 + 7 × 6 + 0,6 × AGI)` → Piercing Gust 20% `+0,20 DCS` → Storm `+0,20 DCS`, ×`(1,05+0,006M)` → ×2 при одной цели → Raging Storm ×1,12 → Shredding Wind 25% ×1,40; итог ×0,5 | Storm без прока — Physical; с проком PG — PIERCE-атака с критом; иначе NORMAL без типа |
| Cyclone | на цель `40 + 0,40 × AGI + 0,35 × DCS`, Fury ×`(1 + 0,004 × M)` | Physical; Hurricane 30% — MELEE-атака с критом |
| Stormrage | 25% на цель Cyclone: `40 + 1,40 × DCS` | Physical |
| Illusions | 50% × удача на каст (LR — два броска): `25 + DCS + 0,5 × AGI` | Physical от героя |
| Charged Blade | 15% (×2 под B04J) × удача на атаку: `0,5 ×` нанесённого, до 3 целей | NORMAL, снова броня |

Potency добавляется к каждому событию урона героя. Крит только у атак: шанс = вещи + Combat `5 + 0,5 × M` + B08H 20; множитель 2,0 + вещи + Balanced Blade 0,25 (+ перебор шанса над 100 под B08H). Balanced Blade ещё +2 пробития брони.

Источники Cyclone: Upheaval (3% × удача на любое событие урона ≥ 1), Storm (Skyslash и каст LR), Combat (30% × удача, ×1,5 на крите, на атаку не-NORMAL типа). Дамми общий, кулдаун 1,0 с — проки в кулдаун теряются.

Upheaval: BTR `+0,10 + 0,006 × M`, 3,5% × удача на любое событие урона — сброс кулдауна Windstorm. Storm: BTR `+CDR`. Piercing Gust: BTR `+0,25 × скорость атаки`. Master's Warbeads: BTR +0,20.

Прочие таланты: Wind Shift — любой каст, кроме Storm Cloud, даёт B006 на 4 с: +40% AS и `+0,40 × AGI` к двум белым атакам. Mistral Strikes — Skyslash замедляет цель на 4 с, атаки по замедленной цели +12%. Chilling Winds — LR замедляет всех на 3 с (работает только вместе с Mistral). Windflow — бафф LR 6 с, AS ×1,75, +10% CDR кастам под баффом. Skywrath Ring — 50% × удача на болт Tornado: −0,3 с кулдауна Skyslash. Fury of the Storm Peaks +10 Mastery.

Не моделируется: Wintergrasp I03S (лечение), страницы I0MD / I0MC.

## Допущения модели

Не числа карты, а выбор модели: дистанция LR 80 (ближний бой); полёт Cyclone 80/475 с; удар иллюзии через 0,33 с (`udp1` e00K); Cyclone попадает по всем целям; faerie fire Shredding Wind — на цель 0; +54 Wind Walk добавляется до множителя Physical; вероятности — детерминированные аккумуляторы (`_Dither`); Storm Cloud кастуется только с Illusions.

## Однослот, 5 целей

Без вещей: Upheaval 350,5, Storm 302,0, Combat 248,1 DPS.

| Спек | Топ-3 таланта | Топ вещи | Топ глифы |
|---|---|---|---|
| Upheaval | Raging Storm 417,7; Stormrage 399,9; Illusions 393,8 | Master's Warbeads 492,8; Unbound Power Core 469,0; Black Raven 464,7 | Fortitude 393,7; Unsealed Power 382,1; Supremacy 380,7 |
| Storm | Illusions 339,5; Raging Storm 334,3; Greater Tornado 322,7 | Gorehowl 439,4; Earthshaper 438,8; Iron Cleaver 420,3 | Unsealed Power 356,3; Mindhaste 348,3; Glass Cannon 347,3 |
| Combat | Hurricane 325,1; Stormrage 281,7; Illusions 279,5 | Sulfuras 379,2; Elemental Orb (Fire) 374,2; Gorehowl 352,9 | Unsealed Power 288,4; Glass Cannon 281,7; Fortitude 276,2 |

В Upheaval герой почти всё время в форме Windstorm (см. аномалию 12), поэтому атакующие таланты (Charged Blade, Mindhaste, Hurricane) там дают 0.

Аномалии — `docs/windmaster-anomalies.md`.
