"""Rebuild the canvas runs from target-sims.json."""

import json
from pathlib import Path

DATA = json.loads(Path(r"C:\Users\eseid\sunken-sim\extract\target-sims.json").read_text(encoding="utf-8"))
CANVAS = Path(r"C:\Users\eseid\.cursor\projects\c-Users-eseid-sunken-sim\canvases\shadow-priest-sim.canvas.tsx")
text = CANVAS.read_text(encoding="utf-8")
prefix = text[: text.index("type RunId")]

LABELS = {"mixed": "Shop + drop", "shop": "Только Shop Item", "drop": "Только Random drop"}
SOURCE_NAME = {"Shadow Word: Pain (удар при обновлении)": "Боль, обновление"}


def js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def tip_of(raw: str) -> str:
    lines = []
    for line in raw.split("\n"):
        if line.startswith('"') or line.startswith("Shop Item"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def points_of(points: dict) -> str:
    return f"крит {points['crit']}, Potency {points['potency']}, Luck {points['luck']}, Mastery {points['mastery']}"


def run_ts(run: dict, indent: str) -> str:
    stats = run["stats"]
    points = points_of(run["points"])
    sources = [[SOURCE_NAME.get(row["name"], row["name"]), round(row["amount"] / 30, 1)] for row in run["sources"]]
    actions = [[f"{row['time']:.2f}", row["spell"]] for row in run["actions"]]
    stat_rows = [
        ["Очки навыков", points],
        ["Сила атаки", f"{stats['ad']:.1f}"],
        ["Potency", f"{stats['potency']:.1f}"],
        ["Mastery", f"{stats['mastery']:.0f}"],
        ["Рейтинг крита", f"{stats['rating']:.2f}"],
        ["Спешка", f"{stats['haste'] * 100:.1f}%"],
        ["Скорость атаки", f"{stats['attack_speed'] * 100:.1f}%"],
        ["Мана", f"{stats['mana_max']:.0f}"],
        ["Интервал атаки", f"{stats['swing']:.2f} с"],
        ["Тик Shadow Word: Pain", f"{stats['swp_period']:.2f} с"],
    ]
    items = [[item["name"], item["source"], tip_of(item["tip"])] for item in run["items"]]
    body = {
        "label": LABELS[run["label"]],
        "dps": str(run["dps"]),
        "total": str(run["total"]),
        "crit": f"{stats['crit']:.0f}%",
        "intel": f"{stats['int']:.0f}",
        "talents": run["talents"],
        "glyphs": run["glyphs"],
        "points": points,
    }
    lines = [f"{indent}{js(run['label'])}: {{"]
    for key in ("label", "dps", "total", "crit", "intel", "talents", "glyphs", "points"):
        lines.append(f"{indent}  {key}: {js(body[key])},")
    lines.append(f"{indent}  sources: {js(sources)},")
    lines.append(f"{indent}  actions: {js(actions)},")
    lines.append(f"{indent}  stats: {js(stat_rows)},")
    lines.append(f"{indent}  items: {js(items)},")
    lines.append(f"{indent}}},")
    return "\n".join(lines)


chunks = ["type RunId = \"mixed\" | \"shop\" | \"drop\";", "type TargetCount = 1 | 2 | 3 | 4 | 5;", "", "const BY_TARGET: Record<TargetCount, Record<RunId, {", "  label: string;", "  dps: string;", "  total: string;", "  crit: string;", "  intel: string;", "  talents: string[];", "  glyphs: string[];", "  points: string;", "  sources: Array<[string, number]>;", "  actions: Array<[string, string]>;", "  stats: Array<[string, string]>;", "  items: Array<[string, string, string]>;", "}>> = {"]
for targets in (1, 2, 3, 4, 5):
    chunks.append(f"  {targets}: {{")
    for mode in ("mixed", "shop", "drop"):
        chunks.append(run_ts(DATA[f"{targets}-{mode}"], "    "))
    chunks.append("  },")
chunks.append("};")
chunks.append(
    """
function GameText({ text }: { text: string }) {
  return (
    <Text size="small" style={{ whiteSpace: "pre-wrap" }}>
      {text}
    </Text>
  );
}

const TARGET_LABEL = ["", "1 цель", "2 цели", "3 цели", "4 цели", "5 целей"];

export default function ShadowPriestSim() {
  const [catalog, setCatalog] = useCanvasState<"all" | "picked">("shadow-catalog", "picked");
  const [mode, setMode] = useCanvasState<RunId>("shadow-source", "mixed");
  const [targets, setTargets] = useCanvasState<TargetCount>("shadow-targets", 1);
  const run = BY_TARGET[targets][mode];
  const talents = catalog === "picked" ? TALENTS.filter((row) => run.talents.includes(row[0])) : TALENTS;
  const glyphs = catalog === "picked" ? GLYPHS.filter((row) => run.glyphs.includes(row[0])) : GLYPHS;

  return (
    <Stack gap={20}>
      <Stack gap={6}>
        <H1>Shadow Priest, {TARGET_LABEL[targets]}</H1>
        <Text tone="secondary">
          Sunken City v2.5.2a · уровень 6 · 30 секунд · ожидаемый урон, без случайного броска
        </Text>
      </Stack>

      <Row gap={8} wrap>
        {([1, 2, 3, 4, 5] as const).map((count) => (
          <Pill key={count} active={targets === count} onClick={() => setTargets(count)}>
            {TARGET_LABEL[count]}
          </Pill>
        ))}
      </Row>
      <Row gap={8} wrap>
        <Pill active={mode === "mixed"} onClick={() => setMode("mixed")}>Shop + drop</Pill>
        <Pill active={mode === "shop"} onClick={() => setMode("shop")}>Только Shop Item</Pill>
        <Pill active={mode === "drop"} onClick={() => setMode("drop")}>Только Random drop</Pill>
      </Row>

      <Grid columns={4} gap={16}>
        <Stat value={run.dps} label="DPS" tone="success" />
        <Stat value={run.total} label="Урон за 30 с" />
        <Stat value={run.crit} label="Крит" />
        <Stat value={run.intel} label="Интеллект" />
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
        Ось категорий: источник урона. Ось значений: урон в секунду. Здоровье цели падает с 100% до 0% за 30 с. Броня манекена 15, у Silent Messenger 12. Ранги умений 1.
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
            Каст 0.15 с до эффекта, затем ещё 0.30 с герой занят.
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
        {run.label}. {TARGET_LABEL[targets]}. Очки навыков: {run.points}.
      </Text>
      <Table
        headers={["Предмет", "Источник", "Описание из игры"]}
        rows={run.items.map(([name, source, tip]) => [name, source, <GameText text={tip} />])}
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
        Прогнаны все тройки из 18 талантов и все тройки из 32 глифов. На каждом бою проверены все 56 раскладок 5 очков. Одна легендарка. Один Elemental Orb. Haste входит в CDR: кулдаун = (база × множитель − плоский CDR) / (1 + haste), пол 0,50 с.
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
        Одна легендарка Странника. Один Elemental Orb: три кода это режимы одной вещи. Предметы других классов нельзя. Quest Item и Quest Reward не входят. Вещи в одном экземпляре не входят. Cursed Skull бьёт регеном по жрецу, лекарь держит 100% здоровья, исходящий ДПС от этого не меняется.
      </Callout>
    </Stack>
  );
}
"""
)

CANVAS.write_text(prefix + "\n".join(chunks), encoding="utf-8")
print("wrote", CANVAS, "chars", CANVAS.stat().st_size)
for targets in (1, 2, 3, 4, 5):
    for mode in ("mixed", "shop", "drop"):
        run = DATA[f"{targets}-{mode}"]
        names = [item["name"] for item in run["items"]]
        print(f"{targets} {mode:5} {run['dps']:7} {run['points']} {', '.join(names)}")
