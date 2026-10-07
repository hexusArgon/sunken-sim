from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import _extract, _parse_objects, _load_strings, _resolve, map_strings

MAP = Path(__file__).resolve().parents[1] / "maps" / "Sunken City v2.5.2a.w3x"
strings = map_strings()
items = _parse_objects(_extract(MAP, "war3map.w3t"))
for code in ("I07O", "I0ET", "I06A", "I0AZ"):
    print(code, list(items[code].keys()))
    for key, vals in items[code].items():
        print(" ", key, vals[:4])
