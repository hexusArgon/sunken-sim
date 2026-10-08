import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from sunken_sim.library import MAP_PATH, _extract, _parse_objects, _resolve, map_strings

strings = map_strings()
units = _parse_objects(_extract(MAP_PATH, "war3map.w3u"))
fields = ("unam", "ustr", "uagi", "uint", "ustb", "uagb", "uinb", "udp1", "udp2", "udp3", "udp4", "udp5", "uabo", "uhab", "uabi", "ua1b", "ua1d", "ua1c", "ua1t", "umvs", "ulev", "uhpm", "umpm", "upoi")
for code, mods in units.items():
    blob = " ".join(str(v) for values in mods.values() for v in values)
    if "A0GE" not in blob and "Paladin" not in blob:
        continue
    name = ""
    if "unam" in mods:
        name = _resolve(str(mods["unam"][0]), strings)
    print("UNIT", code, name)
    for field in fields:
        if field in mods:
            print(" ", field, mods[field][:6])
