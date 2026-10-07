import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
for n in (1, 2, 3, 4):
    name = f"Trig_CDR_Cast_And_Spell_Types_Func034Func004Func004Func00{n}C"
    i = script.find(f"function {name} ")
    print("\n====", n)
    print(script[i : i + 500])

print("\n==== I06M contexts")
start = 0
for n in range(6):
    i = script.find("'I06M'", start)
    if i < 0:
        break
    print(script[max(0, i - 200) : i + 120].replace("\n", " | "))
    print("---")
    start = i + 6
