import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
from sunken_sim.library import load_items
from sunken_sim.search import LEGENDARIES, epic_codes

def tip_of(raw: str) -> str:
    lines = []
    for line in raw.split("\n"):
        if line.startswith('"') or line == "Shop Item":
            continue
        lines.append(line)
    return "\n".join(lines).strip()

def explain_stacks(text: str) -> str:
    if not text:
        return "Вторая копия не прибавляет чисел. У вещи нет бонуса, который игра суммирует по слотам."
    return "Каждая копия в отдельном слоте добавляет: " + text + "."

def explain_blocked(text: str) -> str:
    if not text:
        return "Нет эффекта, который вторая копия обязана потерять."
    sentences = []
    for piece in text.split(", "):
        if piece.startswith("способность:"):
            sentences.append(
                "Способность предмета выдаётся один раз и не повторяется на второй копии: "
                + piece.split(":", 1)[1].strip()
                + "."
            )
        elif "вещь надета" in piece:
            sentences.append(
                "Особый эффект только проверяет, что вещь надета. Вторая копия не делает его сильнее."
            )
        elif "легендарка" in piece:
            sentences.append("Вторую легендарку игра удаляет, даже если часть её чисел могла бы сложиться.")
        elif "Elemental Orb" in piece:
            sentences.append("Второй Elemental Orb игра удаляет. Режим остаётся один.")
        elif "привязка" in piece:
            sentences.append(
                "Привязка заклинания одна на героя. Минус 30% кулдауна применяется один раз, даже если привязана та же способность."
            )
        else:
            sentences.append(piece + ".")
    return " ".join(sentences)

data = json.loads(Path(r"C:\Users\eseid\sunken-sim\extract\stack-rows.json").read_text(encoding="utf-8"))
tips = {item.rawcode: tip_of(item.tip) for item in load_items()}
keep = epic_codes() | set(LEGENDARIES)
rows = [
    {
        "verdict": row["verdict"],
        "name": row["name"],
        "stacks": explain_stacks(row["stacks"]),
        "blocked": explain_blocked(row["blocked"]),
        "tip": tips.get(row["code"], ""),
    }
    for row in data["rows"]
    if row["code"] in keep
]
body = json.dumps(rows, ensure_ascii=False)
counts = {
    "Стакается": sum(1 for row in rows if row["verdict"] == "Стакается"),
    "Не стакается": sum(1 for row in rows if row["verdict"] == "Не стакается"),
    "Частично": sum(1 for row in rows if row["verdict"] == "Частично"),
}
text = f"""import {{
  Callout,
  Divider,
  H1,
  H2,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
  useCanvasState,
}} from "cursor/canvas";

type Mode = "all" | "yes" | "no" | "mix";

const ROWS: Array<{{ verdict: string; name: string; stacks: string; blocked: string; tip: string }}> = {body};

const LABEL: Record<Exclude<Mode, "all">, string> = {{
  yes: "Стакается",
  no: "Не стакается",
  mix: "Частично",
}};

function GameText({{ text }}: {{ text: string }}) {{
  return (
    <Text size="small" style={{{{ whiteSpace: "pre-wrap" }}}}>
      {{text}}
    </Text>
  );
}}

export default function ItemSelfStack() {{
  const [mode, setMode] = useCanvasState<Mode>("stack-filter", "all");
  const shown = ROWS.filter((row) => mode === "all" || row.verdict === LABEL[mode]);
  return (
    <Stack gap={{20}}>
      <Stack gap={{8}}>
        <H1>Стакинг копии предмета</H1>
        <Text tone="secondary">
          Вторая копия в другом слоте. В списке только эпики и легендарки Странника. Сим надевает несколько копий, если у вещи есть стакающийся бонус. Нестакающаяся часть считается один раз.
        </Text>
      </Stack>
      <Callout tone="warning" title="Diamond Ring">
        Можно положить вторую копию в другой слот. Привязка заклинания одна на героя: использование любого кольца перезаписывает её. Минус 30% кулдауна применяется один раз, даже если привязана та же способность. Haste +8 и Mastery +8 со второй копии прибавляются. +7 ко всем статам — способность кольца, игра выдаёт её один раз.
      </Callout>
      <Row gap={{16}} wrap>
        <Stat value="{counts['Стакается']}" label="Стакается" />
        <Stat value="{counts['Не стакается']}" label="Не стакается" />
        <Stat value="{counts['Частично']}" label="Частично" />
      </Row>
      <Text>
        Стакается: бонус с подбора (Haste, Mastery, крит, Potency, Luck, основной атрибут, скорость атаки) и белый урон, который игра суммирует по слотам. Не стакается: способность на вещи (+статы, +урон, +здоровье, +мана, +броня) и любой эффект с проверкой «вещь надета». Вторая легендарка и второй Elemental Orb удаляются.
      </Text>
      <Divider />
      <H2>Все вещи с известным бонусом</H2>
      <Row gap={{8}} wrap>
        <Pill active={{mode === "all"}} onClick={{() => setMode("all")}}>Все {{ROWS.length}}</Pill>
        <Pill active={{mode === "yes"}} onClick={{() => setMode("yes")}}>Стакается {counts['Стакается']}</Pill>
        <Pill active={{mode === "no"}} onClick={{() => setMode("no")}}>Не стакается {counts['Не стакается']}</Pill>
        <Pill active={{mode === "mix"}} onClick={{() => setMode("mix")}}>Частично {counts['Частично']}</Pill>
      </Row>
      <Table
        headers={{["Вердикт", "Предмет", "Что даёт каждая копия", "Что даётся один раз", "Описание из игры"]}}
        rows={{shown.map((row) => [row.verdict, row.name, row.stacks, row.blocked, <GameText text={{row.tip}} />])}}
        striped
        stickyHeader
      />
      <Text size="small" tone="tertiary">
        Источник: триггеры подбора и способности предметов Sunken City v2.5.2a. Показано {{shown.length}} из {{ROWS.length}}.
      </Text>
    </Stack>
  );
}}
"""
# The f-string above doubled braces for JSX. Fix the shown.length which I escaped wrong.
path = Path(r"C:\Users\eseid\.cursor\projects\c-Users-eseid-sunken-sim\canvases\item-self-stack.canvas.tsx")
path.write_text(text, encoding="utf-8")
print("wrote", path, "chars", path.stat().st_size)
