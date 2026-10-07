import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_wts_text
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
wts = map_wts_text()
for key in ("Shadow Specialization", "Holy Specialization", "Discipline Specialization", "Priest:"):
    print(key, wts.find(key))
# spec button text near priest
idx = wts.lower().find("shadow specialization")
print("---")
print(wts[idx:idx+400] if idx>=0 else "no shadow spec phrase")
idx = wts.lower().find("discipline")
print("discipline idx", idx)
print(wts[idx:idx+200] if idx>=0 else "")
