# Monk

Общие правила боя, предметов и кулдаунов — в `docs/guide.md`. Здесь Monk карты Sunken City v2.5.2a. Формулы сняты с триггеров `war3map.j` и объектов `w3a/w3u/w3t` (свой парсер `dump_obj.py`).

Сим `sunken_sim/monk.py` считает ожидаемый урон за 30 секунд на ранге 1, 6 уровень, 5 целей, броня 15, без очков навыков. Однослотовый прогон: `python3 extract/one_slot_monk.py` (пишет `extract/monk-one-slot.json`), быстрая проверка: `python3 extract/one_slot_monk.py --smoke`. Ключ пула классовых вещей — `"Monk"`.

## Лист

Monk N04R (ближний бой, тип атаки SIEGE). Сила 24 + 2,4, ловкость 13 + 1,3, интеллект 13 + 1,3. На 6 уровне 36 силы, 19 ловкости, 19 интеллекта. Основной атрибут — сила. Белый удар 13 + 1d1 = 14, плюс `0,75 × сила` (DCS). Взмах 1,85 с. Мана `120 + 7 × интеллект`, здоровье 300 + сила.

Скорость атаки: вещи + 0,4% за ловкость (до +100%), +40% пока активна любая Celestial Stance, +40% Blessing of Xuen (B08G, 6 с), Frenzied Assault `+10% + 1% × Mastery`.

## Панель

Спек — уровень A040 на `udg_Glyphs_Unit[2]`: 1 — Windwalker, 2 — Brewmaster, 3 — Mistweaver.

| Способность | Код | База, ранг 1 | Стойка после каста |
|---|---|---|---|
| Power Strike | A0JS | 6 с, 12 маны; бафф B02D 4 с — следующая атака бьёт Power Strike | Xuen (Way of the Tiger: WW — Chi'Ji, Brew — Niuzao, MW — Yu'lon) |
| Celestial Wrath | A0OM (WW) / A0R7 (Brew) / A0R6 (MW) | 6 с, 12 маны; WW — Wrath of Xuen (B07B 3 с), Brew — Stagger и броня, MW — лечение | Chi'Ji |
| Fortifying Brew | A0IL | 6 с, 12 маны; следующая атака даёт лишний удар, таунт 400 | Niuzao |
| Renewing Mist | A0F7 | 6 с, 12 маны; лечение (в симе — на себя) | Yu'lon |

Global CD: после любого каста остальные способности получают `max(остаток, 1,5 / (1 + CDR))` (1,0 с Legacy of the Emperor). Каст общий: эффект через 0,15 с, ещё 0,30 с без атаки.

Celestial Stance: 2 усиленные атаки (3 с Martial Artist). Xuen — каждая настоящая атака бьёт White Tiger; Chi'Ji (Red Crane) — гарантированный крит `×(1 + шанс/100) × (2 + рейтинг)`; Niuzao / Yu'lon — защита / лечение. После последней атаки стойка снимается.

Аватары (`Avatar_Current`) зажигают таланты Avatar of …; первая способность после аватара тратит его:

| Аватар | Power Strike | Fortifying Brew | Renewing Mist |
|---|---|---|---|
| Xuen (I0U6, ставит Power Strike) | — | два White Tiger | Blessing of Xuen: +40% AS 6 с |
| Chi'Ji (I0U8, ставит Celestial Wrath) | White Tiger 0,15 PS, затем PS ×1,40 | броня A0EP | Blessing of Yu'lon: +18% CDR 6 с |
| Niuzao (I0PP, ставит Fortifying Brew) | оглушение | — | снижение урона от заклинаний |

Celestial Wrath любого спека сбрасывает аватар.

## Урон

`PS = (60 × ранг + 10 + сила) × (1 + 0,005 × ловкость)`; в Windwalker ещё `×(1,05 + 0,008 × Mastery)`.

| Источник | Формула | Тип |
|---|---|---|
| Автоатака | DCS + Fists of Fury | атака SIEGE, крит героя |
| Power Strike | PS, одна цель | магия |
| Повтор Windwalker | 40% × удача: через 0,5 с ещё PS × 0,5 | магия |
| Celestial Attack (Xuen) | WW: каждая атака (вне стойки Xuen) — 0,15 PS по цели; Flurry Strikes — ещё одна с 40% × удача | магия |
| White Tiger | `2 × 0,15 PS` по всем в 250 | магия |
| Wrath of Xuen | WW: первая атака под B07B — `20 + сила + 0,5 × урон этой атаки` по всем в 250 | магия |
| Fortifying Brew (удар) | `25 × ранг + 0,5 × DCS` отдельной атакой | атака SIEGE, крит героя |

