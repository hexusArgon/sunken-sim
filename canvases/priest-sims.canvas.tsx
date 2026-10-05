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

const TALENTS: Array<[string, string, boolean]> = [
  ["Catharsis", "Increases Magical Type damage by up to 30% scaling with the target’s current health.", true],
  ["Insanity", "Your Magical Type effects deal 15% more damage, multiplicatively, but you take 15% of all Magical damage dealt as Spell damage at intervals of 1 second. While below 40% of maximum Health, the bonus damage will be doubled. The damage inflicted by this effect before modifiers cannot exceed 75% of the Priest's maximum Health.", true],
  ["Clairvoyance", "Grants you 8% Critical Strike and gives your Healing Type effects a chance to be critical at 150% effectiveness.", true],
  ["Dark Torment", "Mind Spike applies Shadow Word: Pain on its target.\n\nYou must have the Shadow Word: Pain ability for this effect to work.", false],
  ["Psychic Link", "Shadow Word: Pain’s periodic damage is increased by 15% plus additional 10% for each enemy affected by it. The duration of Shadow Word: Pain is also increased by 2 seconds.", false],
  ["Cosmic Horrors", "Void Rift has 25% chance to apply Shadow Word: Pain to units it deals damage to. Reduces the delay of Void Rift by 0,5 seconds.", false],
  ["Answered Prayers", "Divine Image’s Naaru now also triggers its effect with each spellcast other than Divine Image.\n\nReduces the cooldown of Divine Image by 1 second.", false],
  ["Touch of the Naaru", "- Naaru healing has 20% chance to apply Renew. The proc chance is halved in Discipline Specialization.\n\n- Naaru damage reduces the remaining cooldown of Mind Spike by 0,4 seconds. The cooldown reduction is halved in Discipline Specialization.\n\nReduces the cooldown of Divine Image by 1 second.", false],
  ["Prayer of Mending", "When a Hero below 80% health takes damage, they will restore 45 health (+70% of Intelligence) (+70% of Strength) and will receive Prayer of Mending for 6 seconds, which increases the healing taken from Healing Type effects by 15%. This effect must wear off before it can occur again.", false],
  ["Smite", "Whenever Renew restores health with its instant healing effect, all enemies within 350 range of the target take 50 Magical damage (+80% Intelligence) (+80% of Strength).", false],
  ["Divine Empowerment", "Applying Renew now also applies Divine Empowerment for 8 seconds which increases the target's Attack Damage by 30%. The Attack Damage bonus is reduced to 20% in Discipline Specialization.", false],
  ["Echo of Light", "The periodic healing of Renew has 18% chance to trigger its instant healing on the target.", false],
  ["Tears of the Gods", "Lightwell spawns with 2 additional charges and its healing done is increased by 10%.", false],
  ["Power Word: Shield", "Casting Renew applies Power Word: Shield on the target for 7 seconds, which absorbs 30 damage (+4% of target maximum Health) (+150% of Intelligence).", false],
  ["Holy Waters", "Lightwell’s healing restores mana to the target equal to 4% of the Priest’s maximum mana. Additionally, while above 3 charges, it also applies Renew.\n\nRenew has to be learned for the buff application effect to work.", false],
  ["Empyreal Blaze", "Radiance now also deals Magical damage to affected enemies each second equal to 8% of its healing before modifiers. In addition, affected enemies take 5% (+8% of Strength) increased damage from all of your sources. While in Holy Specialization, damage dealt by Radiance is halved, but the damage bonus also affects your allies.", false],
  ["Blinding Light", "Increases the duration of Radiance by 2 seconds. Additionally, effected enemies have their Movement Speed reduced by additional 8% and the chance for allies to evade attacks is also increased by additional 8%.", false],
  ["Dark Evangelism", "Healing an allied Hero with a Healing Type effect has 8% chance to grant Mind Spike a stack, up to a maximum of 10 stacks. Casting Mind Spike consumes all stacks to deal 10% increased damage per stack.", false],
];

