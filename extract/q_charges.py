import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
print("GetItemCharges", script.count("GetItemCharges"))
print("SetItemCharges", script.count("SetItemCharges"))
idx = 0
n = 0
while n < 8:
    i = script.find("GetItemCharges", idx)
    if i < 0:
        break
    print(script[max(0, i - 70) : i + 80].replace("\n", " | ")[:200])
    print("---")
    idx = i + 8
    n += 1
