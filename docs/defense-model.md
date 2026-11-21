# Incoming damage on the hero (2.5.2c map) — notes for the defense model

Decided by the user:
- 2026-11-17: each dummy hits for 5% of max HP once per second, dummies 0.2 s apart; heal 75% of max HP every 3 s; HP floor 1.
- 2026-11-20: round(N*122/176) dummies are melee (Normal attack), the rest ranged (Magic attack).
- 2026-11-21: damage reduction is NOT modelled (a hit is exactly 5% of max HP); own temporary reductions are not
  modelled either. All dummies stand right next to the hero. Lifesteal, HP regeneration and healing items are
  ignored unless they change damage dealt (e.g. through an HP-dependent damage effect); then they are counted.
  The pipeline below is kept for reference only.

Monsters on the map (war3map.w3u + placed units, service units with 1 HP excluded; melee = weapon type
"normal", the engine flag UNIT_TYPE_MELEE_ATTACKER):
- melee 60 types / 122 placed (attack types: normal 56, chaos 22, siege 20, pierce 14, hero 8, magic 1);
- ranged 36 types / 54 placed (magic 40, chaos 8, pierce 6, normal 1).

Order of the map's damage pipeline for a hit on a hero (tools/jass_inline.py, tools/jass_rules.py):
1. PreDamage_Reduce (PreDamageEvent 6), attacks only: evasion = 1 - product of hit-chance factors
   (items evtl/rwiz/rump/dust 0.95, I051 0.92, I0BM/I0U9 0.90, I07A 0.88, I07C 0.87, tcas 0.85 at <=30% mana,
   I0IS/I0SU 0.84, I0DL 0.82, I06J 0.82 at low HP, PoG evasion; class: Feral Druid A0C4, Rogue A007,
   DH A0E4 and I04X, Monk Fortifying Brew A0IL, Windmaster B010). On evade: I0BM 50 magic damage back,
   mana/heal items, Monk counter (Fist of the White Tiger), DH Demon Spikes damage, etc.
2. Engine: attack-type table vs Hero armor (war3mapMisc DamageBonus*: Normal 0.85, Magic 0.85, Pierce 0.85,
   Chaos 1.25, Hero 1.25, Siege 1.00), armor reduction 0.04*A/(1+0.04*A) (DefenseArmor=0.04, AGI 0.1 armor).
   Native item abilities: flat "reduces damage taken from attacks by N", Spiked Carapace (AUts) and Thorns
   Aura (AEah) reflect % of melee damage.
3. ArmorDamage_Reduce (ArmorDamageEvent 2): ~60 multiplicative % rules (items, glyphs I0HD/I0HA/I01H/I0EH,
   talents, own buffs), Spell Damage Reduction for spells only, flat DamageFlat_Reduce, absorbs (Ignore Pain,
   Power Word: Shield, Runesword), Stagger, and a floor of 10% of the pre-armor amount.
4. AfterDamage_Global / PreDamage_Enemies: on-damage-taken effects (Berserk I0A2, Axe Mastery I0LO,
   Warlord's Battlemask I0GE, Seal of the Black Empire I09X, Sunstrider Crown I04M, Dragonscale I02Q,
   Shield of Death I0B5, Chaos Shard wneu, Lightning Shield I0GC), lifesteal.
Script reflect of Dragon Sentinel Blazing Shield (A0O1): 5*level + 0.5*armor magical per attack received.

## Berserker: effects of incoming hits (inventory 2026-11-21, map 2.5.2c)

Item pool: 335 items (shop + drop + legendaries, `farm.hybrid.class_cl.full_space`). Source: war3map_norm.j
(`Trig_Hero_Attacked` = EVENT_PLAYER_UNIT_ATTACKED, fires when an attack starts, before evasion;
`Trig_PreDamage_Enemies` = PreDamageEvent 4, before evasion (PreDamageEvent 6); `Trig_OnDamage_Enemies` =
OnDamageEvent 4, after evasion; native item abilities from war3map.w3a + default WC3 ability data).

