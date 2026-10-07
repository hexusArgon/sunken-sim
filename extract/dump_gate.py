import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
for name in (
    "Trig_PreDamage_Increase_Func001Func020C",
    "Trig_PreDamage_Increase_Func001Func024C",
    "Trig_PreDamage_Increase_Func001C",
):
    i = script.find(f"function {name} ")
    print("\n====", name)
    print(script[i : i + 450])
