import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("function Trig_Primary_Gain_Actions")
print(script[i : i + 1100])
print("\n==== stack split head ====")
i = script.find("function Trig_EasyItemStacknSplitGUI_Actions")
print("idx", i)
print(script[i : i + 600] if i >= 0 else "none")
