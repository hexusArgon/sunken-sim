"""Rebuild the Shaman canvas from the Enhancement and Elemental farm files."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sunken_sim.library import load_items
from sunken_sim.search import GLYPHS
from sunken_sim.shaman import TALENTS, simulate
from sunken_sim.shadow import ORB_MODE, Build

ROOT = Path(__file__).resolve().parents[1]
CANVAS = ROOT / "canvases" / "shaman-sims.canvas.tsx"
IDE_CANVAS = Path(r"C:\Users\eseid\.cursor\projects\c-Users-eseid-sunken-sim\canvases\shaman-sims.canvas.tsx")
ONE_SLOT = ROOT / "extract" / "shaman-one-slot.json"
SPECS = {
    "enhancement": {
        "title": "Enhancement",
        "preset": "shaman-enhancement-top80.json",
        "talent_dps": 2,
        "glyph_dps": 3,
        "files": (
            Path(r"C:\Users\eseid\Downloads\eseid-main-shaman-enhancement-mixed-5-0-248334471.json"),
            Path(r"C:\Users\eseid\Downloads\eseid-notebook-shaman-enhancement-mixed-5-248334472-310418089.json"),
        ),
        "note": "Молния бьёт всех, Lesser и Stormfury не больше трёх.",
    },
    "elemental": {
        "title": "Elemental",
        "preset": "shaman-elemental-top80.json",
        "talent_dps": 3,
        "glyph_dps": 4,
        "files": (
            Path(r"C:\Users\eseid\Downloads\eseid-main-shaman-elemental-mixed-5-0-263855375.json"),
            Path(r"C:\Users\eseid\Downloads\eseid-notebook-shaman-elemental-mixed-5-263855376-310418089.json"),
        ),
        "note": "Молния бьёт всех. Lava Burst и Liquid Magma бьют одну цель.",
    },
}
POOLS = (("mixed", "top", "Shop + drop"), ("shop", "top_shop", "Только Shop Item"), ("drop", "top_random", "Только Random drop"))
SOURCE_LABEL = {"shop": "Shop Item", "drop": "Random drop", "legendary": "Mysterious Wanderer"}


def comma(value: float, digits: int) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def plain(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def signature(row: dict) -> tuple:
    return (
        tuple(sorted(item["code"] for item in row["items"])),
        tuple(sorted(row["talents"])),
        tuple(sorted(row["glyphs"])),
        tuple(sorted(row["points"].items())),
    )


def merged(payloads: list[dict], key: str) -> list[dict]:
    rows = [row for payload in payloads for row in payload.get(key) or []]
    rows.sort(key=lambda row: -row["dps"])
    seen: set[tuple] = set()
    chosen = []
    for row in rows:
        mark = signature(row)
        if mark in seen:
            continue
        seen.add(mark)
        chosen.append(row)
        if len(chosen) == 10:
            break
    return chosen


def item_name(item) -> str:
    mode = ORB_MODE.get(item.rawcode)
    if mode:
        return f"{item.name} ({mode})"
    return item.name


def grouped(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def caption(payloads: list[dict]) -> str:
    parts = [
        f"{payload['worker']} {grouped(payload['start'])}–{grouped(payload['end'])}, ошибок {payload['errors']}"
        for payload in payloads
    ]
    return (
        "Sunken City v2.5.2a · уровень 6 · 30 секунд · набор топ-80 и Mind Amplifier · "
        + " · ".join(parts)
    )


def resim(row: dict, by_code: dict, spec: str) -> dict:
    talent_codes = frozenset(code for code, name in TALENTS.items() if name in row["talents"])
    glyph_codes = frozenset(code for code, name in GLYPHS.items() if name in row["glyphs"])
    if len(talent_codes) != len(row["talents"]) or len(glyph_codes) != len(row["glyphs"]):
        raise KeyError(row["talents"] + row["glyphs"])
    items = tuple(by_code[item["code"]] for item in row["items"])
    points = row["points"]
    build = Build(talent_codes, glyph_codes, items, points["potency"], points["mastery"], points["crit"], points["luck"])
    report = simulate(build, 5, spec)
    stats = report.stats
    sources = [
        [name, round(amount / 30, 1)]
        for name, amount in sorted(report.sources.items(), key=lambda pair: -pair[1])
        if amount > 0.05
    ]
    actions = [[f"{moment:.2f}", spell] for moment, spell in report.actions]
    stat_rows = [
        ["Таланты", ", ".join(row["talents"])],
        ["Глифы", ", ".join(row["glyphs"])],
        ["Очки навыков", f"крит {points['crit']}, Potency {points['potency']}, Luck {points['luck']}, Mastery {points['mastery']}"],
        ["Сила", f"{stats['str']:.0f}"],
        ["Ловкость", f"{stats['agi']:.0f}"],
        ["Интеллект", f"{stats['int']:.0f}"],
        ["Сила атаки", f"{stats['ad']:.1f}"],
        ["Potency", f"{stats['potency']:.1f}"],
        ["Mastery", f"{stats['mastery']:.0f}"],
        ["Крит", f"{stats['crit']:.0f}%"],
        ["Рейтинг крита", f"{stats['rating']:.2f}"],
        ["Спешка", f"{stats['haste'] * 100:.1f}%"],
        ["Скорость атаки", f"{stats['attack_speed'] * 100:.1f}%"],
        ["Мана", f"{stats['mana_max']:.0f}"],
        ["Интервал атаки", f"{stats['swing']:.2f} с"],
        ["Мана в конце", f"{report.mana_left:.0f}%"],
    ]
    if report.orb_mode:
        stat_rows.append(["Elemental Orb", report.orb_mode])
    if report.bound_spell:
        stat_rows.append(["Diamond Ring", report.bound_spell])
    shown = []
    for raw, item in zip(row["items"], items):
        name = item_name(item)
        if item.rawcode == "I00D" and report.bound_spell:
            name = f"Diamond Ring ({report.bound_spell})"
        shown.append([name, SOURCE_LABEL.get(raw["source"], raw["source"]), plain(item.tip)])
    return {
        "label": "",
        "farm": f"{row['dps']:.1f}",
        "dps": f"{report.dps:.1f}",
        "total": str(round(report.total)),
        "crit": f"{stats['crit']:.0f}%",
        "intel": f"{stats['int']:.0f}",
        "manaLeft": f"{report.mana_left:.0f}%",
        "sources": sources,
        "actions": actions,
        "stats": stat_rows,
        "items": shown,
        "chunk": row["chunk"],
    }


def catalog(saved: dict, spec: str) -> tuple[list[dict], list[dict]]:
    by_code = {item.rawcode: item for item in load_items()}
    info = SPECS[spec]
    preset = json.loads((ROOT / "extract" / info["preset"]).read_text(encoding="utf-8"))
    allowed = {TALENTS[code] for code in preset["talents"]}
    talents = []
    for row in saved["talents"][1:]:
        if row[0] not in allowed:
            continue
        code = next(code for code, name in TALENTS.items() if name == row[0])
        talents.append({"name": row[0], "tip": plain(by_code[code].tip), "dps": row[info["talent_dps"]]})
    glyphs = []
    for row in saved["glyphs"][1:]:
        if not row[1]:
            continue
        glyphs.append(
            {
                "name": row[0],
                "tip": plain(by_code[row[1]].tip) if row[1] in by_code else "",
                "dps": row[info["glyph_dps"]],
            }
        )
    return talents, glyphs


def main() -> None:
    by_code = {item.rawcode: item for item in load_items()}
    saved = json.loads(ONE_SLOT.read_text(encoding="utf-8"))
    runs = {}
    specs = {}
    for spec, info in SPECS.items():
        payloads = [json.loads(path.read_text(encoding="utf-8")) for path in info["files"]]
        for pool, key, label in POOLS:
            for place, row in enumerate(merged(payloads, key), start=1):
                print(f"{spec} {pool} #{place} farm {row['dps']:.1f}", flush=True)
                built = resim(row, by_code, spec)
                built["label"] = label
                runs[f"{spec}|{pool}|{place}"] = built
                print(f"  sim {built['dps']}", flush=True)
        talents, glyphs = catalog(saved, spec)
        specs[spec] = {
            "title": info["title"],
            "caption": caption(payloads),
            "note": info["note"],
            "talents": talents,
            "glyphs": glyphs,
        }
    body = f"""import {{
  BarChart,
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
}} from "cursor/canvas";

