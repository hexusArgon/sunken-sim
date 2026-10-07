import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")

def dump(name: str, size: int = 1800) -> None:
    index = script.find(f"function {name} ")
    print("\n====", name, index)
    print(script[index : index + size])

dump("Trig_Haste_Gain_Actions", 2200)
