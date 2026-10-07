import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_wts_text
from pathlib import Path
import re, sys
sys.stdout.reconfigure(encoding="utf-8")
wts = map_wts_text()
for m in re.finditer(r"Each point of Mastery.{0,220}", wts):
    print(m.group(0).replace("\n", " ")[:240])
    print("---")
print("\n==== Haste stat button ====")
idx = wts.find("The Haste stat")
print("idx", idx)
if idx < 0:
    idx = wts.find("Haste |c")
print(wts[idx:idx+900] if idx>=0 else "no haste intro")