type SpecId = "enhancement" | "elemental";
type PoolId = "mixed" | "shop" | "drop";

type Run = {{
  label: string;
  dps: string;
  farm: string;
  total: string;
  crit: string;
  intel: string;
  manaLeft: string;
  sources: Array<[string, number]>;
  actions: Array<[string, string]>;
  stats: Array<[string, string]>;
  items: Array<[string, string, string]>;
  chunk: number;
}};

type Entry = {{ name: string; tip: string; dps: number }};
type SpecInfo = {{
  title: string;
  caption: string;
  note: string;
  talents: Entry[];
  glyphs: Entry[];
}};

const RUNS: Record<string, Run> = {json.dumps(runs, ensure_ascii=False)};
const SPECS: Record<SpecId, SpecInfo> = {json.dumps(specs, ensure_ascii=False)};

const POOLS: Array<[PoolId, string]> = [
  ["mixed", "Shop + drop"],
  ["shop", "Только Shop Item"],
  ["drop", "Только Random drop"],
];

function ranksFor(spec: SpecId, pool: PoolId): string[] {{
  return Object.keys(RUNS)
    .filter((id) => id.startsWith(`${{spec}}|${{pool}}|`))
    .sort((a, b) => Number(RUNS[b].dps) - Number(RUNS[a].dps) || Number(a.split("|")[2]) - Number(b.split("|")[2]));
}}

