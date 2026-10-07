from pathlib import Path
import re
import sys
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import MAP_PATH, _extract, _load_strings, _parse_objects, _resolve, load_items, map_strings
from sunken_sim.search import LEGENDARIES

strings = map_strings()
skin = _parse_objects(_extract(MAP_PATH, "war3mapSkin.w3t"))
by = {item.rawcode: item for item in load_items()}
groups = defaultdict(list)
for code, mods in skin.items():
    if "unam" not in mods:
        continue
    raw_id = str(mods["unam"][0])
    raw = strings.get(int(raw_id.split("_")[1]), "") if raw_id.startswith("TRIGSTR_") else raw_id
    found = re.findall(r"\|c([0-9a-fA-F]{8})", raw)
    color = found[0].lower() if found else "none"
    name = by[code].name if code in by else _resolve(raw_id, strings)[:40]
    groups[color].append((name, code, code in LEGENDARIES))

for color, rows in sorted(groups.items(), key=lambda pair: -len(pair[1])):
    print(f"\n== {color} {len(rows)}")
    if len(rows) <= 20:
        for name, code, leg in rows:
            print(f"  {code} {'LEG' if leg else ''} {name}")