Order for one dummy attack on the hero:
1. attack starts -> `Hero_Attacked` effects (melee and ranged, evaded or not);
2. PreDamage 4 (`PreDamage_Enemies`, any damage of an enemy with amount >= 0.01, attacks and non-attacks):
   Axe Mastery, Berserk, Warlord's Battlemask, Seal of the Black Empire — also before evasion;
3. PreDamage 6 (`PreDamage_Reduce`): evasion (attacks only); an evaded hit has amount 0;
4. damage lands (5% max HP in our model) -> native reflects (melee only) and `OnDamage_Enemies`
   (amount after evasion): Sunstrider Crown, Dragonscale Aura.

| Effect | Trigger / rule | Damage / value | Type |
|---|---|---|---|
| Spiked Carapace A083 (The Blockade I0BC, Volcanic Shield stre) | native AUts, melee hits | 10% of the melee damage (A083 Uts1 = 0.10; the Volcanic Shield tooltip says 15%); one ability, does not stack | defensive (native) |
| Thorns Aura A0NH (Topaz Amulet I0BD, Ursal's Mighty Plate I0GX, Lament of the Kaldorei I0JK) | native AEah lvl 1, melee hits | 10% (default AEah DataA1 = .1; Topaz tooltip says 5%); same aura, does not stack | defensive (native) |
| Dragonscale Chestplate I02Q (aura B08E) | OnDamage, attacks | 10% of damage taken, to the attacker | spell, untyped |
| Sunstrider Crown I04M | OnDamage, attacks (melee + ranged) | 15% of damage taken, random enemy in 600 | magical |
| Shield of Death I0B5 | attacked, 8% x Luck | 125 to the attacker | spell (DAMAGE_TYPE_MAGIC) |
| Chaos Shard wneu | attacked, every attack | 12 to the attacker | spell (DAMAGE_TYPE_MAGIC) |
| Axe Mastery talent I0LO | PreDamage 4, any enemy damage; 5% x Luck (10% for self-damage), 0.2 s cooldown | axe 20 + 1.25 x DCS | attack-type (existing kernel formula) |
| Berserk talent I0A2 | PreDamage 4: no buff B03J -> stacks 0 + bloodlust A0K9 (6 s); with buff -> stacks + 1 | +12% AS + 3% (2% Fury) per stack | buff |
| Warlord's Battlemask I0GE | PreDamage 4, 8% x Luck | bloodlust A0OE: +28% AS, 6 s | buff |
| Seal of the Black Empire I09X | PreDamage 4, 25% x Luck, below 20 stacks | +1 Mastery per stack (max 20, until combat ends) | buff |
| Plasma-Core Belt I0F2 | attacked | +3 mana | mana |
| Icecrown Ring I015 | attacked | +2 + 0.2% max mana; freezes the attacker 2.5 s (cooldown 20 s, 12 s at low HP) | mana, fewer hits |
| Nerubian Scales I06N | attacked, 5% x Luck | stuns the attacker 1.5 s | fewer hits |
| Evasion items | PreDamage 6, attacks | Jungle Legguards I07A 12%, Shado-Pan Faceguard I07C 13% (+100 spell damage on evade), Gladiator's Insignia I0IS 16%, Dark Veil Mantle I0SU 16%, Cloak of Revan I0DL 18%, Dark Iron Ale I06J 18% at <= 40% HP; multiplicative | — |

HP-dependent damage in the pool (need the hero's HP): Boneslicer (crit + 0.5 x missing HP%), Mask of the Blood
Fanatic I0U5, Shoulderpads of Crimson Fury I024, Immortal Gladiator's Mask arsc, The Furnace I079, Belt of
Living Strength fgun, Bloodhowl I05N, Blade of the Fallen Seraph I00J (also self-damage). Healing that then
counts: lifesteal, HP regeneration and healing-type effects of the build.
