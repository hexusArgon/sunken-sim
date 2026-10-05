import re
import sys
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import MAP_PATH, WTS_PATH, _extract, _load_strings, _parse_objects, load_items
from sunken_sim.search import LEGENDARIES, _map_script, pools_for

script = _map_script()
epics = set(re.findall(r"set udg_Drops_Epic\[\d+\]='(.{4})'", script))
strings = _load_strings(WTS_PATH)
skin = _parse_objects(_extract(MAP_PATH, "war3mapSkin.w3t"))

def color_of(code):
    mods = skin.get(code)
    if not mods or "unam" not in mods:
        return "missing"
    raw_id = str(mods["unam"][0])
    raw = strings.get(int(raw_id.split("_")[1]), "") if raw_id.startswith("TRIGSTR_") else raw_id
    found = re.findall(r"\|c([0-9a-fA-F]{8})", raw)
    return found[0].lower() if found else "none"

from collections import Counter
print("drop epic colors", Counter(color_of(code) for code in epics))
shop, drop, legs = pools_for(load_items())
print("shop colors", Counter(color_of(item.rawcode) for item in shop))
print("drop colors", Counter(color_of(item.rawcode) for item in drop))
# purple shop sample
by = {item.rawcode: item.name for item in shop}
n = 0
for item in shop:
    if color_of(item.rawcode) == "007c2abb":
        print("shop epic", item.rawcode, item.name)
        n += 1
        if n >= 12:
            break
print("shop purple", sum(1 for item in shop if color_of(item.rawcode) == "007c2abb"))
print("drop purple", sum(1 for item in drop if color_of(item.rawcode) == "007c2abb"))
print("drop epic table but not purple", [code for code in epics if color_of(code) != "007c2abb"][:15])
