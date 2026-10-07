from pathlib import Path
import statistics
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import _extract, _parse_objects, _load_strings, _resolve, MAP_PATH, map_strings

strings = map_strings()
units = _parse_objects(_extract(MAP_PATH, "war3map.w3u"))
skip_words = ("dummy", "portal", "chest", "picker", "barrel", "effect", "spawn", "waypoint", "camera", "circle", "region")

rows = []
for code, mods in units.items():
    if "uhpm" not in mods or "udef" not in mods:
        continue
    abil = ",".join(str(v) for v in mods.get("uabi", []))
    if any(flag in abil for flag in ("Aloc", "Avul", "AInv")):
        continue
    if mods.get("ubdg", [0])[0] not in (0, None):
        continue
    name = _resolve(str(mods["unam"][0]), strings) if "unam" in mods else ""
    blob = f"{name} {code}".lower()
    if any(word in blob for word in skip_words):
        continue
    rows.append((int(mods["uhpm"][0]), code, name))

rows.sort()
values = [hp for hp, _, _ in rows]
print("count", len(rows))
print("median", statistics.median(values))
print("min", values[0], "max", values[-1])
# show a few around median
mid = len(values) // 2
for hp, code, name in rows[max(0, mid - 3) : mid + 4]:
    print(hp, code, name[:50])
