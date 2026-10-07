import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("function Trig_EasyItemStacknSplitGUI_Func019C ")
print(script[i : i + 500])
print("--- 004 ---")
i = script.find("function Trig_EasyItemStacknSplitGUI_Func019Func004C ")
print(script[i : i + 400])
