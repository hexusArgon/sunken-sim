# Dragon Sentinel (O00P): модель для sunken-sim

Карта Sunken City v2.5.2b. Код — точное float64 OpenCL-ядро `farm/hybrid/dragon_sentinel_cl.py` (Python-модель `sunken_sim/dragon_sentinel.py` удалена 2026-11-27; до удаления 2760 боёв и 18 доводок заморожены бит-в-бит в `farm/hybrid/fixtures/dragon_sentinel.json`, проверка — `python3.11 -m unittest farm.hybrid.test_fixtures`). Лист: `python3.11 tools/one_slot_gpu.py dragon_sentinel` → `extract/dragon_sentinel-one-slot.json`.
Все числа взяты из war3map.j и данных объектов. Аномалии описаны в `docs/dragon_sentinel-anomalies.md`.

## Лист
- Бой 30 с, 5 целей, броня пустышки 15, герой 6 уровня, способности 1 ранга. Условия как у tinker/tidewarrior/siren.
- Спеки (уровень A0O6 на `udg_Glyphs_Unit[2]`): **Ruby** (1), **Obsidian** (2), **Emerald** (3).
- Голый DPS: Ruby **152.1**, Obsidian **137.3**, Emerald **103.3**.
- В строках таланты (14 считаются, 6 игнорируются), предметы (333, классовые через `pools_for(catalog, "DragonSentinel")`) и глифы (12).
- Классовые предметы (`udg_ClassItems_DragonSentinel`):
  - I0TI Eye of Wyrmrest: генерация Dragonfury ×1.2.
  - I0TH Lifebinder's Helm: частота тиков Lifebinder +0.25.
  - I0TJ Blazewing Guard: +5 брони; снижение урона защитное.
  - I0TK Dragonplate Gauntlets: Burnout ×1.25.
  - I0TL Drake Sword: 15% (30% на крите) × Luck вызвать Dragon Strike.

## Базовые числа
- O00P на 6 уровне: STR 40, AGI 13, INT 21. A0F6 даёт +4 STR и +4 INT, итого STR 44, AGI 13, INT 25.
- Белый урон 13 + 1d1 = 14, плюс 0.75 × STR и урон с предметов.
- Атака: кулдаун 2.00, ближний бой 80.
- Броня: 4 + 0.1 × AGI + предметы, плюс 3 от Draconic Scales.
- HP 300, мана 120 (дальше масштабирование по общей формуле `stats_of`, как у tinker).
- Формы Dragon Form: O007 Ruby, O015 Obsidian (udef 12, +8 брони), O01Q Emerald. Атака в форме хаос, ×1.25 по пустышке без брони.

## Пайплайны урона
Общая формула: `(сырое + Potency × k) × типовой бонус × (Alexstrasza ×1.10 под Lifebinder) × крит + Melting Flames (плоско) → броня цели (с учётом Branded) → execute`.
- Автоатака: физическая, крит 2.0 + rating.
- Заклинания критуют только при spell_crit.
- Каждый недизейзный удар DS:
  - 2% × Luck на +1 Dragonfury (Dragonwrath A0B4);
  - (1 + бонус)% × Luck (×1.15 с Legacy) на пассивный Burnout. Бьёт ×0.40, тип DISEASE, проков не даёт.
- Ruby: +0.5% к шансу пассива за каждый каст.
- Obsidian: бонус +3 Dragonfury за каст убран в v2.5.2b. Branded: цель без клейма получает −min(6, int(1 + 0.08 × броня DS)) брони на 3 с.

## Способности
| Способность | КД / мана | Урон |
|---|---|---|
| Burnout A00B (Ruby, Obsidian) | 8 / 20 | 25 + 1.2 STR за удар, 2 удара по всем в 200, магический. Ruby ×(1.05 + 0.005 M). Ruby Form ×(1 + 0.05 + 0.002 STR). Gauntlets ×1.25. Worldbreaker: 3-й удар ×0.60 (не Obsidian). В форме КД −2. |
| Blazing Strikes (на крите) | — | 33% × Luck: полный Burnout. |
| Dragon Strike A0OB | 7 / 15 | 60 + 0.03 × max HP по линии. Dragonfire 5 с. В форме ×1.25 и Dragon Claw. |
| Blazing Shield A0O1 | 8 / 10 | (50 + 1.1 STR) × (1 + 0.03 × броня) по одной цели. Heated Shield (после Burnout) ×1.25. Explosive Impact: 15% остальным в 250, КД −1. Molten Armor +2 брони на 5 с (Earthen Crust +3 и +2 с). |
| Lifebinder A0N5 | 7 / 15 | Бафф на себя 6 с (+2 с с Alexstrasza). Первый тик через 1 с, затем каждые 1/(1 + 0.15 + 0.008P [Gift of Life] + 0.25 [Helm]) с. Burning Heart: 5 + 3 × уровень = 23 по всем в 250 за тик. |
| Cleansing Fire A0OO (Emerald) | 8 / 20 | B08M 4 с, тик раз в 1 с: 7 + 0.01 × max HP. Каждое лечение DS героя: 8% × Luck на 4 × этот урон случайному врагу. |
| Engulfing Flames I0QI | — | Каждые 1.5/(1 + 0.01 M) с: 5 × ранг + 0.5 × броня по всем в 400. |
| Melting Flames I0B0 | — | +5 к каждому удару по цели с Dragonfire и ещё +5 с Dragon Claw. Ruby: +0.4% / +0.5% max HP. |
| Dragon Form A0HW | 3 / 0 | Нужна полная Dragonfury. Длится 12 с. Ruby: снаряды по 25 два раза в секунду. В 30 с практически недостижима. |

