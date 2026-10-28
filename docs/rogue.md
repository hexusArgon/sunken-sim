# Rogue

Общие правила боя, предметов и кулдаунов — в `docs/guide.md`. Здесь Rogue карты Sunken City v2.5.2a. Формулы сняты с триггеров `war3map.j` и объектов `w3a/w3u/w3t`.

Сим `sunken_sim/rogue.py` считает ожидаемый урон за 30 секунд на ранге 1, 6 уровень, 5 целей, броня 15, без очков навыков. Однослотовый прогон: `python3 extract/one_slot_rogue.py` (пишет `extract/rogue-one-slot.json`), быстрая проверка: `python3 extract/one_slot_rogue.py --smoke`.

## Лист

Rogue E005 (ближний бой). Ловкость 30 + 3, сила 10 + 1, интеллект 10 + 1. На 6 уровне 45 ловкости, 15 силы, 15 интеллекта. Основной атрибут — ловкость. Белый удар 30 + 1d1 = 31, плюс `0,75 × ловкость` (DCS). Взмах карта не задаёт — берётся стандарт редактора 1,70 с. Тип атаки normal. Мана `120 + 7 × интеллект`. Здоровье `250 + 15 × сила` плюс `+N Health` с вещей.

Скорость атаки: бонус вещей плюс 0,4% за ловкость (до +100%), потолок от −80% до +400%, плюс Ambush +16% на 6 с после Stealth.

## Панель

Уровень A0KU. 1 — Subtlety, 2 — Combat (Sinister Strike A0FH заменяется на Dispatch A0EQ).

| Способность | Код | База, ранг 1 |
|---|---|---|
| Vendetta | A0FB | 25 с, 0 маны (amcs не задан), +0,4 с follow-through. Метка 4,45 с |
| Sinister Strike | A0FH | 9 с, 18 маны, бафф B01A 4 с на следующую атаку (Subtlety) |
| Dispatch | A0EQ | 9 с, 18 маны, бафф B01Z 4 с на следующую атаку (Combat) |
| Shadowstep | A04G | 9 с (стандарт AOcl, совпадает с подсказкой), 15 маны, одна цель, телепорт за спину |
| Fan of Knives | A0GA | 7 с, 15 маны, радиус 300 — все 5 целей |
| Stealth | A007 | 10 с, 10 маны, невидимость 9 с, Ambush B02E 6 с |
| Rupture | A0JP | пассив |
| Inspect | A0H2 | 5 с, 0 маны, +0,8 с follow-through; кастуется только с Elaborate Planning |

Порядок кнопок: Inspect (если нет баффа Elaborate Planning), Vendetta, Shadowstep, Stealth, Sinister Strike / Dispatch, Fan of Knives, потом автоатака. После Stealth каст держится до атаки из невидимости (любой каст снимает невидимость и бэкстаб). Каст общий: эффект через 0,15 с, ещё 0,30 с герой не атакует.

## Урон

| Источник | Формула | Тип |
|---|---|---|
| Автоатака | `DCS = 31 + 0,75 × AGI + урон вещей`; из невидимости +80 (Owk3) | Physical, крит героя |
| Sinister Strike | следующая атака бьёт ещё раз: `35 + 1,10 × DCS + 0,50 × AGI` | Physical, без крита |
| Dispatch | следующая атака: Attack_Increase `+0,40 + 0,01 × шанс крита`, гарантированный крит | Physical атака |
| Shadowstep | `10 + 90 × ранг + 1,40 × DCS`; под Ambush ×1,20 (×1,50 с Nightstrike) и Ambush снимается | Physical, без крита |
| Fan of Knives | `70 × ранг + 0,75 × DCS` по каждой цели | Physical, без крита |
| Rupture | `10 + 2,25 × DCS`; первая атака или Shadowstep по цели | Subtlety: Physical без крита; Combat: Pierce-атака с критом |
| Vendetta | копит `(50% + 1% × Mastery)` всего урона Rogue по цели за 4,45 с, затем бьёт накопленным | ENHANCED: без бонусов урона и крита, только броня |

Бонусы урона в PreDamage_Increase перемножаются: `DamageIncrease × Physical × Attack_Increase`, потом броня, потом крит (`2 + рейтинг`, только атаки). Пока выучен Sinister Strike (Subtlety), Physical +15%. Potency прибавляется к каждому экземпляру урона.

Vendetta: накопление берёт уже нанесённый урон (после брони и крита). Сброс идёт как ATTACK_NORMAL / DAMAGE_TYPE_ENHANCED — Glass Cannon, Sulfuron, Physical, execute и пробивание брони к нему не применяются. Метка B04N снимается до сброса, поэтому −4 брони Marked for Death сброс не получает.

Предметы класса: Assassin's Shadowguise I0RA — Shadowstep ×1,25; Cutthroat's Shiv I0R9 — Rupture ×1,25; Shadowcraft Belt I0RB — Fan of Knives ×1,25; Bounty Hunter's Blades I0RC — на крите +15 (по цели Vendetta +40) до множителя крита.

