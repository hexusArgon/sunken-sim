from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
script = script.replace("\r\n", "\n").replace("\r", "\n")
i = script.find("function Trig_CDR_Cast_And_Spell_Types_Func021Func024C ")
print(script[i : i + 900])
print("\n==== floor condition")
i = script.find("function Trig_CDR_Setup_Func006Func001Func002C ")
print(script[i : i + 400])
