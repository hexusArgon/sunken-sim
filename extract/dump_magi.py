import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("function Trig_CDR_Cast_And_Spell_Types_Func021Func024C ")
print(script[i : i + 900])
print("\n==== floor condition")
i = script.find("function Trig_CDR_Setup_Func006Func001Func002C ")
print(script[i : i + 400])
