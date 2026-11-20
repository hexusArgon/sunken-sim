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
