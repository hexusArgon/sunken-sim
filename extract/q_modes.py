import re
import sys
from pathlib import Path
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import load_items

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
# priest spec ability
for needle in ("Hero_Priest", "A0MH", "Specialization"):
    print(needle, script.count(needle))

items = load_items()
print("\n=== bind / switch tips ===")
for item in items:
    low = item.tip.lower()
    if "binds the last spell" in low or "switches between" in low or "bound spell" in low:
        print(item.rawcode, item.name)
        for line in item.tip.split("\n"):
            if any(word in line.lower() for word in ("bind", "switch", "bound", "orb power")):
                print(" ", line[:160])
