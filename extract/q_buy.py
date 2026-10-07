import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path
import re

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
names = re.findall(r"function (TasItem\w+) takes", script)
print("\n".join(names[:60]))
print("count", len(names))
