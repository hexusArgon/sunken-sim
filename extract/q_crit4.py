import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("Trig_Critical_Gain_Func004C())then")
print(script[i : i + 400])
print("--- cond ---")
i = script.find("function Trig_Critical_Gain_Func004C ")
print(script[i : i + 350])