const GLYPHS: Array<[string, string, boolean]> = [
  ["Unsealed Power", "Offensive Glyph\nIncreases the damage dealt by Magical and Physical Type effects by 18%.", true],
  ["Animosity", "Offensive Glyph\nGrants you 12% Critical Strike chance and increases the damage dealt by Critical Strikes by 15%.", true],
  ["Glass Cannon", "Offensive Glyph\nMultiplicatively increases damage dealt from all sources by 15%, but all of your units take 10% more damage.", true],
  ["Fortitude", "Utility Glyph\nBoosts your Primary Attribute by 4 and additional 2 per Hero Level.", false],
  ["Hellfire", "Offensive Glyph\nDeals 3 damage and additional amount equal to 3 times your hero level to all enemy units within 400 range every 1,25 seconds. Damage dealt is modified based on the amount of targets hit:\n\n• 1 enemy: 200% damage\n• 2-3 enemies: 100% damage\n• 4+ enemies: 50% damage", false],
  ["Mindhaste", "Utility Glyph\nIncreases your Haste by 7% and reduces the cooldown of all abilities by 0,2 seconds.", false],
  ["Supremacy", "Utility Glyph\nIncreases your Mastery by 20.", false],
  ["Thunder", "Offensive Glyph\nYour spellcasts have 18% chance to call down lightnings that deal 35 (+200% of Primary Attribute) to enemy units within 600 range.", false],
  ["Battle Frenzy", "Offensive Glyph\nGives your attacks 18% chance to grant you 32% Attack Speed for 5 seconds. Battle Frenzy must wear off before occuring again.", false],
  ["Blood Violence", "Offensive Glyph\nDealing damage from any source has 3% chance to cause the enemy flesh to explode, dealing 20 Attrition damage (+160% of Primary Attribute).", false],
  ["Arc Striking", "Utility Glyph\nEach of your attacks reduces the remaining cooldown of your Q ability by 8% plus additional 0,25 seconds. Your Q spellcasts refund 40% of their mana cost.", false],
  ["Astral Shift", "Defensive Glyph\nReduces any damage taken by 1% for every 4% of missing health.", false],
  ["Beastfury", "Offensive Glyph\nYour summons spawn with 25% Critical Strike chance.", false],
  ["Bloodthirst", "Defensive Glyph\nCauses your hero to restore health equal to 10% of any damage dealt.", false],
  ["Class Mastery", "Utility Glyph\nAfter casting your Q hotkey ability, your hero will gain Class Mastery for 4 seconds, which provides one of the following effects depending on his primary attribute:\n\n• Strength: increases Armor by 4 and upon taking damage your hero restores 3 health plus 12% of all mitigated damage to the lowest health hero. This is a Healing Type effect.\n• Agility: increases damage dealt from all sources by 20%.\n• Intelligence: instantly restores 8% of maximum mana and then regenerates 0,5% of maximum mana each second.\n\nClass Mastery must wear off before occuring again.", false],
  ["Fortune", "Utility Glyph\nIncreases your Luck by additional 15%.", false],
  ["Commandership", "Utility Glyph\nGrants you 20% Pet Damage and reduces the damage taken by your summons by 12%.", false],
  ["Crippling", "Support Glyph\nYour attacks apply Cripple on the target for 4 seconds, which reduces the damage dealt by attacks by 20% and Movement Speed by 25%.", false],
  ["Dampening", "Defenisve Glyph\nGrants you 20% Spell Damage Reduction.", false],
  ["Deep Healing", "Support Glyph\nIncreases your Healing Power by additional 20%.", false],
  ["Devotion", "Support Glyph\nYour Healing Type spellcasts cause all nearby allies to regenerate 0,75 mana per second, increased by amount equal to 0,4% of their maximum mana for 4 seconds.", false],
  ["Diamond Skin", "Defensive Glyph\nReduces damage taken from attacks by 10%.", false],
  ["Lightforce", "Defensive Glyph\nTaking damage while below 70% of maximum health shields the hero with holy energy, making him invulnerable for 4 seconds. This effect cannot occur more than once every 35 seconds. Invulnerable heroes will be ignored by enemy units.", false],
  ["Magic Find", "Support Glyph\nIncreases item drop chances from all enemy units by 20% for the party and increases the odds of enemies dropping higher quality items. This Glyph stacks with other player's Magic Find Glyphs.", false],
  ["Mana Shield", "Defensive Glyph\nReduces any damage taken by amount equal to 2% of your maximum mana.", false],
  ["Protecting", "Support Glyph\nReduces the damage taken by allied heroes by 12%, but increases the damage your hero takes by 10%. Damage reduction does not stack across multiple Glyphs of Protecting.", false],
  ["Provoking", "Support Glyph\nIncreases the duration of your Taunting effects by 25% and reduces the damage taunted enemies deal by 7%.", false],
  ["Recovery", "Defensive Glyph\nGrants you 2 Health per second (+0,75% of maximum Health). Also causes Health Regeneration to become a Healing Type effect.", false],
  ["Renewal", "Support Glyph\nYour spellcasts have 40% chance to restore 40 health (+130% of Primary Attribute) to all friendly units within 700 range. This is a Healing Type effect.", false],
  ["Replenishment", "Utility Glyph\nCauses you to regenerate 1,5 mana (+0,75% of maximum Mana) each second.", false],
  ["Siphoning", "Defensive Glyph\nWhenever another hero gets healed by a Healing Type effect, you restore health equal to 25% of the healed amount. Overhealing amount is not applied to this effect.", false],
  ["Trepidation", "Support Glyph\nAffects enemies in 600 range with Trepidation Aura, which causes them to take 8% more damage from allied units, not including your own units. This effect does not stack.", false],
];

