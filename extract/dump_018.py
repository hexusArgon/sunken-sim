import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("set udg_MagicalType_Bonus=(udg_MagicalType_Bonus+0.18)")
print("at", i)
# walk back to the if(
back = script.rfind("if(Trig_", 0, i)
print(script[back : i + 40])
name = script[back + 3 : script.find("(", back)]
print("NAME", name)
fn = script.find(f"function {name} ")
print(script[fn : fn + 600])
