from pathlib import Path
import sys
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import _extract, _parse_objects, MAP_PATH

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
items = _parse_objects(_extract(MAP_PATH, "war3map.w3t"))
skin = _parse_objects(_extract(MAP_PATH, "war3mapSkin.w3t"))

# sample shop gear and a drop
for code in ("I07P", "I0NT", "I0BB", "I04F", "I03L", "ritd"):
    mods = items.get(code, {})
    sk = skin.get(code, {})
    print("\n", code)
    for key in ("iabi", "iusa", "istr", "isst", "isto", "ipow", "icid", "ilev", "icla"):
        if key in mods:
            print(" ", key, mods[key])
        elif key in sk:
            print("  skin", key, sk[key])
    print("  jass mentions", script.count(f"'{code}'"))
