from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
from sunken_sim.library import _extract, _parse_objects, _load_strings, _resolve, MAP_PATH, WTS_PATH

strings = _load_strings(WTS_PATH)
skin = _parse_objects(_extract(MAP_PATH, "war3mapSkin.w3t"))
for code in ("I07O", "I0NS", "I0NT", "I0ET", "I06A", "I0AZ"):
    mods = skin.get(code)
    print("\n====", code, "skin" if mods else "NO SKIN")
    if not mods:
        continue
    for key in ("unam", "utub", "ides"):
        if key in mods:
            print(_resolve(mods[key][0], strings)[:1200])
            print("---")
