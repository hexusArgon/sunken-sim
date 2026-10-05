from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
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
