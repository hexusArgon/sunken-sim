import sys
sys.path.insert(0, r"C:\Users\eseid\sunken-sim")
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import load_items
from sunken_sim.search import pools_for
shop, drop, legs = pools_for(load_items())
print("shop", len(shop), "drop", len(drop), "legs", len(legs))
print("shop sample", ", ".join(item.name for item in shop[:8]))
