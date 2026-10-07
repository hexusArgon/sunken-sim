import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
needle = "Func001Func035Func024C())then"
i = script.find(needle)
print("call", i)
print(script[i : i + 250] if i >= 0 else "no 024C call")
needle = "Func001Func035Func024Func002C())then"
i = script.find(needle)
print("\ncall2", i)
print(script[max(0, i - 100) : i + 200] if i >= 0 else "no")
