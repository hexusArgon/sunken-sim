import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
print("0.006", script.count("0.006"))
print("Haste_Stat", script.count("Haste_Stat"))
print("Haste_Items", script.count("Haste_Items"))
index = script.find("function Trig_CDR_Setup_Actions")
print("\nCDR SETUP")
print(script[index : index + 1600])
