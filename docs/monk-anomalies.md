# Monk (N04R) — аномалии карты Sunken City v2.5.2a

Найдено при разборе `war3map.j` и объектов для `sunken_sim/monk.py`.

1. **Avatar of Xuen + Avatar of Chi'Ji конфликтуют.** `Power_Strike_Cast` с I0U6 обнуляет `PowerStrike_Avatar` и ставит Xuen, поэтому аватар Chi'Ji от Celestial Wrath никогда не даёт Power Strike ×1,40 и White Tiger — он тратится на Fortifying Brew (броня) или Renewing Mist (CDR).
2. **Avatar of Niuzao без урона.** На Power Strike — только оглушение, на Renewing Mist — снижение урона от заклинаний; в одноталантовом прогоне равен голому.
3. **Fortifying Brew под аватаром Chi'Ji — только броня.** Даёт A0EP (+6 брони); бафф B090 в скрипте нигде не читается, урона нет.
4. **Way of the Tiger режет урон.** Power Strike ставит стойку спека вместо Xuen: в WW Red Crane вместо White Tiger по всем целям, в Brew / MW — Niuzao / Yu'lon без урона. В симе −26 DPS WW и −35 DPS Brew / MW.
5. **Brewmaster и Mistweaver одинаковы по урону.** Celestial Wrath A0R7 / A0R6 — Stagger, броня и лечение; бонус PS ×(1,05 + 0,008 × Mastery), Celestial Attack и Flurry Strikes — только Windwalker.
6. **Celestial Attack в WW бьёт и с лишнего удара Fortifying Brew.** PreDamage_Heroes Func028 не проверяет кодовую атаку для ветки WW — удар Brew тоже даёт 0,15 PS и бросок Flurry; White Tiger стойки Xuen (и трата стойки) — только на настоящей атаке.
7. **Power Strike от B02D срабатывает и на ударе Fortifying Brew.** Func024 снимает B02D на любой атаке Monk, включая кодовую.
8. **Fists of Fury копит и лечение.** В OnDamage_Heroes запас пополняется 10% магического урона и лечения Monk; в соло-симе лечение 0. Порядок вложенных событий урона (запас Wrath of Xuen → следующая атака) принят по порядку триггеров.
9. **Shado-Pan Teachings — добавка от Stagger.** `GetPowerStrikeDamage` прибавляет часть накопленного Stagger; по манекену урон не приходит, добавка 0, талант игнорируется.
10. **Warstaff of Chi'Ji: 0,3 с за крит.** Подсказка и скрипт совпадают (Dynamic_CDR вычитает секунды из оставшегося кулдауна Celestial Wrath на каждом событии CriticalStrike).
11. **Классовые вещи на лечение.** Scepter of Niuzao, Mistweaver's Bloom, Shoulderpads of Remedy дают урон только статами.
12. **Renewing Mist — цель.** В соло-симе принят каст на себя: Blessing of Xuen (+40% AS) и Blessing of Yu'lon (+18% CDR) идут герою.
13. **Тип атаки SIEGE.** Автоатака и удар Fortifying Brew — SIEGE; множитель типа против брони манекена не моделируется.
