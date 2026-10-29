# Общие кристаллы выбора героя (Sunken City v2.5.2a)

Патч скрипта карты (`war3map.j`). Готовая карта: `maps/patched/Sunken City v2.5.2A All Pick.w3x`,
патченный скрипт: `maps/patched/war3map.j`.


Имя в лобби WC3 берётся из `war3map.wts` STRING 1 и имени файла. Сейчас: **Sunken City v2.5.2A All Pick**.

Пересобрать:

```
python tools/patch_hero_crystals.py <оригинальный war3map.j> maps/patched/war3map.j
python tools/patch_anticheat.py maps/patched/war3map.j maps/patched/war3map.j
python tools/inject_map_script.py "maps/Sunken City v2.5.2a.w3x" maps/patched/war3map.j "maps/patched/_tmp.w3x"
python tools/set_map_lobby_name.py "maps/patched/_tmp.w3x" "Sunken City v2.5.2A All Pick" "maps/patched/Sunken City v2.5.2A All Pick.w3x"
```

Версия с одинаковыми героями (All Pick v2) описана в `docs/hero-all-pick-v2.md`.

Оригинальный скрипт достаётся через `sunken_sim.library.map_script()` (в MPQ он без имени).
`inject_map_script.py` пишет новый зашифрованный блок в конец архива, перенаправляет на него
запись в block table и сам проверяет результат обратным извлечением.

## Что изменилось

1. **Кристалл не исчезает после покупки.** `RemoveUnit(GetSellingUnit())` в `Select_Agi/Str/Int`
   заменён на `HP_RemoveCrystalsIfFull()`. Если кристалл был передан игроку через `-random`,
   его владелец возвращается обратно на Neutral Passive.
2. **Когда заняты все 3 слота, исчезают все 3 кристалла** (n01I/n01K/n01L). Одновременно
   выключаются `-random agi/str/int/all`.
3. **Слот выбирается свободный, а не по атрибуту.** Если родной слот атрибута
   (Agi=1, Str=2, Int=3) свободен, герой встаёт туда, иначе в первый свободный. Поэтому можно взять
   2–3 героя одного атрибута (например, трёх ловкачей), и слот первого игрока не перезаписывается.
   Все слотовые массивы (`Agi_Str_Int`, `Glyphs_Unit`, `BackpackUnit`, `Talents_Unit`, `Ability_Q*`,
   `Talents_X`, `Ability_X*`, `CDR_Flat_X`, `CD_Temp_X`, `SpecTooltipBase_X`) заполняются по
   выбранному слоту.
4. **Проверки талантов и спеков героя идут по его реальному слоту.**
   `UnitHasItemOfTypeBJ(udg_Talents_Unit[N],'Ixxx')` (635 мест) и
   `GetUnitAbilityLevelSwapped('Axxx',udg_Glyphs_Unit[N])` (236 мест) теперь смотрят на
   `[HP_SlotOf(udg_Hero_<Class>)]`. Флэт-CDR от талантов в `CDR_Cast_And_Spell_Types` (26 мест)
   записывается в слот героя.
5. **Чтения `udg_PlayerNumber_AGI/STR/INT` вне `Select_*` (117 мест)** заменены на владельца
   героя-класса (`HP_PidOf(udg_Hero_DemonHunter)`, Monk, DragonSentinel, Mage, Shaman, FeralDruid).
   Слотовые чтения (Eye of Discord, Signet of the Swarm, Talent shop) заменены на владельца
   героя в слоте 1/2/3. Присваивания в `Select_*` не тронуты.
6. **`Specs_Board_Update`** проходит циклом по слотам 1..3, пустые пропускает.
7. **Скины** (`Skins_Dialog`/`Skins_Select`) работают с реальным слотом героя.
8. **`-random agi/str/int`** доступен, пока есть свободный слот, и выбирает только ещё не взятый класс.

9. **Читы в одиночной игре больше не «роняют» карту** (`tools/patch_anticheat.py`), см. ниже.

## Читы (iseedeadpeople, whosyourdaddy, greedisgood …)

Карта не падала. Это был встроенный античит, который заканчивал игру поражением. Пять триггеров-детекторов
срабатывают только если игрок 1 не называется `SpasMaster#2487`:

| Триггер | Что ловит |
|---|---|
| `I_see_dead_players` | раз в секунду проверяет, видна ли игроку скрытая ловушка `hmtm_0592` (iseedeadpeople) |
| `I_am_your_daddy` | смерть юнита-ловушки `h00L_0474` от одного удара (whosyourdaddy) |
| `Greed_Is_Not_Good`, `Greed_Is_Not_Good_2` | у Player(3) золото > 150 / дерево > 1 (greedisgood и т.п.) |
| `Synergy_Disable` | у игрока появился второй герой |

Каждый детектор ставил `udg_PlayerTeam_Lives=1` и включал `Execute`. `Execute` раз в секунду писал
"Cheating Detected…", наводил камеры на `nbsw_0240` и убивал `udg_Agi_Str_Int[1..3]`, что давало поражение.

Патч убирает из пяти детекторов по 3 строки наказания (15 строк: lives=1, обновление мультиборда,
`EnableTrigger(gg_trg_Execute)`), а тело `Trig_Execute_Actions` заменяет на
`DisableTrigger(GetTriggeringTrigger())`. Сами детекторы остаются и просто выключаются после
первого срабатывания. Патч применяется и к All Pick, и к All Pick v2.

## Как проверить в игре

1. Запустить `maps/patched/Sunken City v2.5.2A All Pick.w3x` (лучше LAN или 3 слота).
2. Игрок 1 берёт героя из Agility-кристалла: кристалл должен остаться.
3. Игрок 2 берёт другого Agility-героя из того же кристалла: должен появиться второй
   набор (рюкзак, глифы, таланты), и у первого игрока ничего не должно сломаться.
4. Игрок 3 берёт Agility-героя: все три кристалла должны исчезнуть.
5. Повторная покупка уже взятого класса отклоняется сообщением
   "This hero is already taken or all 3 hero slots are full."
6. Проверить окно талантов и CD способностей у героя в «чужом» слоте (например, Demon Hunter
   в слоте 2), а также ресурс (Fury/Ferocity/Stagger/Dragonfury/Cinderflame).

## Известные ограничения

- **В этой версии один и тот же класс дважды взять нельзя.** Это сделано в All Pick v2
  (`docs/hero-all-pick-v2.md`).
- Кулдаун кристалла (stock replenish `usrg`=70 с у 21 героя) в этой версии не менялся. В v2 он 1 с.
- Логика конкретных классов, вшитая в ветку слота внутри `CDR_Setup` (например, Ferocity/Savage Bite
  у Feral Druid в ветке слота 1), а также отдельные места, где класс добавляет или снимает
  небазовые способности на `udg_Glyphs_Unit[1/2/3]` (например, `'A0JN'` в Talent_Disables), всё ещё
  завязаны на родной слот. Для героя в чужом слоте они могут работать приближённо.
- Если героев выбрано меньше трёх, кристаллы остаются.
- Карта проверена парсером pjass (с common.j и Blizzard.j), но в самой игре не тестировалась.
