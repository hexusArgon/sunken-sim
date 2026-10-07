import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path
import re

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
# custom library functions
names = re.findall(r"function (DCS_\w+) takes", script)
print("custom", names[:40], "n", len(names))
i = script.find("function DCS_Damage")
print("damage fn", i)
# slot loop near item damage
i = script.find("udg_DCS_ItemDamage")
print("var", script.count("udg_DCS_ItemDamage"))
idx = 0
n = 0
while n < 4:
    j = script.find("udg_Inventory_Loop", idx)
    if j < 0:
        break
    window = script[j : j + 200]
    if "Item" in window or "Damage" in window:
        print(window.replace("\n", " | ")[:220])
        print("---")
        n += 1
    idx = j + 10
print("shown", n)
