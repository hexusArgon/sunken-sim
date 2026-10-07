import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
for needle in [
    "udg_MagicalType_Bonus=1",
    "udg_MagicalType_Bonus=0",
    "udg_MagicalType_Dynamic=0",
    "udg_MagicalType_Dynamic=1",
    "udg_PhysicalType_Bonus=1",
    "udg_PhysicalType_Bonus=0",
]:
    print(needle, script.count(needle))
    i = script.find(needle)
    if i >= 0:
        print(script[max(0, i - 80) : i + 90].replace("\n", " | "))
        print("---")
