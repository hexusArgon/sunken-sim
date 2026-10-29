# All Pick v2: одинаковые герои (Sunken City v2.5.2a)

Карта: `maps/patched/Sunken City v2.5.2A All Pick v2.w3x` (имя в лобби: **Sunken City v2.5.2A All Pick v2**).
Скрипт: `maps/patched/war3map_all_pick_v2.j`, объектные данные юнитов: `maps/patched/war3map_all_pick_v2.w3u`.

Основа v2 — All Pick (общие кристаллы, свободный слот, античит снят, см. `docs/hero-crystal-pick.md`).

## Пересобрать

```
python tools/patch_hero_crystals.py <оригинальный war3map.j> maps/patched/war3map.j
python tools/patch_anticheat.py maps/patched/war3map.j maps/patched/war3map.j
python tools/patch_spec_slots.py maps/patched/war3map.j maps/patched/war3map.j
python tools/patch_all_pick_v2.py maps/patched/war3map.j maps/patched/_v2_base.j
python tools/patch_spec_per_copy.py maps/patched/_v2_base.j maps/patched/war3map_all_pick_v2.j
python tools/inject_map_script.py "maps/Sunken City v2.5.2a.w3x" maps/patched/war3map_all_pick_v2.j maps/patched/_tmp_v2a.w3x
python tools/patch_w3u_stock.py <war3map.w3u из оригинала> maps/patched/war3map_all_pick_v2.w3u 1
python tools/mpq_replace_file.py maps/patched/_tmp_v2a.w3x war3map.w3u maps/patched/war3map_all_pick_v2.w3u maps/patched/_tmp_v2b.w3x
python tools/set_map_lobby_name.py maps/patched/_tmp_v2b.w3x "Sunken City v2.5.2A All Pick v2" "maps/patched/Sunken City v2.5.2A All Pick v2.w3x"
```

`war3map.w3u` из оригинала достаётся так: `sunken_sim.library._extract(Path(map), 'war3map.w3u')`.

## Что изменилось относительно All Pick

1. **Один класс можно взять до 3 раз.** Покупка отклоняется только когда заняты все 3 слота
   ("All 3 hero slots are full."). `-random` тоже может выдать уже взятый класс.
2. **Кулдауна героя в кристалле больше нет.** У 21 героя, которых продают кристаллы
   (E000 E005 E00A H000 H001 H01H N03T N03Y N04R O000 O005 O009 O00A O00F O00G O00H O00N O00P O00R O00Y U002),
   интервал пополнения стока `usrg` уменьшен с 70 до 1 с. Это поле юнита в `war3map.w3u`, а не в скрипте.
   Задержку старта стока `usst`=3 с не трогали.
3. **Античит снят** так же, как в All Pick (`patch_anticheat.py`).

## Как хранятся копии одного класса

Вся логика карты завязана на глобал `udg_Hero_<Class>` (один герой на класс) и на сотни
глобалов, относящихся к одному классу (стаки, таймеры, дамми, флаги). `patch_all_pick_v2.py`
не переписывает способности, а «переключает» копию:

- `udg_HP_I[c*4+k]` (k=1..`udg_HP_Cnt[c]`) — все копии класса c (21 класс).
- `udg_HP_Cur[c]` — какая копия сейчас «загружена»: она лежит в `udg_Hero_<Class>`, и её
  личные глобалы лежат в обычных переменных. Личные глобалы остальных копий хранятся в
  `udg_HPS_<var>[k]` (массивы — в `udg_HPS_<var>[k*M+i]`). k=0 — снимок значений по умолчанию,
  которым инициализируется новая копия.
- **Личные глобалы класса** (271 переменная) находятся автоматически: это переменные, к которым
  обращаются только функции, достижимые из триггеров одного класса. Берутся integer/real/boolean/
  string/unit/effect/timer/commandbuttoneffect/item и массивы с литеральными индексами ≤32.
  Не переключаются: group и location (общие или временные), счётчики циклов и переменные-индексы,
  массивы с переменными индексами (индексные системы снарядов и т.п.).
- **Таймеры** класса, созданные в `InitGlobals` (28 штук), для 2-й и 3-й копии создаются заново и
  регистрируются на те же триггеры, так что у каждой копии свой таймер.
- `udg_HP_Dup` = true, как только какой-либо класс взят дважды. Пока дублей нет, все проверки
  идут быстрым путём, и поведение совпадает с All Pick.

Как выбирается нужная копия:

- **Сравнения героя.** 401 сравнение `X==udg_Hero_<Class>` / `!=` заменено на `HP_Is_<Class>(X)`:
  если X — другая копия класса, она загружается, и дальше код работает с ней. 53 сравнения
  `GetOwningPlayer(udg_Hero_<Class>)==P` заменены на `HP_OwnIs_<Class>(P)` (копия этого игрока).
  Сравнения с `null`, `GetFilterUnit()` и `GetEnumUnit()` не тронуты.
- **Вход в триггер.** В начало 137 функций условий/действий триггеров с событиями вставлена
  привязка по событию (389 вызовов): юнит события (GetTriggerUnit, цель заклинания, убийца,
  атакующий, призывающий), для урона `DamageEventSource`/`DamageEventTarget`, для таймеров
  истёкший таймер, иначе владелец/игрок события.
