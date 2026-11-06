# Tinker (N03Y)

## Лист
`extract/tinker-one-slot.json` — один слот: таланты (16 оцениваемых из 20), предметы (332: магазин 135, дроп 189, легендарки 8; классовые предметы `udg_ClassItems_Tinker` I0S3–I0S6 в пуле, предметы других классов исключены), глифы (12). Бой 30 с, 5 целей, броня 15, герой 6 уровня, ранг способностей 1. Спеки: Engineering, Demolitions, Nanotech (уровень A0NB на `udg_Glyphs_Unit[2]` = 1/2/3). Код: `sunken_sim/tinker.py`, выгрузка: `extract/one_slot_tinker.py` (`--smoke`). Лог: `/workspace/sunken-ref/tinker-one-slot-run.log`. Аномалии: `docs/tinker-anomalies.md`.

Голый DPS: Engineering 193.6, Demolitions 218.5, Nanotech 184.1.

## Базовые числа
- Герой N03Y (база Ntin). Белые STR 36, AGI 15, INT 24 (6 уровень). Attribute Bonus A0F6 L1 даёт +4 STR и +4 INT бонусом — учитываются (как A0HI у Tidewarrior).
- HP 300, мана 120 + 7 × INT (316 голым). Автоатака 12 + 1d1 = 13 + 0.75 × STR + урон предметов, своп 2.00 (у N03Y нет ua1c — дефолт Ntin), дальность 600, siege (физика). Основной атрибут STR.
- Exosuit N04I (A0A5, только Nanotech; 5 с, 20 маны): те же статы, ближний бой 80. Постоянный переключатель (Exosuit_Timer — только эффекты). Galactic Fury: своп × 1.20.

## Пайплайны урона
- Герой: (сырой + потенция) × типовые бонусы × крит (атаки; заклинания — только со спелл-критом) × броня (15 − пробитие) × execute.
- Гоблины / турели / наноботы: (сырой + потенция) × (1 + Pet Damage [+ мана Tinker / 50 % в Engineering]) × типовые бонусы × (1 + Repeater Cannon / Clockwork Belt) × крит призыва (только атаки) × броня 15 × execute.
- Zap — без NextDamageType: без +% физ./маг. урона вещей.

## Способности
- Pocket Factory A0BR (21 с, 50 маны): гоблин каждые 0.45 с, 2.5 с (5 шт.; 3.0 с и 6 шт. с Advanced Production), живут 21 с. Гоблин 3 + R2I(0.18 × DCS), своп 1.3. Welding Mask −5 с, Advanced Production −3 с.
  - Engineering: Clockwerk n04K, мана 100 (+R2I(10% макс. маны Tinker) с Battery Pack), реген 1/с, появляется с полной маной. Zap A0A3 (60 маны, 5 с) при атаке: 10 + 0.10 × макс. маны Tinker, ×1.30 по Ionized. Атаки гоблинов и турелей +2 + 0.30 × Mastery.
  - Demolitions: Suicide n05R — при первом контакте взрыв 20 + 1.0 × DCS физикой от героя (250, все цели), 50% Napalm.
  - Nanotech: наноботы n04H (A0BZ — без проков и Master Engineer), мана 0 → 100, реген 1/с. Ion Grenade забирает всю их ману в урон.
- Master Engineer A0C1 (Engineering, Demolitions): каждый экземпляр урона героя, гоблинов (не наноботов) или турелей — 1.5% × Luck на гоблина на 10.5 с (если в Clockwerk_Group < 18).
- Ion Grenade A0QQ (15 с, 25 маны; Engineering и Nanotech): 60 + 1.2 × STR + 1.6 × INT + мана наноботов; Nanotech × (1.05 + 0.006 × M); в Exosuit × (1 + 0.004 × STR) × (1 + 0.002 × INT); ×1.25 по Ionized. Магия, 200 вокруг точки, Ionized B070 на 7 с. Каждое попадание Homing Missiles −0.4 с к откату. Unstable Core −3 с.
- Homing Missiles A02T (4 с, 10 маны): 5 ракет (+2 Cluster Rockets, +2 Box of Harmless Tools, + Wrist Launcher; максимум 13, 15 с Box). Ракета 15 + 0.20 × DCS + 0.15 × STR физикой (магией в Exosuit), Demolitions × (1.10 + 0.01 × M). Задержка 0.8–1.2 с (0.4–0.8 с с Rocketpack) + полёт 750/с. Engineering: урон наносит случайная турель (если есть). Demolitions: 20% Napalm.
- Minigun Sentry A00C (5 с, 15 маны): o013 на 20 с, 15 + R2I(0.10 × DCS), своп 1.0, максимум 2 (3 и −1 с с Pocket Turret). Атака турели: 25% × Luck (×1.5 при крите с Target Locking) на одну ракету; Demolitions: 15% Napalm (+5 с Flammable Rounds).
- Reinforce A0C0 (10 с, 25 маны): мана гоблинов/наноботов +15% от максимума (×1.5 с Battery Pack). Лечение, броня и таунт не учитываются.
- Napalm (A0C2, только Demolitions): шанс × 1.25 с Oiled Munition × Luck; повторное наложение под B069 +1 стак; B069 5 с (8 с с Oiled), по спаду стаки сбрасываются. Тик раз в 1.0 с: 5 + 0.25 × DCS + (1 + 0.04 × DCS) × стаки, максимум 75 × уровень (450), физика от героя.
- Таланты: Lightning Rod I0Q5 — любой каст Tinker 30% × Luck: 40 + 1.25 × STR + 1.25 × INT магией по всем; Overclocking I0S2 — атака героя/гоблина/турели 20% × Luck (×1.5 по Ionized или из Exosuit) на +50% AS на 4 с (пока баф висит — без нового прока); Wrist Launcher I0S1 — каждая атака героя 2 × 33% × Luck на +1 ракету в следующий залп; Master Gambler I0S0 — +2% Luck за секунду боя (до 30%); Electric Discharge I0Q1 — раз за бой при касте Exosuit (100 + 4 × STR) × (1 + 0.01 × INT) магией и Ionized; Battery Pack I0N3; Rocketpack I0N7 (быстрее + 4% × Luck на сброс отката при попадании); Target Locking I0N8 (+15 крита турелям); Repeater Cannon I0N2 (+10% урона турелей); Field Repair I0N4 (Reinforce −2 с, +2% макс. маны при смерти гоблина/турели); Advanced Production I0N9; Oiled Munition I0Q3; Unstable Core I0Q2; Cluster Rockets I0EF; Pocket Turret I0Q4; Shieldtronic Gear I0N5 (гоблины n040 с ×0.75 урона — оценивается как потеря).
- Классовые предметы: Flammable Rounds I0S3 (+18 урона, +7% Luck, +5% Napalm турелей — только Demolitions), Welding Mask I0S4 (+9 Mastery, +6 STR, +100 маны, Pocket Factory −5 с), Box of Harmless Tools I0S5 (+23 урона, +7 Mastery, +2 ракеты, лимит 15), Clockwork Belt I0S6 (+16% Pet Damage, +5% Haste, +2 потенции, +30% урона призывов по Ionized).