function GameText({{ text }}: {{ text: string }}) {{
  return (
    <Text size="small" style={{{{ whiteSpace: "pre-wrap" }}}}>
      {{text}}
    </Text>
  );
}}

export default function ShamanSims() {{
  const [spec, setSpec] = useCanvasState<SpecId>("shaman-spec", "elemental");
  const [pool, setPool] = useCanvasState<PoolId>("shaman-pool", "mixed");
  const [rank, setRank] = useCanvasState<string>("shaman-rank", "1");
  const [catalogMode, setCatalogMode] = useCanvasState<"picked" | "all">("shaman-catalog", "picked");
  const chosenSpec: SpecId = spec === "enhancement" ? "enhancement" : "elemental";
  const info = SPECS[chosenSpec];
  const available = POOLS.filter(([id]) => ranksFor(chosenSpec, id).length > 0);
  const chosenPool: PoolId = available.some(([id]) => id === pool) ? pool : "mixed";
  const ranks = ranksFor(chosenSpec, chosenPool);
  const chosenRank = ranks.some((id) => id.endsWith(`|${{rank}}`)) ? rank : "1";
  const run = RUNS[`${{chosenSpec}}|${{chosenPool}}|${{chosenRank}}`];
  const pickedTalents = (run.stats.find((row) => row[0] === "Таланты")?.[1] ?? "").split(", ").filter(Boolean);
  const pickedGlyphs = (run.stats.find((row) => row[0] === "Глифы")?.[1] ?? "").split(", ").filter(Boolean);
  const talentRows = (catalogMode === "picked" ? info.talents.filter((entry) => pickedTalents.includes(entry.name)) : info.talents)
    .slice()
    .sort((a, b) => b.dps - a.dps);
  const glyphRows = (catalogMode === "picked" ? info.glyphs.filter((entry) => pickedGlyphs.includes(entry.name)) : info.glyphs)
    .slice()
    .sort((a, b) => b.dps - a.dps);

  return (
    <Stack gap={{20}}>
      <Stack gap={{6}}>
        <H1>{{info.title}} Shaman, 5 целей</H1>
        <Text tone="secondary">{{info.caption}}</Text>
      </Stack>

      <Row gap={{8}} wrap>
        <Pill active={{chosenSpec === "enhancement"}} onClick={{() => setSpec("enhancement")}}>Enhancement</Pill>
        <Pill active={{chosenSpec === "elemental"}} onClick={{() => setSpec("elemental")}}>Elemental</Pill>
      </Row>
      <Row gap={{8}} wrap>
        <Pill active={{true}}>5 целей</Pill>
      </Row>
      <Row gap={{8}} wrap>
        {{available.map(([id, label]) => (
          <Pill active={{chosenPool === id}} onClick={{() => setPool(id)}}>{{label}}</Pill>
        ))}}
      </Row>
      {{ranks.length > 1 ? (
        <Row gap={{8}} wrap>
          {{ranks.map((id) => {{
            const place = id.split("|")[2];
            return (
              <Pill active={{chosenRank === place}} onClick={{() => setRank(place)}}>
                {{`${{place}} · ${{RUNS[id].dps}}`}}
              </Pill>
            );
          }})}}
        </Row>
      ) : null}}

      <Grid columns={{5}} gap={{16}}>
        <Stat value={{run.dps}} label="DPS" tone="success" />
        <Stat value={{run.total}} label="Урон за 30 с" />
        <Stat value={{run.crit}} label="Крит" />
        <Stat value={{run.intel}} label="Интеллект" />
        <Stat value={{run.manaLeft}} label="Мана в конце" />
      </Grid>
      {{run.farm !== run.dps ? (
        <Text size="small" tone="tertiary">
          В файле фермы у этой связки {{run.farm}} DPS. Разбор ниже — текущий сим.
        </Text>
      ) : null}}
      {{run.stats.find((row) => row[0] === "Diamond Ring") ? (
        <Text size="small" tone="tertiary">
          Diamond Ring привязан к {{run.stats.find((row) => row[0] === "Diamond Ring")?.[1]}}. База кулдауна этой способности −30%.
        </Text>
      ) : null}}
      {{run.items.some(([name]) => name === "Pipe of Deew") ? (
        <Text size="small" tone="tertiary">
          Pipe of Deew: каждый каст оглушает героя на 0,3 с. В это время нет атак и новых способностей.
        </Text>
      ) : null}}

      <H2>Урон по источникам</H2>
      <BarChart
        horizontal
        height={{280}}
        categories={{run.sources.map((row) => row[0])}}
        series={{[{{ name: "DPS", data: run.sources.map((row) => row[1]) }}]}}
        valueSuffix=" DPS"
        showValues
      />
      <Text size="small" tone="tertiary">
        Ось категорий: источник урона. Ось значений: урон в секунду за 30 с. Броня манекена 15. Ранги умений 1. Пять целей стоят в одной точке. {{info.note}}
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
            Каст 0,15 с до эффекта, затем ещё 0,30 с герой занят. В таблице все нажатия за 30 с. Чанк {{run.chunk}}.
          </Text>
        </Stack>
        <Stack gap={{8}}>
          <H3>Характеристики в бою</H3>
          <Table headers={{["Параметр", "Значение"]}} rows={{run.stats}} />
        </Stack>
      </Grid>

      <Divider />

      <H2>Предметы в связке</H2>
      <Text tone="secondary">{{run.label}}. {{info.title}}. 5 целей.</Text>
      <Table
        headers={{["Предмет", "Источник", "Описание из игры"]}}
        rows={{run.items.map(([name, sourceName, tip]) => [name, sourceName, <GameText text={{tip}} />])}}
        striped
      />

      <Row gap={{8}} align="center">
        <H2>Таланты и глифы</H2>
        <Pill active={{catalogMode === "picked"}} onClick={{() => setCatalogMode("picked")}}>В связке</Pill>
        <Pill active={{catalogMode === "all"}} onClick={{() => setCatalogMode("all")}}>Все прогнанные</Pill>
      </Row>
      <Text size="small" tone="tertiary">
        Порядок — соло-DPS {{info.title}}: один талант или один глиф, пустой инвентарь, 5 целей. В прогоне {{info.talents.length}} талантов набора и {{info.glyphs.length}} глифов.
      </Text>
      <H3>Таланты</H3>
      <Table
        headers={{["Талант", info.title, "Описание из игры"]}}
        columnAlign={{["left", "right", "left"]}}
        rows={{talentRows.map((entry) => [entry.name, entry.dps.toFixed(1), <GameText text={{entry.tip}} />])}}
        striped
        rowTone={{talentRows.map((entry) => (pickedTalents.includes(entry.name) ? "success" : undefined))}}
      />
      <H3>Глифы</H3>
      <Table
        headers={{["Глиф", info.title, "Описание из игры"]}}
        columnAlign={{["left", "right", "left"]}}
        rows={{glyphRows.map((entry) => [entry.name, entry.dps.toFixed(1), <GameText text={{entry.tip}} />])}}
        striped
        rowTone={{glyphRows.map((entry) => (pickedGlyphs.includes(entry.name) ? "success" : undefined))}}
      />
    </Stack>
  );
}}
"""
    CANVAS.write_text(body, encoding="utf-8")
    IDE_CANVAS.write_text(body, encoding="utf-8")
    print("wrote", CANVAS, "runs", len(runs), flush=True)


if __name__ == "__main__":
    main()
