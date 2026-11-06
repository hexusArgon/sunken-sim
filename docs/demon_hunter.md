# Demon Hunter

Общие правила боя, предметов и кулдаунов — в `docs/guide.md`. Здесь Demon Hunter карты Sunken City v2.5.2a. Формулы сняты с триггеров `war3map.j` (блок Demon Hunter: Fury, Metamorphosis, Eye Beam, Leap/The Hunt, Immolation Aura, Collapsing Star, Soul Fragments; PreDamage_Increase, PreDamage_Heroes, OnDamage_Heroes, OnSpellcast_Heroes, Potency_Tooltip) и объектов (`/workspace/sunken-ref/demon_hunter/{abil,talents,unit}_dump.txt`).

Сим `sunken_sim/demon_hunter.py` считает ожидаемый урон за 30 секунд на ранге 1, 6 уровень, 5 целей, броня 15, без очков навыков. Однослотовый прогон: `python3 extract/one_slot_demon_hunter.py` (пишет `extract/demon_hunter-one-slot.json`), быстрая проверка: `python3 extract/one_slot_demon_hunter.py --smoke`. Ключ класса в `search.class_item_codes()` — `DemonHunter`.

## Лист

Demon Hunter E00A, в Metamorphosis — E00B. Сила 12 + 1,2, ловкость 24 + 2,4, интеллект 14 + 1,4: на 6 уровне 18 / 36 / 21. Основной атрибут — ловкость. Белый удар 31 + 1d1 = 32, плюс `0,75 × AGI` (DCS). Взмах 1,70 с. Мана `120 + 7 × INT` = 267. Уклонение в симе 0.

## Специализации

Уровень A0CY: 1 — Havoc, 2 — Vengeance, 3 — Devourer.

| Спек | Что даёт по урону |
|---|---|
| Havoc | Potency `+2` всегда, в Meta ещё `+4 + 0,15 × AGI`; к скейлингу Potency `+0,35`. 8% × удача на каждый удар — +1 Fury. Immolation бьёт второй раз с шансом `(5 + 0,5 × Mastery)%` (без удачи). F = Eye Beam |
| Vengeance | F = Demon Spikes (только отражение). Урона не добавляет; Meta при 0 Fury не кончается — весь бой дальняя Chaos-атака |
| Devourer | В Meta магический урон `× (1,25 + 0,01 × стаки)`. The Hunt `× (1,08 + 0,005 × Mastery)`. Каждый каст (кроме The Hunt) и удар The Hunt роняют Soul Fragment: +5 Fury (подбор мгновенный). F = Collapsing Star |

## Fury и Metamorphosis

Fury — целое, максимум 100, тик раз в секунду. Вне Meta: `+1` (GenerateFury), пока Fury < 25. В Meta при Fury > 0: `−(5 + стаки)`, стак +1; дошло до 0 — Meta кончается, стаки обнуляются. При Fury = 0 тик ничего не делает — Meta длится бесконечно. Demonic Power I0V3: любой прирост Fury удваивается с шансом 25% × удача.

Metamorphosis A0RD: 10 с, 0 маны, жмётся, как только готова и герой не в Meta. В E00B автоатака дальняя, тип Chaos (`× 1,25` по манекену).

## Панель

| Способность | Код | Кулдаун / мана | Урон |
|---|---|---|---|
| Metamorphosis | A0RD | 10 / 0 | — |
| Eye Beam (Havoc) | A0RF | 10 / 25 | 2,5 с канал. Тик каждые `0,5 / (1 + 0,5 × AttackSpeed)`: каждая цель по разу (одна цель — дважды) `7 + 0,15 × DCS` без типа. 25% × удача на удар — Chaos-атака (`× 1,25`, крит, on-attack), общий ICD 0,2 с |
| Demon Spikes (Vengeance) | A0RH | 10 / 25 | только отражение; кастуется лишь ради Chaos Nova |
| Collapsing Star (Devourer) | A0RK | 10 / 25 | через 0,75 с, радиус 275, все цели: `(125 + 2 × AGI) × (1 + 0,003 × (AGI + INT))`, магия |
| The Hunt | A076 | 10 / 15 | `100 + 1,8 × AGI`, магия, одна цель. Thrill: +25% скорости атаки 6 с |
| Immolation Aura | A06F | 10 / 20 | 6 с (9 с Enduring Torment). Тик `1,3 / (1 + Felfire)`; основной бафф и стак-бафф бьют все цели `15 + 0,3 × AGI`, магия. Пассив: каждая атака DH прожигает свою цель той же формулой |
| Inner Demon | A0E4 | 12 / 20 | защитный; кастуется лишь ради Chaos Nova |

Порядок: Meta → F → The Hunt → Immolation → Inner Demon, потом автоатака. Каст общий: эффект через 0,15 с, ещё 0,30 с герой не атакует; на Eye Beam герой занят ещё 2,5 с. Не хватило маны — повтор через 0,25 с.

## Таланты

