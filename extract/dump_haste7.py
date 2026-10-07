import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
for n in (1, 2, 3):
    name = f"Trig_CDR_Cast_And_Spell_Types_Func021Func006Func001Func00{n}C"
    i = script.find(f"function {name} ")
    print("\n====", name)
    print(script[i : i + 320])

# increased amount for I0FW and I0QT
i = script.find("Func026Func008Func005Func002C())then")
print("\n==== increase body")
print(script[i : i + 700])
