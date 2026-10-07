import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")

def dump(name: str, size: int = 400) -> None:
    index = script.find(f"function {name} ")
    print("\n", name, index)
    print(script[index : index + size].replace("\n", " | ")[:size])

dump("Trig_ArmorDamage_Increase_Func001C", 350)
dump("Trig_ArmorDamage_Increase_Func001Func006C", 400)

print("\n==== ram1 damage contexts ====")
index = 0
shown = 0
while shown < 6:
    index = script.find("'ram1'", index)
    if index < 0:
        break
    window = script[max(0, index - 80) : index + 200]
    if "Damage" in window or "1.50" in window or "0.06" in window or "Attack" in window and "Gain" not in window:
        print(window.replace("\n", " | ")[:320])
        print()
        shown += 1
    index += 6
print("shown", shown)
