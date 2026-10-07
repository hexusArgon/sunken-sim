from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import load_catalog
cat = load_catalog()
for code in ("I07O", "I0NS", "I0NT"):
    it = cat[code]
    print("====", code, it.name)
    print(it.tip)
    print("haste", getattr(it, "haste", None), "mastery", getattr(it, "mastery", None), "as", getattr(it, "attack_speed", None), "stats", getattr(it, "all_stats", None), "pen", getattr(it, "armor_pen", None))