Inner Harmony: весь урон Monk `+0,2% × min(сила, ловкость, интеллект)`, плюс +5 ко всем атрибутам (A0EI). Fists of Fury копит 10% магического урона Monk (лечение в соло-симе 0), потолок `50 × уровень` = 300, и прибавляет запас к следующей атаке до крита. Warstaff of Chi'Ji: каждый крит снимает 0,3 с с кулдауна Celestial Wrath.

Магические удары критуют только с вещами spell crit (×1,50, ×1,65 по подсказке «65%»).

## Ротация

Приоритет Power Strike → Celestial Wrath → Fortifying Brew → Renewing Mist. Сим перебирает 24 политики и берёт лучшую: держать ли касты, пока у стойки Xuen / Chi'Ji есть усиленные атаки (полностью, не дольше 1,4 / 0,7 с после кулдауна, до двух потраченных атак, только Brew и Mist, никогда); кастовать ли Renewing Mist без аватара Xuen / Chi'Ji; ждать ли Brew перед Celestial Wrath при аватаре Xuen. Аватар Chi'Ji всегда бережётся под Power Strike, аватар Xuen — под Fortifying Brew.

## Таланты

| Талант | Код | Модель |
|---|---|---|
| Avatar of Xuen | I0U6 | Power Strike ставит аватар Xuen (см. таблицу аватаров) |
| Avatar of Niuzao | I0PP | Fortifying Brew ставит Niuzao — только контроль, урона 0 |
| Avatar of Chi'Ji | I0U8 | Celestial Wrath ставит Chi'Ji |
| Martial Artist | I0KW | 3 усиленные атаки вместо 2 |
| Fists of Fury | I0KX | запас 10% магического урона в следующую атаку |
| Way of the Tiger | I0HX | Power Strike ставит стойку спека вместо Xuen |
| Inner Harmony | I0L0 | +5 атрибутов, урон +0,2% за наименьший атрибут |
| Legacy of the Emperor | I0KZ | Global CD 1,0 с |
| Frenzied Assault | I0PQ | +10% + 1% × Mastery скорости атаки |
| Jab | I0PO | каждая 5-я трата стойки — полный Power Strike по цели |
| Flurry Strikes | I0PR | WW: 40% × удача на атаку — ещё Celestial Attack |

Игнорируются: страницы I0MD / I0MC; Avatar of Yu'lon I0U7, Expel Harm I0L2, Coming of Yu'lon I0PN, Rising Mist I04Y (лечение), Drunken Haze I0L1 (замедление и уклонение), Tigereye Brew I0KY (контратака от уклонения), Shado-Pan Teachings I09U (добавка от Stagger, по манекену 0).

## Предметы класса

| Предмет | Код | Эффект в симе |
|---|---|---|
| Xuen's Gaze | I0UA | +25% AS, +10% haste; Power Strike бьёт White Tiger 0,15 PS |
| Warstaff of Chi'Ji | I0UC | +20 урона, +9% крита; крит −0,3 с Celestial Wrath |
| Scepter of Niuzao | I0U9 | только статы (лечение от Stagger не считается) |
| Mistweaver's Bloom | I0UB | только статы (+15% AS) |
| Shoulderpads of Remedy | I0UD | только статы (+7 силы, +7 интеллекта) |

## Голый DPS (5 целей, 30 с)

| Спек | DPS |
|---|---|
| Windwalker | 130,6 |
| Brewmaster | 77,8 |
| Mistweaver | 77,8 |

Brewmaster и Mistweaver совпадают: их Celestial Wrath и бонусы спека — лечение и защита; урона у них нет ни Wrath of Xuen, ни Celestial Attack, ни множителя PS.

Лучшие таланты одним слотом: Avatar of Xuen (164,1 / 115,0 / 115,0), Inner Harmony (148,6 / 87,7 / 87,7), Avatar of Chi'Ji (144,6 / 92,4 / 92,4). Way of the Tiger снижает урон (104,8 / 42,5 / 42,5). Классовые вещи: Xuen's Gaze 166,2 / 110,0 / 110,0, Warstaff of Chi'Ji 156,1 / 95,0 / 95,0.

## Допущения

- Цели стоят в радиусе 250 — White Tiger и Wrath of Xuen бьют все 5.
- Шансы считаются ожиданием (повтор WW, Flurry); крит — ожиданием, кроме Red Crane.
- Renewing Mist кастуется на себя; лечение, Stagger, таунт и оглушение не считаются.
- Множитель типа атаки SIEGE против брони манекена не моделируется — как у других классов, только броня 15.
- Глифы Arc Striking, Blood Violence, Hellfire, Thunder в сим не заведены (как у Warrior / Hunter) — равны голому.

Аномалии — `docs/monk-anomalies.md`.
