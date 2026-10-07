import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")

for name in [
    "Trig_CDR_Cast_And_Spell_Types_Func034Func002Func004Func001C",
    "Trig_CDR_Cast_And_Spell_Types_Func034Func002Func004Func002C",
    "Trig_CDR_Cast_And_Spell_Types_Func034Func002Func004Func003C",
    "Trig_CDR_Cast_And_Spell_Types_Func021Func006Func001C",
    "Trig_CDR_Cast_And_Spell_Types_Func026Func008Func005Func002C",
    "Trig_CDR_Cast_And_Spell_Types_Func026Func008Func005Func004C",
    "Trig_CDR_Cast_And_Spell_Types_Func026Func008Func007C",
]:
    i = script.find(f"function {name} ")
    print("\n====", name)
    print(script[i : i + 380])
