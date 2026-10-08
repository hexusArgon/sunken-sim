# Жрец

Общие правила боя, предметов и кулдаунов — в `docs/guide.md`. Здесь только жрец: три специализации, уровень 6, 30 секунд, ожидаемый урон. Полные бои, источники и порядок кнопок — канвас Priest sims.

Все тройки талантов и глифов симятся на надетых вещах, каждое значение крита строит свою очередь кастов. Как набираются предметы — в общем гайде. Таблицы ниже — прошлый прогон, до стака кулдауна ядер, посоха, Touch of the Naaru, казни на весь урон, Potency в Psychic Link и регена маны.

Входящий урон и хил — по общему гайду. Пока здоровье героя 40% или ниже, бонус урона Insanity удваивается. Touch of the Naaru снимает с Mind Spike 0,4 с на каждом ударе Naaru, в Discipline 0,2 с, и сокращает базу Divine Image на 1 с. Answered Prayers сокращает её ещё на 1 с. Без этих талантов база 16 с.

Жрец кастер: топ урона всегда от способностей. Эти вещи в пул не входят: Serathil, Ardite Impaler, Stormforged Axe, Cinderblade, Killmaim, Zandalari Kris, Butterfly, Tuskarr Shank, Windcutter, Band of Flame, General's Warhelm, Warlord's Battlemask, Edge of the Red Court, Blackrock Hammer.

Эти таланты не симить: Prayer of Mending, Divine Empowerment, Echo of Light, Tears of the Gods, Power Word: Shield, Holy Waters.

Dark Evangelism даёт стаки. Жрец лечит сам себя Renew, это лечение союзного героя. Каждый такой тик лечения имеет 8% шанс дать Mind Spike стак, до 10. Каст Mind Spike съедает стаки и бьёт на 10% сильнее за каждый. Smite работает так же от своего Renew: мгновенное лечение при обновлении Renew на себе бьёт врагов в 350 от жреца. В симе все цели боя стоят внутри этого радиуса.

## Кнопки

Приоритет один: обновить Shadow Word: Pain, если дот спадёт в ближайшую секунду, иначе Divine Image, пока Naaru не висит, дальше по списку специализации. Divine Image длится 10 секунд и бьёт раз в секунду. Answered Prayers добавляет удар Naaru на каждый другой каст, пока образ жив.

| Спек | Кнопки |
|---|---|
| Shadow | Shadow Word: Pain, Mind Spike, Void Rift, Divine Image |
| Discipline | Radiance, Shadow Word: Pain, Mind Spike, Divine Image. Renew добавляется, если взят Smite |
| Holy | Mind Spike. Radiance есть на панели только с Empyreal Blaze. Renew добавляется, если взят Smite |

Базы кулдаунов: Shadow Word: Pain 6 с, Mind Spike 8 с, Void Rift 10 с, Divine Image 16 с минус 1 с за Answered Prayers и минус 1 с за Touch of the Naaru, Radiance 8 с, Renew 6 с. Дальше режет общая формула кулдауна.

Мана начинается с максимума, тратится на каст и регенится по общей формуле, пока запас не полный. Void Rift и Radiance в формуле урона берут максимальную ману, как в тексте.

## Урон умений

Множитель мастерства Shadow, `1,10 + 0,006 × Mastery`, стоит только на тике и на мгновенном ударе Shadow Word: Pain и только в Shadow. В Discipline и Holy этот множитель равен 1.

| Умение | База до Potency и типа |
|---|---|
| Тик Shadow Word: Pain | `(15 + 0,30 × интеллект) × мастерство Shadow`. С Psychic Link и база тика, и Potency умножаются на `(1,15 + 0,10 × число целей под дотом)` |
| Удар при обновлении дота | `(75 + 1,50 × интеллект) × мастерство Shadow` |
| Mind Spike | одна цель. Текст: targeted enemy. `(80 + 1,50 × интеллект) × (1 + 0,01 × сила атаки)` |
| Void Rift | враги в зоне разлома, в симе все цели боя. `(85 + 0,15 × максимальная мана) × (1 + 0,007 × интеллект)`. Задержка 2 с, с Cosmic Horrors 1,5 с |
| Naaru | `25 + 0,40 × интеллект`. В Discipline ×0,75 |
| Radiance, Discipline | лечение `120 + 1,20 × интеллект + 0,10 × мана`, затем × `(1,10 + 0,008 × Mastery)`. Урон — 80% этого лечения один раз за каст. Potency прибавляется за каждую цель |
| Empyreal Blaze | в Discipline 8% сохранённого лечения (это уже 60% от масштабированного лечения) раз в секунду по каждой цели. В Holy 4% сырого лечения, без множителя Mastery. Окно 4 с, с Blinding Light 6 с |
| Smite | `50 + 0,80 × интеллект + 0,80 × сила` по каждому врагу в 350 от цели Renew. В симе все цели боя стоят внутри этого радиуса |

