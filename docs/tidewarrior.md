# Tidewarrior (H01H)

## Лист
`extract/tidewarrior-one-slot.json` — один слот: таланты (11 оцениваемых из 15), предметы (328: магазин 135, дроп 185, легендарки 8; классовых предметов нет — в карте нет `udg_ClassItems_Tidewarrior`, предметы других классов исключены), глифы (12). Бой 30 с, 5 целей, броня 15, герой 6 уровня, ранг способностей 1. Спеки: Myrmidon, Guardian (уровень A0JA = 1/2, `udg_Mastery_Unit`). Код: `sunken_sim/tidewarrior.py`, выгрузка: `extract/one_slot_tidewarrior.py` (`--smoke`). Лог: `/workspace/sunken-ref/tidewarrior-one-slot-run.log`. Аномалии: `docs/tidewarrior-anomalies.md`.

Голый DPS: Myrmidon 154.3, Guardian 164.4.

## Базовые числа
- Белые STR 39, AGI 19, INT 16 (6 уровень). Amplify Damage A0HI L1 даёт +5 STR и +5 AGI бонусом (зелёные) — учитываются. A0PW (Attribute Bonus) не учитывается (как у воина).
- HP 300, мана 120 + 7 × INT, броня 4. Автоатака 22 + 1d1 = 23 + 0.75 × STR + урон предметов («+N Attack Damage» парсится), своп 1.85, siege (физика). Основной атрибут STR.
- Myrmidon: AS_Base_Reduction × 0.95. Galactic Fury: своп × 1.20.
- Крит героя: каждому удару +12 шанса от пассивки Serpentine Fury (A0MD).

## Пайплайны урона
- Герой: (сырой + потенция) × типовые бонусы × (1 + Attack_Increase) × крит (атаки; заклинания — только со спелл-критом) × броня (15 − пробитие − 2 под Mur'gul) × execute × Ocean Pressure.
- Мурлоки / The One From Below: (сырой + потенция) × (1 + Pet Damage) × типовые бонусы × крит призыва (только атаки) × броня (Guardian: −4 под Fear From Below) × execute × Ocean Pressure.
- Coastal Swing: 0.17 × нанесённого по основной цели × (цели − 1), тип ENHANCED (без PreDamage_Increase, без второй брони) — как cleave воина.

## Способности
- Tidal Strike A0BT (6 с, 10 маны, B009 4 с): следующая атака. Сохранённый крит < 25: отдельный магический удар (20 + 70 × ранг + 2 × STR) × (1 + AGI/500). Крит ≥ 25: к атаке +0.70 × [(20 + 80 × ранг) + 2.25 × STR × (1 + AGI/500)] (критует вместе с атакой); с Rising Tides +2 стака Amplify.
- Пассивка Tidal Strike (атаки): шанс 7 + ранг + 0.05 × AGI + 0.20 × бонусной AGI + 0.35 × Mastery (+5 под Fear From Below) на доп. siege-атаку 1.0 × DCS (полноценная атака: стак, Trident, Shipwrecker, cleave, B009; без цепочки).
- Amplify Damage A0HI: атака героя +1 стак (макс. 8; Rising Tides — ещё 35%). Атака мурлока при ≥ 2 стаках тратит 2: (20 + 25 × ранг) + 0.25 × DCS + 0.20 × STR физикой (не атака).
- Tail Slam A0D8 (9 с, 15 маны): 20 + 1.40 × DCS + 0.60 × STR магией по всем, оглушение 1.5 с (A0ED L5, BPSE). Myrmidon: следующая атака +25 + 10 × 6. Guardian: +4 стака (≥ 4 → 8).
- Call of the Sea A0B7 (10 с, 20 маны, канал 0.75 с): 2 постоянных мурлока n03E: 5 + R2I(0.30 × DCS), своп 1.4. Sea Hunter A0K7 (30 маны, 5 с, B03A 10 с): +20 крита призыва; мана мурлока 60/60, реген 1/с. Advanced Evolution I0LI: первый — Mur'gul n042 (своп 1.1, −2 брони на 3 с). Spawn Gorloc I0LH: второй — Gorloc n04D (без Sea Hunter, Frost Armor защитный).
- The One From Below A089 (18 с, 30 маны, канал 0.75 с): n041 на 8 с (Guardian 10 с), 4 × Phoenix Fire A0A4 по 1 удару/с: 3 + 0.15 × DCS атакой призыва. Аура A09Y — Fear From Below (B02R).
- Serpentine Fury A0MD (12 с, 15 маны): B02P на 8 с на себя: +25% AS (+15% Myrmidon).
- Таланты: Magic Trident I0LM — каждая атака героя 15 + 0.20 × STR + 0.05 × макс. маны магией; Shipwrecker I0MI — каждая 5-я атака героя: крит гарантирован, Attack_Increase += 0.01 × шанса крита; Ocean Pressure I0LJ — ×1.30 по оглушённым (BPSE/B011), иначе ×1.10 под Bfro/B02R; Aspect of the Angler I0LN — мурлоки +10 крита, каждый крит мурлока +1 стак (макс. 8) × 4% AS героя; Aspect of the Octopus I0LL — атака мурлока +4 + 0.3 × AGI + 0.3 × INT физикой; Rising Tides I0LK — Tidal Aura (+10% AS через B03G) и 35% на доп. стак; Storm Trident I05I — AS +(1 − HP цели)/5; Treasures of Atlantis I04N — Mastery +10 + 8 × реликвий; Coastal Swing I0MO — см. выше.

## Игнорируются
Ocean Shield I05P (снижение урона), Coral Trident I05G (лечение), Kraken's Lair I05R (срабатывает, когда атакуют героя/мурлоков — пустышка не атакует), Wrath of Azshara I0LG (нужно ≤ 40% своего HP), страницы I0MD/I0MC. Spawn Gorloc I0LH оценивается (потеря DPS).

## Ротация и политики
Касты до автоатаки. Приоритет: Call of the Sea (если нет мурлоков или политика «перепризыв») → The One From Below → Tail Slam → Tidal Strike (если нет заряда) → Serpentine Fury. Политики (лучшая): Serpentine Fury вкл/выкл × перепризыв Call of the Sea по откату вкл/выкл.

## Допущения
- Цели кучей: Tail Slam (250) и аура Fear From Below (300) накрывают все 5 целей; мурлоки и герой бьют цель 1; удары n041 распределяются по целям по кругу.
- Четыре копии A0A4 на n041 бьют по удару в секунду каждая (по тултипу).
- Sea Hunter игрок кастует вручную на самого мурлока, как только баф спал и есть 30 маны.
- B009 всегда тратится следующей атакой (4 с хватает).
- У пустышки нет маны (Aspect of the Octopus без ×1.5).
- Крит для порога Tidal Strike и Shipwrecker — сохранённый CriticalStrike_Chance (крит + 12 от пассивки).
- Шансы (проки Tidal, Rising Tides, стаки Angler) — детерминированный dither; урон крита — матожидание.
- Тип атаки siege: таблицы типов атаки/брони у пустышки нет (×1.0, как у монаха).
