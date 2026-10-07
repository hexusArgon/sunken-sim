import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("Func001Func020Func004Func002C())then")
print(script[i : i + 450])
print("---- unsealed leaf")
i = script.find("function Trig_PreDamage_Increase_Func001Func020Func002Func002Func001C ")
print(script[i : i + 350])
