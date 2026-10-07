import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
idx = 0
n = 0
while n < 10:
    i = script.find("UnitItemInSlot", idx)
    if i < 0:
        break
    window = script[max(0, i - 60) : i + 180]
    if "DCS" in window or "DamageBonus" in window:
        print(window.replace("\n", " | ")[:260])
        print("---")
        n += 1
    idx = i + 12
print("hits", n)
# LoadInteger item damage
print("LoadInteger", script.count("LoadInteger"))
i = script.find("DamageBonus")
print(script[i - 80 : i + 120].replace("\n", " | ")[:220])
