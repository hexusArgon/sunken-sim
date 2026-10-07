import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")

i = script.find("bj_forLoopAIndexEnd=udg_Drops_EpicUnique")
print("FIRST LOOP")
print(script[i - 400 : i + 700])
print("\n\n==== inventory count ====")
idx = 0
n = 0
while n < 6:
    j = script.find("UnitInventoryCount", idx)
    if j < 0:
        break
    print(script[max(0, j - 80) : j + 100].replace("\n", " | ")[:220])
    print("---")
    idx = j + 10
    n += 1
