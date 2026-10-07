import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_wts_text
from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
wts = map_wts_text()
for key in ["Haste", "Mastery", "Shadow Word", "ignore armor", "Elemental Orb"]:
    print(key, wts.lower().count(key.lower()))
# haste description likely "reduces the cooldown"
idx = wts.find("reduces the cooldown of your abilities")
print("\nreduces idx", idx)
idx = wts.lower().find("cooldown reduction")
print("cdr idx", idx)
# print a window around first "Haste" that looks like a stat explanation
import re
for m in re.finditer(r".{80}Haste.{120}", wts):
    s = m.group(0).replace("\n"," ")
    if "abil" in s.lower() or "cooldown" in s.lower() or "cast" in s.lower() or "%" in s:
        print(s[:220])
        print("---")
