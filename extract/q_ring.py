import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
print("DiamondRing count", script.count("DiamondRing"))
print("I00D count", script.count("'I00D'"))
start = 0
n = 0
while n < 25:
    i = script.find("DiamondRing", start)
    if i < 0:
        break
    print(n, script[max(0, i - 70) : i + 90].replace("\n", " | ")[:200])
    print("---")
    start = i + 11
    n += 1
