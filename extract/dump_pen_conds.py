import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")

def fn(name: str) -> None:
    index = script.find(f"function {name} ")
    print("\n====", name)
    print(script[index : index + 700])

fn("Trig_ArmorDamage_Increase_Func001C")
fn("Trig_ArmorDamage_Increase_Func001Func006C")
fn("Trig_ArmorDamage_Increase_Func001Func006Func003C")
fn("Trig_ArmorDamage_Increase_Func001Func006Func005C")
fn("Trig_ArmorDamage_Increase_Func001Func006Func007C")
fn("Trig_ArmorDamage_Increase_Func001Func006Func009C")
fn("Trig_ArmorDamage_Increase_Func001Func027C")
