from pathlib import Path
import sys
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
from sunken_sim.library import _extract, _parse_objects, _load_strings, _resolve

MAP = Path(r"c:\Users\eseid\Documents\Warcraft III\Maps\Download\Sunken City v2.5.2a.w3x")
strings = _load_strings(Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.wts"))
items = _parse_objects(_extract(MAP, "war3map.w3t"))
for code in ("I07O", "I0NS", "I0NT", "I0ET", "I06A", "I0AZ"):
    mods = items.get(code)
    print("\n====", code, "found" if mods else "MISSING")
    if not mods:
        continue
    for key in ("unam", "utub", "ides", "iabi", "iclb"):
        if key in mods:
            vals = mods[key]
            shown = []
            for v in vals:
                if isinstance(v, str):
                    shown.append(_resolve(v, strings)[:180].replace("\n", " | "))
                else:
                    shown.append(repr(v))
            print(key, shown[:8])
