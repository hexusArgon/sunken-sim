import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("set udg_MagicalType_Dynamic=(udg_MagicalType_Dynamic+0.15)")
print(script[i - 200 : i + 80])
# condition of the 0.15
back = script.rfind("if(Trig_PreDamage_Increase_", 0, i)
name = script[back + 3 : script.find("()", back)]
print("COND", name)
fn = script.find(f"function {name} ")
print(script[fn : fn + 500])