Пока висит дебафф Empyreal Blaze, урон жреца умножается на `1,05 + 0,0008 × сила`.

Dark Torment вешает Shadow Word: Pain с Mind Spike на первую цель. В Holy кнопки Shadow Word: Pain нет, и талант урон не добавляет. Psychic Link удлиняет дот с 10 до 12 секунд. Cosmic Horrors с шансом 25% обновляет дот по целям, которых Void Rift задел и на которых дот уже висит.

Длительность Renew в симе 9 секунд. Лечение само по себе в DPS не входит. Renew жрец кладёт на себя. Smite срабатывает, когда это Renew обновляют до окончания. Dark Evangelism считает эти же лечения источником стаков.

## Глифы, которые доходят до урона

Unsealed Power +18% магического и физического типа. Glass Cannon ×1,15 после Insanity и Catharsis, и столько же физическому типу. Animosity +12% крита и +15% к урону крита. Clairvoyance +8% крита. Fortitude +4 интеллекта и ещё +2 за уровень, на 6 уровне это +16. Supremacy +20 Mastery. Mindhaste +7% спешки и 0,2 с плоского среза.

Thunder: 18% на каст, удар `35 + 200% интеллекта` по каждой цели, магический тип. Hellfire раз в 1,25 с: `3 + 3 × уровень`, ×2 по одной цели, ×1 по двум-трём, ×0,5 по четырём и больше. Hellfire не проходит множитель магического типа, на него влияет Glass Cannon. Blood Violence: 3% на каждое событие урона, `20 + 160% интеллекта`.

Заклинания критуют только с Nightfall (×1,65) или Netherspike (×1,50).

## Что поиск берёт

Insanity есть в каждой теневой и дисциплинарной сборке. В Holy на одной-трёх целях с лавкой третьим талантом остаётся Clairvoyance, с четырёх целей и на дропе — Insanity.

Очки почти всегда уходят в Potency, пять штук. Крит берётся, когда сборка уже открыла крит заклинаний или набрала шанс с Animosity и Clairvoyance. Mastery, пять очков, выигрывает только у Shadow на 2–4 целях в смешанном пуле, рядом с Psychic Link. Luck не берётся ни разу: для жреца это пустое очко.

Глифы Unsealed Power и Glass Cannon стоят почти везде. Thunder сменяет Animosity, когда целей становится три и больше. Fortitude остаётся на бедном дропе в одну цель.

По вещам повтор один. Ядра Unbound Power Core дают +55 интеллекта и +12% кулдауна с каждой копии. Atiesh — легендарка магического типа, +20% входит в урон. The Darkglaive и Staff of Galactic Fury кладут +30% магического типа, это тоже входит. Посох умножает базовый кулдаун атаки на 1,20. Elemental Orb в прошлом прогоне Shadow и Discipline оставался в режиме Shadow, игнор 6 брони. В Holy на 4–5 целях сфера была Fire: всплеск 20 + 35% основного атрибута по каждой цели. Harness of Beyond, The Zircon Star, Pipe of Deew и Cursed Skull держали дроп-сборки. Nightfall нужен там, где выигрывает крит заклинаний.

## Лучший найденный бой

DPS — ожидаемый урон прошлого прогона, делённый на 30. Если в скобках смешанный пул ниже лавки, тот прогон не дошёл до лавочного комплекта.

### Shadow

| Цели | DPS | Таланты | Глифы | Очки | Вещи |
|---|---:|---|---|---|---|
| 1 | 1173.2 | Catharsis, Insanity, Clairvoyance | Unsealed Power, Animosity, Glass Cannon | крит 5 | 4× Unbound Power Core, Nightfall, Staff of Galactic Fury |
| 2 | 1670.5 лавка (смешанный 1593.5) | Psychic Link, Catharsis, Insanity | Unsealed Power, Animosity, Glass Cannon | Potency 5 | 3× Unbound Power Core, Atiesh, Elemental Orb, Orb of Unstable Magic |
| 3 | 2017.0 | Psychic Link, Dark Torment, Insanity | Unsealed Power, Animosity, Glass Cannon | Mastery 5 | 3× Unbound Power Core, Atiesh, The Darkglaive, Staff of Galactic Fury |
| 4 | 2413.7 | Psychic Link, Dark Torment, Insanity | Unsealed Power, Thunder, Glass Cannon | Mastery 5 | Razorwind, 3× Unbound Power Core, Atiesh, The Darkglaive |
| 5 | 2676.1 | Psychic Link, Dark Torment, Insanity | Unsealed Power, Thunder, Glass Cannon | Potency 5 | Razorwind, Atiesh, 3× Unbound Power Core, The Darkglaive |

С трёх целей связка одна: Psychic Link, Dark Torment, Insanity. На одной цели дот не размножается, и поиск оставляет Catharsis с критом.

