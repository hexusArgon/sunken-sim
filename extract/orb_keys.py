from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
from sunken_sim.library import _extract, _parse_objects, _load_strings, _resolve

MAP = Path(r"c:\Users\eseid\Documents\Warcraft III\Maps\Download\Sunken City v2.5.2a.w3x")
strings = _load_strings(Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.wts"))
items = _parse_objects(_extract(MAP, "war3map.w3t"))
for code in ("I07O", "I0ET", "I06A", "I0AZ"):
    print(code, list(items[code].keys()))
    for key, vals in items[code].items():
        print(" ", key, vals[:4])
