import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
for code in ("I07O", "I0NS", "I0NT"):
    print("====", code)
    index = script.find(f"UnitAddItemByIdSwapped('{code}'")
    print(script[max(0, index - 200) : index + 120].replace("\n", " | ")[:400])
    print()
