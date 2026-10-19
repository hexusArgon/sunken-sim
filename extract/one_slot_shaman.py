"""One-slot Shaman screen: each talent alone, each allowed item in one slot, 5 targets."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import load_items
from sunken_sim.search import GLYPHS, LEGENDARIES, pools_for
from sunken_sim.shaman import TALENTS, simulate
from sunken_sim.shadow import ORB_MODE, Build

SPECS = (("Restoration", "restoration"), ("Enhancement", "enhancement"), ("Elemental", "elemental"))


def main() -> None:
    shop, drop, legs = pools_for(load_items(), "Shaman")
    shop_ids = {item.rawcode for item in shop}
    items = []
    seen = set()
    for item in shop + drop + legs:
        if item.rawcode in seen:
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

    bare = {
        title: round(simulate(Build(frozenset(), frozenset(), (), 0, 0, 0, 0), 5, spec).dps, 1)
        for title, spec in SPECS
    }
    talent_rows = [["Талант", "Restoration DPS", "Enhancement DPS", "Elemental DPS"]]
    talent_rows.append(["Без таланта", bare["Restoration"], bare["Enhancement"], bare["Elemental"]])
    for code, name in sorted(TALENTS.items(), key=lambda pair: pair[1]):
        row = [name]
        for _title, spec in SPECS:
            dps = simulate(Build(frozenset({code}), frozenset(), (), 0, 0, 0, 0), 5, spec).dps
            row.append(round(dps, 1))
        talent_rows.append(row)
        print("talent", name, row[1:], flush=True)

    item_rows = [[
        "Предмет",
        "Код",
        "Источник",
        "Restoration DPS",
        "Enhancement DPS",
        "Elemental DPS",
        "Привязка Restoration",
        "Привязка Enhancement",
        "Привязка Elemental",
    ]]
    item_rows.append(["Без предмета", "", "", bare["Restoration"], bare["Enhancement"], bare["Elemental"], "", "", ""])
    for label, rawcode, source, item in items:
        row = [label, rawcode, source]
        bindings = []
        for _title, spec in SPECS:
            report = simulate(Build(frozenset(), frozenset(), (item,), 0, 0, 0, 0), 5, spec)
            row.append(round(report.dps, 1))
            bindings.append(report.bound_spell or "")
        row.extend(bindings)
        item_rows.append(row)
        print("item", label, row[3:6], bindings, flush=True)
    item_rows[2:] = sorted(item_rows[2:], key=lambda row: (-row[4], row[0]))
    glyph_rows = [["Глиф", "Код", "Restoration DPS", "Enhancement DPS", "Elemental DPS"]]
    glyph_rows.append(["Без глифа", "", bare["Restoration"], bare["Enhancement"], bare["Elemental"]])
    for code, name in sorted(GLYPHS.items(), key=lambda pair: pair[1]):
        row = [name, code]
        for _title, spec in SPECS:
            dps = simulate(Build(frozenset(), frozenset({code}), (), 0, 0, 0, 0), 5, spec).dps
            row.append(round(dps, 1))
        glyph_rows.append(row)
        print("glyph", name, row[2:], flush=True)
    out = Path(__file__).with_name("shaman-one-slot.json")
    payload = {"talents": talent_rows, "items": item_rows, "glyphs": glyph_rows}
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print("wrote", out, "items", len(items), "talents", len(TALENTS), "glyphs", len(GLYPHS), flush=True)


if __name__ == "__main__":
    main()
