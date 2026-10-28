# Tinker (N03Y) — аномалии карты Sunken City v2.5.2a

1. Герой — N03Y; N04I — форма Exosuit (A0A5, только Nanotech), а не базовый юнит.
2. У N03Y нет ua1c / uagp — своп 2.00 и AGI +1/уровень берутся из дефолтов базы Ntin.
3. Attribute Bonus A0F6: тултип «+3 ко всем статам» (Agility, Intelligence, Strength), данные L1 — +4 STR, +4 INT, AGI 0.
4. Pocket Factory A0BR: тултип «гоблин каждые 0,5 с», данные Nsy1 = 0.45 (5 гоблинов за 2.5 с, 6 за 3.0 с).
5. Napalm требует A0C2 (Demolitions): Flammable Rounds (+5% Napalm турелей) и Oiled Munition в Engineering/Nanotech ничего не дают.
6. Napalm от Homing Missiles кладётся на `udg_DamageEventTarget` — значение от последнего события урона, а не обязательно цель ракеты.
7. Demolitions сохраняет Master Engineer A0C1, и его гоблины — тоже Suicide n05R (с 50% Napalm). В Nanotech A0C1 снимается.
8. Overclock A0B3: Blo1 L1 = 0 — +50% AS даёт только триггер Attack_Speed (B00F).
9. Наноботы n04H появляются с 0 маны; Battery Pack лишь поднимает максимум (+R2I(10% маны Tinker)), не заполняя его.
10. Napalm: тик ограничен 75 × уровень героя (450 на 6 уровне) — в тултипе предела нет.
11. Shieldtronic Gear меняет Clockwerk на n040 с ×0.75 урона (включая Zap).
12. Zap A0A3 наносится без NextDamageType — не получает +% физ./маг. урона предметов.
13. Задержка Ion Grenade зависит от дистанции до точки: ≤ 50 → 0.10 с, ≤ 200 → 0.35 с, иначе 0.70 с.
14. Repeater Cannon: +50% против Heavy/Hero/Divine — тип брони пустышки в данных не определён (модель берёт +10%).
15. Lightning Rod срабатывает на любой каст Tinker, включая Exosuit и Reinforce.
16. Триггер таланта Rocketpack I0N7 называется Box_of_Harmless_Tools (имя от классового предмета I0S5).
17. Homing Missiles в Engineering наносит случайная турель — урон получает Pet Damage, Repeater Cannon, Clockwork Belt и бонус Engineering от маны, но не крит героя.
18. Модель: Unstable Core в Engineering даёт −1.9 DPS — сдвиг ротации/маны (дробный dither), не эффект карты.