- **Периодические пассивки одного героя** (19 триггеров: Ardent_Defender_CD, Berserker_Rage,
  Insanity, Tenacity, Stagger_Periodic, Presence, Primal_Instinct, Ysera_Gift и др.) выполняются
  по разу для каждой копии (`HP_Loop_<Trigger>`).
- **Ожидания.** В 11 функциях с `TriggerSleepAction`/`PolledWait` (15 мест) копия запоминается
  до ожидания и восстанавливается после.
- **Выбор героя.** В `Select_Agi/Str/Int` `set udg_Hero_<Class>=GetSoldUnit()` (21 место)
  заменено на `HP_New_<Class>(GetSoldUnit())`. **Скины** заменяют юнит внутри списка копий
  (`HP_Replace_<Class>`, 3 места).

## Спек у каждой копии свой (`tools/patch_spec_per_copy.py`)

Сам спек и раньше был на слот: уровень спек-способности на `udg_Glyphs_Unit[slot]`, все проверки идут через
`udg_Glyphs_Unit[HP_SlotOf(udg_Hero_X)]`. Общим было отображение, поэтому две копии выглядели как одна:
- `Specialization_Change` (66 вызовов) и `MetamorphosisIcons` / `DivineImageIcon` / `HomingMissilesTooltip` / Tidewarrior `A0HI` /
  Windmaster `A01T` / DS `A0OB`,`A0O1` / Monk `A0FE` / Warlock `A0QX` вызывали `BlzSetAbilityIcon`. Он меняет
  иконку **типа** способности у всех игроков: кнопка спека и зависящие от спека иконки на всех копиях становились одинаковыми;
- мультиборд `Specs_Board_Update` рисовал каждую строку через `BlzGetAbilityIcon('спек')`, поэтому
  у всех копий класса была иконка того, кто переключил последним;
- клик по глифам/талантам привязывался к «первой копии этого игрока», а не к копии своего слота.

Что сделано:
1. `HP_SpecIcon` / `HP_AbIcon` вместо `BlzSetAbilityIcon`. Пока у класса меньше 2 копий, вызов прежний (глобальный).
   Если копий 2+, иконка ставится только на клиенте владельца (`GetLocalPlayer`, это только визуал, не рассинхрон).
2. `udg_HP_SpecIcon[slot]` хранит иконку спека слота, мультиборд читает её (`HP_SpecIconOf`). При создании глифов слота она сбрасывается.
3. Когда берут новую копию уже взятого класса, иконки класса у её владельца сбрасываются на исходные (`HP_IconReset_<Class>`),
   если у этого игрока ещё нет копии класса.
4. `HP_EvE_<Class>`: юнит глифов/талантов слота s сначала привязывает героя слота s (`HP_AuxHero`).

## Остаточные риски (в игре не тестировалось)

- **Массивы по игроку общие.** Если один игрок возьмёт два одинаковых героя, у них общие
  `Shaman_Rogue_Tauren[pid]`, боевые флаги, крит/удача и т.п. по номеру игрока. Самый надёжный
  сценарий — одинаковые герои у разных игроков.
- **Общие группы и индексные системы** (снаряды, Napalm, Homing Missiles, Leap, Burnout и т.п.)
  не разделены по копиям. Эффект, запущенный одной копией, может считаться от «текущей» копии.
- **Триггеры без событий** (вызываются через TriggerExecute) и общие циклы (Health/Mana Regen,
  Check_Combat, CC_Cleanse) работают с той копией, которая загружена в момент вызова. После цикла
  по слотам загруженной остаётся последняя совпавшая копия.
- **Привязка по владельцу** (когда юнит события не сам герой) неоднозначна, если у одного игрока
  две копии класса.
- Логика CDR_Setup по «родному» слоту — те же ограничения, что в All Pick.
- Скрипт проверен pjass (common.j + Blizzard.j: 0 ошибок в war3map_all_pick_v2.j; 147 ошибок
  самого Blizzard.j такие же, как у оригинала), извлечение скрипта и w3u из карты сверено.
  В самой игре не тестировалось.

- Спеки: тултипы (`BlzSetAbility*Tooltip`: Trophies, Blood Presence, Final Service, форма DS, Homing Missiles, тултипы CDR)
  по-прежнему общие на тип способности. Если **один** игрок держит две копии класса, иконки у этих копий общие.
  Проверка «DS в форме дракона» в `Specialization_Change` блокирует смену спека DS всем копиям (так было и в оригинале).
  Таланты с жёстким номером глифов (например `UnitAddAbilityBJ('A060',udg_Glyphs_Unit[3])`) не трогались, это ограничение All Pick.

## Как проверить в игре

1. LAN на 2–3 игрока. Игроки 1 и 2 берут одного и того же героя (например, Demon Hunter) из одного
   кристалла. Покупка не отклоняется, кулдауна у героя в кристалле нет (1 с).
2. Проверить ресурс (Fury и т.п.), кулдауны и пассивки у обеих копий по отдельности.
3. Третий игрок берёт героя: кристаллы исчезают. Теперь все 3 слота заняты.
4. В одиночной игре ввести `iseedeadpeople` / `whosyourdaddy` / `greedisgood 1000`: игра должна
   продолжаться.
