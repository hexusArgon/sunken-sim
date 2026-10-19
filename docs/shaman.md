# Шаман

Общие правила боя, предметов и кулдаунов — в `docs/guide.md`. Здесь шаман карты Sunken City v2.5.2a. Формулы ниже сняты с триггеров.

Сим `sunken_sim/shaman.py` считает ожидаемый урон за 30 секунд на ранге 1. Однослотовый прогон: `python extract/one_slot_shaman.py`.

## Лист

Юнит O000. Сила 11 + 1,1 за уровень, ловкость 14 + 1,4, интеллект 25 + 2,5. Дробная часть отсекается. На 6 уровне это 16 силы, 21 ловкость, 37 интеллекта.

Белый удар: 12 + один кубик на 1 грань, то есть 13, плюс `0,75 × интеллект`. Базовый взмах 1,85 с. Тип атаки magic: белый удар идёт как магический. Мана `175 + 7 × интеллект`.

Скорость атаки: бонус вещей плюс 0,4% за ловкость, потолок от −80% до +400%.

## Панель

Смена специализации крутит уровень A06Z. Уровень 1 — Restoration, 2 — Enhancement, 3 — Elemental. В Elemental с героя снимается Feral Spirit и надевается Lava Burst.

| Слот | Способность | База, ранг 1 |
|---|---|---|
| Q | Chain Lightning, A037 | 7 с, 20 маны, баф на 4 с |
| W | Lightning Shield, A0AW | 13 с, 25 маны, 8 зарядов, 20 с |
| E | Earth Shield, A08K | лечение, в бою не жмётся |
| R | Totemic Call, A0BY | 16 с, 40 маны, тотем 12 с |
| F | Feral Spirit, A0N8 | 15 с, 35 маны. В Elemental слот занимает Lava Burst |
| F | Lava Burst, A0QF | 8 с, 20 маны, только Elemental |
| D | Chain Heal, A0AX | лечение, в бою не жмётся |

Каст общий: эффект через 0,15 с, ещё 0,30 с герой не атакует и не начинает следующий каст. Кулдаун начинается в момент нажатия. Пять целей стоят в одной точке. Входящий удар медианного моба идёт раз в 0,2 с; Lightning Shield на этих ударах срабатывает не чаще раза в 0,75 с.

## Специализации

| Спек | Уровень A06Z | Урон |
|---|---|---|
| Restoration | 1 | Мастерство поднимает лечение Chain Heal и снижение урона Earth Shield. В исходящий урон не входит |
| Enhancement | 2 | Chain Lightning × `(1,08 + 0,005 × Mastery)`. Шанс Lesser Chain Lightning +10. Тотем пускает Stormfury |
| Elemental | 3 | Lightning Shield × `(1,05 + 0,006 × Mastery)`. Lava Burst × `(1 + 0,008 × Mastery)`. Тотем бьёт магмой |

## Урон

Ранг 1. Potency, тип урона, крит и броня встают общими правилами сима. Ниже сырой кусок из триггера, до них.

| Источник | Формула |
|---|---|
| Chain Lightning | `70 + 1,60 × интеллект` по каждой цели, до 6. Overcharge: основная цель ×1,40 |
| Lesser Chain Lightning | 50% этой формулы, до 3 целей. Шанс с автоатаки: `8 + 0,15 × ловкость`, дальше бонусы спека, вещей и Stormstrike |
| Stormfury | 30% формулы Chain Lightning, до 3 целей. Бьёт с живого тотема Enhancement, когда срабатывает Chain Lightning или Lesser Chain Lightning |
| Lightning Shield | `20 + 0,30 × интеллект`. Заряд тратится на свою атаку и на входящий удар. Входящие не чаще раза в 0,75 с. В Elemental сверху множитель мастерства, со Storm Ward ещё ×1,10 |
| Lava Burst | `100 + 2,50 × интеллект`. Съедает заряды щита: по удару щита за заряд и × `(1 + 0,08 × заряды)` к самому броску |
| Liquid Magma | `20 + 0,50 × интеллект + Mastery` в одну цель раз в 1,5 с, пока тотем Elemental жив |
| Feral Spirit | База духа 8 + целая часть `25%` силы атаки шамана. Взмах 1,4 с, 12 с жизни, двое духов, с Ghost Wolf Shoulderpads трое. Свой крит 10% |
| Thunderstorm | С урона владельца шамана, кроме Disease: `2% × Luck`, затем `30 + 1,80 × интеллект` по врагам в 250 |

Lesser Chain Lightning духов — тот же удар на 3 цели. Шанс 15%, ×1,50 на крите духа и ×1,50 под Storm Infusion. Баф Storm Infusion получают только духи, которые уже живы в момент эффекта Chain Lightning.

## Таланты и классовые вещи

Восемнадцать талантов. В однослотовом прогоне лист `I0MD` / `I0MC` не участвует.

В урон входят Overcharge, Stormstrike, Storm Infusion, Elemental Fusion, Bloodlust, Flash of Lightning, Spirit Call, Totemic Wrath, Totem Mastery, Elemental Fury, Molten Blast, Storm Ward и Thunderstorm.

Elemental Fusion: три разных способности дают +25% урона на 4 с. Bloodlust: 30% × Luck, базовый взмах ×0,82 на 8 с, в Restoration на 5 с. Totemic Wrath: +6 Mastery за тотем и +8% крита, пока тотем жив. Flash of Lightning возвращает заряд с шансом 15% × Luck. Storm Ward даёт +3 к накладываемым и максимальным зарядам. Spirit Call призывает духа каждый 4-й взмах, пока на герое есть Feral Spirit.

Классовые вещи: Epaulets of Ten Storms, Ghost Wolf Shoulderpads, Gloves of Tribal Fury, Helm of Infused Earth, Helmet of Ten Storms, Molten Core Belt, Mulgore Totem. Перчатки включают Bloodlust без таланта. Пояс сбрасывает кулдаун Lava Burst при касте Lightning Shield. Шлем Ten Storms снимает 3 с с Lightning Shield. Mulgore добавляет 4 с к тотему.

Pipe of Deew снимает 1,5 с с баз кулдаунов и после каждого каста держит героя ещё 0,3 с: это ожидание 15% шанса оглушения на 2 с. В эти 0,3 с нет атак и новых кастов. Sulfuras после каста заряжает следующий взмах всплеском на 100% интеллекта по всем целям и с шансом 10% даёт лишний белый удар. Diamond Ring пробует Chain Lightning, Lightning Shield, Totemic Call и кнопку F этого спека, затем оставляет способность с наибольшим DPS и режет её базу кулдауна на 30%.

Landslide, Tidal Waves, Spiritual Guidance, Ancestral Touch и Chain Reaction в этом бою урон не поднимают: лечение, чужие союзники и Chain Heal сим не жмёт.
