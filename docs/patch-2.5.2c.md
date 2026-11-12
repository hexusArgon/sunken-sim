# Sunken City v2.5.2c (апдейт автора, 2026-11-12)

База сима: `maps/Sunken City v2.5.2c.w3x` (`sunken_sim/library.py`, `MAP_PATH`). 2.5.2a и 2.5.2b остаются в `maps/`.

## Что изменилось b → c

Файлы карты: `war3map.j`, `war3map.w3t`, `war3map.w3u`, `war3map.w3i`, `war3map.wts`, `war3map.wpm`,
`war3mapSkin.w3a`, `war3mapSkin.w3t`, `war3mapSkin.txt`. Без изменений: `war3map.w3a`, `war3map.doo` и остальное.

Боевые изменения (скрипт):
- Demon Hunter: Incubus (магический тип) 10% + 0.30 → 0.25 за INT; Collapsing Star 0.03 → 0.02 за 10 AGI+INT.
- Monk: Power Strike — убрана базовая +10; проверка глифа A040 в снижении урона: уровень 1 → 2.
- General's Warhelm: лечение теперь приписывается герою владельца (было — источнику урона).

Прочее: крафт у Illyana (новый предмет I0O7 Sprouting Seed of Idrasill, счётчики Seeds_Rare/Seeds_Epic),
Kilt of Anubisath (добавлен Common-дроп, Uncommon 30% × удача), Belt of Anubisath 5 → 3 атрибута за смерть,
расходник Treasure Bag в тултипе, напоминания о глифах/талантах, рефактор Level Ups, тексты тултипов.

## Влияние на симы

GPU-классы (Mage, Priest, Shaman, Paladin, Druid, Berserker) — без изменений: статы предметов, магазины,
стак-профили, классовые/одиночные предметы и пространства перебора на b и c совпадают
(`epic_codes()` дополнительно содержит I0O7 — материал крафта, в пулы не входит).
Результаты прогонов на b остаются верными для c. Demon Hunter и Monk — CPU-симы, их числа надо поправить отдельно.

## All Pick / All Pick v2 под c

Цепочка та же, что в `docs/hero-all-pick-v2.md` (на исходнике b она воспроизводит B-скрипты байт в байт), плюс
`tools/patch_radius_command.py` для обоих скриптов. Исходный скрипт — безымянный `war3map.j` карты c с
переводами строк `\r\n`/`\r` → `\n`. Итог: `maps/patched/Sunken City v2.5.2C All Pick.w3x` и
`... All Pick v2.w3x` (имя в лобби с буквой C), копии в `Documents\Warcraft III\Maps\Download`.
