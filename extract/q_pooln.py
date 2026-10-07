from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import load_items
from sunken_sim.search import pools_for
shop, drop, legs = pools_for(load_items())
print("shop", len(shop), "drop", len(drop), "legs", len(legs))
print("shop sample", ", ".join(item.name for item in shop[:8]))