## Игнорируются
Nano Deconstruction I0N6 (лечение союзника при смертельном уроне), Rocket Boots I0I6 (потенция только в движении), страницы I0MD/I0MC.

## Ротация и политики
Касты до автоатаки. Приоритет: Exosuit (один раз, политика Nanotech) → Pocket Factory → Minigun Sentry (если турелей меньше максимума) → Ion Grenade → Homing Missiles → Reinforce (если есть гоблины/наноботы с маной). Политики (лучшая): Reinforce вкл/выкл × Exosuit вкл/выкл (только Nanotech).

## Допущения
- Цели кучей: Ion Grenade (200), взрыв гоблина (250), Lightning Rod (600), Electric Discharge (300) накрывают все 5 целей. Герой, гоблины и турели бьют цель 1; ракеты делятся по целям по кругу.
- Призывы атакуют сразу после появления; Suicide-гоблин взрывается через 1.0 с (скорость 295, спавн в 100 от героя).
- Задержка Ion Grenade: дальний каст > 200 → 0.70 с; в Exosuit цель в 50–200 → 0.35 с. Ракеты: задержка 1.0 с (0.6 с с Rocketpack) + 600/750 с полёта (100/750 в Exosuit), ракеты турели — 400/750 с.
- Пустышка не Heavy/Hero/Divine: Repeater Cannon +10% (а не +50%).
- Napalm от ракет кладётся на цель ракеты (в карте — устаревший `udg_DamageEventTarget`).
- Шансы — детерминированный dither; урон крита — матожидание. Luck: множитель 1 + Luck (+ Master Gambler).
- Overclocking действует и на призывов; наноботы его не получают (A0BZ).
- Тип атаки siege: таблицы типов атаки/брони у пустышки нет (×1.0).


## Hybrid potency tape reuse (2026-11-07)

Fixed-policy hero and summon hits emit
`(when, name, raw_weight, KIND_EXEC, pot_coeff)`. Damage scoring is
`(raw_weight + potency * pot_coeff) * execute(when)`. This includes goblins,
sentries, turret-owned missiles, Zap, Suicide Goblin, Napalm and Exosuit
hits. Engineering's mana-based pet bonus stays in both channels, with the
same recovery calls and proc counts. `auto_pct` scales both channels, not
hit counts. Potency-independent Fire Orb/Sulfuras events remain four-tuples.

`TinkerFights` generates each unique fixed-policy tape once per hybrid batch.
The key includes Reinforce/Exosuit policy, spec, targets, ordered items,
talents, glyphs, every ESC field except potency_points, and all non-potency
sheet stats. Each original build rescores every eligible policy in CPU
float64 before choosing its winner, preserving CPU policy order and the
`1e-9` DPS tie tolerance. Sharing only a representative's winning policy
would be unsafe. Non-Nanotech rows exclude Exosuit policies, as on CPU.
`generate_tinker_timelines(..., policies=None)` retains the best-policy API;
an explicit aligned policy list requests fixed-policy rows, including when
Sulfuras or step overflow requires CPU fallback.

Crit/luck, mastery, pet damage, timing and mana remain in the key. Potency is
only an additive hit term for a fixed Tinker policy; proc counts, resource
flows and scheduling do not read dealt damage. The generic Ledger scorer,
kindscore packer and symbolic ESC/device path handle the coefficient. The
ESC trace still guards policy selection; a guard failure must fight afresh.
There is no CPU timeline cache. Scheduling remains on CPU Python floats;
DirectML reduces kind scores. No speedup is claimed without a benchmark.

Eligibility caveats for other Ledger heroes: Dragon Sentinel's Gift of Life
changes Lifebinder tick cadence with potency; Windmaster tornado lifetime
and Necromancer Call of the Grave also alter event cadence. Monk's Fists of
Fury caps a damage-dependent accumulator. Death Knight's Virulent Plague
makes Outbreak quadratic. These heroes are not blindly clustered here.

Tests: `farm.hybrid.test_tinker_event_reuse` and
`tools/_parity_tinker_gpu_tl.py` (all three specializations).
