import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
for needle in (
    "Func012Func017C())then",
    "Func013Func011Func002C())then",
):
    i = script.find(needle)
    print("\n====", needle, i)
    print(script[i : i + 500] if i >= 0 else "no")
