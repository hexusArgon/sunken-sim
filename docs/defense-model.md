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

### Berserker: healing and the DamageIncrease pool (2026-11-27)

Decisions: the model heal (75% max HP every 3 s) is a Healing Type heal from the hero itself if the primary
attribute is Intelligence, otherwise from an ally (Berserker: ally). Healing only runs when the hero's health or
Bloodlord's Regalia changes the damage.
- Healing trigger: amount x (1 + received modifiers [Sacred Claymore .15, Husk of Nordrassil .18 (.30 own),
  Bloodlord's Regalia .10, Dragon Figurine .01 per armor (hero armor taken as 0.1 x Agility), The Darkglaive -.30,
  Titan's Breastplate -.50] + own Healing Power for own heals); own heals add Dreamweaver's 8, Fist of the
  Vindicator 5 + 5% Int, Plaguedoctor's 0.5 x Potency. Crimson Fury: Healing Type, regeneration and lifesteal stop at 38%.
- Bloodlord's Regalia: stores 100% of own / 20% of allies' Healing Type healing; every 3 s (after the model heal)
  deals 20% x stored x (1 + 0.06 x level) to every dummy (all are within 500).
- Lifesteal on auto attacks (AfterDamage_Global): item % + Vampiric Aura (Bloodreaver Scythe 13%, Seraph 10%) x
  damage dealt; Edge of the Red Court makes it Healing Type and adds 10 + level; Goredrinker adds
  min(0.5% of 5300, 3% own max HP).
- Regeneration (continuous): "+N Health per second" + Healing Aura 10 + Unholy Aura 5, x (1 + "Increases your
  Health Regeneration by N%" + Dark Iron Ale 1% per 3% missing), + 1% max HP (Shield of Revendreth, Sigil of the
  Ancients); Titan's disables it, Cursed Skull makes it damage. Primalist Ring: +0.5% Physical Type damage per point.
- Healing Type on attacks (Ursoc's Claw 3% max HP, Nathrezim Shiv 10 + 1%, Earthliving, Moon Scythe), on spellcasts
  (Crown of the Highlord, Amber's Gaze, Crusader's Chestplate, Tribal Staff, Seraphim Staff; Holy Scepter plain),
  on hits (Jade Forest Mantle, Gladiator's Insignia on evade, Staff of Idrassil blessing 2% max HP per second for
  5 s after any damage taken); plain: Masochist Mask, Eversong Defender, Seal of Vampirism, Bloodstone's aura.
- DamageIncrease pool: 1 + hero-health entries + Voodoo Doll .03 + Ancient Voodoo Doll (.04 + .02 per other buff on
  the target) + Giantsbane .0075 x target armor. Buffs counted: Venomous Axes, Wounded, Surge of Toxins (the kernel
  tracks no other Berserker debuff windows).
- Approximations: Cursed Skull regeneration damage is not a damage instance; Axe Mastery's 0.2 s cooldown is not
  modelled; Icecrown's freeze timer restarts on the first attack after it is ready, whatever that attack's share.

## Death Knight: incoming hits and healing (inventory 2026-11-27, map 2.5.2c)

Item pool: 336 items (`full_space`), all screened by `tools/one_slot_gpu.py death_knight`. The shared layer
(farm/hybrid/incoming_cl.py) brings every generic item above; class integration in farm/hybrid/death_knight_cl.py.
Strength hero: the model heal comes from an ally (`CLS_INT_HERO 0`); Primalist Ring 0.4% Physical Type per point
of HP regeneration; hero armour for Dragon Figurine / Bloodforged = 3 + 0.1 AGI + item armour (+4 bone shield with
Marrowrend, as in the damage formula).

| Effect | Trigger / rule (war3map_norm.j) | Value | Modelled |
|---|---|---|---|
| Spell health cost | Death Grip, Blood Strike, Frost Strike 10%, Unholy Fury 15% of current HP; `UnitDamageTargetBJ(negm_0344, ...)` | a damage instance taken (PreDamage_Enemies: Battlemask, Seal, Idrassil); lowers HP | yes |
| Blood specialisation heal | `Blood_Specialization` on every DK spell (A0I0 level 2) | 20 + 3% max HP x Blood Tap, own Healing Type | yes |
| Blood Strike heal | `Blood_Strike` | (60 x rank - 40) + 10% max HP x Blood Tap, x2 Siphoning Sword I0NM, own Healing Type | yes |
| Blood Presence | `Presence` every 0.25 s while mana >= drain, HP < 100%, Blood or Death Presence I05O | (8 + 0.25% max HP x max mana / 100) / 4, own | yes |
| Blood Feast I0CU (or Mask of the Blood Hungerer I0NJ) | PreDamage_Heroes, any damage of the DK player | 2 + 0.2% max HP x Blood Tap per instance, own | yes (talent now active) |
| Bloodworms I03W | OnDamage_Heroes, source o01U | heal 50% of the worm hit; healer = the worm (DK player's Healing Power, Bloodlord 20%) | yes |
| Healing received | trigger Healing | Blood glyph level 2: +8% + 0.7% per Mastery; Bloodforged Armor I03X: +5% + 1% per armor | yes |
| Max HP growth | Blood Strike +1 max HP (not after ERW rest) | hits are 5% of the current max HP | yes |
| Presence mana | Plasma-Core Belt / Icecrown Ring mana on hits | Frost / Unholy presence turn mana into damage | yes (shared layer) |
| DamageIncrease pool | PreDamage_Increase, all damage of the DK player except ENHANCED / UNIVERSAL | chill / freeze / Grim Reaper + hero-health entries + Voodoo Dolls + Giantsbane, one additive pool | yes |
| Will of the Necropolis I0G9, Anti-Magic Zone I03G, Maw's 5% spell reduction, bone shield armour | ArmorDamage_Reduce | damage reduction | no (no reduction modelled) |

Notes: Sulfuras echo is DAMAGE_TYPE_ENHANCED and gets no pool (Berserker fixed the same way); Ancient Voodoo
Doll counts the debuffs the kernel tracks (Outbreak, Blood Plague, Chill, Freeze, Marrowrend). Seal of the Black
Empire Mastery feeds Tlum, Frost Strike (Frost), the Outbreak tick rate (Unholy) and the Blood healing bonus.
Approximations: health is the expected health; max HP growth does not raise current HP.
Fire Orb splash fixed 2026-11-27 (user decision): it is DAMAGE_TYPE_NORMAL damage dealt inside
PreDamage_Items_Glyphs, so PreDamage_Increase runs on it — Potency and the Blood Plague flat are added and the whole
DamageIncrease pool (chill / freeze / Grim Reaper + the entries above) applies per target; no type bonus, no crit.
22 frozen fixtures with the Fire Orb are marked "model_fix". One-slot: Elemental Orb (Fire) +1.3 / +1.3 / +6.3.

Blood Feast in the search (user decision 2026-11-27): `farm.top.TALENT_INCLUDE` puts I0CU in every DK talent pool,
`farm.top.ITEM_INCLUDE` adds Bloodlord's Regalia, Mask of the Blood Hungerer and the health items (Crimson Fury,
Immortal Gladiator's Mask, The Furnace, Belt of Living Strength, Bloodhowl, Dark Iron Ale, Icecrown Ring) to the
top-N item pool when they are not in it. The one-slot file has a "combos" table: Blood Feast with each of them and
the talent's gain over the item alone (Bloodlord +33 / +35 / +37; health items -4 .. +6: healing keeps the health
up, which lowers the missing-health bonuses and raises Belt of Living Strength).

One-slot changes (5 targets, top-150 by spec): entered Frost and Blood — Blade of the Fallen Seraph, The Furnace,
Shield of Death, Giantsbane, Ursal's Mighty Plate, Immortal Gladiator's Mask, Ancient Voodoo Doll, Volcanic Shield;
Unholy — the same without Immortal Gladiator's Mask, plus Icecrown Ring, Warlord's Battlemask, Belt of Living
Strength. Talent pools by the screen unchanged (14 / 14 / 15); Blood Feast is added by TALENT_INCLUDE (below).

## Armour penetration and Ice Cleaver (2026-11-27, war3map_norm.j)

ArmorDamage_Increase runs on every damage >= 1 to an enemy. Sources of one branch add up (sequential ifs).
- Item / ability penetration (Gutripper I031 2, Shadow Blade I0QV 2, Elemental Orb (Shadow) I0NT 6, Silent
  Messenger I0QN 3, ability A042 8, class talents) only for DAMAGE_TYPE_NORMAL with attack type Chaos / Hero / Magic /
  Normal / Pierce / Siege: unit attacks and damage dealt with ATTACK_TYPE_MELEE (Axe Mastery). Triggered spells use
  ATTACK_TYPE_NORMAL = Spells (engine id 0) and get none; items are checked on the damage source, so summons get none.
- Voidseeker Hood I07Y (2): Magical Type DAMAGE_TYPE_NORMAL; Iron Cleaver I055 (3): Physical Type DAMAGE_TYPE_NORMAL.
  A second CalculateArmorPenetration on top: amount x m(A-p1) x m(A-p2) / m(A), A = the target's real armour.
- DAMAGE_TYPE_ENHANCED (Sulfuras echo) and DISEASE (Plaguebearer): none. Giantsbane reads the real armour (no penetration).
Models before: the summed item penetration on all damage. Death Knight top builds (all with the Shadow Orb) lose
14-21% after refinement; one-slot Shadow Orb -38 / -36 / -33, Silent Messenger -16 / -15 / -13.

Ice Cleaver lgdh (Item_Glyphs, OnChill / OnFreeze, CC_Hero = the hero): attacks 18% x Luck Ice Nova (250: every
dummy) chill 4 s; every chill 3% and every freeze 6% of max mana as Magical damage to that unit. Counted: Frost Orb,
Ice Nova, Death Knight ghouls / Sindragosa / Frost Strike, Icecrown Ring freezes of attackers (shared layer).
Item-effect damage (reflects, Sunstrider, Shield of Death, Bloodlord, Ice Cleaver) also gets Potency (and the DK Blood
Plague flat) per instance, like any damage of the hero (PreDamage_Increase).

## Demon Hunter: incoming hits and healing (inventory 2026-11-27, map 2.5.2c)

Item pool: 337 items, all screened (`tools/one_slot_gpu.py demon_hunter`). Agility hero (model heal from an ally),
armour 1 + 0.1 AGI + items (E00A / E00B udef 1), Primalist Ring 0.5% Physical Type per point of HP regeneration.

| Effect | Trigger / rule (war3map_norm.j) | Value | Modelled |
|---|---|---|---|
| Evasion | PreDamage_Reduce: Inner Demon A0E4 learned; Fallout I04X outside Vengeance / Meta | hit chance x 0.88; x 0.92 | yes |
| Demon Spikes (Vengeance, A0RH) | PreDamage_Enemies on every attack against the hero (before evasion); PreDamage_Reduce on every evaded attack | 4 + 10% STR + 10% AGI to the attacker, untyped (Spells); x2 while B05N (A0RJ, 6 s after the cast) | yes (source "Demon Spikes") |
| Vengeance healing | PreDamage_Heroes: every damage instance of the DH player; on evade 20 + Mastery | 2 + 0.3% max HP, own Healing Type | yes |
| Vengeance in Meta | trigger Healing: every heal on the hero +4 + 0.5 x armour (before multipliers) | flat | yes |
| Demonsurge (Vengeance) | own Healing Type and lifesteal while Fury < max: 10 + 8 x level -> GenerateFury(1) | Fury in Meta drains 5 + stacks per second and ends the form at 0 (trigger Fury) | yes: Vengeance Meta now ends and is recast |
| Bloodlet I05S | +10% lifesteal (attacks); own Healing Type (after multipliers) + lifesteal >= 40% max HP -> Feast on Blood (A0RG, 7 s): +17 + 3 x level attack damage; the excess is lost | | yes (talent active) |
| Demonhide Shoulderpads I0V9 | Inner Demon restores 25% max HP (own) | evasion x2 while moving: not modelled (the hero stands) | yes |
| Fallout I04X | on evade: faerie fire A0FQ on the attacker (-3 armour, 4 s) | | yes |
| Demonic Wards I05M, Darkness I0PA, Inner Demon reduction | armour / damage reduction | | no |
| Metamorphosis HP % kept on form change; E00B base regeneration 0.25 / s | | | no (same max HP; 0.25 / s left out) |

Shared fixes with this class: Dark Veil Mantle I0SU restores 4% max mana per evaded attack (all classes: Death Knight
one-slot +7.7 / 0 / +9.0); item armour is a shared column; class hooks for evasion, attacked / evaded, own healing,
lifesteal and flat healing. DH damage kinds for penetration: auto attacks, Throw Glaive and the chaos part of Eye
Beam (ATTACK_TYPE_CHAOS) get the item penetration and Iron Cleaver; Magical Type spells Voidseeker; the rest none.
Fire Orb splash goes through the class damage (Potency with the Havoc 1.35 modifier, DamageIncrease, Havoc Fury
procs). One-slot: Vengeance bare 115.6 -> 151.2 (Demon Spikes 43.5 DPS, Meta ends ~every 10 s by Demonsurge);
Bloodlet Vengeance +30; top-150 refinements with the Shadow Orb 11-15% lower (penetration only on attacks).
Speed (CPU pocl, 2^14 builds without such items): Havoc 121k -> 117k rows/s; Vengeance (hits always on) 403k -> 83k.

