import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
index = script.find("function Trig_ArmorDamage_Increase_Func001Func006Func027C")
print(script[index:index+900])
print("\n==== after pen is set, how damage changes ====")
index = script.find("function Trig_ArmorDamage_Increase_Func001Func008C")
print(script[index:index+200])
# find CalculateArmorPenetration call
i = script.find("CalculateArmorPenetration")
print("\ncalc", i)
print(script[i-200:i+400])
