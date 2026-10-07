import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
needle = "Func001Func020Func008Func005C())then"
i = script.find(needle)
print(script[i : i + 600])
print("--- cond ---")
i = script.find("function Trig_PreDamage_Increase_Func001Func020Func008Func005C ")
print(script[i : i + 400])
