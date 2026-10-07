import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = 0
n = 0
while n < 15:
    i = script.find("udg_Haste_Items", start)
    if i < 0:
        break
    print(n, script[max(0,i-60):i+90].replace("\n"," | "))
    print("---")
    start = i + 14
    n += 1
print("total", script.count("udg_Haste_Items"))
