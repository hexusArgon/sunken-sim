# Berserker

Общие правила боя, предметов и кулдаунов — в `docs/guide.md`. Здесь Berserker карты Sunken City v2.5.2a. Формулы сняты с триггеров `war3map.j` и объектов `w3a/w3u`.

Сим `sunken_sim/berserker.py` считает ожидаемый урон за 30 секунд на ранге 1, 6 уровень, 5 целей, броня 15, без очков навыков. Однослотовый прогон: `python extract/one_slot_berserker.py` (пишет `extract/berserker-one-slot.json`), быстрая проверка: `python extract/one_slot_berserker.py --smoke`.

## Лист

Berserker O005 (дальний бой, 800). Fury меняет юнит на O01R (ближний бой, те же статы). Ловкость 28 + 2,8, сила 14 + 1,4, интеллект 8 + 0,8. На 6 уровне 42 ловкости, 21 сила, 12 интеллекта. Основной атрибут — ловкость. Белый удар 29 + 1 = 30, плюс `0,75 × ловкость` (с зелёной). Взмах 1,6 с. Мана `120 + 7 × интеллект`. Здоровье `230 + 15 × сила` плюс `+N Health` с вещей.

Скорость атаки: бонус вещей плюс 0,4% за ловкость (до +100%), потолок от −80% до +400%, плюс Berserk и Mask of the Blood Fanatic по времени.

## Панель

Уровень A0KW (Glyphs_Unit[1]). 1 — Headhunter, 2 — Poison, 3 — Fury.

| Способность | Код | База, ранг 1 |
|---|---|---|
| Toxic Sack | A0A6 | 10 с, 30 маны, круг 250, урон через 0,75 с после каста |
| Skull Split | A0A7 | 20 с, 25 маны, одна цель |
| Venomous Axes | A004 | пассив: каждая атака вешает яд B05J на 4 с |
| Blood Fury | A016 | переключатель; в симе включён весь бой |
| Regeneration | A0KX | лечение, в DPS не входит |

Порядок кнопок: Toxic Sack, Skull Split, потом автоатака. Каст общий: эффект через 0,15 с, ещё 0,30 с герой не атакует.

## Урон

| Источник | Формула | Тип |
|---|---|---|
| Автоатака | `DCS = 30 + 0,75 × AGI + урон вещей (+30 Blood Craze)` | Physical, крит героя |
| Toxic Sack | `80 × ранг − 20 + 2,2 × AGI` по всем целям; Poison Bomb ×1,3, по цели с ядом ×1,6. Вешает яд на 4 с | Physical, без крита |
| Skull Split | `150 × ранг + 2 × DCS + 0,05 × maxHP цели` (5300); Executor ×1,35 при HP цели ≤ 40% | Physical, без крита |
| Venomous Axes (тик) | `10 × ранг + 0,15 × DCS` (0,25 с Might of Dambala), раз в 1,00 с по каждой цели с ядом. Свой крит: шанс `крит × Luck`, множитель `1,5 + рейтинг` | без типа (Physical с Hemotoxin) |
| Surge of Toxins | `15 × уровень + 2,5 × AGI`, снимается следующей атакой | без типа (disease) |
| Way of the Snake | 20% × Luck за атаку: `2 × (10 × ранг Sack + 0,5 × AGI)` по каждой цели, снимает Surge | без типа |
| Axe Mastery | топор `20 + 1,25 × DCS`, считается атакой | Physical, крит героя |

Крит героя (PreDamage_Increase Func043) срабатывает только на атаках (`IsDamageAttack`). Шанс × Luck, множитель `2 + рейтинг`. Blood Hunter прибавляет `15 + 5% max HP` до множителя.

Яд: Deadly Poison, Wound Poison и Leeching Poison каждый дают ещё 30% × Luck вызова урона за тик. Deadly Poison: × `(1 + 0,5% за 1% недостающего HP цели)`. Wound Poison: яд даёт −3 брони (A0FM уровень 2). Poison: каждый вызов бьёт ещё раз с шансом `5 + 0,5 × Mastery` %. Poisoned Blades (или Venombite I0U2): атака по цели с ядом вызывает лишний тик.

Surge of Toxins (B06W): вне Poison каждый вызов урона яда с шансом 2% × Luck; в Poison любой не-disease урон героя с шансом 3% × Luck.

