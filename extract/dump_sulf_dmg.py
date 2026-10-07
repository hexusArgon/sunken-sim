import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
needle = "Func001Func020Func006Func012C())then"
i = script.find(needle)
print(script[i : i + 500])
print("\n==== 024")
needle = "Func001Func024Func006Func008C())then"
i = script.find(needle)
print(script[i : i + 500])
