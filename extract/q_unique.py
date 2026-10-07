import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")

def show(name, n=1200):
    i = script.find(f"function {name} ")
    print("\n====", name, i)
    if i >= 0:
        print(script[i : i + n])

show("Trig_Backpack_Items_Acquire_Actions", 1500)
show("Trig_Register_Unique_Epics_Actions", 1500)
show("Trig_Shop_Restricted_Items_Actions", 800)
