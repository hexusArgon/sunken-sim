import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")

# specialization change and priest ability lists
for needle in (
    "function Trig_Specialization_Change_Actions",
    "A0MH",
    "Priest_Spell",
    "udg_Ability_Int",
):
    print(needle, script.count(needle))

i = script.find("function Trig_Specialization_Change_Actions")
print("\n==== spec change head ====")
print(script[i : i + 1500])
