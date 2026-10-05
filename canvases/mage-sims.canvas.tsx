import {
  BarChart,
  Callout,
  Divider,
  Grid,
  H1,
  H2,
  H3,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
  useCanvasState,
} from "cursor/canvas";

const TALENTS: Array<[string, string, boolean]> = [["Pyromaniac", "Grants you 3 Potency (+5% of Intelligence).", true], ["Amplification", "Reduces the cooldown of Arcane Blast by 2 seconds.", true], ["Ice Lance", "Casting a spell hurls an Ice Lance towards a random nearby enemy unit, dealing 20 (+50% Intelligence) Magical damage and Chilling the target hit for 4 seconds. Prioritizes non-Chilled targets.", true], ["Supernova", "If Arcane Blast targets an enemy above 90% health, gravity will collapse around it, dealing 50/100/150/200 Magical damage (+300% of Intelligence) to all nearby enemies. Has 10% chance to trigger on enemies at or below 90% health.\n\nValues scale with Arcane Blast level.", true], ["Ice Shards", "Increases the damage of Blizzard by 20% and its damage reduction by 30%.", true], ["Firestarter", "Allows Fire Bomb to trigger on enemies unaffected by Living Bomb and it deals 25% more damage.", true], ["Archmage", "Increases all Intelligence scalings by 35%, multiplicatively.\n\nOnly affects scalings of Mage Abilities and Talents.", true], ["Freezeburn", "Applying Living Bomb also Chills the target for 4 seconds. Applying Chill has 20% chance to apply Living Bomb, reduced to 8% against already Chilled targets. This effect cannot chain.\n\nLiving Bomb has to be learned for its debuff to be applied.", true], ["Lava Spawn", "While you control less than 10 Hydras, dealing damage from any source has 2% chance to spawn a Hydra that lasts half as long.\n\nHydra stats and effects can be found in the Customization Menu (F8).", true], ["Burning Fury", "Hydras last for 4 additional seconds and their cleave now also triggers onto the primary target.", true], ["Runemastery", "Spellcasts other than Arcane Pulse have 25% chance to grant the Mage Rune of Lesser Restoration. The proc chance is increased by 50%, multiplicatively, while in Frost Specialization.\n\nAll Rune healing is now done by the Mage and becomes Healing Type.", true], ["Frostbite", "Chilled enemies take 8% more damage, increased to 12% for Frozen enemies.\n\nApplying Chill on unaffected enemies Freezes them for 1,5 seconds.", true], ["Greater Pyroblast", "Increases the Intelligence scaling of Pyroblast by additional 2% and it now deals Magical damage, but will only fire while at or above 50 Cinderflame.", true], ["Overpowered", "You also benefit from all Spell Mastery effects, regardless of current Specialization.", true], ["Frostfire Bolt", "Arcane Blast also hurls a Frostfire Bolt at the target which deals 20 Magical damage (+90% of Intelligence). Each level of Living Bomb and Ring of Frost increase the damage dealt by 25.\n\nIf the target has Chill, deals 25% more damage and 15% of the damage to other nearby enemies. If the target has Living Bomb, deals 25% more damage and Freezes for 2 seconds. If the target has both debuffs, they’re consumed to fire another Frostfire Bolt after a 0,5 second delay.", true], ["Arcane Surge", "Arcane Blast’s Arcane effect now grants 2 Stacks per cast while below 3 Stacks and the maximum amount of stacks is increased to 8.", true], ["Blazing Soul", "Living Bomb now ticks 15% faster (+50% of Potency) and has additional 15% chance to burst.", true], ["Cold Splinters", "Whenever you Chill an enemy, you restore 0,5% of maximum mana and gain 2 Mastery, up to a maximum of 30 Mastery. Freezing triggers this effect at 200% effectiveness. Mastery bonus resets upon leaving combat.", true]];

