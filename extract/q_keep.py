from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import MAP_PATH, _extract, _load_strings, _parse_objects, load_items, map_strings
from sunken_sim.search import LEGENDARIES, pools_for

strings = map_strings()
skin = _parse_objects(_extract(MAP_PATH, "war3mapSkin.w3t"))

def color_of(code):
    mods = skin.get(code)
    if not mods or "unam" not in mods:
        return "none"
    raw_id = str(mods["unam"][0])
    raw = strings.get(int(raw_id.split("_")[1]), "") if raw_id.startswith("TRIGSTR_") else raw_id
    found = re.findall(r"\|c([0-9a-fA-F]{8})", raw)
    return found[0].lower() if found else "none"

shop, drop, legs = pools_for(load_items())
print("orange drops")
for item in drop:
    if color_of(item.rawcode) == "00f28302":
        print(item.rawcode, item.name, item.tip.split("\n")[0][:80])
print("red drops")
for item in drop:
    if color_of(item.rawcode) == "ffdc1c28":
        print(item.rawcode, item.name)
print("shop non-purple")
for item in shop:
    if color_of(item.rawcode) != "007c2abb":
        print(color_of(item.rawcode), item.rawcode, item.name)