## Специализации

| Спек | Уровень | Урон |
|---|---|---|
| Subtlety | 1 | Vendetta +1% за Mastery. Stealth сбрасывает кулдаун Shadowstep. Есть Sinister Strike и его +15% Physical. Rupture — Physical |
| Combat | 2 | Vendetta +1% за Mastery. Dispatch вместо Sinister Strike. Rupture — Pierce-атака (крит, бонусы атак) |

## Таланты

| Талант | Код | Модель |
|---|---|---|
| Phantom Assassin | I0JX | +25% Attack_Increase сзади; в симе — первая атака после Shadowstep |
| Find Weakness | I0JU | +5% крита, −5 брони цели для всего NORMAL-урона Rogue |
| Shadow Dance | I0QE | Stealth даёт повторный Rupture (следующая атака или Shadowstep), Rupture ×1,15 |
| Honor Among Thieves | I0QF | Союзники копят 40% (соло — 0); на сбросе +12% max маны Rogue |
| Combat Potency | I0JV | Каждая атака по цели с Rupture: 8% × Luck (×1,5 на крите) ещё раз Rupture. В Combat Rupture-атака даёт ещё один бросок |
| Paranoia | I0JS | Каждый каст спелла класса при живой Vendetta: `25 + 0,40 × DCS` Physical по цели Vendetta |
| Subterfuge | I0JT | DamageIncrease `+8% + 1% за 50 текущей маны` |
| Vanish | I0QG | Уворот 30% от входящего удара (каждые 0,2 с давления), раз в 4 с: сброс Stealth и +10% max маны |
| Coup de Grace | I0IP | По цели Vendetta: атака 7%, Physical 4% × Luck — бьёт накопленным (ENHANCED), не снимая метку |
| Nightstrike | I0QC | Shadowstep под Ambush ×1,50 вместо ×1,20 |
| Surprise Attack | I0JQ | +15% крита под Ambush, Shadowstep не снимает Ambush |
| Killing Spree | I04V | Shadowstep: DCS ×1,30 на 4 с (сброс от убийства не моделируется) |
| Dirty Tricks | I0JR | Кулдаун Sinister Strike / Dispatch −1 с, Stealth −1,5 с |
| Hidden Blades | I0QD | Каст спелла класса: 35% × Luck — Fan of Knives ×0,5 по всем целям |
| Marked for Death | I0JW | Vendetta −6 с кулдауна, −4 брони цели под меткой |
| Elaborate Planning | I0IR | Inspect даёт +15% DamageIncrease на 10 с |
| Shuriken Storm | I0IT | Каждое попадание Fan of Knives (и Hidden Blades): 8% × Luck сбросить кулдаун Fan of Knives |

Не входят: Cheap Shot I049 (только стан), I0MD / I0MC (страницы).

## Bare DPS (30 с, 5 целей, без вещей и талантов)

| Спек | DPS |
|---|---|
| Subtlety | 146,4 |
| Combat | 120,4 |

Лучшие таланты одним слотом: Hidden Blades (197,2 / 160,2), Find Weakness (169,6 / 140,3), Vanish (169,6 / 135,9). Следом в Subtlety — Elaborate Planning 163,1, в Combat — Combat Potency 133,7.

## Допущения и пробелы модели

- Взмах 1,70 с — стандарт редактора: E005 не задаёт `ua1c`.
- Мана Vendetta 0: `amcs` уровня 1 у A0FB не задан, берётся стандарт ANcl. Кулдаун Shadowstep 9 с — стандарт AOcl, совпадает с подсказкой.
- Шансы считаются ожиданием: Combat Potency, Coup de Grace, Hidden Blades — доля урона; Shuriken Storm и Vanish — накопители срабатываний.
- Phantom Assassin: позицию «сзади» сим даёт только первой атаке после Shadowstep (телепорт ставит Rogue по направлению взгляда цели).
- Paranoia не засчитывается на касте самой Vendetta: порядок триггеров не определён.
- Rogue бьёт цель 0: Rupture один раз на цели 0, плюс Shadow Dance и Combat Potency. Пассивный Fan of Knives от убийства, сброс Killing Spree от убийства, перенос лишнего урона Vendetta при убийстве (A0Q3) не моделируются.
- Shuriken Storm: шанс не делится пополам (уровень врагов считается не ниже половины уровня героя).
- Бэкстаб Stealth и Killing Spree добавляются к DCS целиком; в игре Inner Fire повышает только базовый урон атаки.
- Combat: Shadowstep, вызвавший Rupture-атаку под баффом Dispatch, мог бы забрать Dispatch — не моделируется.
- Таблица типов атаки (Pierce против брони цели) не применяется.
- Fire Orb и Sulfuras в накопление Vendetta не идут. Лечение (Vanish, Hidden Blades) и уворот в DPS не входят.
- Крит берёт шанс крита героя без Luck; Dispatch берёт текущий шанс крита сборки.
