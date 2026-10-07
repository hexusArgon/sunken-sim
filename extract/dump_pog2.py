import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
idx = script.find("function Trig_PoG")
print("first PoG func", idx)
# find function names
import re
names = re.findall(r"function (Trig_\w*PoG\w*)", script)
print(names[:40], "count", len(names))
idx = script.find("set udg_PoG_Haste_Value")
print("\nset haste value", idx)
print(script[idx-200:idx+400] if idx>0 else "none")
idx = script.find("udg_PoG_Haste=")
print("\nassign haste", script[idx-100:idx+250] if idx>0 else "none")