const GLYPHS: Array<[string, string, boolean]> = [["Animosity", "Offensive Glyph\nGrants you 12% Critical Strike chance and increases the damage dealt by Critical Strikes by 15%.", true], ["Arc Striking", "Utility Glyph\nEach of your attacks reduces the remaining cooldown of your Q ability by 8% plus additional 0,25 seconds. Your Q spellcasts refund 40% of their mana cost.", true], ["Astral Shift", "Defensive Glyph\nReduces any damage taken by 1% for every 4% of missing health.", true], ["Battle Frenzy", "Offensive Glyph\nGives your attacks 18% chance to grant you 32% Attack Speed for 5 seconds. Battle Frenzy must wear off before occuring again.", true], ["Beastfury", "Offensive Glyph\nYour summons spawn with 25% Critical Strike chance.", true], ["Blood Violence", "Offensive Glyph\nDealing damage from any source has 3% chance to cause the enemy flesh to explode, dealing 20 Attrition damage (+160% of Primary Attribute).", true], ["Bloodthirst", "Defensive Glyph\nCauses your hero to restore health equal to 10% of any damage dealt.", true], ["Class Mastery", "Utility Glyph\nAfter casting your Q hotkey ability, your hero will gain Class Mastery for 4 seconds, which provides one of the following effects depending on his primary attribute:\n\n• Strength: increases Armor by 4 and upon taking damage your hero restores 3 health plus 12% of all mitigated damage to the lowest health hero. This is a Healing Type effect.\n• Agility: increases damage dealt from all sources by 20%.\n• Intelligence: instantly restores 8% of maximum mana and then regenerates 0,5% of maximum mana each second.\n\nClass Mastery must wear off before occuring again.", true], ["Fortune", "Utility Glyph\nIncreases your Luck by additional 15%.", true], ["Commandership", "Utility Glyph\nGrants you 20% Pet Damage and reduces the damage taken by your summons by 12%.", true], ["Crippling", "Support Glyph\nYour attacks apply Cripple on the target for 4 seconds, which reduces the damage dealt by attacks by 20% and Movement Speed by 25%.", true], ["Dampening", "Defenisve Glyph\nGrants you 20% Spell Damage Reduction.", true], ["Deep Healing", "Support Glyph\nIncreases your Healing Power by additional 20%.", true], ["Devotion", "Support Glyph\nYour Healing Type spellcasts cause all nearby allies to regenerate 0,75 mana per second, increased by amount equal to 0,4% of their maximum mana for 4 seconds.", true], ["Diamond Skin", "Defensive Glyph\nReduces damage taken from attacks by 10%.", true], ["Fortitude", "Utility Glyph\nBoosts your Primary Attribute by 4 and additional 2 per Hero Level.", true], ["Glass Cannon", "Offensive Glyph\nMultiplicatively increases damage dealt from all sources by 15%, but all of your units take 10% more damage.", true], ["Hellfire", "Offensive Glyph\nDeals 3 damage and additional amount equal to 3 times your hero level to all enemy units within 400 range every 1,25 seconds. Damage dealt is modified based on the amount of targets hit:\n\n• 1 enemy: 200% damage\n• 2-3 enemies: 100% damage\n• 4+ enemies: 50% damage", true], ["Lightforce", "Defensive Glyph\nTaking damage while below 70% of maximum health shields the hero with holy energy, making him invulnerable for 4 seconds. This effect cannot occur more than once every 35 seconds. Invulnerable heroes will be ignored by enemy units.", true], ["Magic Find", "Support Glyph\nIncreases item drop chances from all enemy units by 20% for the party and increases the odds of enemies dropping higher quality items. This Glyph stacks with other player's Magic Find Glyphs.", true], ["Mana Shield", "Defensive Glyph\nReduces any damage taken by amount equal to 2% of your maximum mana.", true], ["Mindhaste", "Utility Glyph\nIncreases your Haste by 7% and reduces the cooldown of all abilities by 0,2 seconds.", true], ["Protecting", "Support Glyph\nReduces the damage taken by allied heroes by 12%, but increases the damage your hero takes by 10%. Damage reduction does not stack across multiple Glyphs of Protecting.", true], ["Provoking", "Support Glyph\nIncreases the duration of your Taunting effects by 25% and reduces the damage taunted enemies deal by 7%.", true], ["Recovery", "Defensive Glyph\nGrants you 2 Health per second (+0,75% of maximum Health). Also causes Health Regeneration to become a Healing Type effect.", true], ["Renewal", "Support Glyph\nYour spellcasts have 40% chance to restore 40 health (+130% of Primary Attribute) to all friendly units within 700 range. This is a Healing Type effect.", true], ["Replenishment", "Utility Glyph\nCauses you to regenerate 1,5 mana (+0,75% of maximum Mana) each second.", true], ["Siphoning", "Defensive Glyph\nWhenever another hero gets healed by a Healing Type effect, you restore health equal to 25% of the healed amount. Overhealing amount is not applied to this effect.", true], ["Supremacy", "Utility Glyph\nIncreases your Mastery by 20.", true], ["Thunder", "Offensive Glyph\nYour spellcasts have 18% chance to call down lightnings that deal 35 (+200% of Primary Attribute) to enemy units within 600 range.", true], ["Trepidation", "Support Glyph\nAffects enemies in 600 range with Trepidation Aura, which causes them to take 8% more damage from allied units, not including your own units. This effect does not stack.", true], ["Unsealed Power", "Offensive Glyph\nIncreases the damage dealt by Magical and Physical Type effects by 18%.", true]];

type SpecId = "Frost" | "Arcane" | "Fire";
type RunId = "mixed" | "shop" | "drop";
type TargetCount = 1 | 2 | 3 | 4 | 5;

type Run = {
  label: string;
  dps: string;
  total: string;
  crit: string;
  intel: string;
  manaLeft: string;
  talents: string[];
  glyphs: string[];
  points: string;
  sources: Array<[string, number]>;
  actions: Array<[string, string]>;
  stats: Array<[string, string]>;
  items: Array<[string, string, string]>;
};

