"""One-slot Paladin screen: each talent alone, each allowed item in one slot, 5 targets."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import load_items
from sunken_sim.paladin import TALENTS, simulate
from sunken_sim.search import LEGENDARIES, pools_for
from sunken_sim.shadow import ORB_MODE, Build

SPECS = (("Retribution", "retribution"), ("Protection", "protection"), ("Holy", "holy"))


def main() -> None:
    shop, drop, legs = pools_for(load_items(), "Paladin")
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
    talent_rows = [["Талант", "Retribution DPS", "Protection DPS", "Holy DPS"]]
    talent_rows.append(["Без таланта", bare["Retribution"], bare["Protection"], bare["Holy"]])
    for code, name in sorted(TALENTS.items(), key=lambda pair: pair[1]):
        row = [name]
        for _title, spec in SPECS:
            dps = simulate(Build(frozenset({code}), frozenset(), (), 0, 0, 0, 0), 5, spec).dps
            row.append(round(dps, 1))
        talent_rows.append(row)
        print("talent", name, row[1:], flush=True)

    item_rows = [["Предмет", "Код", "Источник", "Retribution DPS", "Protection DPS", "Holy DPS"]]
    item_rows.append(["Без предмета", "", "", bare["Retribution"], bare["Protection"], bare["Holy"]])
    for label, rawcode, source, item in items:
        row = [label, rawcode, source]
        for _title, spec in SPECS:
            dps = simulate(Build(frozenset(), frozenset(), (item,), 0, 0, 0, 0), 5, spec).dps
            row.append(round(dps, 1))
        item_rows.append(row)
        print("item", label, row[3:], flush=True)
    item_rows[2:] = sorted(item_rows[2:], key=lambda row: (-row[3], row[0]))
    out = Path(__file__).with_name("paladin-one-slot.json")
    out.write_text(json.dumps({"talents": talent_rows, "items": item_rows}, ensure_ascii=False), encoding="utf-8")
    print("wrote", out, "items", len(items), "talents", len(TALENTS), flush=True)


if __name__ == "__main__":
    main()
