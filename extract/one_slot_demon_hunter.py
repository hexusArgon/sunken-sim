"""One-slot Demon Hunter screen: each talent, each allowed item, each glyph, 5 targets.

Demon Hunter E00A (Meta E00B): Havoc, Vengeance, Devourer.

    python extract/one_slot_demon_hunter.py
    python extract/one_slot_demon_hunter.py --smoke
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.demon_hunter import IGNORED_TALENTS, TALENTS, simulate
from sunken_sim.library import load_items
from sunken_sim.search import GLYPHS, LEGENDARIES, pools_for
from sunken_sim.shadow import ORB_MODE, Build

SPECS = (
    ("Havoc", "havoc"),
    ("Vengeance", "vengeance"),
    ("Devourer", "devourer"),
)


def _build(talents=(), glyphs=(), items=()) -> Build:
    return Build(frozenset(talents), frozenset(glyphs), tuple(items), 0, 0, 0, 0)


def _pools():
    catalog = load_items()
    shop, drop, legs = pools_for(catalog, "DemonHunter")
    shop_ids = {item.rawcode for item in shop}
    found = {}
    for item in shop + drop + legs:
        label = item.name
        if item.rawcode in ORB_MODE:
            label = f"{item.name} ({ORB_MODE[item.rawcode]})"
        if item.rawcode in LEGENDARIES:
            source = "Legendary"
        elif item.rawcode in shop_ids:
            source = "Shop"
        else:
            source = "Drop"
        found[item.rawcode] = (label, source, item)
    return found


def main() -> None:
    smoke = "--smoke" in sys.argv[1:]
    pools = _pools()
    items = list(pools.items())
    talents = sorted(((c, n) for c, n in TALENTS.items() if c not in IGNORED_TALENTS), key=lambda pair: pair[1])
    glyphs = sorted(GLYPHS.items(), key=lambda pair: pair[1])
    if smoke:
        talents = [next(iter(TALENTS.items()))]
        items = items[:1]
        glyphs = []

    bare = {title: round(simulate(_build(), 5, spec).dps, 1) for title, spec in SPECS}
    print("bare", bare, flush=True)
    titles = [title for title, _ in SPECS]

    talent_rows = [["Талант", "Код"] + [f"{t} DPS" for t in titles]]
    talent_rows.append(["Без таланта", ""] + [bare[t] for t in titles])
    for code, name in talents:
        row = [name, code]
        for _title, spec in SPECS:
            row.append(round(simulate(_build(talents=[code]), 5, spec).dps, 1))
        talent_rows.append(row)
        print("talent", name, row[2:], flush=True)

    item_rows = [["Предмет", "Код", "Источник"] + [f"{t} DPS" for t in titles] + [f"Привязка {t}" for t in titles]]
    item_rows.append(["Без предмета", "", ""] + [bare[t] for t in titles] + [""] * len(titles))
    for rawcode, (label, source, item) in items:
        row = [label, rawcode, source]
        bindings = []
        for _title, spec in SPECS:
            report = simulate(_build(items=[item]), 5, spec)
            row.append(round(report.dps, 1))
            bindings.append(report.bound_spell or "")
        row.extend(bindings)
        item_rows.append(row)
        print("item", label, row[3 : 3 + len(SPECS)], bindings, flush=True)

    def sort_key(row):
        best = max((value for value in row[3 : 3 + len(SPECS)] if value != ""), default=0.0)
        return (-best, row[0])

    item_rows[2:] = sorted(item_rows[2:], key=sort_key)

    glyph_rows = [["Глиф", "Код"] + [f"{t} DPS" for t in titles]]
    glyph_rows.append(["Без глифа", ""] + [bare[t] for t in titles])
    for code, name in glyphs:
        row = [name, code]
        for _title, spec in SPECS:
            row.append(round(simulate(_build(glyphs=[code]), 5, spec).dps, 1))
        glyph_rows.append(row)
        print("glyph", name, row[2:], flush=True)

    bad = [title for title, value in bare.items() if not value > 0]
    if bad:
        raise SystemExit(f"bare DPS is not positive for: {', '.join(bad)}")
    if smoke:
        print("smoke ok", flush=True)
        return
    out = Path(__file__).with_name("demon_hunter-one-slot.json")
    payload = {"specs": titles, "talents": talent_rows, "items": item_rows, "glyphs": glyph_rows}
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print("wrote", out, "items", len(items), "talents", len(talents), "glyphs", len(glyphs), flush=True)


if __name__ == "__main__":
    main()
