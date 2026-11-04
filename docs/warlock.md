# Warlock (O00A)

## Лист
`extract/warlock-one-slot.json` — один слот: таланты (18), предметы (334: магазин 135, дроп 191, легендарки 8), глифы (12). Бой 30 с, 5 целей, броня 15, герой 6 уровня. Спеки: Demonology, Destruction, Affliction (уровень A0LF = 1/2/3). Код: `sunken_sim/warlock.py`, выгрузка: `extract/one_slot_warlock.py` (`--smoke`).

## Пайплайны урона
- Автоатака: (18 + 0.75 × INT) × 1.35 под Demonwrath + урон предметов (+35 с Drain Soul), тип атаки магический, своп 1.85.
- DCS = 18 + 0.75 × INT + урон предметов, ×1.35 под Demonwrath; Drain Soul в DCS не входит.
- Урон героя: (сырой + потенция + плоский Affliction-бонус по Agony) × типовые бонусы × крит × броня × execute. Крит Destruction/I0TP: +5 + 0.5 × Mastery.
- Демоны: (сырой + потенция + Affliction-бонус) × (1 + Pet Damage + Revel 0.5) × крит призыва × броня 15 (без пробития героя).
- Havoc, клив Demon Rage — ENHANCED (без брони/потенции/крита).

## Способности
- Haunt (7 с, 35 маны, 10 с): тик 10 + 0.15 × INT каждые 1/rate; rate = 1 (+0.05 + 0.005 × Mastery Affliction/I0TP, +0.12 + 0.12 × DCS/100 с I0PK). 20% × удача на Agony за тик. Повтор по цели под Haunt — мгновенно 10 × rate тиков + гарантированная Agony. Броня −2.
- Agony (12 с): тик 5 + 0.10 × INT; шансы наложения: атаки 5%, Siphon 5%, Haunt 20%.
- Summon Felguard (12 с, 40 маны): Immolate (8 с, тик 5 + 0.10 × DCS каждые 1.5/rate, доп. тик крит% × удача) на всех; 2 Felguard в Demonology. Felguard: 7 + int(8 + 0.2 × DCS + 0.02 × maxHP) + 1, своп 1.5, 12 с.
- Backdraft (не Affliction): ((30 при крите, иначе 12) + 0.08 × DCS)% × Luck от атак (Luck добавлен в v2.5.2b), ×0.5 от демонов; 20 + 0.40 × DCS физ. на цель и половина остальным.
- Chaos Bolt (Destruction, 12 с): следующая атака + (75 + 1.5 × DCS) × (1 + 0.01 × крит), хаос, сокращает себе откат на 0.75 с за Backdraft героя.
- Demonwrath (6 с, 10 с): AS +0.15 герою и живым демонам, DCS ×1.35.
- Life Tap (4 с): −175 HP, +70 маны.
- Siphon Life (Affliction, 3 с, канал 6 с): (40 + 0.65 × INT)/4 каждые 0.25/rate по главной цели, блокирует автоатаки.

## Ротация и политики
Приоритет при равной готовности: Felguard → Demonwrath → Haunt → Chaos Bolt → Siphon → Life Tap. Касты проверяются до автоатаки. Demonwrath обновляется только когда спадает или у демона его нет. Siphon канализуется до готовности другой способности. Политики (берётся лучшая): Haunt focus / spread; Life Tap off / mana / always (только при HP > 30% после тапа); Siphon вкл/выкл.

## Допущения
- Уровень цели для Drain Soul = 6. Шансы урона — матожидание, смены состояния (Agony, Imp, Revel, Drain Soul, Grimoire) — детерминированный dither.
- Скорость Rain of Fire берёт статическую скорость атаки героя. Собственный 0.01 урон пустышки не учитывается.
- Модель HP: только Life Tap и лечение Siphon, без регена.

## Не считаются
Лечение (Demonwrath, Backdraft, Siphon союзнику), угроза, страница талантов I0MD/I0MC.

## Голый DPS
Demonology 141.9, Destruction 122.6, Affliction 139.4 (5 целей).

## Лучшие таланты
- Demonology: Rain of Fire 189.9, Incinerate 170.1, Demon Rage 168.5.
- Destruction: Rain of Fire 170.6, Incinerate 151.3, Drain Soul 139.3.
- Affliction: Rain of Fire 178.1, Implosion 171.3, Incinerate 169.3.

Аномалии: [warlock-anomalies.md](warlock-anomalies.md).
