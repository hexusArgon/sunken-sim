# Warrior

Общие правила боя, предметов и кулдаунов — в `docs/guide.md`. Здесь Warrior карты Sunken City v2.5.2a. Формулы сняты с триггеров.

Сим `sunken_sim/warrior.py` считает ожидаемый урон за 30 секунд на ранге 1, 6 уровень, 5 целей, броня 15, без очков навыков. Однослотовый прогон: `python extract/one_slot_warrior.py`, быстрая проверка: `python extract/one_slot_warrior.py --smoke`.

## Лист

Warrior O00F. Сила 30 + 3,0, ловкость 12 + 1,2, интеллект 8 + 0,8. На 6 уровне 45 силы, 18 ловкости, 12 интеллекта. Белый удар 24 + 1 = 25, плюс `0,75 × сила`. Взмах 1,85 с. Мана `120 + 7 × интеллект`. Здоровье `300 + 15 × сила`. Броня `4 + 0,1 × ловкость` плюс броня вещей.

Скорость атаки: бонус вещей плюс 0,4% за ловкость, потолок от −80% до +400%. DCS_Damage — показанный урон атаки, то есть строка силы атаки листа. Battle Shout добавляет к DCS на время бафа.

## Панель

Уровень A0KO. 1 — Protection, 2 — Arms, 3 — Fury.

| Способность | Код | База, ранг 1 |
|---|---|---|
| Ignore Pain | A0KN | 8 с, 15 маны, защита (в DPS не жмётся) |
| Battle Shout | A0E9 | 10 с (Protection −2 с), 10 маны, баф 4 с: +25 AD |
| Whirlwind | A0LL | 8 с, 15 маны, круг 275 |
| Bloodthirst | A0CS | 6 с, 10 маны, одна цель + следующий удар |
| Demoralizing Shout | A0LU | 10 с (Protection −2 с), 10 маны; урон только в Arms |

Каст общий: эффект через 0,15 с, ещё 0,30 с герой не атакует и не начинает следующий каст. Кулдаун начинается в момент нажатия. Пять целей стоят в одной точке. Порядок кнопок: Battle Shout, Whirlwind, Bloodthirst, Demoralizing Shout (Arms).

## Специализации

| Спек | Уровень | Урон |
|---|---|---|
| Protection | A0KO = 1 | Ignore Pain absorb +40 (+8 × Mastery). Кулдауны Battle/Demo Shout −2 с |
| Arms | A0KO = 2 | Bloodthirst и Whirlwind × `(1 + (0,10 + 0,006 × Mastery) × WarriorMastery_Multiplier)`. Demo Shout бьёт `20 + 0,25 × DCS + 0,05 × max HP` по площади |
| Fury | A0KO = 3 | Удар Bloodthirst + `15 + 2 × Mastery`. Enraged Regeneration также даёт +10% крита и +15% AS |

Weapons Master (I0GR): `WarriorMastery_Multiplier = 1,40` и +10 Mastery.

## Урон

Ранг 1. Potency, тип урона, крит и броня — общие правила сима. Ниже сырой кусок из триггера, до них.

| Источник | Формула |
|---|---|
| Автоатака | `DCS` (Normal). Cleave Whirlwind: шанс `30 + 5 × ранг`%, доля `40%` (`50%` пока WW на КД) по остальным целям |
| Bloodthirst | `75 × ранг + 0,50 × DCS + 0,05 × max HP` (+ `0,75 × сила` с Pain Train). Physical. Вешает флаг следующего удара |
| Bloodthirst (удар) | `20 + 20 × ранг + 0,75 × DCS` (+ Fury `15 + 2 × Mastery`). Normal Attack |
| Whirlwind | `65 × ранг − 10 + 0,75 × DCS` (+ `0,50 × сила` с Pain Train). Physical, все цели в 275 |
| Battle Shout → DCS | без Warcry: `+10 + 15 × ранг`; с Warcry: `+15 + 20 × ранг` на 4 с (баф B063) |
| Demoralizing Shout (Arms) | `20 + 0,25 × DCS + 0,05 × max HP` Physical по врагам в 500 |
| Shockwave (талант) | `15%` урона Bloodthirst волной |

Enraged Regeneration (пассив): атака 10% / входящий урон 6% → баф 4 с, +10% урона со всех источников, реген `0,75%` max HP. Ниже 40% HP эффекты сильнее на 50%.

## Таланты страницы

I0MD / I0MC — переключение страниц, в сим не входят. Остальные коды — в `TALENTS` модуля.
