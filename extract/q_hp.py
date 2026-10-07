from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import _extract, _parse_objects, _load_strings, _resolve, MAP_PATH, map_strings

strings = map_strings()
units = _parse_objects(_extract(MAP_PATH, "war3map.w3u"))
print("units", len(units))
# sample keys of one unit
sample = next(iter(units))
print("sample", sample, list(units[sample].keys())[:30])
hp = []
for code, mods in units.items():
    if "uhpm" not in mods:
        continue
    abil = " ".join(str(v) for v in mods.get("uabi", []))
    name = ""
    if "unam" in mods:
        name = _resolve(str(mods["unam"][0]), strings)
    hp.append((mods["uhpm"][0], code, name[:40], "Aloc" in abil, "Avul" in abil, "AInv" in abil))
print("with hp", len(hp))
print("hp field type", type(hp[0][0]) if hp else None)
