from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
from sunken_sim.library import load_items
from sunken_sim.search import LEGENDARIES, pools_for
from sunken_sim.stacking import item_verdict

shop, drop, legs = pools_for(load_items())
print("shop", len(shop), "drop", len(drop), "legs", len(legs))
print("legendaries", [(item.name, item_verdict(item.rawcode)) for item in legs])
print("partial in shop", sum(1 for item in shop if item_verdict(item.rawcode) == "Частично"))
print("copies ok", sum(1 for item in shop + drop if item.rawcode not in LEGENDARIES and item_verdict(item.rawcode) == "Стакается"))