type SpecId = "Shadow" | "Discipline" | "Holy";
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
  "Shadow|5|mixed": {
    label: "Shop + drop",
    dps: "2623.7",
    total: "78712",
    crit: "0%",
    intel: "149",
    manaLeft: "94%",
    talents: ["Psychic Link", "Dark Torment", "Insanity"],
    glyphs: ["Unsealed Power", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 5, Luck 0, Mastery 0",
    sources: [["Shadow Word: Pain", 916.7], ["Void Rift", 813.8], ["Thunder", 317.5], ["Mind Spike", 219.3], ["Naaru", 152.6], ["Боль, обновление", 120.2], ["Автоатака", 83.6]],
    actions: [["0.00", "Shadow Word: Pain"], ["0.45", "Divine Image"], ["0.90", "Mind Spike"], ["1.35", "Void Rift"], ["4.87", "Shadow Word: Pain"], ["7.93", "Mind Spike"], ["9.46", "Shadow Word: Pain"], ["9.91", "Void Rift"], ["12.53", "Divine Image"], ["14.06", "Shadow Word: Pain"], ["14.51", "Mind Spike"], ["17.13", "Void Rift"], ["18.66", "Shadow Word: Pain"], ["21.72", "Mind Spike"], ["23.26", "Shadow Word: Pain"], ["24.79", "Divine Image"], ["25.24", "Void Rift"], ["27.85", "Shadow Word: Pain"], ["28.30", "Mind Spike"]],
    stats: [["Очки навыков", "крит 0, Potency 5, Luck 0, Mastery 0"], ["Сила атаки", "121.8"], ["Potency", "10.5"], ["Mastery", "20"], ["Рейтинг крита", "0.00"], ["Спешка", "36.0%"], ["Скорость атаки", "56.6%"], ["Мана", "1468"], ["Интервал атаки", "1.53 с"], ["Тик Shadow Word: Pain", "0.74 с"], ["Elemental Orb", "Shadow"]],
    items: [["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["The Darkglaive", "Random drop", "+12 to Primary Attribute\n+8% Haste\n+6 Agility\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Reduces the effectiveness of Healing Type effects on your hero by 30%."], ["Razorwind", "Shop Item", "+32% Attack Speed\n+18% Haste\n+8 Potency"], ["Staff of Galactic Fury", "Shop Item", "Magical Caster Relic\n+16 to Primary Attribute\n+10 Mastery\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Increases your base attack cooldown by 20%."], ["Elemental Orb", "Shop Item", "+15% Attack Speed\n+10% Haste\n+6 All Stats\nUse: Switches between 1 of 3 Orb Powers. (Cooldown: 5 seconds)\nFire: Attacks splash for 20 damage and additional 35% of Primary Attribute.\nFrost: Attacks Chill the target, reducing its movement speed by 50% and its attack speed by 25% for 4 seconds.\nShadow: Attacks ignore 6 of the target's Armor."]],
  },
  "Shadow|5|shop": {
    label: "Только Shop Item",
    dps: "2177.4",
    total: "65321",
    crit: "0%",
    intel: "247",
    manaLeft: "100%",
    talents: ["Psychic Link", "Dark Torment", "Insanity"],
    glyphs: ["Unsealed Power", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 0, Luck 0, Mastery 0",
    sources: [["Void Rift", 773.3], ["Shadow Word: Pain", 451.1], ["Mind Spike", 246.3], ["Thunder", 242.4], ["Всплеск огня", 166.3], ["Naaru", 114.6], ["Боль, обновление", 100.6], ["Автоатака", 82.8]],
    actions: [["0.00", "Shadow Word: Pain"], ["0.45", "Divine Image"], ["0.90", "Mind Spike"], ["1.35", "Void Rift"], ["7.69", "Shadow Word: Pain"], ["9.66", "Mind Spike"], ["13.58", "Void Rift"], ["15.55", "Shadow Word: Pain"], ["19.48", "Divine Image"], ["19.93", "Mind Spike"], ["23.40", "Shadow Word: Pain"], ["25.37", "Void Rift"], ["29.30", "Mind Spike"]],
    stats: [["Очки навыков", "крит 0, Potency 0, Luck 0, Mastery 0"], ["Сила атаки", "195.2"], ["Potency", "0.0"], ["Mastery", "20"], ["Рейтинг крита", "0.00"], ["Спешка", "10.0%"], ["Скорость атаки", "22.2%"], ["Мана", "2154"], ["Интервал атаки", "1.96 с"], ["Тик Shadow Word: Pain", "0.91 с"], ["Elemental Orb", "Fire"]],
    items: [["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Elemental Orb", "Shop Item", "+15% Attack Speed\n+10% Haste\n+6 All Stats\nUse: Switches between 1 of 3 Orb Powers. (Cooldown: 5 seconds)\nFire: Attacks splash for 20 damage and additional 35% of Primary Attribute.\nFrost: Attacks Chill the target, reducing its movement speed by 50% and its attack speed by 25% for 4 seconds.\nShadow: Attacks ignore 6 of the target's Armor."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Staff of Galactic Fury", "Shop Item", "Magical Caster Relic\n+16 to Primary Attribute\n+10 Mastery\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Increases your base attack cooldown by 20%."]],
  },
  "Discipline|5|mixed": {
    label: "Shop + drop",
    dps: "1807.7",
    total: "54231",
    crit: "0%",
    intel: "133",
    manaLeft: "84%",
    talents: ["Psychic Link", "Dark Torment", "Empyreal Blaze"],
    glyphs: ["Unsealed Power", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 5, Luck 0, Mastery 0",
    sources: [["Shadow Word: Pain", 654.3], ["Thunder", 240.2], ["Empyreal Blaze", 188.7], ["Всплеск огня", 187.6], ["Mind Spike", 155.2], ["Radiance", 117.0], ["Автоатака", 98.1], ["Naaru", 91.2], ["Боль, обновление", 75.2]],
    actions: [["0.00", "Shadow Word: Pain"], ["0.45", "Divine Image"], ["0.90", "Radiance"], ["1.35", "Mind Spike"], ["3.92", "Shadow Word: Pain"], ["6.04", "Radiance"], ["6.49", "Mind Spike"], ["8.16", "Shadow Word: Pain"], ["11.34", "Divine Image"], ["11.79", "Radiance"], ["12.24", "Shadow Word: Pain"], ["12.69", "Mind Spike"], ["16.33", "Shadow Word: Pain"], ["17.39", "Radiance"], ["17.84", "Mind Spike"], ["20.57", "Shadow Word: Pain"], ["21.63", "Divine Image"], ["22.69", "Radiance"], ["23.14", "Mind Spike"], ["24.81", "Shadow Word: Pain"], ["27.99", "Radiance"], ["28.44", "Mind Spike"], ["28.89", "Shadow Word: Pain"]],
    stats: [["Очки навыков", "крит 0, Potency 5, Luck 0, Mastery 0"], ["Сила атаки", "109.8"], ["Potency", "18.5"], ["Mastery", "10"], ["Рейтинг крита", "0.00"], ["Спешка", "54.0%"], ["Скорость атаки", "88.6%"], ["Мана", "1356"], ["Интервал атаки", "1.06 с"], ["Тик Shadow Word: Pain", "0.65 с"], ["Elemental Orb", "Fire"]],
    items: [["Elemental Orb", "Shop Item", "+15% Attack Speed\n+10% Haste\n+6 All Stats\nUse: Switches between 1 of 3 Orb Powers. (Cooldown: 5 seconds)\nFire: Attacks splash for 20 damage and additional 35% of Primary Attribute.\nFrost: Attacks Chill the target, reducing its movement speed by 50% and its attack speed by 25% for 4 seconds.\nShadow: Attacks ignore 6 of the target's Armor."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."], ["Razorwind", "Shop Item", "+32% Attack Speed\n+18% Haste\n+8 Potency"], ["The Darkglaive", "Random drop", "+12 to Primary Attribute\n+8% Haste\n+6 Agility\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Reduces the effectiveness of Healing Type effects on your hero by 30%."], ["Razorwind", "Shop Item", "+32% Attack Speed\n+18% Haste\n+8 Potency"]],
  },
  "Discipline|5|shop": {
    label: "Только Shop Item",
    dps: "1553.1",
    total: "46594",
    crit: "0%",
    intel: "176",
    manaLeft: "98%",
    talents: ["Psychic Link", "Dark Torment", "Empyreal Blaze"],
    glyphs: ["Unsealed Power", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 0, Luck 0, Mastery 0",
    sources: [["Shadow Word: Pain", 480.7], ["Всплеск огня", 229.0], ["Thunder", 197.9], ["Mind Spike", 149.1], ["Empyreal Blaze", 147.4], ["Автоатака", 120.3], ["Radiance", 90.8], ["Naaru", 75.6], ["Боль, обновление", 62.4]],
    actions: [["0.00", "Shadow Word: Pain"], ["0.45", "Divine Image"], ["0.90", "Radiance"], ["1.35", "Mind Spike"], ["5.02", "Shadow Word: Pain"], ["7.17", "Radiance"], ["7.62", "Mind Spike"], ["10.39", "Shadow Word: Pain"], ["12.54", "Divine Image"], ["13.62", "Radiance"], ["14.07", "Mind Spike"], ["15.76", "Shadow Word: Pain"], ["20.06", "Radiance"], ["20.51", "Shadow Word: Pain"], ["20.96", "Mind Spike"], ["24.63", "Divine Image"], ["25.08", "Shadow Word: Pain"], ["26.78", "Radiance"], ["27.23", "Mind Spike"]],
    stats: [["Очки навыков", "крит 0, Potency 0, Luck 0, Mastery 0"], ["Сила атаки", "142.0"], ["Potency", "16.0"], ["Mastery", "10"], ["Рейтинг крита", "0.00"], ["Спешка", "46.0%"], ["Скорость атаки", "86.2%"], ["Мана", "1657"], ["Интервал атаки", "1.07 с"], ["Тик Shadow Word: Pain", "0.68 с"], ["Elemental Orb", "Fire"]],
    items: [["Elemental Orb", "Shop Item", "+15% Attack Speed\n+10% Haste\n+6 All Stats\nUse: Switches between 1 of 3 Orb Powers. (Cooldown: 5 seconds)\nFire: Attacks splash for 20 damage and additional 35% of Primary Attribute.\nFrost: Attacks Chill the target, reducing its movement speed by 50% and its attack speed by 25% for 4 seconds.\nShadow: Attacks ignore 6 of the target's Armor."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."], ["Razorwind", "Shop Item", "+32% Attack Speed\n+18% Haste\n+8 Potency"], ["Razorwind", "Shop Item", "+32% Attack Speed\n+18% Haste\n+8 Potency"]],
  },
  "Holy|5|mixed": {
    label: "Shop + drop",
    dps: "1015.5",
    total: "30465",
    crit: "27%",
    intel: "156",
    manaLeft: "99%",
    talents: ["Smite", "Empyreal Blaze", "Insanity"],
    glyphs: ["Unsealed Power", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 5, Luck 0, Mastery 0",
    sources: [["Всплеск огня", 244.0], ["Автоатака", 234.5], ["Thunder", 158.3], ["Smite", 150.3], ["Mind Spike", 141.4], ["Empyreal Blaze", 87.0]],
    actions: [["0.00", "Radiance"], ["0.45", "Mind Spike"], ["0.90", "Renew"], ["6.79", "Renew"], ["7.88", "Radiance"], ["8.33", "Mind Spike"], ["13.32", "Renew"], ["16.58", "Radiance"], ["17.03", "Mind Spike"], ["19.84", "Renew"], ["25.28", "Radiance"], ["25.73", "Mind Spike"], ["26.18", "Renew"]],
    stats: [["Очки навыков", "крит 0, Potency 5, Luck 0, Mastery 0"], ["Сила атаки", "185.0"], ["Potency", "10.5"], ["Mastery", "0"], ["Рейтинг крита", "0.30"], ["Спешка", "28.0%"], ["Скорость атаки", "83.9%"], ["Мана", "1267"], ["Интервал атаки", "1.09 с"], ["Тик Shadow Word: Pain", "0.78 с"], ["Elemental Orb", "Fire"]],
    items: [["Elemental Orb", "Shop Item", "+15% Attack Speed\n+10% Haste\n+6 All Stats\nUse: Switches between 1 of 3 Orb Powers. (Cooldown: 5 seconds)\nFire: Attacks splash for 20 damage and additional 35% of Primary Attribute.\nFrost: Attacks Chill the target, reducing its movement speed by 50% and its attack speed by 25% for 4 seconds.\nShadow: Attacks ignore 6 of the target's Armor."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Aruzal, Fang of Neltharion", "Mysterious Wanderer", "Binds to Player\n+35 Damage\n+15% Attack Speed\n+15% Critical Strike\nEquip: Critical Strike bonus damage is increased by additional 30%.\nEquip: Your hero deals 18% more damage to enemies below 25% of maximum health."], ["Silent Messenger", "Shop Item", "Crit Relic\n+23 Damage\n+12% Critical Strike\nEquip: Your attacks ignore 3 of the target's Armor.\nEquip: Your Critical Strikes grant you 28% Attack Speed for 3 seconds."], ["Razorwind", "Shop Item", "+32% Attack Speed\n+18% Haste\n+8 Potency"]],
  },
  "Holy|5|shop": {
    label: "Только Shop Item",
    dps: "1015.5",
    total: "30465",
    crit: "27%",
    intel: "156",
    manaLeft: "99%",
    talents: ["Smite", "Empyreal Blaze", "Insanity"],
    glyphs: ["Unsealed Power", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 5, Luck 0, Mastery 0",
    sources: [["Всплеск огня", 244.0], ["Автоатака", 234.5], ["Thunder", 158.3], ["Smite", 150.3], ["Mind Spike", 141.4], ["Empyreal Blaze", 87.0]],
    actions: [["0.00", "Radiance"], ["0.45", "Mind Spike"], ["0.90", "Renew"], ["6.79", "Renew"], ["7.88", "Radiance"], ["8.33", "Mind Spike"], ["13.32", "Renew"], ["16.58", "Radiance"], ["17.03", "Mind Spike"], ["19.84", "Renew"], ["25.28", "Radiance"], ["25.73", "Mind Spike"], ["26.18", "Renew"]],
    stats: [["Очки навыков", "крит 0, Potency 5, Luck 0, Mastery 0"], ["Сила атаки", "185.0"], ["Potency", "10.5"], ["Mastery", "0"], ["Рейтинг крита", "0.30"], ["Спешка", "28.0%"], ["Скорость атаки", "83.9%"], ["Мана", "1267"], ["Интервал атаки", "1.09 с"], ["Тик Shadow Word: Pain", "0.78 с"], ["Elemental Orb", "Fire"]],
    items: [["Elemental Orb", "Shop Item", "+15% Attack Speed\n+10% Haste\n+6 All Stats\nUse: Switches between 1 of 3 Orb Powers. (Cooldown: 5 seconds)\nFire: Attacks splash for 20 damage and additional 35% of Primary Attribute.\nFrost: Attacks Chill the target, reducing its movement speed by 50% and its attack speed by 25% for 4 seconds.\nShadow: Attacks ignore 6 of the target's Armor."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Aruzal, Fang of Neltharion", "Mysterious Wanderer", "Binds to Player\n+35 Damage\n+15% Attack Speed\n+15% Critical Strike\nEquip: Critical Strike bonus damage is increased by additional 30%.\nEquip: Your hero deals 18% more damage to enemies below 25% of maximum health."], ["Silent Messenger", "Shop Item", "Crit Relic\n+23 Damage\n+12% Critical Strike\nEquip: Your attacks ignore 3 of the target's Armor.\nEquip: Your Critical Strikes grant you 28% Attack Speed for 3 seconds."], ["Razorwind", "Shop Item", "+32% Attack Speed\n+18% Haste\n+8 Potency"]],
  },
};

const TARGETS: Record<SpecId, TargetCount[]> = {"Shadow": [5], "Discipline": [5], "Holy": [5]};
const MODES: Record<string, RunId[]> = {"Shadow|5": ["mixed", "shop"], "Discipline|5": ["mixed", "shop"], "Holy|5": ["mixed", "shop"]};
const SPEC_NOTE: Record<SpecId, string> = {"Shadow": "Кнопки Shadow Word: Pain, Mind Spike, Void Rift, Divine Image. Мастерство Shadow умножает тик и мгновенный удар Shadow Word: Pain на 1,10 + 0,006×Mastery.", "Discipline": "Кнопки Radiance, Shadow Word: Pain, Mind Spike, Divine Image. Урон Radiance — 80% лечения после множителя 1,10 + 0,008×Mastery; база делится между целями, Potency бьёт каждую. Naaru — 75% урона Shadow. Touch of the Naaru снимает 0,2 с с Mind Spike. Shadow Word: Pain без множителя мастерства Shadow. Empyreal Blaze: 8% сохранённого лечения (уже ×0,60) раз в секунду, 4 с, или 6 с с Blinding Light. Пока дебафф висит, урон жреца × (1,05 + 0,0008×сила).", "Holy": "Из кнопок урон наносит Mind Spike. Radiance без Empyreal Blaze не бьёт. С этим талантом тик 4% лечения раз в секунду, 4 с, или 6 с с Blinding Light, и тот же бонус по дебаффу. Smite срабатывает при обновлении Renew: 50 + 80% интеллекта + 80% силы по каждой цели в 350. Apotheosis и стаки Dark Evangelism не считаются: раненого союзника в бою нет."};


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

export default function PriestSims() {
  const [spec, setSpec] = useCanvasState<SpecId>("priest-spec", "Shadow");
  const [catalog, setCatalog] = useCanvasState<"all" | "picked">("priest-catalog", "picked");
  const [mode, setMode] = useCanvasState<RunId>("priest-source", "mixed");
  const [targets, setTargets] = useCanvasState<TargetCount>("priest-targets", 1);
  const target = TARGETS[spec].includes(targets) ? targets : TARGETS[spec][0];
  const modeList = MODES[`${spec}|${target}`];
  const source = modeList.includes(mode) ? mode : modeList[0];
  const run = RUNS[`${spec}|${target}|${source}`];
  const talents = catalog === "picked" ? TALENTS.filter((row) => run.talents.includes(row[0])) : TALENTS;
  const glyphs = catalog === "picked" ? GLYPHS.filter((row) => run.glyphs.includes(row[0])) : GLYPHS;

  return (
    <Stack gap={20}>
      <Stack gap={6}>
        <H1>{spec} Priest, {target === 1 ? "1 цель" : target < 5 ? `${target} цели` : "5 целей"}</H1>
        <Text tone="secondary">
          Sunken City v2.5.2a · уровень 6 · 30 секунд · ожидаемый урон, без случайных бросков
        </Text>
      </Stack>

      <Row gap={8} wrap>
        <Pill active={spec === "Shadow"} onClick={() => setSpec("Shadow")}>Shadow</Pill>
        <Pill active={spec === "Discipline"} onClick={() => setSpec("Discipline")}>Discipline</Pill>
        <Pill active={spec === "Holy"} onClick={() => setSpec("Holy")}>Holy</Pill>
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
        Ось категорий: источник урона. Ось значений: урон в секунду за 30 с. Здоровье цели падает с 100% до 0%. Броня манекена 15. Ранги умений 1.
      </Text>

      <Grid columns={2} gap={20}>
        <Stack gap={8}>
          <H3>Порядок кнопок</H3>
          <Table
            headers={["Секунда", "Способность"]}
            columnAlign={["right", "left"]}
            rows={run.actions}
            striped
          />
          <Text size="small" tone="tertiary">
            Каст 0.15 с до эффекта, затем ещё 0.30 с герой занят. Pipe of Deew добавляет 0,3 с оглушения после каста.
          </Text>
        </Stack>
        <Stack gap={8}>
          <H3>Характеристики в бою</H3>
          <Table
            headers={["Параметр", "Значение"]}
            rows={run.stats}
          />
        </Stack>
      </Grid>

      <Divider />

      <H2>Предметы в связке</H2>
      <Text tone="secondary">
        {run.label}. {spec}. {target === 1 ? "1 цель" : target < 5 ? `${target} цели` : "5 целей"}. Очки навыков: {run.points}.
        {run.stats
          .filter(([label]) =>
            label === "Elemental Orb" ||
            label === "Diamond Ring" ||
            label === "Skyfeather Crown" ||
            label === "Masochist Mask" ||
            label === "Runic Gauntlets" ||
            label === "Dragonwrath, Tarecgosa's Rest",
          )
          .map(([label, value]) => ` ${label}: ${value}.`)
          .join("")}
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
        Только эпики и легендарки Странника. Частично стакающиеся и нестакающиеся вещи — одна копия. Несколько копий только если бонус стакается полностью. Одна легендарка. Один Elemental Orb: в названии предмета написан режим Fire, Frost или Shadow. Diamond Ring, Skyfeather Crown, Masochist Mask, Runic Gauntlets и Dragonwrath пишутся вместе с привязанной способностью или режимом. Предметы других классов нельзя. Quest Item и Quest Reward не входят. Cursed Skull бьёт регеном по жрецу, лекарь держит 100% здоровья, исходящий ДПС от этого не меняется. Soulstealer прибавляет к автоатаке 0,3% текущего здоровья цели. Максимум здоровья цели — медиана монстров, 5300. Pipe of Deew: −1,5 с к откату. После каждого заклинания оглушение на 0,3 с: нет атак, кастов и предметов.
      </Callout>
      <Text size="small">{SPEC_NOTE[spec]}</Text>
    </Stack>
  );
}
