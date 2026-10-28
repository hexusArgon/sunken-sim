# Siren (N03T)

## Лист
`extract/siren-one-slot.json` — один слот: таланты (15), предметы (332: магазин 135, дроп 189, легендарки 8, классовые I0RD/I0RE/I0RF/I0RG в дропе), глифы (12). Бой 30 с, 5 целей, броня 15, герой 6 уровня, ранг способностей 1. Спеки: Sharpshooter, Watershaper, Seagrace (уровень A0JW на udg_Glyphs_Unit[1] = 1/2/3). Код: `sunken_sim/siren.py`, выгрузка: `extract/one_slot_siren.py` (`--smoke`). Лог: `/workspace/sunken-ref/siren-one-slot-run.log`. Аномалии: `docs/siren-anomalies.md`.

Голый DPS: Sharpshooter 169.0, Watershaper 194.5, Seagrace 116.4.

## Базовые числа
- STR 13, AGI 39, INT 22 (база 9/26/15 + 5 × 0.9/2.6/1.5, вниз). Основной атрибут AGI. A0PV не учитывается.
- HP 230, мана 120 + 7 × INT (umpr 0). Автоатака 27 + 1d1 = 28 + 0.75 × AGI + урон предметов («+N Attack Damage» парсится), своп 1.7, pierce (физика), дальность 525.
- DCS = 28 + 0.75 × AGI + урон предметов.

## Пайплайны урона
- Урон героя: (сырой + Icy Quiver + потенция) × типовые бонусы × крит (атаки; заклинания — только с предметом спелл-крита) × броня (15 − пробитие − 2 под Snake Bite) × execute.
- Призывы (элементали, отражение, Snake Bite): (сырой + Icy Quiver + потенция) × (1 + Pet Damage) × (1 + Water Core) × крит призыва (только атаки) × броня.
- Icy Quiver I0AQ: Liquid Arrows под B058 вешают Chill (frostnova, Bfro) на 4 с; любой урон Сирены и её юнитов по цели с Bfro +1% макс. маны Сирены (Seagrace: +0.5%).

## Способности
- Tidal Shot A0ER (5 с, 15 маны): заряд B05F, следующая атака Сирены запускает thunderbolt: 80 × ранг + 2.0 × AGI (+0.40 × текущая мана с I0MZ), Sharpshooter ×(1.10 + 0.01 × Mastery), Elemental Shot ×1.35 (убивает элементаля), магия. После попадания Tidal Fletcher B058 на 3.5 с (6.0 с с I0N0). Sharpshooter: 25% × удача Crushing Wave 0.40 × выстрела по всем целям; копия отражения ×0.30 × Reflection_Bonus.
- Liquid Arrows A0D2 (тоггл): на каждую атаку Сирены 2 маны, 20 + 0.40 × AGI + 0.40 × INT магией, ×1.15 под B058 (×1.45 с Seaflurry). Каждый 3-й удар элементалей — Liquid Arrows ×0.40 за 0.8 маны. Seagrace — только лечение.
- Song of the Siren A0OS (10 с, 10 маны): B04R 6 с (8 с с I0OW) — +15% скорости атаки Сирене, мана 1 + 0.5% макс. маны/с (×1.5 I0OW) Сирене и элементалям. Seagrace + отражение: копия B08S (+50%/75% от эффекта).
- Sea Elemental A051 (10 с, 25 маны): n03U на 10 с (+4 с I0MW), 12 + R2I(0.15 × DCS), своп 1.3, отскок на 2-ю цель ×0.65. Water Core: +0.5% урона за каждую ману элементаля, +3 маны за удар (+1 I0MW, ×2 на крите с I0MX). Watershaper: 2 элементаля; копия отражения ещё 2 на 40% × Reflection_Bonus времени. Hydraxian Waterlord I08F: первый — n03H (своп 1.0, 3 цели).
- Stone Gaze A0JQ (15 с, −3 с I0OV, 30 маны): 90 + 1.45 × AGI + 2.40 × INT магией по всем целям.
- Mirror Image A0N7 (25 с, 0 маны): отражение e00M на 15 с (+3 с I0N1): своя атака R2I(0.5 × DCS) + 1 каждые 2.25 с и pierce-удар Сирены 0.5 × DCS как атака (проки Liquid Arrows, Snake Bite, Bow, тратит B05F).
- Snake Bite I0MU: 25% × удача на атаку Сирены: 30 + 0.50 × AGI + 1.50 × DCS (Pet Damage), −2 брони на 4 с.
- Coral Arrowheads I08G: под B058 атаки Сирены +10 шанса и +0.18 рейтинга крита. Gift of Neptulon I0MX: крит элементалей +10 + 0.20 × INT.
- Классовые предметы: Bow of the Sea Witch I0RD (10% × удача Tidal Shot на атаку без заряда), Vest of the Tides I0RE (+15 маны/+25 макс. маны элементалям, Pet Damage), Maelstrom Band I0RG (Reflection_Bonus 1.25), Scepter of Azshara I0RF (только статы; снижение урона Song — защита).

## Игнорируются
Healing Waters I0OY (лечение), Flow of the Ocean I0MY (AS только союзным героям), Alluring Voice I08H (контроль), страницы I0MD/I0MC. Viper Sting I0OZ оценивается (Liquid Arrows без расхода маны), оглушение — нет.

## Ротация и политики
Касты до автоатаки. Приоритет: Mirror Image → Sea Elemental → Tidal Shot (если нет заряда) → Song → Stone Gaze. Политики (лучшая): Liquid Arrows вкл/выкл × Song вкл/выкл.

## Допущения
- Цели кучей: Stone Gaze и Crushing Wave задевают все 5 целей; отскок элементаля по цели 2 (3).
- Полёт Tidal Shot 525/1300 ≈ 0.40 с. Начальная мана элементаля 0 (umpi нет). Кубик отражения 1d1.
- Удары отскока считаются атаками элементаля (Water Core, счётчик Liquid Arrows).
- Song вешается на всех живых элементалей (в радиусе 600); тики маны на целых секундах.
- Elemental Shot убивает элементаля с наименьшим остатком жизни (в игре — случайного).
- Chill от Liquid Arrows = Bfro (frostnova A00H) только на цель; заморозка Stone Gaze не считается Bfro.
- Мана цели 0 (Viper Sting ничего не крадёт, оглушение не оценивается).
- Шансы — детерминированный dither.
