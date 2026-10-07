import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = 0
n = 0
while n < 10:
    i = script.find("'I0JA'", start)
    if i < 0:
        break
    print(n, script[max(0, i - 80) : i + 160].replace("\n", " | ")[:280])
    print("---")
    start = i + 6
    n += 1
print("total", script.count("'I0JA'"))
