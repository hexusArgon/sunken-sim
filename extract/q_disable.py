import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
print("SetPlayerAbilityAvailable priest-ish")
idx = 0
n = 0
while n < 15:
    i = script.find("SetPlayerAbilityAvailable", idx)
    if i < 0:
        break
    window = script[i : i + 120]
    if any(code in window for code in ("A0GB", "A0NC", "A0JK", "A0GC", "A0GK", "A0MC", "A0MI")):
        print(window.replace("\n", " | ")[:200])
        n += 1
    idx = i + 20
print("shown", n)

# full shadow form tooltip from skin already partially known
# search ability available false for priest
print("\ncount available", script.count("SetPlayerAbilityAvailableBJ"))
