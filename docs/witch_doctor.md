# Witch Doctor (O00N)

## Лист
`extract/witch_doctor-one-slot.json` — один слот: таланты (15), предметы (332: магазин 135, дроп 189, легендарки 8), глифы (12). Бой 30 с, 5 целей, броня 15, герой 6 уровня, ранг способностей 1. Спеки: Voodoo, Poison (уровень A0J8 = 1/2). Код: `sunken_sim/witch_doctor.py`, выгрузка: `extract/one_slot_witch_doctor.py` (`--smoke`). Лог: `/workspace/sunken-ref/witch_doctor-one-slot-run.log`.

## Базовые числа
- STR 15, AGI 19, INT 40 (база + 5 × прирост, с округлением вниз). Бонус атрибутов A0PV не учитывается, как A0F6 в других симах.
- HP 230, мана 175 + 7 × INT. Автоатака 10 + 1d1 = 11 + 0.75 × INT + урон предметов, своп 2.0, магическая, дальность 800.
- DCS = 11 + 0.75 × INT + урон предметов.

## Пайплайны урона
- Урон героя: (сырой + потенция) × типовые бонусы × (1 + Hex + Grasp) × крит × броня (15 − пробитие) × execute.
- Призывы (пауки, кобры, тики, жабы Addling, тики Noxious Venom): (сырой + потенция) × (1 + Pet Damage) × (1 + Hex + Grasp) × крит призыва (только атаки) × броня 15.
- Hex I0M8: +4% + 2% за каждый бафф на цели (считаются B082, B084, B028). Grasp I0RN: аура B028 на всех целях, +7% (+12% под B084). Обе суммируются в DamageIncrease и идут отдельным множителем.
- Jungle Fortitude I0BA: Pet Damage + 0.006 × AGI (0.60 × AGI в процентах).

## Способности
- Plague Toad A0PK (5.5 с, 20 маны): BaseDmg = 20 + 60 × ранг + 1.65 × INT. Жаб N = числу врагов в 600, каждая бьёт BaseDmg/N по AoE 150 (185 и ×1.15 с I0M7). Каждая цель получает N экземпляров урона героя (магия, не атака), потенция в каждом.
- Vile Spider A07U (12 с, 30 маны): 2 паука n022 (3 с I0RP) на 12 с. Атака 3 + int(4 × ранг + 0.20 × DCS) + 1, своп 1.5, по главной цели. Каждый паук кастует Noxious Venom A0PL (2 с, 30 маны из 60, B082 на 4 с) и предпочитает цели без баффа.
- Noxious Venom: глобальный таймер 1 с, на каждую цель с B082: 5 × ранг + AGI магией. Источник — случайный юнит VileSpider_Group (живые пауки + пустышка n01F). Widow Venom I0MH: 25% × удача на второй тик. Toxic Bite I0RM: +3 маны пауку за атаку и доп. тик по цели с B082.
- Poison Ward A0LS (только Poison, 12 с, 30 маны, тотем 12 с): на каждый недисиз-экземпляр урона владельца, на каждый тотем — 3% (×1.5 при кобрах ≤ 4, ×1.3 с I0AK от не-героя, × удача). Прок: 50 + 0.10 × макс. мана + INT уроном героя (DISEASE), затем паук с шансом 5% + 0.4 × Mastery, иначе кобра n04C (лимит 6, 8 с I0M5) на 20 с. Кобра: 4 + int(0.10 × DCS) + 1, тики I0M5 (n03J): 4 + int(0.18 × DCS) + 1, хаос.
- Soul Possession A0PJ (25 с, 40 маны, −6 с от I0RR): B084 на главную цель на 12 с (+4 с I0RL). Урон души не считается (атака пустышки неизвестна).
- Poison Dart I0FN: таймер 3 с, 1.0 × DCS + 0.75 × AGI хаосом, считается атакой (крит), DISEASE. Цель — случайная без B082, вешает B082 на 4 с. Каждый недисиз-экземпляр урона владельца: 10% × удача на −0.5 с таймера.
- Addling Toad I0A4: каждый экземпляр урона владельца не-героя — 2.5% (5% от n022 и душ) × удача; жаба бьёт полным BaseDmg (×1.15 с I0M7) по всем целям. Источник — жаба (1 HP): Pet Damage, без крита и без проков.
- Grave Injustice I013: смерть своего призыва в 600 режет остаток откатов всех слотов на 3% (6% для n022 и душ): пауки 6%, кобры 3%, тотем 3%, душа 6%.
- Spirits Unbound I00A: +15 Mastery при мане ≥ 75% (влияет на Spellbinder и шанс паука от тотема).

