import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sunken_sim.library import map_script
from pathlib import Path

script = map_script()
script = script.replace("\r\n", "\n").replace("\r", "\n")

names = [
    "Trig_CDR_Cast_And_Spell_Types_Func026Func002Func001Func003C",
    "Trig_CDR_Cast_And_Spell_Types_Func026Func004Func001Func003C",
    "Trig_CDR_Cast_And_Spell_Types_Func026Func006Func001Func003C",
    "Trig_CDR_Cast_And_Spell_Types_Func026Func008Func009Func003C",
    "Trig_CDR_Cast_And_Spell_Types_Func026C",
    "Trig_CDR_Cast_And_Spell_Types_Func026Func002C",
    "Trig_CDR_Cast_And_Spell_Types_Func026Func004C",
    "Trig_CDR_Cast_And_Spell_Types_Func026Func006C",
    "Trig_CDR_Cast_And_Spell_Types_Func026Func008C",
    "Trig_CDR_Cast_And_Spell_Types_Func034Func002Func003C",
    "Trig_CDR_Cast_And_Spell_Types_Func034C",
    "Trig_CDR_Cast_And_Spell_Types_Func034Func002C",
]
for name in names:
    i = script.find(f"function {name} ")
    print("\n====", name, i)
    if i >= 0:
        print(script[i : i + 450])
