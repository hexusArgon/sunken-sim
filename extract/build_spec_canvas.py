"""Rebuild the single Priest sim canvas from every finished spec json."""

import json
from pathlib import Path

ROOT = Path(r"C:\Users\eseid\sunken-sim\extract")
CANVAS_DIR = Path(r"C:\Users\eseid\.cursor\projects\c-Users-eseid-sunken-sim\canvases")
CANVAS = CANVAS_DIR / "priest-sims.canvas.tsx"
SHADOW = CANVAS_DIR / "shadow-priest-sim.canvas.tsx"

SOURCES = (
    ("Shadow", ROOT / "target-sims.json"),
    ("Discipline", ROOT / "discipline-sims.json"),
    ("Holy", ROOT / "holy-sims.json"),
)
LABELS = {"mixed": "Shop + drop", "shop": "Только Shop Item", "drop": "Только Random drop"}
SOURCE_NAME = {"Shadow Word: Pain (удар при обновлении)": "Боль, обновление"}
TARGET_WORD = {1: "1 цель", 2: "2 цели", 3: "3 цели", 4: "4 цели", 5: "5 целей"}
NOTES = {
    "Shadow": "Кнопки Shadow Word: Pain, Mind Spike, Void Rift, Divine Image. Мастерство Shadow умножает тик и мгновенный удар Shadow Word: Pain на 1,10 + 0,006×Mastery.",
    "Discipline": "Кнопки Radiance, Shadow Word: Pain, Mind Spike, Divine Image. Урон Radiance — 80% лечения после множителя 1,10 + 0,008×Mastery; база делится между целями, Potency бьёт каждую. Naaru — 75% урона Shadow. Touch of the Naaru снимает 0,2 с с Mind Spike. Shadow Word: Pain без множителя мастерства Shadow. Empyreal Blaze: 8% сохранённого лечения (уже ×0,60) раз в секунду, 4 с, или 6 с с Blinding Light. Пока дебафф висит, урон жреца × (1,05 + 0,0008×сила).",
    "Holy": "Из кнопок урон наносит Mind Spike. Radiance без Empyreal Blaze не бьёт. С этим талантом тик 4% лечения раз в секунду, 4 с, или 6 с с Blinding Light, и тот же бонус по дебаффу. Smite срабатывает при обновлении Renew: 50 + 80% интеллекта + 80% силы по каждой цели в 350. Apotheosis и стаки Dark Evangelism не считаются: раненого союзника в бою нет.",
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


def catalog_prefix() -> str:
    for path in (CANVAS, SHADOW):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if "const TALENTS" not in text:
            continue
        cut = text.find("type SpecId")
        if cut < 0:
            cut = text.find("type RunId")
        if cut > 0:
            return text[:cut]
    raise SystemExit("нет каталога талантов")


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
        print("нет готовых симов", flush=True)
        return
    prefix = catalog_prefix()
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

export default function PriestSims() {{
  const [spec, setSpec] = useCanvasState<SpecId>("priest-spec", "{spec_ids[0]}");
  const [catalog, setCatalog] = useCanvasState<"all" | "picked">("priest-catalog", "picked");
  const [mode, setMode] = useCanvasState<RunId>("priest-source", "mixed");
  const [targets, setTargets] = useCanvasState<TargetCount>("priest-targets", 1);
  const target = TARGETS[spec].includes(targets) ? targets : TARGETS[spec][0];
  const modeList = MODES[`${{spec}}|${{target}}`];
  const source = modeList.includes(mode) ? mode : modeList[0];
  const run = RUNS[`${{spec}}|${{target}}|${{source}}`];
  const talents = catalog === "picked" ? TALENTS.filter((row) => run.talents.includes(row[0])) : TALENTS;
  const glyphs = catalog === "picked" ? GLYPHS.filter((row) => run.glyphs.includes(row[0])) : GLYPHS;

  return (
    <Stack gap={{20}}>
      <Stack gap={{6}}>
        <H1>{{spec}} Priest, {{target === 1 ? "1 цель" : target < 5 ? `${{target}} цели` : "5 целей"}}</H1>
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
        Ось категорий: источник урона. Ось значений: урон в секунду за 30 с. Здоровье цели падает с 100% до 0%. Броня манекена 15. Ранги умений 1.
      </Text>

      <Grid columns={{2}} gap={{20}}>
        <Stack gap={{8}}>
          <H3>Порядок кнопок</H3>
          <Table
            headers={{["Секунда", "Способность"]}}
            columnAlign={{["right", "left"]}}
            rows={{run.actions}}
            striped
          />
          <Text size="small" tone="tertiary">
            Каст 0.15 с до эффекта, затем ещё 0.30 с герой занят. Pipe of Deew добавляет 0,3 с оглушения после каста.
          </Text>
        </Stack>
        <Stack gap={{8}}>
          <H3>Характеристики в бою</H3>
          <Table
            headers={{["Параметр", "Значение"]}}
            rows={{run.stats}}
          />
        </Stack>
      </Grid>

      <Divider />

      <H2>Предметы в связке</H2>
      <Text tone="secondary">
        {{run.label}}. {{spec}}. {{target === 1 ? "1 цель" : target < 5 ? `${{target}} цели` : "5 целей"}}. Очки навыков: {{run.points}}.
        {{run.stats
          .filter(([label]) =>
            label === "Elemental Orb" ||
            label === "Diamond Ring" ||
            label === "Skyfeather Crown" ||
            label === "Masochist Mask" ||
            label === "Runic Gauntlets" ||
            label === "Dragonwrath, Tarecgosa's Rest",
          )
          .map(([label, value]) => ` ${{label}}: ${{value}}.`)
          .join("")}}
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
        Только эпики и легендарки Странника. Частично стакающиеся и нестакающиеся вещи — одна копия. Несколько копий только если бонус стакается полностью. Одна легендарка. Один Elemental Orb: в названии предмета написан режим Fire, Frost или Shadow. Diamond Ring, Skyfeather Crown, Masochist Mask, Runic Gauntlets и Dragonwrath пишутся вместе с привязанной способностью или режимом. Предметы других классов нельзя. Quest Item и Quest Reward не входят. Cursed Skull бьёт регеном по жрецу, лекарь держит 100% здоровья, исходящий ДПС от этого не меняется. Soulstealer прибавляет к автоатаке 0,3% текущего здоровья цели. Максимум здоровья цели — медиана монстров, 5300. Pipe of Deew: −1,5 с к откату. После каждого заклинания оглушение на 0,3 с: нет атак, кастов и предметов.
      </Callout>
      <Text size="small">{{SPEC_NOTE[spec]}}</Text>
    </Stack>
  );
}}
"""
    # The f-string above doubled braces for TS. Spec pills were inserted raw.
    text = prefix + "\n".join(chunks) + "\n" + ui
    CANVAS.write_text(text, encoding="utf-8")
    print("wrote", CANVAS, "specs", ", ".join(f"{name} {len(targets_of[name])} цели" for name in spec_ids), flush=True)


def write_canvas(_spec: str | None = None) -> None:
    write_all()


if __name__ == "__main__":
    write_all()