Blood Fury: при включении `AGI += floor(maxHP / 25)`, потолок 100 (без потолка с Gift of the Blood God). Gift даёт `10 + уровень` силы уже после снимка ловкости. Каждая атака бьёт героя на `3 + 6 × уровень`. Blood Craze: ещё 30% × Luck на дополнительный самоурон и +30 DCS на 6–10 уровне (A0KA уровень 3).

## Специализации

| Спек | Уровень | Урон |
|---|---|---|
| Headhunter | 1 | Рейтинг крита `+0,10 + 0,008 × Mastery`, Attack_Increase +12% при Blood Fury |
| Poison | 2 | Двойной тик яда `5 + 0,5 × Mastery` %, Surge с любого урона 3% |
| Fury | 3 | Весь урон героя × 0,85. Лайфстил и реген — лечение. Berserk 2% за стак вместо 3% |

## Таланты

| Талант | Код | Модель |
|---|---|---|
| Axe Mastery | I0LO | 5% × Luck за входящий удар (каждые 0,2 с давления), 10% × Luck за самоурон Blood Fury |
| Might of Dambala | I0PE | Яд 0,25 × DCS; 20% × Luck за каждый вызов урона яда (Deadly/Wound/Leeching добавляют вызовы) — заново наложить яд на 4 с |
| Berserk | I0A2 | Bloodlust A0K9 6 с: AS `0,12 + 0,03 × стаки`, стак за каждый входящий удар |
| Executor | I0LS | Атаки +35% при HP цели ≤ 40%, Skull Split ×1,35 |
| Deadly Poison / Wound Poison / Leeching Poison | I09O / I0HS / I0PD | см. «Яд». Лечение Leeching не входит |
| Poison Bomb | I0LR | Toxic Sack ×1,3 / ×1,6 |
| Boneslicer | I09V | Крит атак `+10 + 0,5 × % недостающего HP героя` |
| Blood Craze | I0LQ | +30 DCS, лишний самоурон |
| Poisoned Blades | I0PF | Лишний тик яда на атаке |
| Blood Hunter | I0A3 | На крите атаки `+15 + 5% max HP` |
| Way of the Snake | I0PG | Веер ножей |
| Hemotoxin | I0TZ | Physical +`8% + 0,25% × AGI`, яд становится Physical |
| Gift of the Blood God | I0U1 | Снимает потолок 100 AGI, +16 силы |

Не входят: Voodoo Shuffle I0LP, Taz'dingo I0PH, Gurubashi Ward I0U0 (защита), I0MD / I0MC (страницы).

## Bare DPS (30 с, 5 целей, без вещей и талантов)

| Спек | DPS |
|---|---|
| Headhunter | 164,9 |
| Poison | 167,8 |
| Fury | 136,4 |

Лучшие таланты одним слотом: Way of the Snake (208 / 214 / 173), Hemotoxin (203 / 206 / 168), Axe Mastery (Headhunter 191,5) / Blood Craze (Poison 192,3, Fury 156,8).

## Допущения и пробелы модели

- Blood Fury включён с 0 с; потеря HP от самоурона не считается, HP героя берётся из общей модели давления (`pressure.hero_hp_ratio`).
- Berserk: цикл 6 с баффа + 0,2 с паузы, стаки от ударов давления раз в 0,2 с. Самоурон Blood Fury стаков не добавляет.
- Шансы считаются ожиданием: Surge — вероятность на цели, Might of Dambala — распределение времени окончания яда на каждой цели (с вероятностью q тик переносит долю в «тик + 4 с»; до 2026-11-12 был накопитель, который держал яд на побочных целях постоянно — завышение ~9–11 % DPS), Axe Mastery и Way of the Snake — доля урона.
- Крит яда берёт базовый шанс крита; в карте переменная `CriticalStrike_Chance` хранит значение с последней атаки (с Boneslicer и т.п.).
- Казнь Skull Split (сброс кулдауна, Trophy Hunter's Cape I0U4) работает только на убийстве — в симе не срабатывает. Трофеи (Trophies_Total) берутся как накопленные до боя: `round(13,333… × уровень)` (15 ур. → 200), каждый стак +1 к DCS, как в карте.
- Без типа (яд, Surge, Way of the Snake) не получает +% физ/маг урона вещей, только Glass Cannon и Sulfuron Gloves.
- Стан Darkspear Vestment I0U3, таунт Fury, +15% входящего урона Berserk — не входят.
- Potency прибавляется к каждому экземпляру урона (как у Warrior).
