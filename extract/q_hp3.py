from pathlib import Path
import statistics
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import _extract, _parse_objects, _load_strings, _resolve, MAP_PATH, map_strings

strings = map_strings()
units = _parse_objects(_extract(MAP_PATH, "war3map.w3u"))

def name_of(mods):
    if "unam" not in mods:
        return ""
    return _resolve(str(mods["unam"][0]), strings)

# show huge hp
print("huge")
for code, mods in units.items():
    if "uhpm" in mods and int(mods["uhpm"][0]) >= 50000:
        print(int(mods["uhpm"][0]), code, name_of(mods)[:60], "udef" in mods, "uabi", mods.get("uabi", [])[:2])

rows = []
for code, mods in units.items():
    if "uhpm" not in mods or "udef" not in mods:
        continue
    if "ua1b" not in mods and "ua1c" not in mods:
        continue
    abil = ",".join(str(v) for v in mods.get("uabi", []))
    if any(flag in abil for flag in ("Aloc", "Avul", "AInv")):
        continue
    if mods.get("ubdg", [0])[0] not in (0, None):
        continue
    name = name_of(mods)
    blob = f"{name} {code}".lower()
    if any(word in blob for word in ("dummy", "portal", "chest", "picker", "ward", "totem")):
        continue
    rows.append(int(mods["uhpm"][0]))
rows.sort()
print("fighters", len(rows), "median", statistics.median(rows))
print("p25", rows[len(rows)//4], "p75", rows[3*len(rows)//4])
