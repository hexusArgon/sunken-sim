import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
idx = 0
n = 0
while n < 6:
    i = script.find("AddItemToStock", idx)
    if i < 0:
        break
    print(script[max(0, i - 80) : i + 160].replace("\n", " | ")[:280])
    print("---")
    idx = i + 10
    n += 1
