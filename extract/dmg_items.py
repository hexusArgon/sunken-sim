from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import load_items
from sunken_sim.search import pools_for

shop, drop, legs = pools_for(load_items())
n = 0
for item in shop + drop + legs:
    if item.damage_pct:
        n += 1
        if n <= 15:
            print(item.rawcode, item.name, item.damage_pct)
            for line in item.tip.split("\n"):
                if "%" in line and ("damage" in line.lower() or "Magical" in line or "Physical" in line):
                    print("  ", line[:180])
print("count", n)
