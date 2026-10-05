import re
import sys
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import MAP_PATH, WTS_PATH, _extract, _load_strings, _parse_objects, load_items
from sunken_sim.search import _map_script, pools_for

script = _map_script()
epics = set(re.findall(r"set udg_Drops_Epic\[\d+\]='(.{4})'", script))
strings = _load_strings(WTS_PATH)
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
print("purple drops not in Drops_Epic")
for item in drop:
    if color_of(item.rawcode) == "007c2abb" and item.rawcode not in epics:
        print(item.rawcode, item.name, item.tip.split("\n")[0][:70])