| Талант | Код | Эффект в симе |
|---|---|---|
| Enduring Torment | I0DA | Immolation 9 с |
| Incubus | I0PC | магический урон `+0,10 + 0,003 × INT` |
| Chaos Blade | I07E | на атаке стак B06M (4 с, не обновляется): `стаки` ударов `10 + 0,1 × DCS` без типа |
| Cosmic Force | I0FL | DamageIncrease `+0,003 × Fury` |
| Consume | I04P | Collapsing Star роняет ещё 3 фрагмента |
| Fallout | I04X | +8 крита (Vengeance — только в Meta); крит снимает 3 брони цели на 4 с |
| Soul Cleave | I07H | +1 Fury за атаку, на крите +3 |
| Felfire | I0FK | тик Immolation быстрее на `0,15 + 0,0012 × AGI` |
| Chaos Nova | I05K | каждый каст DH: `25 + 0,5 × AGI` магией по всем целям |
| Soul Immolation | I0V2 | каждый удар Immolation −0,1 с кулдауна F |
| Throw Glaive | I0PB | крит обычной автоатаки — 50% × удача, Chaos-удар Eye Beam — 20% × удача: глефа `15 + 0,4 × DCS` Chaos-атакой + отскок 50% |
| Singularity | I08D | Collapsing Star: раз на цель `40 + 2 × AGI + 0,1 × MaxMana`; The Hunt — 50% этого каждый раз |
| Void Glaive | I0V1 | базовый взмах `× 0,92` (уклонение 0) |
| Chains of Anguish | I0C5 | атакам `+10%` DamageIncrease |
| Demonic Power | I0V3 | удвоение Fury 25% × удача |

Не моделируются (`IGNORED_TALENTS`): Demonic Wards I05M, Darkness I0PA, Bloodlet I05S, страницы I0MD/I0MC.

## Классовые предметы

| Предмет | Код | Эффект |
|---|---|---|
| Tormentor's Visage | I0V4 | +10 AGI, +7 Mastery, +5% Haste; в Meta `+20%` DamageIncrease |
| Deceiver's Warglaive | I0V5 | +10% Haste, +4 Potency, +4% удачи; The Hunt накладывает Immolation |
| Helm of the Cosmic Destroyer | I0V6 | +12 AGI, +10 INT; Devourer: тик Fury в Meta −1 с кулдауна Collapsing Star |
| Shard of the Dark Naaru | I0V7 | +20% AS, +5 AGI, +3 ко всем; включает эффект Void Glaive без таланта |
| Abyssal Legwraps | I0V8 | фрагменты при смерти врага — в симе нет |
| Demonhide Shoulderpads | I0V9 | лечение Inner Demon — в симе нет |

## Урон

`amount = raw + Potency × ((AttackPotency, если атака, иначе 1) + 0,35 Havoc)`, затем `× DamageIncrease`, затем тип: физика `1 + phys_add` (Chaos `× 1,25`, крит `2 + rating`), магия `1 + magic_add` (+Sulfuron, Spellbinder, Glass; Devourer в Meta), без типа — без бонусов и крита. Дальше броня манекена 15 (Fallout −3) и execute (доля).

## Голый DPS (5 целей, 30 с)

| Havoc | Vengeance | Devourer |
|---|---|---|
| 141,2 | 88,2 | 179,9 |

Лучшие таланты (одним слотом): Chaos Nova (220,2 / 144,3 / 262,5), Incubus (152,1 / 97,0 / 204,6), Singularity (145,7 / 92,5 / 203,5). Прогон: 334 предмета, 15 талантов, 12 глифов.

Аномалии карты — `docs/demon_hunter-anomalies.md`.


## Hybrid potency tape reuse (2026-11-07)

Both `sunken_sim/demon_hunter.py` and the hybrid timeline generator emit
`(when, name, raw_weight, KIND_EXEC, pot_coeff)` for hero hits. Scoring is
`(raw_weight + stats["potency"] * pot_coeff) * execute(when)`. Legacy four-tuples
remain valid for potency-independent Fire Orb and Sulfuras damage. Havoc's +2
and Metamorphosis's additional `4 + 0.15 * AGI` stay in the raw channel; the
Havoc +0.35 potency scale applies to both channels. `auto_pct` scales both
channels without writing a potency-baked FLAT correction.

`DemonHunterFights` generates one tape per safe key within each GPU-timeline
batch, then rescores that tape with each original build's stats. Only
`potency_points` is omitted from ESC fields; item order, talents, glyphs, spec,
target count and all non-potency computed stats remain in the key. Crit and luck
remain baked because proc dithers influence Fallout, Fury and extra attacks;
mastery changes extra Immolation hits, while haste, attack speed and mana can
change scheduling. There is no CPU timeline cache. ESC algebra normalizes the
optional coefficient into a symbolic potency expression before building its
four-tuple device IR.

This reuses work; it is not GPU-native timeline scheduling: the existing
scheduler runs on CPU Python floats and DirectML runs kind-score reduction.
Sulfuras and step overflow retain the CPU fallback. No speedup is claimed
without a benchmark. Regression suite: `farm.hybrid.test_demon_hunter_event_reuse`;
all-spec parity runner: `tools/_parity_dh_gpu_tl.py`.

Death Knight was checked first but not changed: Virulent Plague multiplies
Outbreak by `(1 + (0.12 + 0.005 * potency) * luck_mult)`, while the hit itself
also contains potency. That is quadratic, not the affine coefficient format
used here; it must not be blindly clustered under the same optimization.
