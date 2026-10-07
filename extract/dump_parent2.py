import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
call = script.find("if(Trig_PreDamage_Items_Glyphs_Func002Func005Func012C())then")
parent = script.rfind("if(Trig_PreDamage_Items_Glyphs_Func002Func005C())then", 0, call)
print("parent at", parent, "call at", call, "delta", call - parent)
print(script[parent : parent + 250])
print("--- between end snippet ---")
print(script[call - 80 : call + 40])
