"""Rebuild the Mage sim canvas from every finished spec json."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CANVAS_DIR = Path(__file__).resolve().parents[1] / "canvases"
CANVAS = CANVAS_DIR / "mage-sims.canvas.tsx"

sys.path.insert(0, str(ROOT.parent))

SOURCES = (
    ("Frost", ROOT / "frost-sims.json"),
    ("Arcane", ROOT / "arcane-sims.json"),
    ("Fire", ROOT / "fire-sims.json"),
)
LABELS = {"mixed": "Shop + drop", "shop": "Только Shop Item", "drop": "Только Random drop"}
TARGET_WORD = {1: "1 цель", 2: "2 цели", 3: "3 цели", 4: "4 цели", 5: "5 целей"}
NOTES = {
    "Frost": "Кнопки Living Bomb, Blizzard, Arcane Blast, Ring of Frost. Мастерство Frost усиливает снижение урона, в исходящий урон не входит. Волн Blizzard: округление 5×(1+спешка), с Iceflow Mantle 5×(1,20+спешка). Интервал волны 1/(1+спешка).",
    "Arcane": "Blizzard заменён на Evocation. Пассив: +8% магического типа и ещё 1% за каждые 75 маны, в симе мана для этого бонуса держится на максимуме. Стаки Arcane Blast: каждый следующий каст ×1,20, потолок 3, с Arcane Surge 8. Шанс сброса кулдауна считается по Mastery с вещей, пять очков навыков его не двигают.",
    "Fire": "Blizzard заменён на Hydra. Скорость атаки мага на его взмах не идёт, гидры получают 75% этого стата. Pyroblast тратит Cinderflame. В Fire его урон ×(1+0,0075×Mastery), и эти очки навыков в формуле есть.",
}


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


def run_object(run: dict, indent: str) -> str:
    stats = run["stats"]
    points = points_of(run["points"])
    sources = [[row["name"], round(row["amount"] / 30, 1)] for row in run["sources"]]
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
        ["Тик Living Bomb", f"{stats['bomb_period']:.2f} с"],
    ]
    if stats.get("hydra_swing"):
        stat_rows.append(["Интервал гидры", f"{stats['hydra_swing']:.2f} с"])
    if run.get("orb_mode"):
        stat_rows.append(["Elemental Orb", run["orb_mode"]])
    if run.get("bound_spell"):
        stat_rows.append(["Diamond Ring", run["bound_spell"]])
    items = [[item["name"], item["source"], tip_of(item["tip"])] for item in run["items"]]
    body = {
        "label": LABELS[run["label"]],
        "dps": str(run["dps"]),
        "total": str(run["total"]),
        "crit": f"{stats['crit']:.0f}%",
        "intel": f"{stats['int']:.0f}",
        "manaLeft": "—" if run.get("mana_left") is None else f"{run['mana_left']:.0f}%",
        "talents": run["talents"],
        "glyphs": run["glyphs"],
        "points": points,
    }
    lines = [f"{indent}{{"]
    for key in ("label", "dps", "total", "crit", "intel", "manaLeft", "talents", "glyphs", "points"):
        lines.append(f"{indent}  {key}: {js(body[key])},")
    lines.append(f"{indent}  sources: {js(sources)},")
    lines.append(f"{indent}  actions: {js(actions)},")
    lines.append(f"{indent}  stats: {js(stat_rows)},")
    lines.append(f"{indent}  items: {js(items)},")
    lines.append(f"{indent}}},")
    return "\n".join(lines)


def catalog_text() -> str:
    from sunken_sim.library import load_items
    from sunken_sim.mage import TALENTS
    from sunken_sim.search import GLYPHS

    items = {item.rawcode: item for item in load_items()}
    talents = [[name, tip_of(items[code].tip), True] for code, name in TALENTS.items()]
    glyphs = [[name, tip_of(items[code].tip), True] for code, name in GLYPHS.items()]
    return (
        "const TALENTS: Array<[string, string, boolean]> = "
        + js(talents)
        + ";\n\nconst GLYPHS: Array<[string, string, boolean]> = "
        + js(glyphs)
        + ";\n\n"
    )


def load_specs() -> list[tuple[str, dict]]:
    loaded = []
    for name, path in SOURCES:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data:
            loaded.append((name, data))
    return loaded


def write_all() -> None:
    loaded = load_specs()
    if not loaded:
        print("нет готовых симов мага", flush=True)
        return
    spec_ids = [name for name, _data in loaded]
    spec_union = " | ".join(js(name) for name in spec_ids)
    chunks = [
        f"type SpecId = {spec_union};",
        'type RunId = "mixed" | "shop" | "drop";',
        "type TargetCount = 1 | 2 | 3 | 4 | 5;",
        "",
        "type Run = {",
        "  label: string;",
        "  dps: string;",
        "  total: string;",
        "  crit: string;",
        "  intel: string;",
        "  manaLeft: string;",
        "  talents: string[];",
        "  glyphs: string[];",
        "  points: string;",
        "  sources: Array<[string, number]>;",
        "  actions: Array<[string, string]>;",
        "  stats: Array<[string, string]>;",
        "  items: Array<[string, string, string]>;",
        "};",
        "",
        "const RUNS: Record<string, Run> = {",
    ]
    targets_of: dict[str, list[int]] = {}
    modes_of: dict[str, list[str]] = {}
    for name, data in loaded:
        present_targets = []
        for targets in (1, 2, 3, 4, 5):
            modes = [mode for mode in ("mixed", "shop", "drop") if f"{targets}-{mode}" in data]
            if not modes:
                continue
            present_targets.append(targets)
            modes_of[f"{name}|{targets}"] = modes
            for mode in modes:
                run = data[f"{targets}-{mode}"]
                chunks.append(f"  {js(f'{name}|{targets}|{mode}')}: {run_object(run, '  ').strip()}")
        targets_of[name] = present_targets
    chunks.append("};")
    chunks.append("")
    chunks.append(f"const TARGETS: Record<SpecId, TargetCount[]> = {js(targets_of)};")
    chunks.append(f"const MODES: Record<string, RunId[]> = {js(modes_of)};")
    chunks.append(f"const SPEC_NOTE: Record<SpecId, string> = {js({name: NOTES[name] for name in spec_ids})};")
    chunks.append("")
    spec_pills = "\n".join(
        f'        <Pill active={{spec === "{name}"}} onClick={{() => setSpec("{name}")}}>{name}</Pill>'
        for name in spec_ids
    )
    target_pills = "\n".join(
        "        {TARGETS[spec].includes(" + str(n) + ") ? "
        f'<Pill active={{target === {n}}} onClick={{() => setTargets({n})}}>{TARGET_WORD[n]}</Pill> : null}}'
        for n in (1, 2, 3, 4, 5)
    )
    mode_pills = "\n".join(
        "        {MODES[`${spec}|${target}`].includes(\"" + mode + "\") ? "
        f'<Pill active={{source === "{mode}"}} onClick={{() => setMode("{mode}")}}>{LABELS[mode]}</Pill> : null}}'
        for mode in ("mixed", "shop", "drop")
    )
    header = """import {
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

"""
    ui = f"""
function GameText({{ text }}: {{ text: string }}) {{
  return (
    <Text size="small" style={{{{ whiteSpace: "pre-wrap" }}}}>
      {{text}}
    </Text>
  );
}}

function notedName(name: string, stats: Array<[string, string]>): string {{
  const row = stats.find(([label]) => label === name);
  return row ? `${{name}} — ${{row[1]}}` : name;
}}

export default function MageSims() {{
  const [spec, setSpec] = useCanvasState<SpecId>("mage-spec", "{spec_ids[0]}");
  const [catalog, setCatalog] = useCanvasState<"all" | "picked">("mage-catalog", "picked");
  const [mode, setMode] = useCanvasState<RunId>("mage-source", "mixed");
  const [targets, setTargets] = useCanvasState<TargetCount>("mage-targets", 5);
  const target = TARGETS[spec].includes(targets) ? targets : TARGETS[spec][0];
  const modeList = MODES[`${{spec}}|${{target}}`];
  const source = modeList.includes(mode) ? mode : modeList[0];
  const run = RUNS[`${{spec}}|${{target}}|${{source}}`];
  const talents = catalog === "picked" ? TALENTS.filter((row) => run.talents.includes(row[0])) : TALENTS;
  const glyphs = catalog === "picked" ? GLYPHS.filter((row) => run.glyphs.includes(row[0])) : GLYPHS;

  return (
    <Stack gap={{20}}>
      <Stack gap={{6}}>
        <H1>{{spec}} Mage, {{target === 1 ? "1 цель" : target < 5 ? `${{target}} цели` : "5 целей"}}</H1>
        <Text tone="secondary">
          Sunken City v2.5.2a · уровень 6 · 30 секунд · ожидаемый урон, без случайных бросков
        </Text>
      </Stack>

      <Row gap={{8}} wrap>
{spec_pills}
      </Row>
      <Row gap={{8}} wrap>
{target_pills}
      </Row>
      <Row gap={{8}} wrap>
{mode_pills}
      </Row>

      <Grid columns={{5}} gap={{16}}>
        <Stat value={{run.dps}} label="DPS" tone="success" />
        <Stat value={{run.total}} label="Урон за 30 с" />
        <Stat value={{run.crit}} label="Крит" />
        <Stat value={{run.intel}} label="Интеллект" />
        <Stat value={{run.manaLeft}} label="Мана в конце" />
      </Grid>

      <H2>Урон по источникам</H2>
      <BarChart
        horizontal
        height={{260}}
        categories={{run.sources.map((row) => row[0])}}
        series={{[{{ name: "DPS", data: run.sources.map((row) => row[1]), tone: "info" }}]}}
        valueSuffix=" DPS"
        showValues
      />
      <Text size="small" tone="tertiary">
        Ожидаемый урон источника за 30 с, делённый на 30. Броня манекена 15.
      </Text>

      <H2>Порядок кнопок</H2>
      <Table
        headers={{["Секунда", "Заклинание"]}}
        columnAlign={{["right", "left"]}}
        rows={{run.actions}}
      />
      <Text size="small" tone="tertiary">
        Каст 0,15 с до эффекта, затем ещё 0,30 с герой занят. Living Bomb обновляется, если дот спадёт в ближайшую секунду.
      </Text>

      <H2>Характеристики в бою</H2>
      <Table
        headers={{["Параметр", "Значение"]}}
        rows={{run.stats}}
      />

      <Divider />

      <H2>Предметы в связке</H2>
      <Text tone="secondary">
        {{run.label}}. {{spec}}. {{target === 1 ? "1 цель" : target < 5 ? `${{target}} цели` : "5 целей"}}. Очки навыков: {{run.points}}.
      </Text>
      <Table
        headers={{["Предмет", "Источник", "Описание из игры"]}}
        rows={{run.items.map(([name, sourceName, tip]) => [
          notedName(name, run.stats),
          sourceName,
          <GameText text={{tip}} />,
        ])}}
        striped
        rowTone={{run.items.map(() => "success" as const)}}
      />

      <Row gap={{8}} align="center">
        <H2>Таланты и глифы</H2>
        <Pill active={{catalog === "picked"}} onClick={{() => setCatalog("picked")}}>
          В связке
        </Pill>
        <Pill active={{catalog === "all"}} onClick={{() => setCatalog("all")}}>
          Все прогнанные
        </Pill>
      </Row>
      <Text size="small" tone="tertiary">
        Прогнаны все тройки из 18 талантов и все тройки из 32 глифов. На каждом бою проверены все 56 раскладок 5 очков.
      </Text>

      <H3>Таланты</H3>
      <Table
        headers={{["Талант", "Описание из игры"]}}
        rows={{talents.map(([name, tip]) => [name, <GameText text={{tip}} />])}}
        striped
        stickyHeader
        rowTone={{talents.map((row) => (run.talents.includes(row[0]) ? "success" : undefined))}}
      />

      <H3>Глифы</H3>
      <Table
        headers={{["Глиф", "Описание из игры"]}}
        rows={{glyphs.map(([name, tip]) => [name, <GameText text={{tip}} />])}}
        striped
        stickyHeader
        rowTone={{glyphs.map((row) => (run.glyphs.includes(row[0]) ? "success" : undefined))}}
      />

      <Callout tone="warning" title="Правила">
        Те же фильтры предметов, что у жреца: только эпики и легендарки Странника, одна легендарка, один Elemental Orb, без вещей других классов и без квестовых. Поиск предметов жадный. Пять очков навыков не перестраивают очередь кастов: они входят в урон, крит, Potency и в множитель Pyroblast, но не в шанс Cinderflame и не в сброс кулдауна Arcane.
      </Callout>
      <Text size="small">{{SPEC_NOTE[spec]}}</Text>
    </Stack>
  );
}}
"""
    text = header + catalog_text() + "\n".join(chunks) + "\n" + ui
    CANVAS.write_text(text, encoding="utf-8")
    print("wrote", CANVAS, "specs", ", ".join(name for name in spec_ids), flush=True)


if __name__ == "__main__":
    write_all()
