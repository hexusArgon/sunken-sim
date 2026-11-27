# Feral Druid

Общие правила боя, предметов и кулдаунов — в `docs/guide.md`. Здесь Feral Druid карты Sunken City v2.5.2a (отдельный герой от Druid E009). Формулы сняты с триггеров.

Сим — точное float64 OpenCL-ядро `farm/hybrid/feral_druid_cl.py` (Python-модель `sunken_sim/feral_druid.py` удалена 2026-11-27; до удаления 2760 боёв и 18 доводок заморожены бит-в-бит в `farm/hybrid/fixtures/feral_druid.json`, проверка — `python3.11 -m unittest farm.hybrid.test_fixtures`). Ожидаемый урон за 30 секунд, 5 целей, броня 15. Однослотовый прогон: `python3.11 tools/one_slot_gpu.py feral_druid` (пишет `extract/feral-druid-one-slot.json`). Входящие удары манекенов и правки по карте — `docs/defense-model.md`.

## Лист

Feral Druid O00R. Сила 14 + 1,4, ловкость 25 + 2,5, интеллект 11 + 1,1. На 6 уровне 21 сила, 37 ловкости, 16 интеллекта. Белый удар 31 + 1 = 32, плюс `0,75 × ловкость`. Взмах 1,7 с, в Cat Form (O00J) 1,4 с, в Bear Form (O01B) 1,7 с с типом siege. Мана `120 + 7 × интеллект`. Здоровье `250 + 15 × сила`, в Bear Form ещё `180 + 20 × уровень`. Броня `1 + 0,1 × ловкость` плюс броня вещей.

Скорость атаки: бонус вещей плюс 0,4% за ловкость, потолок от −80% до +400%. DCS_Damage — показанный урон атаки, то есть строка силы атаки листа.

## Панель

Уровень A0MP. 1 — Primal (облик Tauren O00R), 2 — Guardian (Bear Form O01B), 3 — Savage (Cat Form O00J). Бой начинается уже в облике своего спека, смена облика не жмётся.

| Способность | База, ранг 1 |
|---|---|
| Swipe, A0MM | 6 с, 15 маны, круг 275 |
| Savage Bite, A0CN | 10 с, 10 маны, одна цель |
| Stampeding Roar, A068 | 12 с, 20 маны, баф 7 с |
| Rake, A0MN | пассив, дебафф A0MO на 4 с |
| Survival Instincts, A0C4 | лечение, в бою не жмётся |

Каст общий: эффект через 0,15 с, ещё 0,30 с герой не атакует и не начинает следующий каст. Кулдаун начинается в момент нажатия. Пять целей стоят в одной точке. Порядок кнопок: Swipe, Savage Bite, Stampeding Roar.

## Специализации

| Спек | Уровень | Урон |
|---|---|---|
| Primal | A0MP = 1 | Ресурс Ferocity: `12 × (1 + Haste) × (1 + 0,01 × Mastery)` в секунду, потолок `100 + Mastery`. Бонусы облика Tauren |
| Guardian | A0MP = 2 | Bear Form: Swipe получает `3%` здоровья. Ferocity только с Grizzly Bear |
| Savage | A0MP = 3 | Cat Form: атаки × `(1,05 + 0,005 × Mastery)`, +10% крита, атаки вешают Rake на цель без него |

## Урон

Ранг 1. Potency, тип урона, крит и броня — общие правила сима. Ниже сырой кусок из триггера, до них.

| Источник | Формула |
|---|---|
| Swipe | `30 + 1,15 × DCS`. Tauren: `+0,55 × ловкость + 0,20 × DCS`. Bear: `+0,03 × здоровье`. Cat: `+0,40 × ловкость`. ×1,15 по цели, у которой % здоровья не выше шанса крита |
| Ferocity на Swipe | При Ferocity ≥ 40 тратит до 80 и даёт × `(1 + 0,01 × потрачено)` |
| Savage Bite | `100 + 1,5 × DCS`. Tauren ×1,25. В облике Bear/Cat вешает Berserk на 5 с |
| Ferocity на Bite | При Ferocity ≥ 40 тратит до 80 (не больше `10 × остаток кулдауна`) и снимает `потрачено / 10` с кулдауна, минимум 0,5 с |
| Berserk | В Cat или с I0Q0: DCS × `1,20`, с I0Q0 в облике ещё +0,15 |
| Rake | Swipe и Bite вешают на 4 с. Тик `10 + 0,10 × DCS`, период `1 / (1 + Haste)`. Tauren: шанс `30% × Luck` на ×1,35 и +2 Ferocity |
| Stampeding Roar | Tauren: +25% потолка Ferocity. Cat: следующая атака `+50 + 1,5 × ловкость` |

Способности физические. Физический бонус типа идёт и в белый удар. Крит способностей — только с вещами spell crit, как у остальных классов.

## Таланты и классовые вещи

Восемнадцать талантов. В урон входят Primal Fury (I0KJ), Razor Claws (I0NO), Savage Roar (I0MN), Maim (I0KL), Feral Frenzy (I0PX), Strength of the Wild (I0PZ), Grizzly Bear (I0RU), Savage Momentum (I0Q0), Rend and Tear (I09M), Son of Ursoc (I0KM), Open Wounds (I0KI), Shred (I0PY), Fresh Wound (I0AE), Lunar Inspiration (I0RT).

Dreamwalker, Guardian of Elune, Survival of the Fittest и Primal Instinct в этом бою урон не поднимают.

Классовые вещи: Ashamane's Claw (Swipe ×1,25), Shapeshifter's Guise (Mastery при смене облика — бой начинается в облике, не считается), Ursoc's Shoulderpads (включает Son of Ursoc), Packleader's Belt (под Roar физический урон +15%), Cenarion Guardian's Stave (оглушение Swipe, урон не поднимает). Пул вещей: класс `FeralDruid`.

Pipe of Deew, Sulfuras и Diamond Ring — как у остальных классов.

## Открытые вопросы

- Siege-атака Bear и тип брони целей (Shred +25% по Hero/Light/Divine) не учтены: таблица типов атаки не применяется, Shred берёт +10%.
- Berserk через Inner Fire сим берёт как множитель ко всему DCS, включая белый удар.

## Изменения 2026-11-14

- Основной атрибут — ловкость: бонус «основного атрибута» с вещей (Sulfuras +20, Nightfall +13 и т.д.) и глиф Fortitude идут в ловкость (`shadow.character(..., primary="agi")`). До этого шли в интеллект. В среднем +9…+13% DPS, на сборках с такими вещами до +60%.
- Battle Frenzy и Silent Messenger — проки боя (`sunken_sim.attack_procs`). До этого не учитывались (лист собирается без запечённых баффов).
- GPU: точное ядро `farm/hybrid/feral_druid_cl.py` (float64, бит в бит с симом, все привязки Diamond Ring).
