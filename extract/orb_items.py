from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import _extract, _parse_objects, _load_strings, _resolve, map_strings

MAP = Path(__file__).resolve().parents[1] / "maps" / "Sunken City v2.5.2a.w3x"
strings = map_strings()
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
