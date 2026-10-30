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
  ["Fortune", "Utility Glyph\nIncreases your Luck by additional 15%.", false],
];

type SpecId = "Shadow";
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
    dps: "2649.8",
    total: "79495",
    crit: "0%",
    intel: "156",
    manaLeft: "93%",
    talents: ["Psychic Link", "Dark Torment", "Insanity"],
    glyphs: ["Unsealed Power", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 5, Luck 0, Mastery 0",
    sources: [["Void Rift", 1053.1], ["Shadow Word: Pain", 720.3], ["Thunder", 323.0], ["Mind Spike", 229.5], ["Naaru", 132.7], ["Боль, обновление", 126.5], ["Автоатака", 64.6]],
    actions: [["0.00", "Shadow Word: Pain"], ["0.45", "Divine Image"], ["0.90", "Mind Spike"], ["1.35", "Void Rift"], ["5.57", "Shadow Word: Pain"], ["7.45", "Mind Spike"], ["7.90", "Void Rift"], ["11.22", "Shadow Word: Pain"], ["13.10", "Divine Image"], ["13.55", "Void Rift"], ["14.00", "Mind Spike"], ["16.87", "Shadow Word: Pain"], ["20.64", "Mind Spike"], ["21.09", "Void Rift"], ["21.54", "Shadow Word: Pain"], ["26.29", "Shadow Word: Pain"], ["26.74", "Divine Image"], ["27.19", "Mind Spike"], ["27.64", "Void Rift"]],
    stats: [["Очки навыков", "крит 0, Potency 5, Luck 0, Mastery 0"], ["Сила атаки", "127.0"], ["Potency", "2.5"], ["Mastery", "28"], ["Рейтинг крита", "0.00"], ["Спешка", "26.0%"], ["Скорость атаки", "27.4%"], ["Мана", "1517"], ["Интервал атаки", "1.88 с"], ["Тик Shadow Word: Pain", "0.79 с"], ["Elemental Orb", "Shadow"], ["Diamond Ring", "Void Rift"]],
    items: [["Diamond Ring", "Shop Item", "+8% Haste\n+8 Mastery\n+7 All Stats\nUse: Binds the last spell you've cast to this item. (Cooldown: 30 seconds)\nEquip: Your bound spell has its base cooldown reduced by 30%."], ["Elemental Orb", "Shop Item", "+15% Attack Speed\n+10% Haste\n+6 All Stats\nUse: Switches between 1 of 3 Orb Powers. (Cooldown: 5 seconds)\nFire: Attacks splash for 20 damage and additional 35% of Primary Attribute.\nFrost: Attacks Chill the target, reducing its movement speed by 50% and its attack speed by 25% for 4 seconds.\nShadow: Attacks ignore 6 of the target's Armor."], ["Staff of Galactic Fury", "Shop Item", "Magical Caster Relic\n+16 to Primary Attribute\n+10 Mastery\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Increases your base attack cooldown by 20%."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["The Darkglaive", "Random drop", "+12 to Primary Attribute\n+8% Haste\n+6 Agility\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Reduces the effectiveness of Healing Type effects on your hero by 30%."], ["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."]],
  },
  "Shadow|5|shop": {
    label: "Только Shop Item",
    dps: "2452.7",
    total: "73580",
    crit: "0%",
    intel: "243",
    manaLeft: "100%",
    talents: ["Dark Torment", "Catharsis", "Insanity"],
    glyphs: ["Unsealed Power", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 5, Luck 0, Mastery 0",
    sources: [["Void Rift", 680.8], ["Sulfuras", 546.4], ["Shadow Word: Pain", 366.6], ["Thunder", 260.2], ["Mind Spike", 238.3], ["Автоатака", 142.5], ["Naaru", 113.7], ["Боль, обновление", 93.8], ["Sulfuras (удар)", 10.4]],
    actions: [["0.00", "Shadow Word: Pain"], ["0.45", "Divine Image"], ["0.90", "Mind Spike"], ["1.35", "Void Rift"], ["7.13", "Shadow Word: Pain"], ["9.79", "Mind Spike"], ["12.45", "Void Rift"], ["13.78", "Shadow Word: Pain"], ["19.11", "Divine Image"], ["19.56", "Mind Spike"], ["20.44", "Shadow Word: Pain"], ["24.44", "Void Rift"], ["27.10", "Shadow Word: Pain"], ["28.43", "Mind Spike"]],
    stats: [["Очки навыков", "крит 0, Potency 5, Luck 0, Mastery 0"], ["Сила атаки", "192.2"], ["Potency", "2.5"], ["Mastery", "10"], ["Рейтинг крита", "0.00"], ["Спешка", "25.0%"], ["Скорость атаки", "50.2%"], ["Мана", "1876"], ["Интервал атаки", "1.33 с"], ["Тик Shadow Word: Pain", "0.80 с"], ["Elemental Orb", "Shadow"]],
    items: [["Orb of Unstable Magic", "Shop Item", "Magical Caster Relic\n+12 Primary Attribute\n+15% Haste\nEquip: Increases the damage dealt by Magical Type effects by 10%.\nEquip: Every 3rd Magical Type spellcast fires a massive bolt of Arcane Energy at the closest non-Lesser Creature enemy, dealing damage equal to 20% of Primary Attribute for each second of the total base cooldown of the 3 spells that were cast. Spells  benefit from this effect at 10% effectiveness while having Glyph of Arc Striking. This is a Magical Type effect."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Unbound Power Core", "Shop Item", "+55 to Primary Attribute\nEquip: Increases the cooldown of all abilities by 12%. This effect stacks additively."], ["Elemental Orb", "Shop Item", "+15% Attack Speed\n+10% Haste\n+6 All Stats\nUse: Switches between 1 of 3 Orb Powers. (Cooldown: 5 seconds)\nFire: Attacks splash for 20 damage and additional 35% of Primary Attribute.\nFrost: Attacks Chill the target, reducing its movement speed by 50% and its attack speed by 25% for 4 seconds.\nShadow: Attacks ignore 6 of the target's Armor."], ["Sulfuras, Hand of Ragnaros", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+28% Attack Speed\n+10 Mastery\nEquip: Your attacks have 10% chance to strike an additional time.\nEquip: Whenever you cast a spell, you ignite your weapon, causing your next attack to splash for amount equal to 100% of your Primary Attribute. This is a Magical Type effect."]],
  },
  "Shadow|5|drop": {
    label: "Только Random drop",
    dps: "2161.3",
    total: "64838",
    crit: "0%",
    intel: "125",
    manaLeft: "83%",
    talents: ["Psychic Link", "Dark Torment", "Insanity"],
    glyphs: ["Unsealed Power", "Thunder", "Glass Cannon"],
    points: "крит 0, Potency 5, Luck 0, Mastery 0",
    sources: [["Shadow Word: Pain", 734.8], ["Void Rift", 708.1], ["Thunder", 263.5], ["Боль, обновление", 170.5], ["Mind Spike", 152.1], ["Naaru", 93.3], ["Автоатака", 39.0]],
    actions: [["0.00", "Shadow Word: Pain"], ["0.75", "Divine Image"], ["1.50", "Mind Spike"], ["2.25", "Void Rift"], ["3.00", "Shadow Word: Pain"], ["5.62", "Shadow Word: Pain"], ["6.37", "Mind Spike"], ["7.48", "Void Rift"], ["8.23", "Shadow Word: Pain"], ["11.21", "Shadow Word: Pain"], ["11.96", "Divine Image"], ["12.71", "Mind Spike"], ["13.46", "Void Rift"], ["14.21", "Shadow Word: Pain"], ["16.83", "Shadow Word: Pain"], ["17.58", "Mind Spike"], ["18.69", "Void Rift"], ["19.44", "Shadow Word: Pain"], ["22.43", "Shadow Word: Pain"], ["23.18", "Divine Image"], ["23.93", "Mind Spike"], ["24.68", "Void Rift"], ["25.43", "Shadow Word: Pain"], ["28.04", "Shadow Word: Pain"], ["28.79", "Mind Spike"]],
    stats: [["Очки навыков", "крит 0, Potency 5, Luck 0, Mastery 0"], ["Сила атаки", "103.8"], ["Potency", "2.5"], ["Mastery", "10"], ["Рейтинг крита", "0.00"], ["Спешка", "29.0%"], ["Скорость атаки", "7.2%"], ["Мана", "1600"], ["Интервал атаки", "1.87 с"], ["Тик Shadow Word: Pain", "0.78 с"]],
    items: [["Harness of Beyond", "Random drop", "+30 Intelligence\n-10 Strength\nEquip: Your abilities have their base cooldown reduced by 8%."], ["Pipe of Deew", "Random drop", "+200 Mana\nEquip: Reduces the cooldowns of all abilities by 1,5 seconds.\nEquip: Your spellcasts have 15% chance to stun you for 2 seconds."], ["Staff of the Magister", "Random drop", "+10 Intelligence\n+100 Mana\n+8% Haste\nEquip: Targeting an enemy with a spell deals 40 damage plus additional 8% of your maximum mana. This is a Magical Type effect."], ["The Darkglaive", "Random drop", "+12 to Primary Attribute\n+8% Haste\n+6 Agility\nEquip: Increases the damage dealt by Magical Type effects by 30%.\nEquip: Reduces the effectiveness of Healing Type effects on your hero by 30%."], ["The Zircon Star", "Random drop", "+13 to Primary Attribute\n+13% Haste"], ["Atiesh, Greatstaff of the Guardian", "Mysterious Wanderer", "Binds to Player\n+20 to Primary Attribute\n+10 Mastery\n+250 Mana\nEquip: Increases the damage dealt by Magical Type effects by 20%.\nEquip: Your abilities have their base cooldown reduced by 13%."]],
  },
};

const TARGETS: Record<SpecId, TargetCount[]> = {"Shadow": [5]};
const MODES: Record<string, RunId[]> = {"Shadow|5": ["mixed", "shop", "drop"]};
const SPEC_NOTE: Record<SpecId, string> = {"Shadow": "Кнопки Shadow Word: Pain, Mind Spike, Void Rift, Divine Image. Мастерство Shadow умножает тик и мгновенный удар Shadow Word: Pain на 1,10 + 0,006×Mastery."};

const TALENT_SHADOW_DPS: Record<string, number> = {"Dark Torment": 156.7, "Insanity": 149.9, "Catharsis": 149.8, "Psychic Link": 144.9, "Answered Prayers": 139.7, "Touch of the Naaru": 135.4, "Cosmic Horrors": 135.1, "Clairvoyance": 133.0, "Smite": 132.0, "Empyreal Blaze": 132.0, "Blinding Light": 132.0, "Dark Evangelism": 132.0};
const GLYPH_SHADOW_DPS: Record<string, number> = {"Fortitude": 159.9, "Hellfire": 158.2, "Thunder": 157.8, "Unsealed Power": 155.7, "Glass Cannon": 151.8, "Mindhaste": 136.9, "Blood Violence": 135.7, "Supremacy": 134.7, "Animosity": 133.7, "Battle Frenzy": 133.6, "Arc Striking": 132.0, "Fortune": 132.0};
const ITEM_SHADOW_DPS: Record<string, number> = {"Atiesh, Greatstaff of the Guardian": 225.8, "Unbound Power Core": 222.5, "Elemental Orb (Fire)": 218.0, "The Darkglaive": 201.4, "Staff of Galactic Fury": 197.1, "Harness of Beyond": 191.5, "Elemental Orb (Shadow)": 176.8, "Diamond Ring": 173.9, "The Zircon Star": 164.4, "Staff of the Magister": 163.8, "Pipe of Deew": 152.0};


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

function shadowItemDps(name: string, stats: Array<[string, string]>): number {
  const mode = stats.find(([label]) => label === name);
  const keyed = mode ? `${name} (${mode[1]})` : name;
  return ITEM_SHADOW_DPS[keyed] ?? ITEM_SHADOW_DPS[name] ?? -1;
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
  const talents = (catalog === "picked" ? TALENTS.filter((row) => run.talents.includes(row[0])) : TALENTS)
    .slice()
    .sort((a, b) => (TALENT_SHADOW_DPS[b[0]] ?? -1) - (TALENT_SHADOW_DPS[a[0]] ?? -1));
  const glyphs = (catalog === "picked" ? GLYPHS.filter((row) => run.glyphs.includes(row[0])) : GLYPHS)
    .slice()
    .sort((a, b) => (GLYPH_SHADOW_DPS[b[0]] ?? -1) - (GLYPH_SHADOW_DPS[a[0]] ?? -1));
  const rankedItems = [...run.items].sort(
    (a, b) => shadowItemDps(b[0], run.stats) - shadowItemDps(a[0], run.stats),
  );

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
        rows={rankedItems.map(([name, sourceName, tip]) => [
          notedName(name, run.stats),
          sourceName,
          <GameText text={tip} />,
        ])}
        striped
        rowTone={rankedItems.map(() => "success" as const)}
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
        Прогнаны все тройки из 8 талантов Shadow и все тройки из 12 глифов, которые поднимают урон. На победителе проверены все 56 раскладок 5 очков.
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