## Ротация и политики
Касты проверяются до автоатаки. Приоритет при равной готовности: Poison Ward → Vile Spider → Plague Toad → Soul Possession (или жаба раньше паука). Политики (берётся лучшая): Soul Possession вкл/выкл; паук или жаба первым.

## Допущения
- Цели стоят кучей: каждая цель внутри AoE каждой жабы.
- Полёт жабы до цели 1.0 с (данных нет).
- Реген маны паука 0 (в данных нет umpr).
- Тики Noxious Venom на целых секундах, первый дротик в t = 0.
- Урон DISEASE (Poison Dart, прок тотема) берёт физические бонусы предметов.
- Пауки и кобры бьют главную цель. Цель Noxious Venom/дротика — первая без B082.
- Источник тика Noxious Venom взвешен: n / (n + 1) — паук (шанс Addling 5%), остальное — n01F (2.5%).
- На пустышке нет своих баффов для Hex. Тотем не механический (его смерть даёт Grave Injustice).
- Шансы проков и спавнов — детерминированный dither (как в warlock.py).

## Не считаются
Лечение (Voodoo Ward A0GO, Spiritual Touch I0M6), защита (Superstition I0MG, Horrify I09P, снижение урона цели от B082), Soul Harvest A0F3 (кража маны), урон души Soul Possession, Ravenous Spirit I0FM (только души), Tribal Warding I012 (A0PR L1 = 0), страницы I0MD/I0MC.

## Голый DPS
Voodoo 141.2, Poison 190.8 (5 целей).

## Лучшие таланты
- Voodoo: Addling Toad 186.9, Poison Dart 186.3, Mutated Toads 154.9.
- Poison: Addling Toad 266.9, Poison Dart 241.3, Tiki Army 208.0.

## Лучшие предметы и глифы
- Voodoo: Sulfuras 232.6, Elemental Orb (Fire) 227.8, Atiesh 220.4. Глифы: Unsealed Power 160.1, Glass Cannon 157.0.
- Poison: Sulfuras 297.9, Sigil of Al'ar 287.9, Elemental Orb (Fire) 283.4. Глифы: Unsealed Power 215.8, Glass Cannon 211.6.
- Классовые: Black Toad I0RO 186.4 / 252.6, Webmaster's Pendant I0RP 187.7 / 250.7, Idol of the Otherside I0RQ 154.9 / 208.9, Severed Eredar Head I0RR 146.7 / 201.5.


## Fixed-policy potency tape reuse (2026-11-07)

Hero and owner-unit hits emit optional five-tuples
`(when, name, raw_weight, KIND_EXEC, pot_coeff)`. Scoring applies
`(raw_weight + potency * pot_coeff) * execute(when)`; old four-tuples are
unchanged. Fire Orb and Sulfuras remain potency-independent four-tuples.
The source-only `auto_pct` multiplier scales both channels, not proc counts,
resource gains or other sources. Zero raw damage retains a nonzero coefficient.

The hybrid engine generates all four policies for each unique conservative key,
then rescores and selects a winner separately for every original build in CPU
float64, preserving policy order and the CPU `1e-9` DPS tie tolerance. Never
reuse only the representative's winning policy. The key keeps spec, targets,
policy, ordered item rawcodes, talents, glyphs, every ESC field except
`potency_points` and all non-potency sheet stats (without rounding).
Crit/luck, mastery, timing, mana and pet attributes remain baked/keyed.

The timeline API's optional aligned `policies` list requests fixed-policy rows;
omitting it preserves best-policy behavior. Sulfuras and explicit step overflow
fall back to the corresponding CPU fixed policy, not a different winner.
There is no CPU timeline cache. Scheduling remains CPU-side Python; DirectML
reduces packed kind scores. No speedup is claimed without a benchmark.

Shared Ledger/kindscore and ESC algebra/device already support this coefficient.
ESC tracing normalizes five-tuples into its symbolic four-tuple IR and guards
policy decisions; failed guards require a fresh fight. Tests cover old events,
individual/all talents, fresh/reused potency, policy crossovers and near ties,
strict keys, zero/negative auto multipliers, CPU/DirectML and fallback paths:
`farm.hybrid.test_siren_witch_doctor_event_reuse`, plus the hero's official
`tools/_parity_*_gpu_tl.py` for every specialization.

Witch Doctor-specific invariants: Hex/Grasp and chaos multipliers apply to
both channels. Weighted toads/venom preserve owner-proc weights and order;
auto scaling does not scale those proc weights. Spirits Unbound still recovers
mana at the original typed-hit call; mastery thresholds, summon/death schedules,
Grave Injustice cooldown reductions and Poison Dart/ward dithers are independent
of dealt damage for a fixed policy. They remain dependent on other keyed stats.
Existing owner-unit multiplier semantics are preserved.
