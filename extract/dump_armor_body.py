import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
index = script.find("function Trig_PreDamage_Items_Glyphs_Func002Func005C ")
print(script[index : index + 350])
print("\n==== armor function body ====")
index = script.find("function Trig_ArmorDamage_Increase_Actions")
print(script[index : index + 1800])
