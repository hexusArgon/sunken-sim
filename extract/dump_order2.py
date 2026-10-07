import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path
import re

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = script.find("set udg_MagicalType_Bonus=1.00")
end = script.find("set udg_PhysicalType_Bonus=1.00", start)
chunk = script[start:end]
for m in re.finditer(r"set udg_MagicalType_(Bonus|Dynamic)=\(udg_MagicalType_\1([+\*])", chunk):
    line = chunk[m.start() : m.start() + 140].replace("\n", " ")
    print(f"{m.start():5} {line}")
