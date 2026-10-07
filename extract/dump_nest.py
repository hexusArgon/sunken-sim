import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
start = script.find("set udg_MagicalType_Bonus=1.00")
end = script.find("set udg_PhysicalType_Bonus=1.00", start)
chunk = script[start:end]
depth = 0
for line in chunk.split("\n"):
    s = line.strip()
    if s.startswith("if(") and s.endswith("then"):
        depth += 1
    elif s == "endif":
        depth -= 1
print("depth at physical reset", depth)
# show last 15 lines
print("\n".join(chunk.split("\n")[-12:]))
