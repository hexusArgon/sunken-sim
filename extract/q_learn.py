from pathlib import Path
import sys
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import MAP_PATH, _extract, _parse_objects

units = _parse_objects(_extract(MAP_PATH, "war3map.w3u"))
print("uhab", units["O009"].get("uhab"))
print("uacq", units["O009"].get("uacq"))

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
for code in ("A0GB", "A0JK", "A0MH"):
    print("\n====", code, script.count(f"'{code}'"))
    start = 0
    n = 0
    while n < 6:
        i = script.find(f"'{code}'", start)
        if i < 0:
            break
        window = script[max(0, i - 90) : i + 70].replace("\n", " | ")
        if "AddAbility" in window or "RemoveAbility" in window or "Hero" in window or "Spell" in window:
            print(n, window[:220])
            n += 1
        start = i + 6
    print("shown", n)
