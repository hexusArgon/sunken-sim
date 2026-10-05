"""One empty fight, each allowed talent alone, each allowed item in one slot."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import load_items
from sunken_sim.search import LEGENDARIES, TALENTS, pools_for
from sunken_sim.shadow import ORB_MODE, Build, simulate

ROOT = Path(__file__).resolve().parents[1]


def banned_names() -> set[str]:
    guide = (ROOT / "docs" / "guide.md").read_text(encoding="utf-8")
    priest = (ROOT / "docs" / "priest.md").read_text(encoding="utf-8")
    found = set()
    for text in (guide, priest):
        marker = "Эти вещи в пул не входят:"
        start = text.find(marker)
        if start < 0:
            continue
        chunk = text[start + len(marker) : text.find("\n\n", start)]
        for name in chunk.split(","):
            found.add(name.strip().strip("."))
    return found


def main() -> None:
    ban = banned_names()
    shop, drop, legs = pools_for(load_items())
    shop_ids = {item.rawcode for item in shop}
    items = []
    seen = set()
    for item in shop + drop + legs:
        if item.rawcode in seen or item.name in ban:
            continue
        seen.add(item.rawcode)
        label = item.name
        if item.rawcode in ORB_MODE:
            label = f"{item.name} ({ORB_MODE[item.rawcode]})"
        if item.rawcode in LEGENDARIES:
            source = "Legendary"
        elif item.rawcode in shop_ids:
            source = "Shop"
        else:
            source = "Drop"
        items.append((label, item.rawcode, source, item))

    specs = (("Shadow", "shadow"), ("Discipline", "discipline"), ("Holy", "holy"))
    bare = {
        title: round(simulate(Build(frozenset(), frozenset(), (), 0, 0, 0, 0), 5, spec=spec).dps, 1)
        for title, spec in specs
    }
    talent_rows = [["Без таланта", bare["Shadow"], bare["Discipline"], bare["Holy"]]]
    for _code, name in sorted(TALENTS.items(), key=lambda pair: pair[1]):
        code = _code
        row = [name]
        for title, spec in specs:
            dps = simulate(Build(frozenset({code}), frozenset(), (), 0, 0, 0, 0), 5, spec=spec).dps
            row.append(round(dps, 1))
        talent_rows.append(row)
        print("talent", name, row[1:], flush=True)

    item_rows = [["Без предмета", "", "", bare["Shadow"], bare["Discipline"], bare["Holy"]]]
    for label, rawcode, source, item in items:
        row = [label, rawcode, source]
        for _title, spec in specs:
            dps = simulate(Build(frozenset(), frozenset(), (item,), 0, 0, 0, 0), 5, spec=spec).dps
            row.append(round(dps, 1))
        item_rows.append(row)
        print("item", label, row[2:], flush=True)
    item_rows[1:] = sorted(item_rows[1:], key=lambda row: (-row[3], row[0]))
    out = Path(__file__).with_name("one-slot.json")
    out.write_text(
        json.dumps({"talents": talent_rows, "items": item_rows}, ensure_ascii=False),
        encoding="utf-8",
    )
    print("items", len(item_rows) - 1, "talents", len(talent_rows) - 1, "bare", bare, flush=True)


if __name__ == "__main__":
    main()