Дроп на пяти целях — 1932.3: те же таланты, Unsealed Power, Thunder, Glass Cannon, Potency 5, Atiesh, Harness of Beyond, The Darkglaive, Cursed Skull, Nightborne Scepter, Pipe of Deew.

### Discipline

| Цели | DPS | Таланты | Глифы | Очки | Вещи |
|---|---:|---|---|---|---|
| 1 | 1122.6 | Psychic Link, Catharsis, Insanity | Unsealed Power, Animosity, Glass Cannon | крит 5 | 3× Unbound Power Core, Nightfall, Aruzal, Elemental Orb |
| 2 | 1434.7 лавка (смешанный 1283.8) | Psychic Link, Empyreal Blaze, Insanity | Unsealed Power, Thunder, Glass Cannon | Potency 5 | Atiesh, Elemental Orb, Orb of Unstable Magic, 2× Unbound Power Core, Staff of Galactic Fury |
| 3 | 1731.9 | Dark Torment, Smite, Insanity | Unsealed Power, Thunder, Glass Cannon | Potency 5 | Atiesh, 2× Unbound Power Core, The Darkglaive, Diamond Ring, Elemental Orb |
| 4 | 1782.1 лавка (смешанный 1755.4) | Dark Torment, Smite, Insanity | Unsealed Power, Thunder, Glass Cannon | Potency 5 | Elemental Orb, Razorwind, Staff of Galactic Fury, 2× Unbound Power Core, Atiesh |
| 5 | 1707.0 лавка (смешанный 1669.7) | Smite, Empyreal Blaze, Insanity | Unsealed Power, Thunder, Animosity | крит 5 | 2× Razorwind, Staff of Galactic Fury, Atiesh, Predaplant Thorn, Nightfall |

На пяти целях цифра прошлого прогона ниже, чем на четырёх. База Radiance от числа целей не растёт: текст делит урон поровну. Potency, Smite, Thunder и тик Blaze растут с числом целей. Просев дал набор с двумя Razorwind вместо ядер. Это результат того прогона, не свойство пятой цели.

Diamond Ring на трёх целях в смешанном пуле привязывает Mind Spike.

Дроп на пяти целях — 1585.8: Smite, Empyreal Blaze, Insanity, Unsealed Power, Thunder, Glass Cannon, Potency 5, Atiesh, The Darkglaive, Harness of Beyond, Cursed Skull, Qiraji Talisman, The Zircon Star.

### Holy

Лавка и смешанный пул здесь совпали на всех пяти клетках. Урон кнопками дают Mind Spike, Smite и тик Empyreal Blaze. Без Empyreal Blaze Radiance в симе не бьёт, и поиск берёт этот талант во всех 15 боях. Smite тоже во всех 15.

| Цели | DPS | Третий талант | Глифы | Очки | Вещи |
|---|---:|---|---|---|---|
| 1 | 672.1 | Clairvoyance | Unsealed Power, Animosity, Glass Cannon | крит 5 | Aruzal, Silent Messenger, Ardite Impaler, Nightfall, 2× Unbound Power Core |
| 2 | 724.2 | Clairvoyance | Unsealed Power, Animosity, Glass Cannon | крит 5 | Aruzal, Silent Messenger, Ardite Impaler, Nightfall, Elemental Orb, Unbound Power Core |
| 3 | 825.2 | Clairvoyance | Unsealed Power, Thunder, Animosity | крит 5 | Elemental Orb, Nightfall, 2× Unbound Power Core, Aruzal, Silent Messenger |
| 4 | 1090.6 | Insanity | Unsealed Power, Thunder, Glass Cannon | Potency 5 | Elemental Orb (Fire), 4× Unbound Power Core, Staff of Galactic Fury |
| 5 | 1263.7 | Insanity | Unsealed Power, Thunder, Glass Cannon | Potency 5 | Elemental Orb (Fire), Staff of Galactic Fury, 4× Unbound Power Core |

На одной-трёх целях сборка автоатака и крит: Aruzal, Nightfall, реликвии крита. С четырёх целей интеллект ядер и огненный всплеск обгоняют этот крит.

Дроп на пяти целях — 975.3: Smite, Empyreal Blaze, Insanity, Unsealed Power, Thunder, Glass Cannon, Potency 5, Atiesh, The Darkglaive, The Zircon Star, Pipe of Deew, Manual of Dark Arts, Harness of Beyond. Призыв с Manual of Dark Arts в урон не входит, сим берёт статы книги.

## Как читать разрыв спек

На пяти целях в прошлом прогоне Shadow 2676, Discipline 1707, Holy 1264. Mind Spike бьёт одну цель. По всем целям боя идут Void Rift, Smite, Thunder, тик Empyreal Blaze и Potency у Radiance. База урона Radiance одна на каст и делится текстом «split evenly». У Holy из панели в урон остаётся Mind Spike, пока нет Empyreal Blaze, а с ним тик вдвое слабее дисциплинарного и без множителя Mastery.
