import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = 0
n = 0
while n < 30:
    i = script.find("udg_Mastery_Stat[", start)
    if i < 0:
        break
    window = script[max(0, i-180): i+80]
    if "Priest" in window or "A0MH" in window or "Shadow" in window or "Mind" in window:
        print(n, window.replace("\n", " | ")[:400])
        print("---")
        n += 1
    start = i + 16
print("done windows", n)
