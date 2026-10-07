import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")

def dump(name: str, size: int = 500) -> None:
    index = script.find(f"function {name} ")
    print("\n", name)
    print(script[index : index + size])

dump("Trig_ArmorDamage_Increase_Func001Func006Func027C", 400)
index = script.find("UnitHasItemOfTypeBJ(udg_DamageEventSource,'ram1')")
print("\nRAM CONTEXT")
print(script[index - 600 : index + 900])
