import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path
import re

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
for m in re.finditer(r"set udg_PoG_Haste_Value\[", script):
    print(script[m.start()-120:m.start()+180].replace("\n"," | "))
    print("---")
print("COUNT", len(re.findall(r"set udg_PoG_Haste_Value\[", script)))
print("SUM sets", len(re.findall(r"set udg_PoG_Haste_Sum\[", script)))