const RUNS: Record<string, Run> = {
  "Frost|5|mixed": {
    label: "Shop + drop",
    dps: "2913.8",
    total: "87413",
    crit: "0%",
    intel: "251",
    manaLeft: "78%",
    talents: ["Archmage", "Overpowered", "Lava Spawn"],
    glyphs: ["Hellfire", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 0, Luck 5, Mastery 0",
    sources: [["Pyroblast", 599.3], ["Blizzard", 564.2], ["Ring of Frost", 361.1], ["Thunder", 243.2], ["Hydra", 237.4], ["Всплеск огня", 202.2], ["Клив Hydra", 190.0], ["Living Bomb", 167.5], ["Arcane Blast", 133.3], ["Взрыв Living Bomb", 99.5], ["Автоатака", 85.9], ["Hellfire", 30.2]],
    actions: [["0.00", "Living Bomb"], ["0.45", "Blizzard"], ["0.90", "Arcane Blast"], ["1.35", "Ring of Frost"], ["8.22", "Living Bomb"], ["8.67", "Arcane Blast"], ["13.04", "Blizzard"], ["13.49", "Ring of Frost"], ["16.25", "Living Bomb"], ["16.70", "Arcane Blast"], ["24.27", "Living Bomb"], ["24.72", "Blizzard"], ["25.17", "Arcane Blast"], ["25.62", "Ring of Frost"]],
    stats: [["Очки навыков", "крит 0, Potency 0, Luck 5, Mastery 0"], ["Сила атаки", "199.2"], ["Potency", "0.0"], ["Mastery", "10"], ["Рейтинг крита", "0.00"], ["Спешка", "18.0%"], ["Скорость атаки", "24.6%"], ["Мана", "2182"], ["Интервал атаки", "1.61 с"], ["Тик Living Bomb", "0.75 с"], ["Elemental Orb", "Fire"]],
    items: [["Elemental Orb", "Shop Item", "+15% Attack Speed\n+10% Haste\n+6 All Stats\nUse: Switches between 1 of 3 Orb Powers. (Cooldown: 5 seconds)\nFire: Attacks splash for 20 damage and additional 35% of Primary Attribute.\nFrost: Attacks Chill the target, reducing its movement speed by 50% and its attack speed by 25% for 4 seconds.\nShadow: Attacks ignore 6 of the target's Armor."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["The Darkglaive", "Random drop", "+12 to Primary Attribute\n+8% Haste\n+6 Agility\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Reduces the effectiveness of Healing Type effects on your hero by 30%."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."]],
  },
  "Frost|5|shop": {
    label: "Только Shop Item",
    dps: "2759.4",
    total: "82782",
    crit: "0%",
    intel: "145",
    manaLeft: "49%",
    talents: ["Archmage", "Overpowered", "Lava Spawn"],
    glyphs: ["Hellfire", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 0, Luck 5, Mastery 0",
    sources: [["Blizzard", 598.1], ["Pyroblast", 584.9], ["Ring of Frost", 307.9], ["Thunder", 242.6], ["Hydra", 194.1], ["Всплеск огня", 191.6], ["Клив Hydra", 155.3], ["Arcane Blast", 147.3], ["Living Bomb", 106.7], ["Автоатака", 84.6], ["Hellfire", 76.2], ["Взрыв Living Bomb", 70.2]],
    actions: [["0.00", "Living Bomb"], ["0.45", "Blizzard"], ["0.90", "Arcane Blast"], ["1.35", "Ring of Frost"], ["5.02", "Living Bomb"], ["5.47", "Arcane Blast"], ["8.24", "Blizzard"], ["9.32", "Ring of Frost"], ["9.77", "Living Bomb"], ["10.22", "Arcane Blast"], ["14.97", "Living Bomb"], ["15.42", "Arcane Blast"], ["15.87", "Blizzard"], ["17.39", "Ring of Frost"], ["19.54", "Living Bomb"], ["19.99", "Arcane Blast"], ["23.83", "Blizzard"], ["24.28", "Living Bomb"], ["24.73", "Arcane Blast"], ["25.18", "Ring of Frost"], ["28.86", "Living Bomb"], ["29.31", "Arcane Blast"]],
    stats: [["Очки навыков", "крит 0, Potency 0, Luck 5, Mastery 0"], ["Сила атаки", "119.8"], ["Potency", "16.0"], ["Mastery", "20"], ["Рейтинг крита", "0.00"], ["Спешка", "46.0%"], ["Скорость атаки", "86.2%"], ["Мана", "1440"], ["Интервал атаки", "1.07 с"], ["Тик Living Bomb", "0.75 с"], ["Elemental Orb", "Fire"]],
    items: [["Elemental Orb", "Shop Item", "+15% Attack Speed\n+10% Haste\n+6 All Stats\nUse: Switches between 1 of 3 Orb Powers. (Cooldown: 5 seconds)\nFire: Attacks splash for 20 damage and additional 35% of Primary Attribute.\nFrost: Attacks Chill the target, reducing its movement speed by 50% and its attack speed by 25% for 4 seconds.\nShadow: Attacks ignore 6 of the target's Armor."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."], ["Razorwind", "Shop Item", "+32% Attack Speed\n+18% Haste\n+8 Potency"], ["Staff of Galactic Fury", "Shop Item", "Magical Caster Relic\n+16 to Primary Attribute\n+10 Mastery\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Increases your base attack cooldown by 20%."], ["Razorwind", "Shop Item", "+32% Attack Speed\n+18% Haste\n+8 Potency"]],
  },
  "Frost|5|drop": {
    label: "Только Random drop",
    dps: "2358.9",
    total: "70766",
    crit: "0%",
    intel: "159",
    manaLeft: "44%",
    talents: ["Archmage", "Overpowered", "Lava Spawn"],
    glyphs: ["Unsealed Power", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 5, Luck 0, Mastery 0",
    sources: [["Blizzard", 670.1], ["Ring of Frost", 361.3], ["Pyroblast", 335.4], ["Thunder", 296.2], ["Arcane Blast", 264.7], ["Hydra", 115.4], ["Living Bomb", 98.6], ["Клив Hydra", 92.3], ["Автоатака", 63.8], ["Взрыв Living Bomb", 61.0]],
    actions: [["0.00", "Living Bomb"], ["0.45", "Blizzard"], ["0.90", "Arcane Blast"], ["1.35", "Ring of Frost"], ["5.21", "Living Bomb"], ["5.66", "Arcane Blast"], ["8.63", "Blizzard"], ["9.08", "Ring of Frost"], ["9.53", "Living Bomb"], ["9.98", "Arcane Blast"], ["13.84", "Living Bomb"], ["14.29", "Arcane Blast"], ["15.55", "Blizzard"], ["16.00", "Ring of Frost"], ["18.96", "Living Bomb"], ["19.41", "Arcane Blast"], ["22.37", "Blizzard"], ["22.82", "Ring of Frost"], ["23.27", "Living Bomb"], ["23.72", "Arcane Blast"], ["27.58", "Living Bomb"], ["28.03", "Arcane Blast"], ["29.29", "Blizzard"]],
    stats: [["Очки навыков", "крит 0, Potency 5, Luck 0, Mastery 0"], ["Сила атаки", "130.2"], ["Potency", "2.5"], ["Mastery", "10"], ["Рейтинг крита", "0.00"], ["Спешка", "32.0%"], ["Скорость атаки", "17.2%"], ["Мана", "1538"], ["Интервал атаки", "1.71 с"], ["Тик Living Bomb", "0.75 с"]],
    items: [["The Darkglaive", "Random drop", "+12 to Primary Attribute\n+8% Haste\n+6 Agility\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Reduces the effectiveness of Healing Type effects on your hero by 30%."], ["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."], ["Harness of Beyond", "Random drop", "+30 Intelligence\n-10 Strength\nEquip: Your abilities have their base cooldown reduced by 8%."], ["Girdle of the Elemental Triad", "Random drop", "+11 Intelligence\n+11% Haste\nClasses: Mage\nEquip: Arcane Blast benefits from all of its Specialization effects regardless of current Specialization."], ["Cursed Skull", "Random drop", "+25 All Stats\n+15 Health per second\nEquip: Your Health Regeneration inflicts Spell damage to your Hero instead of restoring health. Health Regeneration now only works during combat."], ["The Zircon Star", "Random drop", "+13 to Primary Attribute\n+13% Haste"]],
  },
  "Arcane|5|mixed": {
    label: "Shop + drop",
    dps: "2263.1",
    total: "67893",
    crit: "0%",
    intel: "203",
    manaLeft: "45%",
    talents: ["Archmage", "Arcane Surge", "Amplification"],
    glyphs: ["Unsealed Power", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 5, Luck 0, Mastery 0",
    sources: [["Arcane Blast", 1086.8], ["Ring of Frost", 391.1], ["Thunder", 353.0], ["Всплеск огня", 180.2], ["Living Bomb", 101.3], ["Автоатака", 89.0], ["Взрыв Living Bomb", 61.7]],
    actions: [["0.00", "Living Bomb"], ["0.45", "Arcane Blast"], ["0.90", "Ring of Frost"], ["2.92", "Arcane Blast"], ["6.06", "Living Bomb"], ["6.51", "Arcane Blast"], ["9.20", "Arcane Blast"], ["9.65", "Ring of Frost"], ["12.34", "Living Bomb"], ["12.79", "Arcane Blast"], ["15.48", "Arcane Blast"], ["18.62", "Living Bomb"], ["19.07", "Arcane Blast"], ["19.52", "Ring of Frost"], ["21.76", "Arcane Blast"], ["24.90", "Living Bomb"], ["25.35", "Arcane Blast"], ["28.04", "Arcane Blast"], ["28.49", "Ring of Frost"]],
    stats: [["Очки навыков", "крит 0, Potency 5, Luck 0, Mastery 0"], ["Сила атаки", "163.2"], ["Potency", "2.5"], ["Mastery", "18"], ["Рейтинг крита", "0.00"], ["Спешка", "26.0%"], ["Скорость атаки", "27.4%"], ["Мана", "1846"], ["Интервал атаки", "1.57 с"], ["Тик Living Bomb", "0.75 с"], ["Elemental Orb", "Fire"], ["Diamond Ring", "Arcane Blast"]],
    items: [["Elemental Orb", "Shop Item", "+15% Attack Speed\n+10% Haste\n+6 All Stats\nUse: Switches between 1 of 3 Orb Powers. (Cooldown: 5 seconds)\nFire: Attacks splash for 20 damage and additional 35% of Primary Attribute.\nFrost: Attacks Chill the target, reducing its movement speed by 50% and its attack speed by 25% for 4 seconds.\nShadow: Attacks ignore 6 of the target's Armor."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."], ["Diamond Ring", "Shop Item", "+8% Haste\n+8 Mastery\n+7 All Stats\nUse: Binds the last spell you've cast to this item. (Cooldown: 30 seconds)\nEquip: Your bound spell has its base cooldown reduced by 30%."], ["The Darkglaive", "Random drop", "+12 to Primary Attribute\n+8% Haste\n+6 Agility\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Reduces the effectiveness of Healing Type effects on your hero by 30%."]],
  },
  "Arcane|5|shop": {
    label: "Только Shop Item",
    dps: "2199.3",
    total: "65978",
    crit: "0%",
    intel: "294",
    manaLeft: "84%",
    talents: ["Supernova", "Archmage", "Lava Spawn"],
    glyphs: ["Unsealed Power", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 0, Luck 0, Mastery 0",
    sources: [["Ring of Frost", 489.9], ["Supernova", 343.3], ["Thunder", 260.5], ["Arcane Blast", 242.7], ["Всплеск огня", 230.4], ["Living Bomb", 155.1], ["Hydra", 149.0], ["Клив Hydra", 119.2], ["Автоатака", 117.8], ["Взрыв Living Bomb", 91.4]],
    actions: [["0.00", "Living Bomb"], ["0.45", "Arcane Blast"], ["0.90", "Ring of Frost"], ["7.90", "Living Bomb"], ["8.35", "Arcane Blast"], ["12.81", "Ring of Frost"], ["16.08", "Living Bomb"], ["16.53", "Arcane Blast"], ["24.26", "Living Bomb"], ["24.71", "Arcane Blast"], ["25.16", "Ring of Frost"]],
    stats: [["Очки навыков", "крит 0, Potency 0, Luck 0, Mastery 0"], ["Сила атаки", "231.5"], ["Potency", "0.0"], ["Mastery", "10"], ["Рейтинг крита", "0.00"], ["Спешка", "10.0%"], ["Скорость атаки", "22.2%"], ["Мана", "2483"], ["Интервал атаки", "1.64 с"], ["Тик Living Bomb", "0.75 с"], ["Elemental Orb", "Fire"]],
    items: [["Elemental Orb", "Shop Item", "+15% Attack Speed\n+10% Haste\n+6 All Stats\nUse: Switches between 1 of 3 Orb Powers. (Cooldown: 5 seconds)\nFire: Attacks splash for 20 damage and additional 35% of Primary Attribute.\nFrost: Attacks Chill the target, reducing its movement speed by 50% and its attack speed by 25% for 4 seconds.\nShadow: Attacks ignore 6 of the target's Armor."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."]],
  },
  "Arcane|5|drop": {
    label: "Только Random drop",
    dps: "1788.8",
    total: "53665",
    crit: "0%",
    intel: "160",
    manaLeft: "49%",
    talents: ["Supernova", "Archmage", "Arcane Surge"],
    glyphs: ["Unsealed Power", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 5, Luck 0, Mastery 0",
    sources: [["Arcane Blast", 536.1], ["Ring of Frost", 441.3], ["Thunder", 282.5], ["Supernova", 276.2], ["Living Bomb", 114.1], ["Взрыв Living Bomb", 70.6], ["Автоатака", 67.9]],
    actions: [["0.00", "Living Bomb"], ["0.45", "Arcane Blast"], ["0.90", "Ring of Frost"], ["4.54", "Living Bomb"], ["4.99", "Arcane Blast"], ["7.74", "Ring of Frost"], ["9.34", "Living Bomb"], ["9.79", "Arcane Blast"], ["14.13", "Living Bomb"], ["14.58", "Arcane Blast"], ["15.03", "Ring of Frost"], ["18.92", "Living Bomb"], ["19.37", "Arcane Blast"], ["22.12", "Ring of Frost"], ["23.71", "Living Bomb"], ["24.16", "Arcane Blast"], ["28.51", "Living Bomb"], ["28.96", "Arcane Blast"]],
    stats: [["Очки навыков", "крит 0, Potency 5, Luck 0, Mastery 0"], ["Сила атаки", "131.0"], ["Potency", "2.5"], ["Mastery", "10"], ["Рейтинг крита", "0.00"], ["Спешка", "21.0%"], ["Скорость атаки", "25.2%"], ["Мана", "1545"], ["Интервал атаки", "1.60 с"], ["Тик Living Bomb", "0.75 с"]],
    items: [["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."], ["The Darkglaive", "Random drop", "+12 to Primary Attribute\n+8% Haste\n+6 Agility\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Reduces the effectiveness of Healing Type effects on your hero by 30%."], ["Harness of Beyond", "Random drop", "+30 Intelligence\n-10 Strength\nEquip: Your abilities have their base cooldown reduced by 8%."], ["Cursed Skull", "Random drop", "+25 All Stats\n+15 Health per second\nEquip: Your Health Regeneration inflicts Spell damage to your Hero instead of restoring health. Health Regeneration now only works during combat."], ["Nightborne Scepter", "Random drop", "+12 to Primary Attribute\n+8% Attack Speed\nEquip: Increases the damage dealt by Magical Type effects by 12%.\nEquip: Grants you and nearby allies Brilliance Aura, which provides 4 mana per 5 seconds. Auras with the same name do not stack."], ["The Zircon Star", "Random drop", "+13 to Primary Attribute\n+13% Haste"]],
  },
  "Fire|5|mixed": {
    label: "Shop + drop",
    dps: "5064.1",
    total: "151924",
    crit: "5%",
    intel: "113",
    manaLeft: "28%",
    talents: ["Archmage", "Burning Fury", "Greater Pyroblast"],
    glyphs: ["Fortitude", "Unsealed Power", "Glass Cannon"],
    points: "крит 5, Potency 0, Luck 0, Mastery 0",
    sources: [["Pyroblast", 2339.7], ["Hydra", 1203.7], ["Клив Hydra", 802.5], ["Ring of Frost", 327.3], ["Arcane Blast", 143.6], ["Living Bomb", 115.4], ["Взрыв Living Bomb", 76.1], ["Автоатака", 55.9]],
    actions: [["0.00", "Living Bomb"], ["0.45", "Hydra"], ["0.90", "Arcane Blast"], ["1.35", "Ring of Frost"], ["3.80", "Hydra"], ["4.25", "Living Bomb"], ["5.80", "Arcane Blast"], ["7.80", "Hydra"], ["8.25", "Ring of Frost"], ["8.70", "Living Bomb"], ["11.80", "Hydra"], ["12.25", "Arcane Blast"], ["13.80", "Living Bomb"], ["15.80", "Hydra"], ["16.25", "Ring of Frost"], ["16.70", "Arcane Blast"], ["19.80", "Living Bomb"], ["20.25", "Hydra"], ["21.80", "Arcane Blast"], ["23.80", "Hydra"], ["24.25", "Living Bomb"], ["24.70", "Ring of Frost"], ["27.80", "Hydra"], ["28.25", "Arcane Blast"], ["28.70", "Living Bomb"]],
    stats: [["Очки навыков", "крит 5, Potency 0, Luck 0, Mastery 0"], ["Сила атаки", "95.8"], ["Potency", "11.0"], ["Mastery", "28"], ["Рейтинг крита", "0.00"], ["Спешка", "42.0%"], ["Скорость атаки", "77.0%"], ["Мана", "1216"], ["Интервал атаки", "2.00 с"], ["Тик Living Bomb", "0.75 с"], ["Интервал гидры", "0.89 с"], ["Elemental Orb", "Shadow"], ["Diamond Ring", "Hydra"]],
    items: [["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."], ["Elemental Orb", "Shop Item", "+15% Attack Speed\n+10% Haste\n+6 All Stats\nUse: Switches between 1 of 3 Orb Powers. (Cooldown: 5 seconds)\nFire: Attacks splash for 20 damage and additional 35% of Primary Attribute.\nFrost: Attacks Chill the target, reducing its movement speed by 50% and its attack speed by 25% for 4 seconds.\nShadow: Attacks ignore 6 of the target's Armor."], ["Diamond Ring", "Shop Item", "+8% Haste\n+8 Mastery\n+7 All Stats\nUse: Binds the last spell you've cast to this item. (Cooldown: 30 seconds)\nEquip: Your bound spell has its base cooldown reduced by 30%."], ["Felo'melorn", "Random drop", "+20% Attack Speed\n+6% Haste\n+3 Potency\nClasses: Mage\nEquip: Reduces the cooldown of Hydra by 3 seconds."], ["Razorwind", "Shop Item", "+32% Attack Speed\n+18% Haste\n+8 Potency"], ["Staff of Galactic Fury", "Shop Item", "Magical Caster Relic\n+16 to Primary Attribute\n+10 Mastery\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Increases your base attack cooldown by 20%."]],
  },
  "Fire|5|shop": {
    label: "Только Shop Item",
    dps: "5900.4",
    total: "177011",
    crit: "0%",
    intel: "90",
    manaLeft: "17%",
    talents: ["Archmage", "Lava Spawn", "Greater Pyroblast"],
    glyphs: ["Unsealed Power", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 0, Luck 5, Mastery 0",
    sources: [["Pyroblast", 2801.4], ["Hydra", 1088.2], ["Клив Hydra", 870.6], ["Ring of Frost", 358.3], ["Thunder", 264.8], ["Arcane Blast", 181.7], ["Living Bomb", 167.9], ["Взрыв Living Bomb", 116.1], ["Автоатака", 51.1]],
    actions: [["0.00", "Living Bomb"], ["0.45", "Hydra"], ["0.90", "Arcane Blast"], ["1.35", "Ring of Frost"], ["3.80", "Living Bomb"], ["5.80", "Arcane Blast"], ["7.80", "Living Bomb"], ["8.25", "Hydra"], ["8.70", "Ring of Frost"], ["9.80", "Arcane Blast"], ["11.80", "Living Bomb"], ["13.80", "Arcane Blast"], ["14.25", "Hydra"], ["14.70", "Ring of Frost"], ["15.80", "Living Bomb"], ["17.80", "Arcane Blast"], ["19.80", "Living Bomb"], ["20.25", "Hydra"], ["20.70", "Ring of Frost"], ["21.80", "Arcane Blast"], ["23.80", "Living Bomb"], ["25.80", "Arcane Blast"], ["26.25", "Hydra"], ["26.70", "Ring of Frost"], ["27.80", "Living Bomb"], ["29.80", "Arcane Blast"]],
    stats: [["Очки навыков", "крит 0, Potency 0, Luck 5, Mastery 0"], ["Сила атаки", "78.5"], ["Potency", "24.0"], ["Mastery", "20"], ["Рейтинг крита", "0.00"], ["Спешка", "64.0%"], ["Скорость атаки", "118.2%"], ["Мана", "1055"], ["Интервал атаки", "2.00 с"], ["Тик Living Bomb", "0.75 с"], ["Интервал гидры", "0.74 с"], ["Elemental Orb", "Shadow"]],
    items: [["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."], ["Razorwind", "Shop Item", "+32% Attack Speed\n+18% Haste\n+8 Potency"], ["Razorwind", "Shop Item", "+32% Attack Speed\n+18% Haste\n+8 Potency"], ["Elemental Orb", "Shop Item", "+15% Attack Speed\n+10% Haste\n+6 All Stats\nUse: Switches between 1 of 3 Orb Powers. (Cooldown: 5 seconds)\nFire: Attacks splash for 20 damage and additional 35% of Primary Attribute.\nFrost: Attacks Chill the target, reducing its movement speed by 50% and its attack speed by 25% for 4 seconds.\nShadow: Attacks ignore 6 of the target's Armor."], ["Razorwind", "Shop Item", "+32% Attack Speed\n+18% Haste\n+8 Potency"], ["Staff of Galactic Fury", "Shop Item", "Magical Caster Relic\n+16 to Primary Attribute\n+10 Mastery\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Increases your base attack cooldown by 20%."]],
  },
  "Fire|5|drop": {
    label: "Только Random drop",
    dps: "4255.2",
    total: "127657",
    crit: "0%",
    intel: "129",
    manaLeft: "38%",
    talents: ["Archmage", "Lava Spawn", "Greater Pyroblast"],
    glyphs: ["Unsealed Power", "Hellfire", "Glass Cannon"],
    points: "крит 0, Potency 0, Luck 5, Mastery 0",
    sources: [["Pyroblast", 2481.5], ["Hydra", 614.6], ["Клив Hydra", 491.7], ["Ring of Frost", 303.1], ["Arcane Blast", 127.4], ["Living Bomb", 92.8], ["Взрыв Living Bomb", 58.5], ["Автоатака", 47.0], ["Hellfire", 38.8]],
    actions: [["0.00", "Living Bomb"], ["0.45", "Hydra"], ["0.90", "Arcane Blast"], ["1.35", "Ring of Frost"], ["5.80", "Living Bomb"], ["6.25", "Hydra"], ["6.70", "Arcane Blast"], ["7.80", "Ring of Frost"], ["9.80", "Living Bomb"], ["11.80", "Hydra"], ["12.25", "Arcane Blast"], ["13.80", "Living Bomb"], ["14.25", "Ring of Frost"], ["17.80", "Living Bomb"], ["18.25", "Hydra"], ["18.70", "Arcane Blast"], ["21.80", "Living Bomb"], ["22.25", "Ring of Frost"], ["22.70", "Hydra"], ["23.15", "Arcane Blast"], ["25.80", "Living Bomb"], ["27.80", "Hydra"], ["28.25", "Arcane Blast"], ["28.70", "Ring of Frost"]],
    stats: [["Очки навыков", "крит 0, Potency 0, Luck 5, Mastery 0"], ["Сила атаки", "107.8"], ["Potency", "3.0"], ["Mastery", "20"], ["Рейтинг крита", "0.00"], ["Спешка", "34.0%"], ["Скорость атаки", "27.2%"], ["Мана", "1328"], ["Интервал атаки", "2.00 с"], ["Тик Living Bomb", "0.75 с"], ["Интервал гидры", "1.16 с"]],
    items: [["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."], ["Harness of Beyond", "Random drop", "+30 Intelligence\n-10 Strength\nEquip: Your abilities have their base cooldown reduced by 8%."], ["Felo'melorn", "Random drop", "+20% Attack Speed\n+6% Haste\n+3 Potency\nClasses: Mage\nEquip: Reduces the cooldown of Hydra by 3 seconds."], ["The Darkglaive", "Random drop", "+12 to Primary Attribute\n+8% Haste\n+6 Agility\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Reduces the effectiveness of Healing Type effects on your hero by 30%."], ["Staff of the Kirin'tor", "Random drop", "+10 Mastery\n+7% Haste\n+6 Intelligence\nClasses: Mage\nEquip: Increases the proc chance of Arcane Spell Mastery by additional 5%.\nEquip: Increases the damage reduction of Frost Spell Mastery by additional 5%.\nEquip: Increases the proc chance of Fire Spell Mastery by additional 5%."], ["The Zircon Star", "Random drop", "+13 to Primary Attribute\n+13% Haste"]],
  },
};

const TARGETS: Record<SpecId, TargetCount[]> = {"Frost": [5], "Arcane": [5], "Fire": [5]};
const MODES: Record<string, RunId[]> = {"Frost|5": ["mixed", "shop", "drop"], "Arcane|5": ["mixed", "shop", "drop"], "Fire|5": ["mixed", "shop", "drop"]};
const SPEC_NOTE: Record<SpecId, string> = {"Frost": "Кнопки Living Bomb, Blizzard, Arcane Blast, Ring of Frost. Мастерство Frost усиливает снижение урона, в исходящий урон не входит. Волн Blizzard: округление 5×(1+спешка), с Iceflow Mantle 5×(1,20+спешка). Интервал волны 1/(1+спешка).", "Arcane": "Blizzard заменён на Evocation. Пассив: +8% магического типа и ещё 1% за каждые 75 маны, в симе мана для этого бонуса держится на максимуме. Стаки Arcane Blast: каждый следующий каст ×1,20, потолок 3, с Arcane Surge 8. Шанс сброса кулдауна считается по Mastery с вещей, пять очков навыков его не двигают.", "Fire": "Blizzard заменён на Hydra. Скорость атаки мага на его взмах не идёт, гидры получают 75% этого стата. Pyroblast тратит Cinderflame. В Fire его урон ×(1+0,0075×Mastery), и эти очки навыков в формуле есть."};


function GameText({ text }: { text: string }) {
  return (
    <Text size="small" style={{ whiteSpace: "pre-wrap" }}>
      {text}
    </Text>
  );
}

function notedName(name: string, stats: Array<[string, string]>): string {
  const row = stats.find(([label]) => label === name);
  return row ? `${name} — ${row[1]}` : name;
}

export default function MageSims() {
  const [spec, setSpec] = useCanvasState<SpecId>("mage-spec", "Frost");
  const [catalog, setCatalog] = useCanvasState<"all" | "picked">("mage-catalog", "picked");
  const [mode, setMode] = useCanvasState<RunId>("mage-source", "mixed");
  const [targets, setTargets] = useCanvasState<TargetCount>("mage-targets", 5);
  const target = TARGETS[spec].includes(targets) ? targets : TARGETS[spec][0];
  const modeList = MODES[`${spec}|${target}`];
  const source = modeList.includes(mode) ? mode : modeList[0];
  const run = RUNS[`${spec}|${target}|${source}`];
  const talents = catalog === "picked" ? TALENTS.filter((row) => run.talents.includes(row[0])) : TALENTS;
  const glyphs = catalog === "picked" ? GLYPHS.filter((row) => run.glyphs.includes(row[0])) : GLYPHS;

  return (
    <Stack gap={20}>
      <Stack gap={6}>
        <H1>{spec} Mage, {target === 1 ? "1 цель" : target < 5 ? `${target} цели` : "5 целей"}</H1>
        <Text tone="secondary">
          Sunken City v2.5.2a · уровень 6 · 30 секунд · ожидаемый урон, без случайных бросков
        </Text>
      </Stack>

      <Row gap={8} wrap>
        <Pill active={spec === "Frost"} onClick={() => setSpec("Frost")}>Frost</Pill>
        <Pill active={spec === "Arcane"} onClick={() => setSpec("Arcane")}>Arcane</Pill>
        <Pill active={spec === "Fire"} onClick={() => setSpec("Fire")}>Fire</Pill>
      </Row>
      <Row gap={8} wrap>
        {TARGETS[spec].includes(1) ? <Pill active={target === 1} onClick={() => setTargets(1)}>1 цель</Pill> : null}
        {TARGETS[spec].includes(2) ? <Pill active={target === 2} onClick={() => setTargets(2)}>2 цели</Pill> : null}
        {TARGETS[spec].includes(3) ? <Pill active={target === 3} onClick={() => setTargets(3)}>3 цели</Pill> : null}
        {TARGETS[spec].includes(4) ? <Pill active={target === 4} onClick={() => setTargets(4)}>4 цели</Pill> : null}
        {TARGETS[spec].includes(5) ? <Pill active={target === 5} onClick={() => setTargets(5)}>5 целей</Pill> : null}
      </Row>
      <Row gap={8} wrap>
        {MODES[`${spec}|${target}`].includes("mixed") ? <Pill active={source === "mixed"} onClick={() => setMode("mixed")}>Shop + drop</Pill> : null}
        {MODES[`${spec}|${target}`].includes("shop") ? <Pill active={source === "shop"} onClick={() => setMode("shop")}>Только Shop Item</Pill> : null}
        {MODES[`${spec}|${target}`].includes("drop") ? <Pill active={source === "drop"} onClick={() => setMode("drop")}>Только Random drop</Pill> : null}
      </Row>

      <Grid columns={5} gap={16}>
        <Stat value={run.dps} label="DPS" tone="success" />
        <Stat value={run.total} label="Урон за 30 с" />
        <Stat value={run.crit} label="Крит" />
        <Stat value={run.intel} label="Интеллект" />
        <Stat value={run.manaLeft} label="Мана в конце" />
      </Grid>

      <H2>Урон по источникам</H2>
      <BarChart
        horizontal
        height={260}
        categories={run.sources.map((row) => row[0])}
        series={[{ name: "DPS", data: run.sources.map((row) => row[1]), tone: "info" }]}
        valueSuffix=" DPS"
        showValues
      />
      <Text size="small" tone="tertiary">
        Ожидаемый урон источника за 30 с, делённый на 30. Броня манекена 15.
      </Text>

      <H2>Порядок кнопок</H2>
      <Table
        headers={["Секунда", "Заклинание"]}
        columnAlign={["right", "left"]}
        rows={run.actions}
      />
      <Text size="small" tone="tertiary">
        Каст 0,15 с до эффекта, затем ещё 0,30 с герой занят. Living Bomb обновляется, если дот спадёт в ближайшую секунду.
      </Text>

      <H2>Характеристики в бою</H2>
      <Table
        headers={["Параметр", "Значение"]}
        rows={run.stats}
      />

      <Divider />

      <H2>Предметы в связке</H2>
      <Text tone="secondary">
        {run.label}. {spec}. {target === 1 ? "1 цель" : target < 5 ? `${target} цели` : "5 целей"}. Очки навыков: {run.points}.
      </Text>
      <Table
        headers={["Предмет", "Источник", "Описание из игры"]}
        rows={run.items.map(([name, sourceName, tip]) => [
          notedName(name, run.stats),
          sourceName,
          <GameText text={tip} />,
        ])}
        striped
        rowTone={run.items.map(() => "success" as const)}
      />

      <Row gap={8} align="center">
        <H2>Таланты и глифы</H2>
        <Pill active={catalog === "picked"} onClick={() => setCatalog("picked")}>
          В связке
        </Pill>
        <Pill active={catalog === "all"} onClick={() => setCatalog("all")}>
          Все прогнанные
        </Pill>
      </Row>
      <Text size="small" tone="tertiary">
        Прогнаны все тройки из 18 талантов и все тройки из 32 глифов. На каждом бою проверены все 56 раскладок 5 очков.
      </Text>

      <H3>Таланты</H3>
      <Table
        headers={["Талант", "Описание из игры"]}
        rows={talents.map(([name, tip]) => [name, <GameText text={tip} />])}
        striped
        stickyHeader
        rowTone={talents.map((row) => (run.talents.includes(row[0]) ? "success" : undefined))}
      />

      <H3>Глифы</H3>
      <Table
        headers={["Глиф", "Описание из игры"]}
        rows={glyphs.map(([name, tip]) => [name, <GameText text={tip} />])}
        striped
        stickyHeader
        rowTone={glyphs.map((row) => (run.glyphs.includes(row[0]) ? "success" : undefined))}
      />

      <Callout tone="warning" title="Правила">
        Те же фильтры предметов, что у жреца: только эпики и легендарки Странника, одна легендарка, один Elemental Orb, без вещей других классов и без квестовых. Поиск предметов жадный. Пять очков навыков не перестраивают очередь кастов: они входят в урон, крит, Potency и в множитель Pyroblast, но не в шанс Cinderflame и не в сброс кулдауна Arcane.
      </Callout>
      <Text size="small">{SPEC_NOTE[spec]}</Text>
    </Stack>
  );
}
