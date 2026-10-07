import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")

def show(name, n=1800):
    i = script.find(f"function {name} ")
    print("\n====", name, "at", i)
    print(script[i : i + n] if i >= 0 else "missing")

show("TasItemShop_CanBuyItem", 900)
show("TasItemShop_GiveItem", 2200)
