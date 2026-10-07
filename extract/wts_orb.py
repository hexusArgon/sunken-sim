import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_wts_text
from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
wts = map_wts_text()
idx = 0
n = 0
low = wts.lower()
while n < 8:
    i = low.find("elemental orb", idx)
    if i < 0:
        break
    print(wts[max(0,i-200):i+600].replace("\r","")[:800])
    print("========")
    idx = i + 12
    n += 1
print("hits", n)
