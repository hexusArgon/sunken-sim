import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script, map_wts_text
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
needle = "Trig_PreDamage_Items_Glyphs_Func002Func005Func012C()"
print("calls", script.count(needle))
index = script.find(needle)
print(script[index - 400 : index + 80])
print("\n==== mastery tooltip text ====")
# WTS search for shadow mastery description
wts = map_wts_text()
idx = wts.find("Shadow Specialization")
print("idx", idx)
print(wts[idx:idx+800] if idx>=0 else "no")
idx = wts.lower().find("haste")
print("\nhaste string sample")
# find a tooltip about haste stat
import re
for m in re.finditer(r"Haste.{0,180}", wts):
    s = m.group(0).replace("\n", " ")
    if "cooldown" in s.lower() or "reduc" in s.lower() or "%" in s:
        print(s[:200])
        print("---")
        break
