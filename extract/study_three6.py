import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
needle = "Trig_PreDamage_Items_Glyphs_Func002Func005Func016Func002C()"
index = script.find(needle)
print("call", index)
print(script[index - 200 : index + 1200])
print("\n\n==== pen types rest ====")
index = script.find("function Trig_ArmorDamage_Increase_Func001Func006Func027C")
print(script[index : index + 900])
