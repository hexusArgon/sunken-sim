import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_wts_text
from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
wts = map_wts_text()
# priest mastery button
idx = wts.find("Priest:")
print("Priest: count", wts.count("Priest:"))
# find mastery class list
idx = wts.find("Necromancer:")
print(wts[idx:idx+2500][:2000])
