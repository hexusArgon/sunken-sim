import re
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import MAP_PATH, WTS_PATH, _extract, _load_strings, _parse_objects, _resolve, load_items
from sunken_sim.search import LEGENDARIES, _map_script, pools_for, shop_codes

script = _map_script()
epics = set(re.findall(r"set udg_Drops_Epic\[\d+\]='(.{4})'", script))
rares = set(re.findall(r"set udg_Drops_Rare\[\d+\]='(.{4})'", script))
uncommons = set(re.findall(r"set udg_Drops_Uncommon\[\d+\]='(.{4})'", script))
commons = set(re.findall(r"set udg_Drops_Common\[\d+\]='(.{4})'", script))
print("tables", "epic", len(epics), "rare", len(rares), "unc", len(uncommons), "common", len(commons))
print("legendary in epic", sorted(LEGENDARIES & epics))

shop, drop, legs = pools_for(load_items())
print("pools", len(shop), len(drop), len(legs))
shop_ids = {item.rawcode for item in shop}
drop_ids = {item.rawcode for item in drop}
print("shop that are epic drops", len(shop_ids & epics))
print("drop that are epic", len(drop_ids & epics))
print("drop not epic", len(drop_ids - epics))
print("shop not in any drop table", len(shop_ids - epics - rares - uncommons - commons))

# color on raw name before strip
strings = _load_strings(WTS_PATH)
skin = _parse_objects(_extract(MAP_PATH, "war3mapSkin.w3t"))
colors = {}
for code, mods in skin.items():
    if "unam" not in mods:
        continue
    raw = strings.get(int(re.fullmatch(r"TRIGSTR_(\d+)", mods["unam"][0]).group(1)), "") if str(mods["unam"][0]).startswith("TRIGSTR_") else str(mods["unam"][0])
    found = re.findall(r"\|c([0-9a-fA-F]{8})", raw)
    if found:
        colors.setdefault(found[0].lower(), 0)
        colors[found[0].lower()] += 1
print("name colors", colors)