## Игнорируются
- I0JE Ysera's Gift: лечит раненого союзника, в соло эффекта нет.
- I0MF Pacify: контроль.
- I0HQ Backfire: срабатывает от атак врага, а пустышка не атакует.
- I0MQ Lifeblossom: только лечение.
- I0MD, I0MC: страницы талантов.

Считаются, но могут дать 0:
- Earthen Crust, Gift of Life: без Burning Heart Lifebinder урона не даёт.
- Waking Dragon: форма недостижима.
- Dragonborn у Obsidian и Emerald.

## Ротация и политики
- Цикл GCD: касты раньше автоатаки. Порядок: Dragon Form (если шкала полна), Lifebinder, Burnout / Cleansing Fire, Dragon Strike, Blazing Shield.
- Перебираются 2 политики (обе с Dragon Form): Lifebinder на себя да/нет. В строку идёт лучшая. Без формы не считается с 2026-11-13 (см. ниже). С 2026-11-14 вариант с Lifebinder пробуется только при Burning Heart, Alexstrasza или в Emerald: без них Lifebinder урона не даёт (`dragon_sentinel.policies_for`).
- Legacy of the Aspects: на каждом проке (пассивный Burnout, проки Cleansing Fire) самый длинный оставшийся КД −0.75 с.

## Допущения
- Все 5 целей внутри каждой области и линии. DS стоит в зоне Cleansing Fire, поэтому его самолечение даёт прок.
- Burnout приземляется через 0.5 с после точки каста.
- Новый Molten Armor не попадает в урон своего же Blazing Shield.
- Potency от брони (Draconic Scales: 0.5 × броня) считается динамически.
- Melting Flames добавляется плоско после крита, до брони.
- Снаряды Ruby Form: 2 в секунду (в данных нет acdn, взято из подсказки).
- Проки от крита идут через p_crit = crit/100 и детерминированный «дизер».

## Шансы как вероятности и GPU (2026-11-13)

Детерминированные «копилки» шансов (`_Dither`) убраны: каждый шанс — вес удара.
- Dragonwrath (+1 Dragonfury, 2% × удача), пассивный Burnout ((1 + бонус)% × удача), Burnout от крита (33% × удача), Drake Sword, лечение и урон Cleansing Fire у Emerald — вероятности. Бонус шанса Ruby после срабатывания уменьшается на долю срабатывания: `бонус × (1 − p)`.
- Legacy of the Aspects снимает `0,75 × p` с самого долгого кулдауна.
- Dragonfire и Dragon Claw на целях — распределения времени окончания (`death_knight._Buff`); Melting Flames — доля по вероятности.
- Obsidian Branded — записи (окончание, вероятность, броня) на цели; удар клеймит только неклеймёную долю (`_Brand`).
- Burnout_Triggers — вероятности значений 0 / 2 / 3 (Obsidian + Worldbreaker берёт прошлое значение).
- Урон Cleansing Fire от лечения — по случайной цели: каждой цели `p / цели`.
- Battle Frenzy и Silent Messenger — в бою (`sunken_sim/attack_procs.py`), вместо плоских +10%. Удача с предметов — только строки характеристик.

Детерминированная «копилка» теряла хвост шансов в конце боя, поэтому Ruby и Obsidian выросли (медиана +8% и +5%), Emerald почти не изменился.

GPU: `farm/hybrid/dragon_sentinel_cl.py` — точное ядро OpenCL float64 (все 4 политики, лучшая), совпадает с `simulate` бит в бит. Отбор топ-50, в конце топ-20.

## Dragonfury в начале боя (2026-11-13)

Таймер Dragonfury запускается при покупке героя и тикает всё время, в бою и вне боя (+1 каждые `1 / (1 + CDR)` с, пока шкала не полная). Поэтому сим начинает бой с полной шкалой (100, с Waking Dragon 85): Dragon Form выходит в первые секунды. Раньше бой начинался с 0, и за 30 с форма не набиралась ни разу. Медиана по случайным сборкам: Ruby +25%, Obsidian +10%, Emerald +5%.

## Ускорение (2026-11-13)

- Пассивные Burnout, выпавшие в один момент от одного удара (по одному на цель), — одно попадание с суммарным шансом; Burnout_Triggers берёт произведение промахов. Урон тот же (Ruby / Emerald совпадают до 4 знаков).
- Branded хранит 3 записи на цель вместо 8 (случайные сборки Obsidian в пределах −0,02%…+0,04%).
- Политики: только с Dragon Form — (Lifebinder, форма) и (без Lifebinder, форма). На 180 случайных сборках форма выигрывала всегда (без неё минимум на 0,5% / 2,5% / 9,7% хуже у Emerald / Obsidian / Ruby).

## GPU-ядро: ускорения 2026-11-14

- Ядро собирается под каждый спек (`-DSPEC`): поля клейм (Branded) есть только у Obsidian, Cleansing Fire только у Emerald.
- Очередь событий: 16 (Ruby, Obsidian), 8 (Emerald). На 6000 случайных боях на спек максимум 11 / 10 / 4. Переполнение -> status 5 -> строку пересчитывает Python.
- Dragonfire / Dragon Claw обновляются только при Melting Flames (их больше никто не читает).
- Порядок перебора (`farm.catalog._scan_order`): предметы со своей веткой в ядре (`SPECIAL_BITS`) стоят первыми, поэтому соседние строки делят их. Набор сборок и DPS те же, меняется только нумерация чанков.
