from pathlib import Path

script = Path(r"C:\Users\eseid\AppData\Local\Temp\sunken_city\war3map.j").read_text(encoding="utf-8", errors="replace")
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
