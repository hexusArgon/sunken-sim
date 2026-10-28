# Tidewarrior (H01H) — аномалии карты Sunken City v2.5.2a

1. Tidal Strike: путь при крите ≥ 25 использует 80 × ранг, 2.25 × STR и множитель ×0.70, а (1 + AGI/500) — только на часть от STR; обычный путь — 70 × ранг и 2.0 × STR, AGI-множитель на всю сумму.
2. Пассивный шанс Tidal Strike: скрипт 7 + ранг = 8% на 1 ранге против 7% в тултипе. Тултип: «+5% базовой Agility», скрипт берёт полную AGI (0.05) плюс 0.20 × бонусной AGI.
3. Tidal Aura A09X (AOr2): Oae1 = 0.12 — это скорость бега (тултип 10%), Oae2 = 0. Скорость атаки +10% даёт только триггер Attack_Speed (B03G).
4. Serpentine Fury: тултип +35% скорости атаки, скрипт +25% (B02P), Myrmidon ещё +15%. У A0MY Blo1 = 0, всё из триггера.
5. Aspect of the Angler: тултип 5% за крит до 40%, скрипт 0.04 за стак, максимум 8 стаков (32%). Сброс только вне боя.
6. Скопированные тексты: A0JA 3 уровень — текст Vengeance; Serpentine Fury уровни 2–4 — Holy Light; A089 уровни 2+ — Mass Entanglement; A0H2 — Arcane Pulse.
7. У n041 (The One From Below) способность A0A4 Phoenix Fire указана 4 раза — работают ли копии независимо, не ясно (в модели — 4 удара/с, по тултипу).
8. В карте нет `udg_ClassItems_Tidewarrior` — классовых предметов у Tidewarrior нет. I01V Murloc Blade и rots Shugi Staff — общие предметы.
9. Shipwrecker и порог Tidal Strike читают CriticalStrike_Chance, сохранённый с предыдущего удара (крит + 12 от пассивки Serpentine Fury), а не текущий.
10. Call of the Sea: у мурлоков umpi 100 при umpm 60 — стартовая мана обрезается до 60. Мурлоки без таймера жизни (живут до перепризыва).
11. Мурлоки (n03E/n042/n04D) не имеют A0QG — хуки скорости атаки (Tidal Aura, Serpentine) на них не действуют.
