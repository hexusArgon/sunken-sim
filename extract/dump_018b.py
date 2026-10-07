import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
name = "Trig_PreDamage_Increase_Func001Func020Func002Func002C"
i = script.find(f"function {name} ")
print(script[i : i + 700])
print("---- parent")
name = "Trig_PreDamage_Increase_Func001Func020Func002C"
i = script.find(f"function {name} ")
print(script[i : i + 400])
