from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import load_items
from sunken_sim.search import class_item_codes, pools_for

items = load_items()
by = {item.rawcode: item for item in items}
shop, drop, legs = pools_for(items)
pool = {item.rawcode: item for item in shop + drop + legs}
classes = class_item_codes()

print("=== Find Weakness ===")
for item in items:
    if "weakness" in item.name.lower() or "find weakness" in item.tip.lower():
        owners = [name for name, codes in classes.items() if item.rawcode in codes]
        in_pool = item.rawcode in pool
        print(item.rawcode, item.name, "pool", in_pool, "class", owners)
        print(item.tip[:800])
        print("---")

print("\n=== percent health damage lines ===")
for item in pool.values():
    low = item.tip.lower()
    if "health" in low and ("%" in item.tip) and ("damage" in low):
        for line in item.tip.split("\n"):
            l = line.lower()
            if "health" in l and "%" in line and "damage" in l:
                print(item.rawcode, item.name)
                print(" ", line[:220])
