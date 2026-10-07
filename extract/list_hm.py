import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
import re
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
names = sorted(set(re.findall(r"function (Trig_\w*(?:Haste|Mastery)\w*)", script)))
for name in names:
    if "Tooltip" in name or name.endswith("_Actions"):
        print(name)
